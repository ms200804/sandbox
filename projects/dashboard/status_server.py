#!/usr/bin/env python3
"""
Status Server — lightweight HTTP API for remote dashboard access.

Runs on the server (enlightenment), serves system/task/library status
as JSON. The dashboard TUI connects to this over Tailscale.

Usage:
    python status_server.py                # default port 7433
    python status_server.py --port 8080    # custom port
    python status_server.py --bind 0.0.0.0 # listen on all interfaces
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

SANDBOX_ROOT = Path(__file__).parent.parent.parent

# Import data sources from dashboard module
sys.path.insert(0, str(Path(__file__).parent))


def get_tasks() -> list[dict]:
    """Get task status."""
    state_file = SANDBOX_ROOT / "projects" / "slack-bot" / ".task_state.json"
    if state_file.exists():
        try:
            return json.loads(state_file.read_text())
        except Exception:
            pass

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
    import os
    status = {}

    try:
        result = subprocess.run(["uptime", "-p"], capture_output=True, text=True)
        status["uptime"] = result.stdout.strip()
    except Exception:
        status["uptime"] = "unknown"

    try:
        with open("/proc/loadavg") as f:
            parts = f.read().split()
            status["load"] = f"{parts[0]} {parts[1]} {parts[2]}"
    except Exception:
        status["load"] = "?"

    try:
        with open("/proc/meminfo") as f:
            meminfo = {}
            for line in f:
                key, val = line.split(":")
                meminfo[key.strip()] = int(val.strip().split()[0])
            total_gb = meminfo["MemTotal"] / 1048576
            avail_gb = meminfo.get("MemAvailable", meminfo.get("MemFree", 0)) / 1048576
            used_gb = total_gb - avail_gb
            pct = int(used_gb / total_gb * 100) if total_gb > 0 else 0
            status["ram"] = f"{used_gb:.1f}/{total_gb:.1f}GB ({pct}%)"
    except Exception:
        status["ram"] = "?"

    status["cpus"] = str(os.cpu_count() or "?")

    try:
        temp_path = Path("/sys/class/thermal/thermal_zone0/temp")
        if temp_path.exists():
            temp_c = int(temp_path.read_text().strip()) / 1000
            status["temp"] = f"{temp_c:.0f}C"
        else:
            status["temp"] = None
    except Exception:
        status["temp"] = None

    try:
        result = subprocess.run(["df", "-h", "/"], capture_output=True, text=True)
        line = result.stdout.strip().splitlines()[-1].split()
        status["disk_used"] = line[4]
        status["disk_avail"] = line[3]
    except Exception:
        status["disk_used"] = "?"

    try:
        result = subprocess.run(
            ["systemctl", "is-active", "claude-bot"],
            capture_output=True, text=True,
        )
        status["bot"] = result.stdout.strip()
    except Exception:
        status["bot"] = "unknown"

    # Hostname
    try:
        import socket
        status["hostname"] = socket.gethostname()
    except Exception:
        status["hostname"] = "?"

    return status


class StatusHandler(BaseHTTPRequestHandler):
    """Serves dashboard status data as JSON."""

    def do_GET(self):
        if self.path == "/status" or self.path == "/":
            data = {
                "timestamp": datetime.now().isoformat(),
                "system": get_system_status(),
                "tasks": get_tasks(),
                "library": get_library_status(),
            }
            self._json_response(200, data)
        elif self.path == "/system":
            self._json_response(200, get_system_status())
        elif self.path == "/tasks":
            self._json_response(200, get_tasks())
        elif self.path == "/library":
            self._json_response(200, get_library_status())
        elif self.path == "/health":
            self._json_response(200, {"status": "ok"})
        else:
            self._json_response(404, {"error": "not found"})

    def _json_response(self, code, data):
        body = json.dumps(data, indent=2).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        # Quiet logging — just timestamp + path
        pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dashboard status server")
    parser.add_argument("--port", type=int, default=7433, help="Port (default: 7433)")
    parser.add_argument("--bind", default="0.0.0.0", help="Bind address (default: 0.0.0.0)")
    args = parser.parse_args()

    server = HTTPServer((args.bind, args.port), StatusHandler)
    print(f"Status server listening on {args.bind}:{args.port}")
    print(f"  http://localhost:{args.port}/status")
    print(f"  Endpoints: /status, /system, /tasks, /library, /health")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()
