"""
Simple background task manager for the Enlightenment bot.

Tracks tasks launched by tool calls (adversarial sims, research queries, etc.).
Tasks run as subprocesses; status is tracked in memory with optional
callback for posting results to Slack when complete.
"""

import subprocess
import threading
import uuid
import logging
from dataclasses import dataclass, field
from datetime import datetime

log = logging.getLogger("enlightenment.tasks")


@dataclass
class Task:
    id: str
    name: str
    command: list[str]
    cwd: str
    status: str  # "running", "completed", "failed"
    started_at: str
    finished_at: str | None = None
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    on_complete: object = None  # callback(task) when done

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "exit_code": self.exit_code,
            "stdout_lines": len(self.stdout.splitlines()) if self.stdout else 0,
            "stderr_lines": len(self.stderr.splitlines()) if self.stderr else 0,
        }


class TaskManager:
    """Manages background tasks as subprocesses."""

    def __init__(self, max_completed: int = 50):
        self.tasks: dict[str, Task] = {}
        self.lock = threading.Lock()
        self.max_completed = max_completed

    def launch(self, name: str, command: list[str], cwd: str = ".",
               on_complete=None) -> str:
        """Launch a background task. Returns task ID."""
        task_id = uuid.uuid4().hex[:8]
        task = Task(
            id=task_id,
            name=name,
            command=command,
            cwd=cwd,
            status="running",
            started_at=datetime.now().isoformat(),
            on_complete=on_complete,
        )

        with self.lock:
            self.tasks[task_id] = task

        thread = threading.Thread(target=self._run, args=(task,), daemon=True)
        thread.start()

        log.info(f"Task {task_id} launched: {name} ({' '.join(command)})")
        return task_id

    def _run(self, task: Task):
        """Run a task in a background thread."""
        try:
            result = subprocess.run(
                task.command,
                capture_output=True,
                text=True,
                cwd=task.cwd,
                timeout=1800,  # 30 min max
            )
            task.stdout = result.stdout
            task.stderr = result.stderr
            task.exit_code = result.returncode
            task.status = "completed" if result.returncode == 0 else "failed"

        except subprocess.TimeoutExpired:
            task.status = "failed"
            task.stderr = "Task timed out (30 minute limit)"
            task.exit_code = -1

        except Exception as e:
            task.status = "failed"
            task.stderr = str(e)
            task.exit_code = -1

        task.finished_at = datetime.now().isoformat()
        log.info(f"Task {task.id} {task.status}: {task.name} (exit {task.exit_code})")

        # Fire completion callback (e.g., post to Slack)
        if task.on_complete:
            try:
                task.on_complete(task)
            except Exception as e:
                log.error(f"Task {task.id} completion callback failed: {e}")

        # Prune old completed tasks
        self._prune()

    def _prune(self):
        """Remove oldest completed tasks if over limit."""
        with self.lock:
            completed = [t for t in self.tasks.values()
                         if t.status in ("completed", "failed")]
            if len(completed) > self.max_completed:
                completed.sort(key=lambda t: t.finished_at or "")
                for t in completed[:len(completed) - self.max_completed]:
                    del self.tasks[t.id]

    def get_status(self, task_id: str) -> dict | None:
        """Get task status as a dict."""
        with self.lock:
            task = self.tasks.get(task_id)
            if not task:
                return None
            result = task.to_dict()
            # Include tail of output for completed tasks
            if task.status != "running" and task.stdout:
                lines = task.stdout.strip().splitlines()
                result["stdout_tail"] = "\n".join(lines[-20:])
            if task.status == "failed" and task.stderr:
                result["stderr_tail"] = task.stderr[-500:]
            return result

    def list_tasks(self, status_filter: str = "all") -> list[dict]:
        """List tasks, optionally filtered by status."""
        with self.lock:
            tasks = list(self.tasks.values())

        if status_filter != "all":
            tasks = [t for t in tasks if t.status == status_filter]

        tasks.sort(key=lambda t: t.started_at, reverse=True)
        return [t.to_dict() for t in tasks]
