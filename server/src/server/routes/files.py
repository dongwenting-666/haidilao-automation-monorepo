
from __future__ import annotations
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from server.config import settings
from server.run_guard import require_run_token

router = APIRouter(prefix="/api/files", tags=["files"])

_OUTPUT_ROOT = settings.output_dir.resolve()


def _safe_path(subpath: str) -> Path:
    """Resolve *subpath* under the output dir, rejecting traversal attempts."""
    target = (_OUTPUT_ROOT / subpath).resolve()
    if not target.is_relative_to(_OUTPUT_ROOT):
        raise HTTPException(status_code=400, detail="Invalid path")
    return target


@router.get("/", dependencies=[Depends(require_run_token)])
async def list_files(subdir: str = "") -> list[dict[str, Any]]:
    root = _safe_path(subdir)
    if not root.is_dir():
        raise HTTPException(status_code=404, detail="Directory not found")
    items = []
    for entry in sorted(root.iterdir()):
        items.append({
            "name": entry.name,
            "path": str(entry.relative_to(_OUTPUT_ROOT)),
            "is_dir": entry.is_dir(),
            "size": entry.stat().st_size if entry.is_file() else None,
        })
    return items


@router.get("/{path:path}", dependencies=[Depends(require_run_token)])
async def download_file(path: str) -> FileResponse:
    target = _safe_path(path)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(target, filename=target.name)
