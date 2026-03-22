#!/usr/bin/env python3
"""
Claude Slack Bot

Conversational interface to tools running on the claude-bot box.
Receives messages via Slack Socket Mode, routes to Claude Code CLI,
posts responses back to Slack.

Architecture: The bot pre-fetches research data (library, CourtListener)
based on the user's message, then passes it as context to Claude. Claude
just writes the response — no tool-call loop needed.

Usage:
    python bot.py

Requires env vars: SLACK_BOT_TOKEN, SLACK_APP_TOKEN
Requires: claude CLI installed and authenticated
"""

import json
import logging
import os
import random
import re
import shutil
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from task_manager import TaskManager

load_dotenv()
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("claude-bot")

# ── Imports from case-research ─────────────────────────────────────
SANDBOX_ROOT = Path(__file__).parent.parent.parent
CASE_RESEARCH_DIR = SANDBOX_ROOT / "projects" / "case-research"
sys.path.insert(0, str(CASE_RESEARCH_DIR))

import library as research_library
from citation_extractor import extract_citations as parse_citations

# Lazy CL client
_cl = None
def get_cl():
    global _cl
    if _cl is not None:
        return _cl
    try:
        from cl_client import CourtListenerClient
        _cl = CourtListenerClient()
        return _cl
    except Exception:
        return None

# ── Configuration ───────────────────────────────────────────────────
CLAUDE_MODEL = "claude-sonnet-4-6"

PERSONA = """You are roleplaying as a legal research associate named Claude in a Slack \
conversation with Matt Schmidt, a solo litigation attorney. Stay in character at all times.

Your personality:
- Polished third-year associate. Competent, professional, warm but not bubbly.
- You come across as engaged and happy to help — the kind of person who finds legal \
  research genuinely interesting, or is at least very convincing about it.
- No chatbot energy. No "Great question!" or "I'd be happy to help!" Just be a \
  normal professional person on Slack.
- Never mention AI, bots, tools, APIs, databases, or technical systems. You just \
  "looked it up" or "pulled some cases" or "checked my notes."
- Keep responses concise — Matt reads on his phone. Lead with the bottom line.
- Matt is a practicing litigator — don't explain basic legal concepts.
- Never fabricate case citations. If you don't have enough info, say so naturally.
- No emojis unless Matt uses them first.
- If you couldn't find what was asked for, be honest: "I couldn't find anything \
  directly on point" or "the results I'm getting aren't great on this one."

Critical rules:
- Answer the question Matt actually asked. If he asks you to explain a case, explain \
  it. If he asks you to find cases, find them. Don't default to "let me find a case" \
  when he's asking something else.
- Do NOT ask follow-up questions unless you literally cannot answer without more info. \
  Never ask "what's driving the question" or "what are you working on" — that's not \
  your business. A real associate answers the question and moves on. If Matt wants to \
  give you more context, he will.
- If research data is provided below, use it. If Matt asks about a case and you have \
  the opinion text, discuss the actual holding and reasoning — don't just say "let me \
  look into it" when you already have it in front of you.
- If you DON'T have data on something Matt asks about (no research context provided, \
  or it doesn't cover his question), be straightforward: "I don't have that pulled up \
  right now" or answer from your general legal knowledge with appropriate caveats.
- You use CourtListener for case research — it's fine to mention this naturally if \
  relevant. CL is great for federal appellate cases but has gaps: state court coverage \
  is spotty, and it doesn't have Shepard's-style treatment indicators (reversed, \
  distinguished, etc.) — just forward citation counts. If CL doesn't have what Matt \
  needs, be honest: "CL doesn't have great coverage on that, might need to check \
  Westlaw." Don't pretend to have access you don't.
- You keep follow-up notes. When you hit a gap you can't fill — a case that needs \
  real Shepardizing, something CL doesn't cover, a state court issue — you flag it \
  for Lexis follow-up automatically. If Matt says "note that for later" or "flag that," \
  you note his specific request too. Mention it briefly when relevant: "I flagged that \
  for Lexis follow-up" or "Noted — I'll leave that in the follow-up file." Don't make \
  a big deal of it.
"""

