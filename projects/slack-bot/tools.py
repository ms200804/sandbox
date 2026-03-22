"""
Tool definitions and implementations for the Claude Slack bot.

Each tool is defined as a Claude API tool schema + an implementation function.
The bot's Claude instance calls these via tool_use; execute_tool() dispatches.
"""

import json
import subprocess
import os
import sys
from pathlib import Path
from datetime import datetime

# Root of the sandbox repo (relative to this file's location)
SANDBOX_ROOT = Path(__file__).parent.parent.parent
ADVERSARIAL_SIM_DIR = SANDBOX_ROOT / "projects" / "adversarial-sim"
CASE_RESEARCH_DIR = SANDBOX_ROOT / "projects" / "case-research"

# Add case-research to path so we can import library
sys.path.insert(0, str(CASE_RESEARCH_DIR))
import library as research_library
from citation_extractor import extract_citations as _parse_citations, extract_from_file, auto_categorize

# ── Tool Schemas (Claude API format) ────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "run_adversarial_sim",
        "description": (
            "Run an adversarial simulation on a legal argument. "
            "Provide either a scenario file path (relative to adversarial-sim/scenarios/) "
            "or an inline argument description. The orchestrator will ask clarifying "
            "questions before running unless force=true. Returns immediately with a task ID; "
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
                        "Can be anything from a bare legal question to a full brief. "
                        "The orchestrator will classify the input level and ask "
                        "clarifying questions if needed."
                    ),
                },
                "forum": {
                    "type": "string",
                    "description": "Court/forum (e.g., 'SDNY', '9th Cir.', 'CDCA')",
                },
                "calibration": {
                    "type": "string",
                    "enum": ["standard", "aggressive", "elite"],
                    "description": "Adversary calibration level (default: aggressive)",
                    "default": "aggressive",
                },
                "force": {
                    "type": "boolean",
                    "description": (
                        "If true, skip clarifying questions and run immediately "
                        "with reasonable assumptions. Default: false (ask first)."
                    ),
                    "default": False,
                },
                "passes": {
                    "type": "integer",
                    "description": "Number of full passes (default: 1)",
                    "default": 1,
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
        "name": "find_similar_cases",
        "description": (
            "Find cases similar to a specific case or set of cases. "
            "Uses CourtListener's citation network to find opinions that cite "
            "the same authorities, address the same legal issues, or have "
            "similar fact patterns. Use this when the user says 'more like this' "
            "or 'find similar' after reviewing research results."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "reference_case": {
                    "type": "string",
                    "description": (
                        "Citation or CL ID of the case to find similar cases to. "
                        "Can also be a case name if unambiguous."
                    ),
                },
                "aspect": {
                    "type": "string",
                    "description": (
                        "What aspect to find similar on: 'holding' (same legal issue), "
                        "'facts' (similar fact pattern), 'cited_by' (cases citing the same "
                        "authorities), or 'all' (default)"
                    ),
                    "default": "all",
                },
                "court": {
                    "type": "string",
                    "description": "Court filter for similar cases",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default 10)",
                    "default": 10,
                },
            },
            "required": ["reference_case"],
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
        "name": "library_search",
        "description": (
            "Search the research library for previously researched topics. "
            "Returns cached research results if available, with staleness info. "
            "Use this BEFORE running a new search — if we've already researched "
            "the topic, no need to hit CourtListener again."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search term (e.g., 'tvpa', 'arbitration unconscionability', 'charging lien')",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "library_save",
        "description": (
            "Save research results to the library for future use. "
            "Auto-creates categories on the fly. Use after completing a "
            "research query to avoid re-researching the same topic."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Broad area (e.g., 'tvpa', 'arbitration', 'securities', 'employment'). Creates new categories automatically.",
                },
                "topic": {
                    "type": "string",
                    "description": "Specific topic (e.g., 'private_right_of_action', 'unconscionability', 'fee_shifting')",
                },
                "query": {
                    "type": "string",
                    "description": "The original search query",
                },
                "jurisdiction": {
                    "type": "string",
                    "description": "Target jurisdiction (e.g., 'ca9', 'ca2', 'scotus')",
                },
                "results": {
                    "type": "object",
                    "description": "The structured JSON research results to save",
                },
            },
            "required": ["category", "topic", "results"],
        },
    },
    {
        "name": "batch_lookup",
        "description": (
            "Look up multiple case citations at once. Takes a list of citations, "
            "resolves each against CourtListener, pulls full opinion text, and "
            "optionally saves to the research library under a category. "
            "Like Westlaw's batch retrieve but free."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "citations": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of citation strings (e.g., ['546 U.S. 440', '68 F.3d 554'])",
                },
                "save_to_library": {
                    "type": "boolean",
                    "description": "Save results to research library (default: true)",
                    "default": True,
                },
                "category": {
                    "type": "string",
                    "description": "Library category to save under (e.g., 'tvpa', 'arbitration')",
                },
                "topic": {
                    "type": "string",
                    "description": "Library topic name (e.g., 'key_authorities')",
                },
            },
            "required": ["citations"],
        },
    },
    {
        "name": "extract_citations",
        "description": (
            "Extract all case citations from a document (brief, memo, letter). "
            "Parses the text, finds every case citation, resolves against "
            "CourtListener for full text, and optionally saves to the library. "
            "Use this to seed the research library from existing work product."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the document (relative to sandbox root)",
                },
                "text": {
                    "type": "string",
                    "description": "Or provide raw text directly instead of a file path",
                },
                "save_to_library": {
                    "type": "boolean",
                    "description": "Save extracted citations to library (default: true)",
                    "default": True,
                },
                "category": {
                    "type": "string",
                    "description": "Library category (auto-detected from content if omitted)",
                },
            },
        },
    },
    {
        "name": "library_list",
        "description": (
            "List all categories and topics in the research library, "
            "with staleness indicators. Use to see what's available."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
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
            "Run a sandboxed shell command on the server. "
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
        "find_similar_cases": _find_similar_cases,
        "lookup_citation": _lookup_citation,
        "shepardize": _shepardize,
        "batch_lookup": _batch_lookup,
        "extract_citations": _extract_citations,
        "library_search": _library_search,
        "library_save": _library_save,
        "library_list": _library_list,
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
    forum = input_data.get("forum")
    calibration = input_data.get("calibration", "aggressive")
    force = input_data.get("force", False)
    passes = input_data.get("passes", 1)
    phase1_only = input_data.get("phase1_only", False)

    if scenario_file:
        scenario_path = ADVERSARIAL_SIM_DIR / "scenarios" / scenario_file
        if not scenario_path.exists():
            available = [f.name for f in (ADVERSARIAL_SIM_DIR / "scenarios").glob("*.md")]
            return f"Scenario not found: {scenario_file}. Available: {available}"
    elif inline:
        # Build a scenario file from the inline input
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        scenario_path = ADVERSARIAL_SIM_DIR / "scenarios" / f"inline_{timestamp}.md"

        # Compose scenario with metadata
        sections = [f"# Inline Scenario ({timestamp})"]
        if forum:
            sections.append(f"\n## Forum\n{forum}")
        sections.append(f"\n## Adversary Calibration\n{calibration}")
        sections.append(f"\n## Context\n{inline}")
        scenario_path.write_text("\n".join(sections))
    else:
        return "Provide either scenario_file or inline_argument."

    # If not forced, return clarifying questions instead of launching
    if not force and inline and not scenario_file:
        # Read the orchestrator prompt and use it to generate questions
        # For now, check for minimum required info
        missing = []
        if not forum:
            missing.append("What forum/court is this in?")

        # Detect input level to ask appropriate questions
        content = scenario_path.read_text()
        word_count = len(content.split())
        if word_count < 100:
            missing.append("Can you give me a bit more context on the facts and procedural posture?")
            missing.append("Which side are you on?")
        elif word_count < 300:
            missing.append("Any key cases you're planning to rely on?")

        if missing:
            questions = "\n".join(f"• {q}" for q in missing)
            return (
                f"Before I run this, a couple quick questions:\n\n{questions}\n\n"
                f"Or say 'just run it' and I'll make reasonable assumptions."
            )

    cmd = ["python", str(ADVERSARIAL_SIM_DIR / "sim.py"), str(scenario_path)]
    if passes > 1:
        cmd.extend(["--passes", str(passes)])
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
        f"Scenario: {scenario_path.name}, Calibration: {calibration}, "
        f"Passes: {passes}. "
        f"Running 6 agents in parallel on Opus — I'll post results "
        f"to #adversarial when done. Use check_task to monitor."
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


def _find_similar_cases(input_data: dict) -> str:
    """Find cases similar to a reference case."""
    # TODO: Implement via CL citation network
    ref = input_data.get("reference_case", "")
    aspect = input_data.get("aspect", "all")
    court = input_data.get("court")
    limit = input_data.get("limit", 10)

    return json.dumps({
        "status": "not_implemented",
        "message": (
            f"Find-similar not yet implemented. "
            f"Reference: '{ref}', Aspect: {aspect}, Court: {court}, Limit: {limit}. "
            f"Will use CL citation network: find opinions that cite the same authorities "
            f"as the reference case, filter by court/date, and rank by citation overlap."
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


def _batch_lookup(input_data: dict) -> str:
    """Look up multiple citations at once."""
    citations = input_data.get("citations", [])
    save = input_data.get("save_to_library", True)
    category = input_data.get("category", "")
    topic = input_data.get("topic", "batch_lookup")

    if not citations:
        return "No citations provided."

    # TODO: Resolve each citation against CL
    # For now, parse and return structured data
    results = []
    for cite_str in citations:
        parsed = _parse_citations(cite_str)
        if parsed:
            cit = parsed[0]
            results.append({
                "input": cite_str,
                "parsed": cit.standard_cite,
                "case_name": cit.case_name or "(needs CL lookup)",
                "year": cit.year,
                "resolved": False,
                "status": "CL client not yet implemented — citation parsed but not resolved",
            })
        else:
            results.append({
                "input": cite_str,
                "parsed": None,
                "status": "Could not parse citation format",
            })

    output = {
        "total": len(citations),
        "parsed": sum(1 for r in results if r.get("parsed")),
        "resolved": 0,  # TODO: will be non-zero once CL client works
        "results": results,
        "note": "CL client not yet implemented. Citations parsed but full text not pulled.",
    }

    if save and category:
        research_library.save_research(
            category=category, topic=topic, results=output,
            query=f"Batch lookup: {len(citations)} citations",
        )
        output["saved_to"] = f"{category}/{topic}"

    return json.dumps(output, indent=2)


def _extract_citations(input_data: dict) -> str:
    """Extract citations from a document."""
    file_path = input_data.get("file_path")
    text = input_data.get("text")
    save = input_data.get("save_to_library", True)
    category = input_data.get("category", "")

    if file_path:
        full_path = (SANDBOX_ROOT / file_path).resolve()
        if not str(full_path).startswith(str(SANDBOX_ROOT.resolve())):
            return "Access denied: path is outside the sandbox repo."
        if not full_path.exists():
            return f"File not found: {file_path}"
        text = full_path.read_text(errors='replace')
        source = file_path
    elif text:
        source = "inline text"
    else:
        return "Provide either file_path or text."

    citations = _parse_citations(text)

    if not citations:
        return "No citations found in the document."

    # Auto-categorize if no category specified
    if not category:
        categories = auto_categorize(citations, text)
        category = categories[0]

    results = {
        "source": source,
        "citation_count": len(citations),
        "citations": [c.to_dict() for c in citations],
        "auto_category": category,
        "note": "Citations parsed. CL resolution pending client implementation.",
    }

    if save:
        topic = Path(file_path).stem if file_path else "extracted"
        research_library.save_research(
            category=category, topic=topic, results=results,
            query=f"Citation extraction from {source}",
        )
        results["saved_to"] = f"{category}/{topic}"

    return json.dumps(results, indent=2)


def _library_search(input_data: dict) -> str:
    """Search the research library for cached results."""
    query = input_data.get("query", "")
    matches = research_library.search_library(query)
    if not matches:
        return json.dumps({
            "found": False,
            "message": f"No library entries match '{query}'. Run a fresh search.",
        })

    return json.dumps({
        "found": True,
        "matches": matches,
        "message": f"Found {len(matches)} matching topic(s). Stale entries may need refresh.",
    }, indent=2)


def _library_save(input_data: dict) -> str:
    """Save research results to the library."""
    category = input_data.get("category", "")
    topic = input_data.get("topic", "")
    results = input_data.get("results", {})
    query = input_data.get("query", "")
    jurisdiction = input_data.get("jurisdiction", "")

    if not category or not topic:
        return "Need both category and topic to save."

    path = research_library.save_research(
        category=category,
        topic=topic,
        results=results,
        query=query,
        jurisdiction=jurisdiction,
    )
    return f"Saved to library: {category}/{topic} ({path.name})"


def _library_list(input_data: dict) -> str:
    """List all library categories and topics."""
    categories = research_library.list_categories()
    if not categories:
        return "Research library is empty. Run some searches to populate it."

    stale = research_library.list_stale()
    stale_keys = {s["key"] for s in stale}

    lines = []
    for cat, topics in sorted(categories.items()):
        lines.append(f"**{cat}:**")
        for topic in sorted(topics):
            key = research_library._topic_key(cat, topic)
            marker = " (stale)" if key in stale_keys else ""
            lines.append(f"  • {topic}{marker}")

    return "\n".join(lines)


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
