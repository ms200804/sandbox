"""
Tool definitions and implementations for the Enlightenment bot.

Each tool is defined as a Claude API tool schema + an implementation function.
The bot's Claude instance calls these via tool_use; execute_tool() dispatches.
"""

import json
import subprocess
import os
from pathlib import Path
from datetime import datetime

# Root of the sandbox repo (relative to this file's location)
SANDBOX_ROOT = Path(__file__).parent.parent.parent
ADVERSARIAL_SIM_DIR = SANDBOX_ROOT / "projects" / "adversarial-sim"
CASE_RESEARCH_DIR = SANDBOX_ROOT / "projects" / "case-research"

# ── Tool Schemas (Claude API format) ────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "run_adversarial_sim",
        "description": (
            "Run an adversarial simulation on a legal argument. "
            "Provide either a scenario file path (relative to adversarial-sim/scenarios/) "
            "or an inline argument description. Returns immediately with a task ID; "
            "results are posted to the Slack thread when complete."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "scenario_file": {
                    "type": "string",
                    "description": "Path to scenario file, e.g. 'example.md'",
                },
                "inline_argument": {
                    "type": "string",
                    "description": (
                        "If no scenario file, describe the argument inline. "
                        "Include: forum, position, context, and any key authorities."
                    ),
                },
                "model": {
                    "type": "string",
                    "description": "Claude model to use (default: claude-sonnet-4-6)",
                    "default": "claude-sonnet-4-6",
                },
                "phase1_only": {
                    "type": "boolean",
                    "description": "Run only Phase 1 (parallel analysis), skip synthesis",
                    "default": False,
                },
            },
        },
    },
    {
        "name": "search_cases",
        "description": (
            "Search CourtListener for case law. Returns structured JSON with "
            "case name, citation, court, date, holding summary, and key quotes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search terms (e.g., 'TVPA private right of action')",
                },
                "court": {
                    "type": "string",
                    "description": "Court filter (e.g., 'scotus', 'ca2', 'ca5', 'nysd')",
                },
                "date_after": {
                    "type": "string",
                    "description": "Only cases after this date (ISO format, e.g. '2020-01-01')",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default 10)",
                    "default": 10,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "lookup_citation",
        "description": (
            "Look up a specific case by citation string. "
            "Returns the full opinion text and metadata."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "citation": {
                    "type": "string",
                    "description": "Citation string, e.g. '546 U.S. 440' or '68 F.3d 554'",
                },
            },
            "required": ["citation"],
        },
    },
    {
        "name": "shepardize",
        "description": (
            "Check citations for negative treatment. Takes a list of citations "
            "and checks CourtListener's citation network for overrulings, "
            "distinguishings, and other negative treatment."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "citations": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of citation strings to check",
                },
            },
            "required": ["citations"],
        },
    },
    {
        "name": "check_task",
        "description": "Check the status of a running or completed background task.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "Task ID returned when the task was started",
                },
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "list_tasks",
        "description": "List all running and recently completed tasks.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["all", "running", "completed", "failed"],
                    "default": "all",
                },
            },
        },
    },
    {
        "name": "read_file",
        "description": (
            "Read a file from the sandbox repo. Path is relative to the sandbox root. "
            "For long files, returns first 200 lines with a note about truncation."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path relative to sandbox root",
                },
                "tail": {
                    "type": "boolean",
                    "description": "If true, return last 200 lines instead of first",
                    "default": False,
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "run_shell",
        "description": (
            "Run a sandboxed shell command on enlightenment. "
            "Allowed: ls, cat, head, tail, wc, git, find, grep, df, uptime, ps. "
            "Blocked: rm, mv, sudo, curl, wget, pip, apt, and anything destructive."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Shell command to run",
                },
            },
            "required": ["command"],
        },
    },
]


# ── Tool Implementations ────────────────────────────────────────────

ALLOWED_SHELL_COMMANDS = {"ls", "cat", "head", "tail", "wc", "git", "find",
                          "grep", "df", "uptime", "ps", "echo", "date", "pwd"}
BLOCKED_SHELL_COMMANDS = {"rm", "mv", "sudo", "curl", "wget", "pip", "apt",
                          "apt-get", "kill", "killall", "reboot", "shutdown",
                          "chmod", "chown", "mkfs", "dd", "python", "node"}


def execute_tool(name: str, input_data: dict, task_mgr,
                 post_callback_factory=None) -> str:
    """
    Dispatch a tool call to its implementation.

    post_callback_factory: optional callable(channel) -> callback(task)
        Used by task-launching tools to post results to the right Slack channel.
    """
    handlers = {
        "run_adversarial_sim": _run_adversarial_sim,
        "search_cases": _search_cases,
        "lookup_citation": _lookup_citation,
        "shepardize": _shepardize,
        "check_task": _check_task,
        "list_tasks": _list_tasks,
        "read_file": _read_file,
        "run_shell": _run_shell,
    }

    handler = handlers.get(name)
    if not handler:
        return f"Unknown tool: {name}"

    # Pass task_mgr and callback factory to handlers that need them
    if name == "run_adversarial_sim":
        return handler(input_data, task_mgr, post_callback_factory)
    if name in ("check_task", "list_tasks"):
        return handler(input_data, task_mgr)
    return handler(input_data)