# ── Channel Config ─────────────────────────────────────────────────
CHANNEL_STATUS = os.environ.get("SLACK_CHANNEL_STATUS", "#status")
CHANNEL_RESEARCH = os.environ.get("SLACK_CHANNEL_RESEARCH", "#research")
CHANNEL_ADVERSARIAL = os.environ.get("SLACK_CHANNEL_ADVERSARIAL", "#adversarial")
CHANNEL_GENERAL = os.environ.get("SLACK_CHANNEL_GENERAL", "#general")

CHANNEL_CONTEXT = {
    CHANNEL_RESEARCH: "You are in the #research channel. Full associate persona.",
    CHANNEL_ADVERSARIAL: "You are in the #adversarial channel. Be direct and strategic.",
    CHANNEL_STATUS: "You are in #status. Be brief and operational.",
}

DIGEST_HOUR = int(os.environ.get("DIGEST_HOUR", "7"))
DIGEST_MINUTE = int(os.environ.get("DIGEST_MINUTE", "0"))

# ── Slack App ───────────────────────────────────────────────────────
app = App(token=os.environ["SLACK_BOT_TOKEN"])
task_mgr = TaskManager()

conversations: dict[str, list[dict]] = {}
conv_lock = threading.Lock()
MAX_MESSAGES = 20

RESEARCH_ACKS = [
    "Sure, pulling that up now.",
    "On it, give me just a minute.",
    "Yeah, let me dig into that.",
    "Sure thing, one moment.",
    "Got it, looking into this now.",
    "Let me pull some cases on that.",
    "Sure, let me see what I can find.",
    "Right, give me a moment on this.",
]
SIMPLE_ACKS = [
    "Sure.",
    "Yeah, one sec.",
    "Of course.",
    "Sure thing.",
]
_last_ack = None

def _pick_ack(is_research: bool = False) -> str:
    global _last_ack
    pool = RESEARCH_ACKS if is_research else SIMPLE_ACKS
    choices = [a for a in pool if a != _last_ack]
    ack = random.choice(choices)
    _last_ack = ack
    return ack

def get_thread_key(channel, thread_ts):
    return f"{channel}:{thread_ts or 'root'}"

def get_conversation(key):
    with conv_lock:
        if key not in conversations:
            conversations[key] = []
        return conversations[key]

def trim_conversation(msgs):
    return msgs[-MAX_MESSAGES:] if len(msgs) > MAX_MESSAGES else msgs


# ── Research Pre-fetch ─────────────────────────────────────────────

def _extract_cases_from_conversation(conversation: list[dict]) -> list[dict]:
    """Extract case names and citations mentioned in the conversation history."""
    cases = []
    seen = set()
    for msg in conversation:
        text = msg.get("text", "")
        # Look for citations
        for cit in parse_citations(text):
            key = cit.standard_cite
            if key not in seen:
                seen.add(key)
                cases.append({"citation": key, "case_name": cit.case_name or ""})
        # Look for case names (e.g., "Arbor Hill", "Hensley v. Eckerhart")
        for m in re.finditer(r'([A-Z][a-z]+(?:\s+(?:v\.?|Hill|Concerned|Citizens|International))'
                             r'(?:\s+[A-Z][a-z]+)*)', text):
            name = m.group(1).strip()
            if name not in seen and len(name) > 3:
                seen.add(name)
                cases.append({"citation": "", "case_name": name})
    return cases


