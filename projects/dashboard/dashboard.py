#!/usr/bin/env python3
"""
Sandbox Dashboard — terminal UI for monitoring tasks, library, and system status.

Run locally on the server, or remotely over Tailscale.

Usage:
    python dashboard.py                           # local mode
    python dashboard.py --remote enlightenment    # remote via Tailscale
    python dashboard.py --remote 100.x.y.z:7433   # remote with explicit host:port

Requires: textual (pip install textual)
Remote mode requires status_server.py running on the server.
"""

import argparse
import json
import subprocess
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

# Remote mode: set by CLI args, used by data functions
_REMOTE_URL: str | None = None

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
        with open("/proc/loadavg") as f:
            parts = f.read().split()
            print(f"  Load: {parts[0]} {parts[1]} {parts[2]}")
    except Exception:
        pass

    try:
        with open("/proc/meminfo") as f:
            mi = {}
            for line in f:
                k, v = line.split(":")
                mi[k.strip()] = int(v.strip().split()[0])
            total = mi["MemTotal"] / 1048576
            avail = mi.get("MemAvailable", mi.get("MemFree", 0)) / 1048576
            print(f"  RAM: {total - avail:.1f}/{total:.1f} GB ({int((total-avail)/total*100)}%)")
    except Exception:
        pass

    try:
        import os as _os
        print(f"  CPUs: {_os.cpu_count()}")
    except Exception:
        pass

    try:
        temp_path = Path("/sys/class/thermal/thermal_zone0/temp")
        if temp_path.exists():
            print(f"  Temp: {int(temp_path.read_text().strip()) / 1000:.0f}C")
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


# ── Remote Fetch ───────────────────────────────────────────────────

_remote_cache: dict = {}
_remote_cache_ts: float = 0


def _fetch_remote() -> dict:
    """Fetch all status data from the remote server, with a 2s cache."""
    global _remote_cache, _remote_cache_ts
    now = time.time()
    if now - _remote_cache_ts < 2 and _remote_cache:
        return _remote_cache
    try:
        req = urllib.request.Request(f"{_REMOTE_URL}/status", headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            _remote_cache = json.loads(resp.read())
            _remote_cache_ts = now
            return _remote_cache
    except Exception as e:
        return {"error": str(e), "system": {}, "tasks": [], "library": {}}


# ── Data Sources ────────────────────────────────────────────────────

SANDBOX_ROOT = Path(__file__).parent.parent.parent


def get_tasks() -> list[dict]:
    if _REMOTE_URL:
        return _fetch_remote().get("tasks", [])
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
    if _REMOTE_URL:
        return _fetch_remote().get("library", {})
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
    if _REMOTE_URL:
        return _fetch_remote().get("system", {})
    status = {}
    try:
        result = subprocess.run(["uptime", "-p"], capture_output=True, text=True)
        status["uptime"] = result.stdout.strip()
    except Exception:
        status["uptime"] = "unknown"

    # Load average
    try:
        with open("/proc/loadavg") as f:
            parts = f.read().split()
            status["load"] = f"{parts[0]} {parts[1]} {parts[2]}"
    except Exception:
        status["load"] = "?"

    # RAM
    try:
        with open("/proc/meminfo") as f:
            meminfo = {}
            for line in f:
                key, val = line.split(":")
                meminfo[key.strip()] = int(val.strip().split()[0])  # kB
            total_gb = meminfo["MemTotal"] / 1048576
            avail_gb = meminfo.get("MemAvailable", meminfo.get("MemFree", 0)) / 1048576
            used_gb = total_gb - avail_gb
            pct = int(used_gb / total_gb * 100) if total_gb > 0 else 0
            status["ram"] = f"{used_gb:.1f}/{total_gb:.1f}GB ({pct}%)"
    except Exception:
        status["ram"] = "?"

    # CPU count
    try:
        import os as _os
        status["cpus"] = str(_os.cpu_count() or "?")
    except Exception:
        status["cpus"] = "?"

    # CPU temp (thermal zones)
    try:
        temp_path = Path("/sys/class/thermal/thermal_zone0/temp")
        if temp_path.exists():
            temp_c = int(temp_path.read_text().strip()) / 1000
            status["temp"] = f"{temp_c:.0f}C"
        else:
            status["temp"] = None
    except Exception:
        status["temp"] = None

    # Disk
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
        line1_parts = [
            f"uptime: {s.get('uptime', '?')}",
            f"cpus: {s.get('cpus', '?')}",
            f"load: {s.get('load', '?')}",
        ]
        if s.get("temp"):
            line1_parts.append(f"temp: {s['temp']}")
        line2_parts = [
            f"ram: {s.get('ram', '?')}",
            f"disk: {s.get('disk_used', '?')} used ({s.get('disk_avail', '?')} free)",
            f"bot: {s.get('bot', '?')}",
        ]
        self.update("  " + "  │  ".join(line1_parts) + "\n  " + "  │  ".join(line2_parts))


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
    #system { height: 4; }
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
    parser = argparse.ArgumentParser(description="Sandbox dashboard")
    parser.add_argument("--remote", metavar="HOST",
                        help="Connect to remote status server (e.g., 'enlightenment', "
                             "'100.x.y.z', or 'host:port'). Requires status_server.py "
                             "running on the server. Default port: 7433.")
    parser.add_argument("--refresh", type=int, default=10,
                        help="Refresh interval in seconds (default: 10)")
    args = parser.parse_args()

    if args.remote:
        host = args.remote
        if ":" not in host or host.count(":") == 0:
            host = f"{host}:7433"
        if not host.startswith("http"):
            host = f"http://{host}"
        _REMOTE_URL = host
        print(f"Connecting to {_REMOTE_URL}...")
        # Quick health check
        try:
            req = urllib.request.Request(f"{_REMOTE_URL}/health")
            with urllib.request.urlopen(req, timeout=5) as resp:
                print(f"Server OK: {resp.read().decode()}")
        except Exception as e:
            print(f"WARNING: Could not reach server: {e}")
            print("Make sure status_server.py is running on the remote host.")

    app = DashboardApp()
    app.run()
