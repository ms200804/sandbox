#!/usr/bin/env python3
"""
Claude Slack Bot

Conversational interface to tools running on the claude-bot box.
Receives messages via Slack Socket Mode, routes to Claude API with tools,
posts responses back to Slack.

Usage:
    python bot.py

Requires env vars: SLACK_BOT_TOKEN, SLACK_APP_TOKEN, ANTHROPIC_API_KEY
"""

import json
import logging
import os
import re
import threading
from datetime import datetime, time as dtime
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from tools import TOOL_DEFINITIONS, execute_tool
from task_manager import TaskManager

load_dotenv()
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("claude-bot")

# ── Configuration ───────────────────────────────────────────────────
CLAUDE_MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 4096
SYSTEM_PROMPT = """You are Claude, a helpful assistant running on a headless Debian \
server. You help Matt Schmidt, a solo litigation attorney, with legal research, argument \
testing, and task management.

You have access to tools for:
- Running adversarial simulations on legal arguments (6 parallel agents + synthesis)
- Searching CourtListener for case law, looking up citations, shepardizing
- Finding similar cases ("more like this") via citation network analysis
- Checking on running tasks and reading output files
- Running sandboxed shell commands

Matt will message you from his phone via Slack. Expect casual, typo-laden messages. \
Interpret intent generously. Respond conversationally but concisely — he's reading on \
a small screen.

## Adversarial Sim Workflow
When Matt wants to stress-test an argument, he can give you anything from a bare \
legal question ("can I argue unconscionability of JAMS fees in SDNY") to a full \
draft brief. By default, ask 1-3 short clarifying questions before running — forum, \
procedural context, and any specific concerns. If he says "just run it" or seems \
impatient, set force=true and make reasonable assumptions.

The sim takes a few minutes. Acknowledge immediately, launch it as a background \
task, and results will auto-post to #adversarial when done.

## Case Research Workflow
ALWAYS check the research library first (library_search) before running a new search. \
If we've already researched the topic and it's not stale, use the cached results. \
If stale, offer to refresh. If not found, run a fresh search and save results to \
the library (library_save) with an appropriate category and topic name. Create new \
categories freely — the library self-organizes.

When Matt says "more like this," "find similar," or refers to a previously found \
case, use find_similar_cases with the reference case from the conversation context.

Research results stay in the thread context, so he can refine ("narrow to 9th circuit," \
"only after 2020," "that second case looks good, more like that") without re-explaining.

Note on citation analysis: CourtListener shows which cases cite which — it does NOT \
tell you whether a case was reversed or distinguished. When shepardizing, be clear \
this is forward citation analysis, not Shepard's/KeyCite treatment status.

## Cross-Tool Chaining
Matt may want to feed research results into a sim: "run the adversarial sim on \
the steiner argument, use those cases." Use the research results from the thread \
to compose the scenario's Key Authorities section.

## General Rules
- Lead with the bottom line, then supporting detail
- Matt is a practicing litigator — don't explain basic legal concepts
- When a task will take more than a few seconds, acknowledge and launch in background
- If unsure what he wants, ask ONE short clarifying question
- Never fabricate case citations"""

# ── Channel Routing ─────────────────────────────────────────────────
# Set these to your Slack channel IDs (not names).
# Find IDs: right-click channel → "View channel details" → ID at bottom.
# Or leave as channel names and resolve at startup.
CHANNEL_STATUS = os.environ.get("SLACK_CHANNEL_STATUS", "#claude-bot")
CHANNEL_RESEARCH = os.environ.get("SLACK_CHANNEL_RESEARCH", "#research")
CHANNEL_ADVERSARIAL = os.environ.get("SLACK_CHANNEL_ADVERSARIAL", "#adversarial")

# Digest schedule (24h, server-local time — Pacific on claude-bot)
DIGEST_HOUR = int(os.environ.get("DIGEST_HOUR", "7"))
DIGEST_MINUTE = int(os.environ.get("DIGEST_MINUTE", "0"))