def _run_adversarial_sim(input_data: dict, task_mgr,
                         post_callback_factory=None) -> str:
    """Launch an adversarial sim as a background task."""
    scenario_file = input_data.get("scenario_file")
    inline = input_data.get("inline_argument")
    model = input_data.get("model", "claude-sonnet-4-6")
    phase1_only = input_data.get("phase1_only", False)

    if scenario_file:
        scenario_path = ADVERSARIAL_SIM_DIR / "scenarios" / scenario_file
        if not scenario_path.exists():
            available = [f.name for f in (ADVERSARIAL_SIM_DIR / "scenarios").glob("*.md")]
            return f"Scenario not found: {scenario_file}. Available: {available}"
    elif inline:
        # Write inline argument to a temp scenario file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        scenario_path = ADVERSARIAL_SIM_DIR / "scenarios" / f"inline_{timestamp}.md"
        scenario_path.write_text(f"# Inline Scenario\n\n{inline}")
    else:
        return "Provide either scenario_file or inline_argument."

    cmd = ["python", str(ADVERSARIAL_SIM_DIR / "sim.py"), str(scenario_path)]
    if model != "claude-sonnet-4-6":
        cmd.extend(["--model", model])
    if phase1_only:
        cmd.append("--phase1-only")

    # Set up callback to post results to #adversarial when done
    on_complete = None
    if post_callback_factory:
        on_complete = post_callback_factory("adversarial")

    task_id = task_mgr.launch(
        name=f"adversarial-sim:{scenario_path.stem}",
        command=cmd,
        cwd=str(ADVERSARIAL_SIM_DIR),
        on_complete=on_complete,
    )

    return (
        f"Adversarial sim launched (task_id: {task_id}). "
        f"Scenario: {scenario_path.name}, Model: {model}. "
        f"This will take a few minutes — I'll post results to #adversarial when done. "
        f"Use check_task to monitor progress."
    )


def _search_cases(input_data: dict) -> str:
    """Search CourtListener for cases."""
    # TODO: Implement with actual CourtListener API
    query = input_data.get("query", "")
    court = input_data.get("court")
    date_after = input_data.get("date_after")
    limit = input_data.get("limit", 10)

    return json.dumps({
        "status": "not_implemented",
        "message": (
            f"CourtListener search not yet implemented. "
            f"Query: '{query}', Court: {court}, After: {date_after}, Limit: {limit}. "
            f"Need to implement cl_client.py with httpx first."
        ),
    })


def _lookup_citation(input_data: dict) -> str:
    """Look up a case by citation."""
    # TODO: Implement
    return json.dumps({
        "status": "not_implemented",
        "message": f"Citation lookup not yet implemented. Citation: {input_data.get('citation')}",
    })


def _shepardize(input_data: dict) -> str:
    """Check citations for negative treatment."""
    # TODO: Implement
    citations = input_data.get("citations", [])
    return json.dumps({
        "status": "not_implemented",
        "message": f"Shepardize not yet implemented. Citations: {citations}",
    })


def _check_task(input_data: dict, task_mgr) -> str:
    """Check status of a background task."""
    task_id = input_data.get("task_id")
    status = task_mgr.get_status(task_id)
    if not status:
        return f"No task found with ID: {task_id}"
    return json.dumps(status)


def _list_tasks(input_data: dict, task_mgr) -> str:
    """List all tasks."""
    status_filter = input_data.get("status", "all")
    tasks = task_mgr.list_tasks(status_filter)
    if not tasks:
        return "No tasks found."
    return json.dumps(tasks, indent=2)


def _read_file(input_data: dict) -> str:
    """Read a file from the sandbox repo."""
    rel_path = input_data.get("path", "")
    file_path = (SANDBOX_ROOT / rel_path).resolve()

    # Security: ensure path is within sandbox
    if not str(file_path).startswith(str(SANDBOX_ROOT.resolve())):
        return "Access denied: path is outside the sandbox repo."

    if not file_path.exists():
        return f"File not found: {rel_path}"

    if file_path.is_dir():
        entries = sorted(f.name for f in file_path.iterdir())
        return f"Directory listing ({len(entries)} items):\n" + "\n".join(entries)

    try:
        content = file_path.read_text()
    except UnicodeDecodeError:
        return f"Binary file, can't display: {rel_path}"

    lines = content.splitlines()
    tail = input_data.get("tail", False)
    if len(lines) > 200:
        if tail:
            shown = "\n".join(lines[-200:])
            return f"(showing last 200 of {len(lines)} lines)\n\n{shown}"
        else:
            shown = "\n".join(lines[:200])
            return f"{shown}\n\n(truncated — {len(lines)} total lines, showing first 200)"

    return content


def _run_shell(input_data: dict) -> str:
    """Run a sandboxed shell command."""
    command = input_data.get("command", "").strip()
    if not command:
        return "No command provided."

    # Extract the base command (first word)
    base_cmd = command.split()[0].split("/")[-1]  # handle /usr/bin/ls etc.

    if base_cmd in BLOCKED_SHELL_COMMANDS:
        return f"Blocked: '{base_cmd}' is not allowed for safety."

    if base_cmd not in ALLOWED_SHELL_COMMANDS:
        return (
            f"Unknown command: '{base_cmd}'. "
            f"Allowed: {', '.join(sorted(ALLOWED_SHELL_COMMANDS))}. "
            f"If you need this command, ask Matt to add it to the allowlist."
        )

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(SANDBOX_ROOT),
        )
        output = result.stdout
        if result.stderr:
            output += f"\n(stderr: {result.stderr})"
        if result.returncode != 0:
            output += f"\n(exit code: {result.returncode})"

        # Truncate very long output
        if len(output) > 4000:
            output = output[:4000] + f"\n\n(truncated — {len(output)} chars total)"

        return output or "(no output)"

    except subprocess.TimeoutExpired:
        return "Command timed out (30s limit)."
    except Exception as e:
        return f"Error running command: {e}"