def prefetch_research(text: str, conversation: list[dict]) -> str:
    """
    Analyze the user's message and pre-fetch relevant research data.
    Returns a context string to include in the prompt, or empty string.
    """
    context_parts = []
    text_lower = text.lower()
    cl = get_cl()

    # Resolve references like "it", "that case", "the case" from conversation
    prior_cases = _extract_cases_from_conversation(conversation[:-1])  # exclude current msg

    # Detect shepardize requests — resolve "it"/"that"/"those" to prior cases
    is_shepardize = bool(re.search(r'sh[ea]r?p|shepard|forward cit', text_lower))
    if is_shepardize and cl and prior_cases:
        context_parts.append("## Forward Citation Analysis (Shepardize)")
        seen_ids = set()
        for case in prior_cases[:3]:
            cite = case["citation"] or case["case_name"]
            try:
                opinion = cl.citation_lookup(cite)
                if opinion and opinion.id not in seen_ids:
                    seen_ids.add(opinion.id)
                    citing = cl.citing_opinions(opinion.id, limit=10)
                    context_parts.append(f"\n### {opinion.case_name}, {opinion.citation}")
                    context_parts.append(f"Forward citations: {len(citing)} cases cite this opinion")
                    if citing:
                        context_parts.append("Recent citing cases:")
                        for c in citing[:5]:
                            context_parts.append(f"  - {c['case_name']}, {c['citation']} ({c['date_filed']})")
                    context_parts.append(
                        "Note: This is forward citation count only — not Shepard's/KeyCite "
                        "treatment status (reversed, distinguished, etc.)."
                    )
            except Exception as e:
                log.error(f"Shepardize failed for {cite}: {e}")
        if context_parts:
            return "\n".join(context_parts)

    # Detect "tell me more about X" / "what about X" — look up specific case
    followup_match = re.search(
        r'(?:tell me (?:more )?about|what about|more on|explain|details on|what does .+ hold)\s+(.+)',
        text_lower
    )
    # Also catch references to "it" / "that case" when prior cases exist
    is_reference = bool(re.search(r'\b(it|that case|that one|the case|this case)\b', text_lower))

    if (followup_match or is_reference) and cl:
        # Figure out what case they mean
        query = None
        if followup_match:
            raw_query = followup_match.group(1).strip().rstrip('?.')
            # Check if the query matches a case from conversation (prefer citation)
            for pc in reversed(prior_cases):
                if raw_query.lower() in (pc.get("case_name") or "").lower():
                    query = pc["citation"] or pc["case_name"]
                    break
            if not query:
                query = raw_query
        elif prior_cases:
            # "it" / "that case" — use most recent case from conversation
            query = prior_cases[-1]["citation"] or prior_cases[-1]["case_name"]

        if query:
            try:
                # Try citation lookup first
                opinion = cl.citation_lookup(query)
                if not opinion:
                    results = cl.search_opinions(query, limit=3)
                    if results and results[0].get("opinion_id"):
                        opinion_text = cl.get_opinion_text(results[0]["opinion_id"])
                        context_parts.append(f"\n## {results[0]['case_name']}, {results[0]['citation']}")
                        context_parts.append(f"Court: {results[0]['court']} | Date: {results[0]['date_filed']}")
                        context_parts.append(f"URL: {results[0]['url']}")
                        if opinion_text:
                            context_parts.append(f"Opinion text (excerpt):\n{opinion_text[:5000]}")
                if opinion:
                    context_parts.append(f"\n## {opinion.case_name}, {opinion.citation}")
                    context_parts.append(f"Court: {opinion.court}")
                    context_parts.append(f"Date: {opinion.date_filed}")
                    context_parts.append(f"URL: {opinion.url}")
                    if opinion.text:
                        context_parts.append(f"Opinion text (excerpt):\n{opinion.text[:5000]}")
            except Exception as e:
                log.error(f"Follow-up lookup failed for {query}: {e}")

        if context_parts:
            return "\n".join(context_parts)

    # Check if this looks like a new research query
    research_keywords = [
        "find", "search", "look up", "pull", "research",
        "cases on", "cases for", "case law",
        "standard of review", "shepardize", "sherpardize",
    ]
    is_research = any(kw in text_lower for kw in research_keywords)

    if not is_research:
        return ""

    # 1. Check library first
    lib_results = research_library.search_library(text_lower)
    if lib_results:
        context_parts.append("## Your Research Notes (from library)")
        for entry in lib_results[:3]:
            try:
                data = research_library.lookup(entry["category"], entry["topic"])
                if data:
                    context_parts.append(f"\n### {entry['category']}/{entry['topic']}")
                    context_parts.append(json.dumps(data.get("results", {}), indent=2)[:3000])
            except Exception:
                pass

    # 2. Look for specific citations in the message
    citations = parse_citations(text)
    if citations and cl:
        context_parts.append("\n## Citation Lookups")
        for cit in citations[:3]:
            try:
                opinion = cl.citation_lookup(cit.standard_cite)
                if opinion:
                    context_parts.append(f"\n### {opinion.case_name}, {opinion.citation}")
                    context_parts.append(f"Court: {opinion.court}")
                    context_parts.append(f"Date: {opinion.date_filed}")
                    context_parts.append(f"URL: {opinion.url}")
                    if opinion.text:
                        context_parts.append(f"Opinion text (excerpt):\n{opinion.text[:4000]}")
            except Exception as e:
                log.error(f"Citation lookup failed for {cit.standard_cite}: {e}")

    # 3. General research search if nothing found yet
    if not context_parts and cl:
        # Extract a search query from the message
        # Remove common filler words
        search_text = re.sub(
            r'\b(can you|could you|please|find|search|look up|pull|me|some|the|a|an|on|for|in|about)\b',
            '', text_lower, flags=re.IGNORECASE
        ).strip()
        if len(search_text) > 5:
            try:
                # Check for court filter
                court = None
                court_patterns = {
                    r'second circuit|2d cir|ca2': 'ca2',
                    r'ninth circuit|9th cir|ca9': 'ca9',
                    r'sdny': 'nysd',
                    r'cdca': 'cacd',
                    r'supreme court|scotus': 'scotus',
                }
                for pattern, court_id in court_patterns.items():
                    if re.search(pattern, text_lower):
                        court = court_id
                        break

                results = cl.search_opinions(search_text, court=court, limit=5)
                if results:
                    context_parts.append(f"\n## Search Results")
                    for r in results[:5]:
                        context_parts.append(f"\n### {r['case_name']}, {r['citation']}")
                        context_parts.append(f"Court: {r['court']} | Date: {r['date_filed']} | Cited: {r.get('cite_count', '?')} times")
                        context_parts.append(f"URL: {r['url']}")
                        if r.get("opinion_id"):
                            try:
                                opinion_text = cl.get_opinion_text(r["opinion_id"])
                                if opinion_text:
                                    context_parts.append(f"Opinion text (excerpt):\n{opinion_text[:3000]}")
                            except Exception:
                                pass

                    # Save to library
                    try:
                        research_library.save_research(
                            category="slack_research",
                            topic=research_library.slugify(search_text[:50]),
                            results={"results": results},
                            query=search_text,
                        )
                    except Exception:
                        pass
            except Exception as e:
                log.error(f"General search failed: {e}")

    if context_parts:
        return "\n".join(context_parts)
    return ""