# ── Slack App ───────────────────────────────────────────────────────
app = App(token=os.environ["SLACK_BOT_TOKEN"])
claude = anthropic.Anthropic()
task_mgr = TaskManager()

# Per-thread conversation history: {thread_key: [messages]}
conversations: dict[str, list[dict]] = {}
conv_lock = threading.Lock()

MAX_CONVERSATION_MESSAGES = 40  # trim oldest when exceeded


def get_thread_key(channel: str, thread_ts: str | None) -> str:
    """Unique key for a Slack conversation thread."""
    return f"{channel}:{thread_ts or 'root'}"


def get_conversation(thread_key: str) -> list[dict]:
    """Get or create conversation history for a thread."""
    with conv_lock:
        if thread_key not in conversations:
            conversations[thread_key] = []
        return conversations[thread_key]


def trim_conversation(messages: list[dict]) -> list[dict]:
    """Keep conversation within context limits."""
    if len(messages) > MAX_CONVERSATION_MESSAGES:
        return messages[-MAX_CONVERSATION_MESSAGES:]
    return messages


def call_claude(messages: list[dict]) -> str:
    """
    Call Claude API with tool use. Handles the tool-use loop:
    Claude may request tool calls, we execute them and feed results back,
    until Claude produces a final text response.
    """
    working_messages = list(messages)

    while True:
        response = claude.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            tools=TOOL_DEFINITIONS,
            messages=working_messages,
        )

        # Collect text and tool_use blocks
        text_parts = []
        tool_uses = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_uses.append(block)

        # If no tool calls, we're done
        if not tool_uses:
            return "\n".join(text_parts)

        # Add assistant's response (with tool_use blocks) to history
        working_messages.append({"role": "assistant", "content": response.content})

        # Execute each tool and collect results
        tool_results = []
        for tool_use in tool_uses:
            log.info(f"Tool call: {tool_use.name}({json.dumps(tool_use.input)[:200]})")
            try:
                result = execute_tool(
                    tool_use.name, tool_use.input, task_mgr,
                    post_callback_factory=_make_channel_callback,
                )
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": str(result),
                })
            except Exception as e:
                log.error(f"Tool error: {tool_use.name}: {e}")
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": f"Error: {e}",
                    "is_error": True,
                })

        working_messages.append({"role": "user", "content": tool_results})

    # Unreachable, but just in case
    return "Something went wrong — no response from Claude."


def handle_message(text: str, channel: str, thread_ts: str | None,
                   say_fn, user: str):
    """Process an incoming message and respond."""
    thread_key = get_thread_key(channel, thread_ts)
    messages = get_conversation(thread_key)

    # Add user message
    messages.append({"role": "user", "content": text})
    messages[:] = trim_conversation(messages)

    try:
        response_text = call_claude(messages)

        # Add assistant response to history
        messages.append({"role": "assistant", "content": response_text})

        # Post to Slack (in thread if applicable)
        reply_kwargs = {"text": response_text}
        if thread_ts:
            reply_kwargs["thread_ts"] = thread_ts
        say_fn(**reply_kwargs)

    except Exception as e:
        log.error(f"Error handling message: {e}", exc_info=True)
        error_kwargs = {"text": f"Something broke: {e}"}
        if thread_ts:
            error_kwargs["thread_ts"] = thread_ts
        say_fn(**error_kwargs)


# ── Event Handlers ──────────────────────────────────────────────────

@app.event("message")
def handle_dm(event, say):
    """Handle direct messages."""
    # Skip bot's own messages and message edits
    if event.get("bot_id") or event.get("subtype"):
        return

    text = event.get("text", "")
    if not text.strip():
        return

    handle_message(
        text=text,
        channel=event["channel"],
        thread_ts=event.get("thread_ts"),
        say_fn=say,
        user=event.get("user", "unknown"),
    )


