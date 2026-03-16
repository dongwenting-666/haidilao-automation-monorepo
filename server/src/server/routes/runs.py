from __future__ import annotations

import asyncio
import collections
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from fastapi import APIRouter, HTTPException

from server.commands import get_command
from server.config import REPO_ROOT

router = APIRouter(prefix="/api/runs", tags=["runs"])

_MAX_HISTORY = 200
_MAX_CONCURRENT = 8


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class Run:
    __slots__ = ("id", "command", "status", "params", "started_at", "finished_at", "logs")

    def __init__(self, command: str, params: dict[str, Any]) -> None:
        self.id: str = uuid.uuid4().hex[:12]
        self.command = command
        self.params = params
        self.status: RunStatus = RunStatus.PENDING
        self.started_at: datetime = datetime.now(timezone.utc)
        self.finished_at: datetime | None = None
        self.logs: str = ""

    def to_dict(self, include_logs: bool = False) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "command": self.command,
            "status": self.status.value,
            "params": self.params,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }
        if include_logs:
            d["logs"] = self.logs
        return d


_runs: collections.OrderedDict[str, Run] = collections.OrderedDict()
_semaphore = asyncio.Semaphore(_MAX_CONCURRENT)


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


async def execute_run(run: Run) -> None:
    """Run a command as a subprocess and capture output."""
    cmd = get_command(run.command)
    if cmd is None:
        run.status = RunStatus.FAILED
        run.logs = f"Unknown command: {run.command}"
        run.finished_at = datetime.now(timezone.utc)
        return

    args = cmd.build_args(run.params)
    async with _semaphore:
        run.status = RunStatus.RUNNING
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


def create_run(command_name: str, params: dict[str, Any]) -> Run:
    """Create a Run, store it, and schedule background execution.

    Safe to call from both async and sync-in-event-loop contexts.
    """
    run = Run(command_name, params)
    _runs[run.id] = run
    _evict_old_runs()

    loop = asyncio.get_running_loop()
    loop.create_task(execute_run(run))
    return run


@router.get("")
async def list_runs() -> list[dict[str, Any]]:
    return [r.to_dict() for r in reversed(_runs.values())]


@router.get("/{run_id}")
async def get_run(run_id: str) -> dict[str, Any]:
    run = _runs.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run.to_dict(include_logs=True)
