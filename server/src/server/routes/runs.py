from __future__ import annotations

import asyncio
import collections
import json
import uuid
from datetime import datetime, date, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from server.run_guard import require_run_token

from server.commands import get_command
from server.config import REPO_ROOT

router = APIRouter(prefix="/api/runs", tags=["runs"])

_MAX_HISTORY = 200
_RUN_LOG_RETENTION_DAYS = 30

# Serial execution queue — automations are not headless and must not overlap.
_queue: asyncio.Queue[Run] = asyncio.Queue()
_worker_task: asyncio.Task[None] | None = None


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class Run:
    __slots__ = ("id", "command", "status", "params", "started_at", "finished_at", "logs", "queue_position", "notify_chat")

    def __init__(self, command: str, params: dict[str, Any], *, notify_chat: str = "") -> None:
        self.id: str = uuid.uuid4().hex[:12]
        self.command = command
        self.params = params
        self.status: RunStatus = RunStatus.PENDING
        self.started_at: datetime = datetime.now(timezone.utc)
        self.finished_at: datetime | None = None
        self.logs: str = ""
        self.queue_position: int | None = None  # None when running or done
        self.notify_chat: str = notify_chat  # chat alias for file delivery ("" = no delivery)

    def to_dict(self, include_logs: bool = False) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "command": self.command,
            "status": self.status.value,
            "params": self.params,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "queue_position": self.queue_position,
        }
        if include_logs:
            d["logs"] = self.logs
        return d


_runs: collections.OrderedDict[str, Run] = collections.OrderedDict()


# ── Run log persistence ───────────────────────────────────────────────────────

def _run_log_dir() -> Path:
    from server.config import settings
    d = settings.output_dir.resolve() / "runs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _run_log_path(dt: datetime) -> Path:
    return _run_log_dir() / f"{dt.date().isoformat()}.jsonl"


def _persist_run(run: Run) -> None:
    """Append a completed run to today's JSONL log file."""
    try:
        record = run.to_dict(include_logs=True)
        with _run_log_path(run.finished_at or datetime.now(timezone.utc)).open("a") as f:
            f.write(json.dumps(record) + "\n")
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("Failed to persist run %s: %s", run.id, exc)


def _load_recent_runs() -> None:
    """Load completed runs from the last 30 days into _runs on startup."""
    import logging
    log = logging.getLogger(__name__)
    log_dir = _run_log_dir()
    cutoff = date.today() - timedelta(days=_RUN_LOG_RETENTION_DAYS)
    loaded = 0

    for day_offset in range(_RUN_LOG_RETENTION_DAYS, -1, -1):  # oldest first
        day = date.today() - timedelta(days=day_offset)
        if day < cutoff:
            continue
        path = log_dir / f"{day.isoformat()}.jsonl"
        if not path.exists():
            continue
        try:
            for line in path.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    run = Run(d["command"], d.get("params", {}), notify_chat=d.get("notify_chat", ""))
                    run.id = d["id"]
                    run.status = RunStatus(d["status"])
                    run.logs = d.get("logs", "")
                    run.started_at = datetime.fromisoformat(d["started_at"])
                    run.finished_at = datetime.fromisoformat(d["finished_at"]) if d.get("finished_at") else None
                    run.queue_position = None
                    _runs[run.id] = run
                    loaded += 1
                except Exception:
                    pass  # skip malformed lines
        except Exception as exc:
            log.warning("Failed to load run log %s: %s", path, exc)

    if loaded:
        log.info("Loaded %d historical runs from the last %d days", loaded, _RUN_LOG_RETENTION_DAYS)

    # Evict to keep memory bounded
    while len(_runs) > _MAX_HISTORY:
        _runs.popitem(last=False)


def _purge_old_run_logs() -> None:
    """Delete run log files older than 30 days."""
    import logging
    log = logging.getLogger(__name__)
    cutoff = date.today() - timedelta(days=_RUN_LOG_RETENTION_DAYS)
    for path in _run_log_dir().glob("*.jsonl"):
        try:
            file_date = date.fromisoformat(path.stem)
            if file_date < cutoff:
                path.unlink()
                log.info("Purged old run log: %s", path.name)
        except (ValueError, OSError):
            pass