@app.event("app_mention")
def handle_mention(event, say):
    """Handle @mentions in channels."""
    text = event.get("text", "")
    # Strip the bot mention from the text
    # Slack formats mentions as <@U12345> — remove it
    text = re.sub(r"<@[A-Z0-9]+>\s*", "", text).strip()

    if not text:
        say(text="What's up?", thread_ts=event.get("ts"))
        return

    handle_message(
        text=text,
        channel=event["channel"],
        # Always thread @mention responses
        thread_ts=event.get("thread_ts", event.get("ts")),
        say_fn=say,
        user=event.get("user", "unknown"),
    )


# ── Channel Posting ─────────────────────────────────────────────────

def post_to_channel(channel: str, text: str, thread_ts: str | None = None):
    """Post a message to a specific channel. Used for async task results."""
    kwargs = {"channel": channel, "text": text}
    if thread_ts:
        kwargs["thread_ts"] = thread_ts
    app.client.chat_postMessage(**kwargs)


def post_task_result(task, channel: str):
    """Post task completion results to the appropriate channel."""
    if task.status == "completed":
        msg = f"*Task complete:* `{task.name}`\n"
        # Include tail of stdout as summary
        if task.stdout:
            lines = task.stdout.strip().splitlines()
            tail = "\n".join(lines[-15:])
            msg += f"```\n{tail}\n```"
    else:
        msg = f"*Task failed:* `{task.name}`\n"
        if task.stderr:
            msg += f"```\n{task.stderr[-500:]}\n```"

    post_to_channel(channel, msg)


def make_task_callback(channel: str):
    """Create a callback that posts task results to the right channel."""
    def callback(task):
        try:
            post_task_result(task, channel)
        except Exception as e:
            log.error(f"Failed to post task result to {channel}: {e}")
    return callback


def route_task_channel(task_name: str) -> str:
    """Determine which channel a task's results should go to."""
    if "adversarial" in task_name or "sim" in task_name:
        return CHANNEL_ADVERSARIAL
    if "research" in task_name or "search" in task_name or "shepard" in task_name:
        return CHANNEL_RESEARCH
    return CHANNEL_STATUS


def _make_channel_callback(channel_hint: str):
    """
    Factory for task completion callbacks.
    channel_hint: "adversarial", "research", or "status"
    """
    channel_map = {
        "adversarial": CHANNEL_ADVERSARIAL,
        "research": CHANNEL_RESEARCH,
        "status": CHANNEL_STATUS,
    }
    channel = channel_map.get(channel_hint, CHANNEL_STATUS)
    return make_task_callback(channel)


# ── Morning Digest ──────────────────────────────────────────────────

def run_digest():
    """Post a morning digest to #claude-bot."""
    tasks_24h = task_mgr.list_tasks("all")
    # Filter to last 24 hours (rough — checks started_at string)
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

    # TODO: Add docket monitor alerts here when case-research is implemented
    # TODO: Add template refinement progress here when docx-pipeline is wired in

    post_to_channel(CHANNEL_STATUS, "\n".join(lines))
    log.info("Morning digest posted")


def start_digest_scheduler():
    """Run the digest at the configured time each day."""
    import time as _time

    def scheduler_loop():
        last_run_date = None
        while True:
            now = datetime.now()
            today = now.date()
            target = now.replace(hour=DIGEST_HOUR, minute=DIGEST_MINUTE,
                                 second=0, microsecond=0)

            if now >= target and last_run_date != today:
                try:
                    run_digest()
                except Exception as e:
                    log.error(f"Digest failed: {e}", exc_info=True)
                last_run_date = today

            # Check every 60 seconds
            _time.sleep(60)

    thread = threading.Thread(target=scheduler_loop, daemon=True)
    thread.start()
    log.info(f"Digest scheduler started (daily at {DIGEST_HOUR:02d}:{DIGEST_MINUTE:02d})")


# ── Main ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    log.info("Starting Claude bot (Socket Mode)")

    # Start the morning digest scheduler
    start_digest_scheduler()

    # Post startup message
    try:
        post_to_channel(CHANNEL_STATUS,
                        f"Claude bot online. ({datetime.now().strftime('%H:%M')})")
    except Exception as e:
        log.warning(f"Couldn't post startup message: {e}")

    handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    handler.start()
