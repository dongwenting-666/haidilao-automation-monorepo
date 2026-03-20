from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from server.commands import get_command, list_commands
from server.routes.runs import create_run
from server.run_guard import require_run_token

router = APIRouter(prefix="/api/commands", tags=["commands"])


class RunRequest(BaseModel):
    params: dict[str, Any] = {}
    notify_chat: str = ""  # chat alias for file delivery ("" = no delivery)


@router.get("")
async def list_all_commands() -> list[dict[str, str]]:
    return [
        {"name": c.name, "description": c.description}
        for c in list_commands()
    ]


@router.post("/{name}/run", dependencies=[Depends(require_run_token)])
async def run_command(name: str, body: RunRequest | None = None) -> dict[str, str]:
    cmd = get_command(name)
    if cmd is None:
        raise HTTPException(status_code=404, detail=f"Command '{name}' not found")
    params = body.params if body else {}
    notify_chat = body.notify_chat if body else ""
    run = create_run(name, params, notify_chat=notify_chat)
    return {"run_id": run.id, "status": run.status.value}