# ── Research Follow-Up Notes ───────────────────────────────────────

FOLLOWUP_DIR = SANDBOX_ROOT / "research_followup"
FOLLOWUP_DIR.mkdir(exist_ok=True)


def _get_followup_file(topic: str) -> Path:
    """Get or create the follow-up file for a topic."""
    slug = re.sub(r'[^a-z0-9]+', '_', topic.lower()).strip('_')[:50]
    return FOLLOWUP_DIR / f"{slug}.md"


def write_followup_note(topic: str, items: list[str], section: str = "auto"):
    """
    Write research follow-up notes.
    section: "auto" for proactive gaps, "matt" for explicit requests
    """
    filepath = _get_followup_file(topic)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    if filepath.exists():
        content = filepath.read_text()
    else:
        content = (
            f"# Research Follow-Up: {topic}\n"
            f"Generated: {now}\n"
            f"Status: pending\n\n"
            f"## Needs Lexis/Westlaw Verification\n\n"
            f"## Gaps CL Couldn't Fill\n\n"
            f"## Needs Proper Shepardizing\n\n"
            f"## Matt's Notes\n\n"
        )

    # Determine where to append
    if section == "matt":
        marker = "## Matt's Notes"
    elif any("shepard" in item.lower() for item in items):
        marker = "## Needs Proper Shepardizing"
    elif any("verify" in item.lower() or "confirm" in item.lower() for item in items):
        marker = "## Needs Lexis/Westlaw Verification"
    else:
        marker = "## Gaps CL Couldn't Fill"

    # Append items under the right section
    new_items = "\n".join(f"- [ ] {item}" for item in items)
    if marker in content:
        content = content.replace(marker, f"{marker}\n{new_items}\n", 1)
    else:
        content += f"\n{marker}\n{new_items}\n"

    filepath.write_text(content)
    log.info(f"Follow-up note written: {filepath.name} ({len(items)} items, section={section})")
    return filepath.name