def _evict_old_runs() -> None:
    """Remove oldest completed runs when history exceeds _MAX_HISTORY."""
    if len(_runs) <= _MAX_HISTORY:
        return
    to_delete = []
    for key, run in _runs.items():
        if len(_runs) - len(to_delete) <= _MAX_HISTORY:
            break
        if run.status in (RunStatus.SUCCESS, RunStatus.FAILED):
            to_delete.append(key)
    for key in to_delete:
        del _runs[key]


def _refresh_queue_positions() -> None:
    """Update queue_position for all PENDING runs based on queue order."""
    pending = [r for r in _runs.values() if r.status == RunStatus.PENDING]
    # The queue drains FIFO, so order in _runs matches queue order.
    for i, run in enumerate(pending):
        run.queue_position = i + 1


async def execute_run(run: Run) -> None:
    """Execute a single run as a subprocess and capture output."""
    cmd = get_command(run.command)
    if cmd is None:
        run.status = RunStatus.FAILED
        run.logs = f"Unknown command: {run.command}"
        run.finished_at = datetime.now(timezone.utc)
        run.queue_position = None
        return

    # Allow commands to block themselves (e.g. SAP disabled on this machine)
    if hasattr(cmd, "validate"):
        error = cmd.validate(run.params)
        if error:
            run.status = RunStatus.FAILED
            run.logs = f"Command blocked: {error}"
            run.finished_at = datetime.now(timezone.utc)
            run.queue_position = None
            return

    args = cmd.build_args(run.params)
    run.status = RunStatus.RUNNING
    run.queue_position = None
    _refresh_queue_positions()

    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=REPO_ROOT,
        )
        stdout, _ = await proc.communicate()
        run.logs = stdout.decode(errors="replace") if stdout else ""
        run.status = RunStatus.SUCCESS if proc.returncode == 0 else RunStatus.FAILED
    except Exception as exc:
        run.logs = str(exc)
        run.status = RunStatus.FAILED
    finally:
        run.finished_at = datetime.now(timezone.utc)
        run.queue_position = None
        # Persist to disk before notifying (so it survives even if notify fails)
        _persist_run(run)
        # Send Lark notification (non-blocking, errors are swallowed in notify module)
        await asyncio.to_thread(_notify_run, run)


def _notify_run(run: Run) -> None:
    """Send Lark notifications for a completed run (called in a thread).

    All notifications are gated on ``run.notify_chat``:
    - Empty notify_chat → no notifications at all (manual/test runs stay silent)
    - Non-empty → send run-complete card + file delivery (if applicable)
    """
    if not run.notify_chat:
        return  # no chat target = silent run (manual/test/rogue agent)

    try:
        from server.notify import notify_run_complete
        notify_run_complete(run)
    except Exception:
        pass  # notification failures must never affect the run result

    # If the daily-report succeeded, deliver the xlsx to the target chat.
    if run.command == "daily-report" and run.status.value == "success":
        try:
            from server.notify import notify_daily_report_file
            report_path = _find_report_from_run(run)
            if report_path:
                notify_daily_report_file(report_path, target_chat=run.notify_chat)
        except Exception:
            pass  # file delivery failures must never affect the run result

    # If ksb1 succeeded, deliver the report xlsx and @mention the requester.
    if run.command == "ksb1" and run.status.value == "success":
        try:
            from server.notify import notify_ksb1_file
            report_path = _find_ksb1_report_from_run(run)
            if report_path:
                notify_ksb1_file(
                    report_path,
                    target_chat=run.notify_chat or "production_accounting_report_chat",
                    triggered_by_open_id=run.params.get("triggered_by_open_id", ""),
                    triggered_by_name=run.params.get("triggered_by_name", ""),
                )
        except Exception:
            pass  # file delivery failures must never affect the run result

    # If travel-expense-budget succeeded, deliver the report xlsx.
    if run.command == "travel-expense-budget" and run.status.value == "success":
        try:
            from server.notify import notify_travel_budget_file
            report_path = _find_travel_budget_from_run(run)
            if report_path:
                notify_travel_budget_file(
                    report_path,
                    target_chat=run.notify_chat or "hongming",
                    report_month=int(run.params.get("report_month", 0)),
                    year=int(run.params.get("year", 0)),
                )
        except Exception:
            pass


