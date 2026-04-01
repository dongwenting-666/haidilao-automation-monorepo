
from __future__ import annotations
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from server.run_guard import require_run_token
from server.scheduler import scheduler

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.post("/{job_id}/trigger", dependencies=[Depends(require_run_token)])
async def trigger_job(job_id: str) -> dict[str, str]:
    """Manually trigger a scheduled job immediately."""
    job = scheduler.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    # Run the job's function directly
    result = job.func()
    # If it's a coroutine, await it
    import asyncio
    if asyncio.iscoroutine(result):
        await result
    return {"status": "triggered", "job_id": job_id}


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
