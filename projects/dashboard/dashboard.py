#!/usr/bin/env python3
"""
Sandbox Dashboard — terminal UI for monitoring tasks, library, and system status.

Run in a tmux pane alongside Claude Code for a heads-up display of
what's happening on the box.

Usage:
    python dashboard.py
    python dashboard.py --refresh 5  # refresh every 5 seconds

Requires: textual (pip install textual)
"""

import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    from textual.app import App, ComposeResult
    from textual.containers import Horizontal, Vertical
    from textual.widgets import Header, Footer, Static, DataTable, Log
    from textual.timer import Timer
except ImportError:
    print("textual not installed. Run: uv pip install textual")
    print("For now, here's a plain-text status:\n")

    # Fallback: plain-text status dump
    SANDBOX_ROOT = Path(__file__).parent.parent.parent
    TASK_MGR_IMPORT = SANDBOX_ROOT / "projects" / "slack-bot"
    sys.path.insert(0, str(TASK_MGR_IMPORT))
    RESEARCH_DIR = SANDBOX_ROOT / "projects" / "case-research"
    sys.path.insert(0, str(RESEARCH_DIR))

    print("=== RESEARCH LIBRARY ===")
    try:
        import library
        categories = library.list_categories()
        if categories:
            for cat, topics in sorted(categories.items()):
                stale_list = [t for t in topics if library.is_stale(cat, t)]
                print(f"  {cat}: {', '.join(topics)}"
                      + (f" ({len(stale_list)} stale)" if stale_list else ""))
        else:
            print("  (empty)")
    except Exception as e:
        print(f"  Error: {e}")

    print("\n=== SYSTEM ===")
    try:
        uptime = subprocess.run(["uptime", "-p"], capture_output=True, text=True).stdout.strip()
        print(f"  {uptime}")
    except Exception:
        pass

    try:
        df = subprocess.run(["df", "-h", "/"], capture_output=True, text=True).stdout
        for line in df.strip().splitlines()[1:]:
            parts = line.split()
            print(f"  Disk: {parts[4]} used ({parts[3]} available)")
    except Exception:
        pass

    sys.exit(0)


# ── Data Sources ────────────────────────────────────────────────────

SANDBOX_ROOT = Path(__file__).parent.parent.parent


def get_tasks() -> list[dict]:
    """Get task status from the task manager (reads shared state)."""
    # Task manager runs in the bot process — we read its state file if available
    state_file = SANDBOX_ROOT / "projects" / "slack-bot" / ".task_state.json"
    if state_file.exists():
        try:
            return json.loads(state_file.read_text())
        except Exception:
            pass

    # Fallback: check for recent output directories
    tasks = []
    for project in ["adversarial-sim", "case-research", "docx-pipeline"]:
        output_dir = SANDBOX_ROOT / "projects" / project / "output"
        if output_dir.exists():
            for d in sorted(output_dir.iterdir(), reverse=True)[:3]:
                if d.is_dir():
                    summary = d / "summary.md"
                    tasks.append({
                        "name": f"{project}:{d.name}",
                        "status": "completed" if summary.exists() else "unknown",
                        "finished_at": datetime.fromtimestamp(d.stat().st_mtime).isoformat(),
                    })
    return tasks


def get_library_status() -> dict:
    """Get research library summary."""
    sys.path.insert(0, str(SANDBOX_ROOT / "projects" / "case-research"))
    try:
        import library
        categories = library.list_categories()
        stale = library.list_stale()
        return {
            "categories": categories,
            "total_topics": sum(len(t) for t in categories.values()),
            "stale_count": len(stale),
        }
    except Exception as e:
        return {"error": str(e)}


def get_system_status() -> dict:
    """Get system health info."""
    status = {}
    try:
        result = subprocess.run(["uptime", "-p"], capture_output=True, text=True)
        status["uptime"] = result.stdout.strip()
    except Exception:
        status["uptime"] = "unknown"

    try:
        result = subprocess.run(["df", "-h", "/"], capture_output=True, text=True)
        line = result.stdout.strip().splitlines()[-1].split()
        status["disk_used"] = line[4]
        status["disk_avail"] = line[3]
    except Exception:
        status["disk_used"] = "?"

    # Check if bot is running
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "claude-bot"],
            capture_output=True, text=True,
        )
        status["bot"] = result.stdout.strip()
    except Exception:
        status["bot"] = "unknown"

    return status


# ── TUI App ─────────────────────────────────────────────────────────

class TaskPanel(Static):
    """Shows running and recent tasks."""

    def refresh_content(self):
        tasks = get_tasks()
        if not tasks:
            self.update("  No recent tasks.")
            return

        lines = []
        for t in tasks[:8]:
            status = t.get("status", "?")
            icon = {"running": "●", "completed": "✓", "failed": "✗"}.get(status, "○")
            name = t.get("name", "unknown")[:40]
            lines.append(f"  {icon} {name:<42} [{status}]")

        self.update("\n".join(lines))


class LibraryPanel(Static):
    """Shows research library categories."""

    def refresh_content(self):
        lib = get_library_status()
        if "error" in lib:
            self.update(f"  Error: {lib['error']}")
            return

        categories = lib.get("categories", {})
        if not categories:
            self.update("  (empty — run some research to populate)")
            return

        lines = []
        for cat, topics in sorted(categories.items()):
            lines.append(f"  {cat} ({len(topics)})")
            for topic in sorted(topics)[:5]:
                lines.append(f"    • {topic}")
            if len(topics) > 5:
                lines.append(f"    ... +{len(topics) - 5} more")

        total = lib.get("total_topics", 0)
        stale = lib.get("stale_count", 0)
        lines.append(f"\n  {total} topics, {stale} stale")
        self.update("\n".join(lines))


class SystemPanel(Static):
    """Shows system health."""

    def refresh_content(self):
        s = get_system_status()
        parts = [
            f"uptime: {s.get('uptime', '?')}",
            f"disk: {s.get('disk_used', '?')} used",
            f"bot: {s.get('bot', '?')}",
        ]
        self.update("  " + "  │  ".join(parts))


class DashboardApp(App):
    """Main dashboard application."""

    CSS = """
    Screen {
        layout: vertical;
    }
    .panel-title {
        background: $accent;
        color: $text;
        padding: 0 1;
        text-style: bold;
    }
    .panel-content {
        height: auto;
        min-height: 3;
        padding: 0 1;
    }
    #tasks { height: 1fr; }
    #middle { height: 1fr; }
    #system { height: 3; }
    """

    TITLE = "sandbox"
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("  TASKS", classes="panel-title")
        yield TaskPanel(id="tasks", classes="panel-content")
        yield Static("  LIBRARY", classes="panel-title")
        yield LibraryPanel(id="library", classes="panel-content")
        yield Static("  SYSTEM", classes="panel-title")
        yield SystemPanel(id="system", classes="panel-content")
        yield Footer()

    def on_mount(self) -> None:
        self.action_refresh()
        self.set_interval(10, self.action_refresh)

    def action_refresh(self) -> None:
        self.query_one("#tasks", TaskPanel).refresh_content()
        self.query_one("#library", LibraryPanel).refresh_content()
        self.query_one("#system", SystemPanel).refresh_content()


if __name__ == "__main__":
    app = DashboardApp()
    app.run()
