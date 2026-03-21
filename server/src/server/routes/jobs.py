
from __future__ import annotations
from typing import Any

from fastapi import APIRouter

from server.scheduler import scheduler

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("")
async def list_jobs() -> list[dict[str, Any]]:
    jobs = scheduler.get_jobs()
    return [
        {
            "id": job.id,
            "name": job.name,
            "trigger": str(job.trigger),
            "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
        }
        for job in jobs
    ]