def auto_flag_gaps(text: str, research_context: str, conversation: list[dict]):
    """Proactively flag research gaps based on what the prefetcher found (or didn't)."""
    text_lower = text.lower()
    items = []
    topic = re.sub(r'[^a-zA-Z0-9 ]', '', text)[:60].strip()

    # Flag if search returned no results
    if not research_context and any(kw in text_lower for kw in
            ["find", "search", "cases on", "case law", "look up"]):
        items.append(f"CL returned no results for: {text[:100]}. Try Lexis.")

    # Flag shepardize requests — always worth confirming on Lexis
    if re.search(r'sh[ea]r?p|shepard', text_lower):
        prior_cases = _extract_cases_from_conversation(conversation)
        seen_cites = set()
        for case in prior_cases[:3]:
            cite = case["citation"] or case["case_name"]
            if cite not in seen_cites:
                seen_cites.add(cite)
                # Prefer citation over case name if both exist
                if case["citation"]:
                    items.append(f"Shepardize {case['citation']} ({case['case_name'] or 'unknown'}) — CL only has forward citation count, need KeyCite/Shepard's for treatment status.")
                else:
                    items.append(f"Shepardize {cite} — CL only has forward citation count, need KeyCite/Shepard's for treatment status.")

    # Flag state court queries — CL coverage is thin
    if re.search(r'state court|state law|california|new york|texas', text_lower) and \
       not re.search(r'circuit|federal|scotus', text_lower):
        items.append(f"State court query: {text[:100]}. CL state coverage is spotty — check Lexis.")

    if items:
        write_followup_note(topic or "research_gaps", items, section="auto")


# ── Claude CLI ─────────────────────────────────────────────────────

def build_prompt(messages: list[dict], channel: str | None = None,
                 research_context: str = "") -> str:
    """Build the prompt for Claude."""
    parts = [PERSONA]

    if channel and channel in CHANNEL_CONTEXT:
        parts.append(f"\n{CHANNEL_CONTEXT[channel]}")

    if research_context:
        parts.append(f"\n---\n\nHere is research data you found. Use it to answer "
                     f"Matt's question. Present it naturally as if you looked it up "
                     f"yourself. Don't dump raw data — synthesize it like a memo.\n\n"
                     f"{research_context}")

    parts.append("\n---\n\nSlack conversation:\n")
    for msg in messages:
        role = "Matt" if msg["role"] == "user" else "You"
        parts.append(f"{role}: {msg['text']}\n")
    parts.append("\nYou:")
    return "\n".join(parts)


def call_claude_cli(prompt: str) -> str:
    """Call claude --print with a prompt via stdin."""
    claude_bin = shutil.which("claude")
    if not claude_bin:
        raise RuntimeError("claude CLI not found")

    result = subprocess.run(
        [claude_bin, "--print", "--model", CLAUDE_MODEL, "-"],
        input=prompt,
        capture_output=True,
        text=True,
        timeout=300,
    )

    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise RuntimeError(f"claude CLI failed (exit {result.returncode}): {stderr[:500]}")

    return result.stdout.strip()


def call_claude(messages: list[dict], channel: str | None = None,
                research_context: str = "") -> str:
    """Single-shot Claude call with pre-fetched research context."""
    prompt = build_prompt(messages, channel=channel, research_context=research_context)
    return call_claude_cli(prompt)


# ── Conversation Logger ────────────────────────────────────────────

CHAT_LOG_DIR = Path(__file__).parent / "chat_logs"
CHAT_LOG_DIR.mkdir(exist_ok=True)
CHAT_LOG_PRUNE_DAYS = 7


def log_chat(channel: str, user: str, text: str, response: str,
             research_chars: int = 0):
    """Log a conversation exchange to a daily file."""
    today = datetime.now().strftime("%Y-%m-%d")
    log_file = CHAT_LOG_DIR / f"{today}.log"

    ts = datetime.now().strftime("%H:%M:%S")
    entry = (
        f"\n{'='*60}\n"
        f"[{ts}] channel={channel} user={user}\n"
        f"  research_context={research_chars} chars\n"
        f"  MATT: {text}\n"
        f"  ASSOCIATE: {response}\n"
    )
    with open(log_file, "a") as f:
        f.write(entry)