def _find_report_from_run(run: "Run") -> "Path | None":
    """Locate the daily report file generated by *run*.

    Strategy:
    1. If the run params include a ``date``, look up that exact file.
    2. Otherwise parse the output path from the run logs
       (``Report saved to /path/to/database_report_YYYY_MM_DD.xlsx``).
    3. Fall back to the most recently modified xlsx in the daily-report dir.
    """
    import re
    from pathlib import Path
    from server.config import settings

    daily_dir = settings.output_dir.resolve() / "daily-report"

    # Strategy 1: explicit date param
    if date_str := run.params.get("date"):
        try:
            from datetime import date as _date
            d = _date.fromisoformat(str(date_str))
            p = daily_dir / f"database_report_{d.year}_{d.month:02d}_{d.day:02d}.xlsx"
            if p.exists():
                return p
        except Exception:
            pass

    # Strategy 2: parse log line "Report saved to /abs/path/database_report_*.xlsx"
    if run.logs:
        m = re.search(r"Report saved to (.+database_report_\d{4}_\d{2}_\d{2}\.xlsx)", run.logs)
        if m:
            p = Path(m.group(1))
            if p.exists():
                return p

    # Strategy 3: most recently modified xlsx in the output dir
    candidates = sorted(daily_dir.glob("database_report_*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def _find_ksb1_report_from_run(run: "Run") -> "Path | None":
    """Locate the KSB1 report file generated by *run*.

    Parses the log line: ``Done! Report saved to /abs/path/{year_month}_KSB1_检查报告_{ts}.XLSX``
    Falls back to the most recently modified XLSX in the output/ksb1/ directory.
    """
    import re
    from pathlib import Path
    from server.config import settings

    ksb1_root = settings.output_dir.resolve() / "ksb1"

    # Strategy 1: parse log line "Done! Report saved to ..."
    if run.logs:
        m = re.search(r"Report saved to (.+\.XLSX)", run.logs, re.IGNORECASE)
        if m:
            p = Path(m.group(1).strip())
            if p.exists():
                return p

    # Strategy 2: most recently modified XLSX anywhere under ksb1/
    candidates = sorted(ksb1_root.rglob("*.XLSX"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def _find_travel_budget_from_run(run: "Run") -> "Path | None":
    """Locate the travel budget report file from run logs."""
    import re
    from pathlib import Path

    if run.logs:
        m = re.search(r"Report saved to (.+\.xlsx)", run.logs, re.IGNORECASE)
        if m:
            p = Path(m.group(1).strip())
            if p.exists():
                return p
    return None


async def _queue_worker() -> None:
    """Background task: drain the queue one run at a time."""
    while True:
        run = await _queue.get()
        try:
            await execute_run(run)
        finally:
            _queue.task_done()


def start_queue_worker() -> None:
    """Start the background queue worker. Call once from app lifespan.

    Recreates the async queue to bind it to the current event loop — necessary
    when the server restarts (or in tests where each TestClient creates a new loop).
    Also loads historical runs from disk and purges old log files.
    """
    global _worker_task, _queue
    _queue = asyncio.Queue()
    _load_recent_runs()
    _purge_old_run_logs()
    loop = asyncio.get_running_loop()
    _worker_task = loop.create_task(_queue_worker())


def create_run(command_name: str, params: dict[str, Any], *, notify_chat: str = "") -> Run:
    """Create a Run, enqueue it for serial execution, and return it.

    *notify_chat* is a chat alias from ``server/notify.toml [chats]``.
    When set, the run's output file (e.g. daily report xlsx) is delivered
    to that chat on success.  Empty string = no file delivery.

    The internal scheduler passes ``notify_chat="production_accounting_report_chat"``
    for the daily-report cron. Manual/API-triggered runs default to "" (no delivery).
    """
    run = Run(command_name, params, notify_chat=notify_chat)
    _runs[run.id] = run
    _evict_old_runs()
    _queue.put_nowait(run)
    _refresh_queue_positions()
    return run


@router.get("", dependencies=[Depends(require_run_token)])
async def list_runs() -> list[dict[str, Any]]:
    return [r.to_dict() for r in reversed(_runs.values())]


@router.get("/{run_id}", dependencies=[Depends(require_run_token)])
async def get_run(run_id: str) -> dict[str, Any]:
    run = _runs.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run.to_dict(include_logs=True)
