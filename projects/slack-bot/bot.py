#!/usr/bin/env python3
"""
Enlightenment Slack Bot

Conversational interface to tools running on the enlightenment box.
Receives messages via Slack Socket Mode, routes to Claude API with tools,
posts responses back to Slack.

Usage:
    python bot.py

Requires env vars: SLACK_BOT_TOKEN, SLACK_APP_TOKEN, ANTHROPIC_API_KEY
"""

import json
import logging
import os
import threading
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
log = logging.getLogger("enlightenment")

# ── Configuration ───────────────────────────────────────────────────
CLAUDE_MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 4096
SYSTEM_PROMPT = """You are Enlightenment, a helpful assistant running on a headless Debian \
server. You help Matt Schmidt, a solo litigation attorney, with legal research, argument \
testing, and task management.

You have access to tools for:
- Running adversarial simulations on legal arguments
- Searching CourtListener for case law
- Checking on running tasks
- Reading files from the sandbox repo
- Running sandboxed shell commands

Matt will message you from his phone via Slack. Expect casual, typo-laden messages. \
Interpret intent generously. Respond conversationally but concisely — he's reading on \
a small screen.

When a task will take more than a few seconds, acknowledge immediately and explain \
you'll post results when done. Don't make him wait for a loading spinner.

For legal research results, lead with the bottom line, then supporting detail. \
Matt is a practicing litigator — you don't need to explain basic legal concepts.

If you're unsure what he wants, ask a short clarifying question rather than guessing wrong."""

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
                result = execute_tool(tool_use.name, tool_use.input, task_mgr)
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
    import re
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


# ── Main ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    log.info("Starting Enlightenment bot (Socket Mode)")
    handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    handler.start()
