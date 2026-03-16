from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from server.commands import get_command, list_commands
from server.routes.runs import create_run

router = APIRouter(prefix="/api/commands", tags=["commands"])


class RunRequest(BaseModel):
    params: dict[str, Any] = {}


@router.get("")
async def list_all_commands() -> list[dict[str, str]]:
    return [
        {"name": c.name, "description": c.description}
        for c in list_commands()
    ]


@router.post("/{name}/run")
async def run_command(name: str, body: RunRequest | None = None) -> dict[str, str]:
    cmd = get_command(name)
    if cmd is None:
        raise HTTPException(status_code=404, detail=f"Command '{name}' not found")
    params = body.params if body else {}
    run = create_run(name, params)
    return {"run_id": run.id, "status": run.status.value}