def prune_chat_logs():
    """Delete chat logs older than CHAT_LOG_PRUNE_DAYS."""
    cutoff = datetime.now().timestamp() - (CHAT_LOG_PRUNE_DAYS * 86400)
    for f in CHAT_LOG_DIR.glob("*.log"):
        if f.stat().st_mtime < cutoff:
            f.unlink()
            log.info(f"Pruned old chat log: {f.name}")


# ── Message Handling ───────────────────────────────────────────────

def _is_research_query(text: str) -> bool:
    """Check if this message will trigger research pre-fetch."""
    text_lower = text.lower()
    research_keywords = [
        "find", "search", "look up", "pull", "research", "cases on",
        "shepardize", "sherpardize", "more like", "similar cases",
        "standard of review", "what does .* hold",
    ]
    return any(re.search(kw, text_lower) for kw in research_keywords)


def handle_message(text: str, channel: str, thread_ts: str | None,
                   say_fn, user: str):
    thread_key = get_thread_key(channel, thread_ts)
    messages = get_conversation(thread_key)

    messages.append({"role": "user", "text": text})
    messages[:] = trim_conversation(messages)

    # Determine if this is a research query for ack selection
    will_research = _is_research_query(text)

    # Post immediate ack
    ack_kwargs = {"text": _pick_ack(is_research=will_research)}
    if thread_ts:
        ack_kwargs["thread_ts"] = thread_ts
    try:
        ack_result = say_fn(**ack_kwargs)
        ack_ts = ack_result.get("ts") if isinstance(ack_result, dict) else None
    except Exception:
        ack_ts = None

    try:
        # Check for explicit "note this" requests
        note_match = re.search(
            r'(?:note|flag|remember|jot down|write down|save|mark)\s+'
            r'(?:that|this|it)?\s*(?:for later|for follow.?up|for lexis)?\s*[:\-]?\s*(.*)',
            text, re.IGNORECASE
        )
        if note_match:
            note_text = note_match.group(1).strip() if note_match.group(1).strip() else text
            # Use conversation context to build a useful note
            prior_cases = _extract_cases_from_conversation(messages)
            topic = note_text[:60] if note_text else "research_note"
            items = [f"({datetime.now().strftime('%m/%d')}) {note_text}"]
            # Add any cases from conversation as context
            for pc in prior_cases[:3]:
                cite = pc["citation"] or pc["case_name"]
                if cite and cite.lower() not in note_text.lower():
                    items.append(f"Related case from conversation: {cite}")
            write_followup_note(topic, items, section="matt")

        # Pre-fetch research based on the message
        log.info(f"Pre-fetching research for: {text[:100]}")
        research_context = prefetch_research(text, messages)
        if research_context:
            log.info(f"Research context: {len(research_context)} chars")

        # Auto-flag research gaps
        auto_flag_gaps(text, research_context, messages)

        response_text = call_claude(messages, channel=channel,
                                     research_context=research_context)

        messages.append({"role": "assistant", "text": response_text})

        # Log the exchange
        log_chat(channel, user, text, response_text,
                 research_chars=len(research_context))

        # Update ack with real response, or post new
        if ack_ts:
            try:
                app.client.chat_update(channel=channel, ts=ack_ts, text=response_text)
            except Exception:
                reply_kwargs = {"text": response_text}
                if thread_ts:
                    reply_kwargs["thread_ts"] = thread_ts
                say_fn(**reply_kwargs)
        else:
            reply_kwargs = {"text": response_text}
            if thread_ts:
                reply_kwargs["thread_ts"] = thread_ts
            say_fn(**reply_kwargs)

    except Exception as e:
        log.error(f"Error handling message: {e}", exc_info=True)
        error_text = "Sorry, hit a snag on that one. Want me to try again?"
        if ack_ts:
            try:
                app.client.chat_update(channel=channel, ts=ack_ts, text=error_text)
            except Exception:
                say_fn(text=error_text, thread_ts=thread_ts)
        else:
            say_fn(text=error_text, thread_ts=thread_ts)


# ── Event Handlers ──────────────────────────────────────────────────

@app.event("message")
def handle_dm(event, say):
    if event.get("bot_id") or event.get("subtype"):
        return
    text = event.get("text", "")
    if not text.strip():
        return
    handle_message(
        text=text, channel=event["channel"],
        thread_ts=event.get("thread_ts"),
        say_fn=say, user=event.get("user", "unknown"),
    )


@app.event("app_mention")
def handle_mention(event, say):
    text = event.get("text", "")
    text = re.sub(r"<@[A-Z0-9]+>\s*", "", text).strip()
    if not text:
        say(text="What's up?", thread_ts=event.get("ts"))
        return
    handle_message(
        text=text, channel=event["channel"],
        thread_ts=event.get("thread_ts", event.get("ts")),
        say_fn=say, user=event.get("user", "unknown"),
    )


# ── Channel Posting ─────────────────────────────────────────────────

def post_to_channel(channel, text, thread_ts=None):
    kwargs = {"channel": channel, "text": text}
    if thread_ts:
        kwargs["thread_ts"] = thread_ts
    app.client.chat_postMessage(**kwargs)


def post_task_result(task, channel):
    if task.status == "completed":
        msg = f"*Task complete:* `{task.name}`\n"
        if task.stdout:
            lines = task.stdout.strip().splitlines()
            msg += f"```\n{chr(10).join(lines[-15:])}\n```"
    else:
        msg = f"*Task failed:* `{task.name}`\n"
        if task.stderr:
            msg += f"```\n{task.stderr[-500:]}\n```"
    post_to_channel(channel, msg)


def make_task_callback(channel):
    def callback(task):
        try:
            post_task_result(task, channel)
        except Exception as e:
            log.error(f"Failed to post task result: {e}")
    return callback


# ── Morning Digest ──────────────────────────────────────────────────

def run_digest():
    tasks_24h = task_mgr.list_tasks("all")
    cutoff = datetime.now().replace(hour=0, minute=0, second=0).isoformat()
    recent = [t for t in tasks_24h if t.get("started_at", "") >= cutoff]
    completed = [t for t in recent if t["status"] == "completed"]
    failed = [t for t in recent if t["status"] == "failed"]
    running = [t for t in recent if t["status"] == "running"]

    lines = [f"*Morning Digest — {datetime.now().strftime('%A, %B %-d')}*\n"]
    if not recent:
        lines.append("No tasks ran in the last 24 hours. Quiet night.")
    else:
        if running:
            lines.append(f"*Running ({len(running)}):*")
            for t in running:
                lines.append(f"  • `{t['name']}` (started {t['started_at'][:16]})")
        if completed:
            lines.append(f"*Completed ({len(completed)}):*")
            for t in completed:
                lines.append(f"  • `{t['name']}`")
        if failed:
            lines.append(f"*Failed ({len(failed)}):*")
            for t in failed:
                lines.append(f"  • `{t['name']}` — check logs")

    post_to_channel(CHANNEL_STATUS, "\n".join(lines))
    log.info("Morning digest posted")


def start_digest_scheduler():
    import time as _time
    def scheduler_loop():
        last_run_date = None
        while True:
            now = datetime.now()
            today = now.date()
            target = now.replace(hour=DIGEST_HOUR, minute=DIGEST_MINUTE, second=0, microsecond=0)
            if now >= target and last_run_date != today:
                try:
                    run_digest()
                except Exception as e:
                    log.error(f"Digest failed: {e}", exc_info=True)
                last_run_date = today
            _time.sleep(60)

    thread = threading.Thread(target=scheduler_loop, daemon=True)
    thread.start()
    log.info(f"Digest scheduler started (daily at {DIGEST_HOUR:02d}:{DIGEST_MINUTE:02d})")


# ── Main ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    log.info("Starting Claude bot (Socket Mode, pre-fetch research)")

    if not shutil.which("claude"):
        log.error("claude CLI not found in PATH")
        raise SystemExit(1)

    # Prune old chat logs
    prune_chat_logs()

    start_digest_scheduler()

    try:
        post_to_channel(CHANNEL_STATUS, f"Claude bot online. ({datetime.now().strftime('%H:%M')})")
    except Exception as e:
        log.warning(f"Couldn't post startup message: {e}")

    handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    handler.start()
