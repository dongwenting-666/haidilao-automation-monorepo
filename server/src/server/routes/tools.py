"""Admin Tools — super-admin file storage via MinIO.

Routes:
    GET  /admin/tools                → HTML page (super admin only)
    POST /admin/tools/upload         → upload file → MinIO, returns {key, url}
    GET  /admin/tools/files          → list files JSON
    GET  /admin/tools/files/{key}    → download/proxy file (auth required)
    DELETE /admin/tools/files/{key}  → delete file (super admin only)

Agent-access (localhost only, no auth):
    GET  /api/tools/agent/{key}      → download file (localhost-only check)
"""

from __future__ import annotations

import io
import logging
import os
from pathlib import PurePosixPath
from urllib.parse import quote
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from server.auth import is_super_admin, require_auth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/tools", tags=["tools"])
agent_router = APIRouter(prefix="/api/tools", tags=["tools-agent"])


def _get_bucket() -> str:
    return os.environ.get("MINIO_BUCKET", "tools-uploads")


def _get_minio_client():
    """Return a configured MinIO client, or raise HTTPException if unavailable."""
    try:
        from minio import Minio
    except ImportError:
        raise HTTPException(status_code=503, detail="minio package not installed")

    endpoint = os.environ.get("MINIO_ENDPOINT", "localhost:9000")
    access_key = os.environ.get("MINIO_ROOT_USER", "haidilao")
    secret_key = os.environ.get("MINIO_ROOT_PASSWORD", "haidilao_minio_dev")
    secure = os.environ.get("MINIO_SECURE", "false").lower() in ("true", "1", "yes")

    try:
        client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)
        bucket = _get_bucket()
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)
        return client
    except Exception as exc:
        logger.error("MinIO connection failed: %s", exc)
        raise HTTPException(status_code=503, detail=f"MinIO unavailable: {exc}")


def _require_super_admin(session: dict = Depends(require_auth)) -> dict:
    """FastAPI dependency — requires super admin, else 403."""
    if not is_super_admin(session.get("open_id", "")):
        raise HTTPException(status_code=403, detail="Super admin only")
    return session


def _agent_url(key: str) -> str:
    return f"http://localhost:8000/api/tools/agent/{key}"


# ── Shared HTML pieces ────────────────────────────────────────────────────────

_BASE_STYLE = """
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  * { box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         margin: 0; background: #f5f5f5; color: #222; }
  header { background: #c0392b; color: #fff; padding: 12px 24px;
           display: flex; align-items: center; gap: 20px; }
  header h1 { margin: 0; font-size: 1.2rem; flex: 1; }
  nav { display: flex; align-items: center; gap: 8px; }
  nav a { color: #fff; text-decoration: none; font-size: 0.95rem;
          padding: 6px 14px; border-radius: 4px; }
  nav a:hover, nav a.active { background: rgba(255,255,255,0.25); }
  .user-info { color: rgba(255,255,255,0.85); font-size: 0.88rem; }
  .container { max-width: 1100px; margin: 24px auto; padding: 0 16px; }
  .card { background: #fff; border-radius: 8px; padding: 20px;
          box-shadow: 0 1px 4px rgba(0,0,0,.12); margin-bottom: 20px; }
  .drop-zone { border: 2px dashed #ccc; border-radius: 8px; padding: 48px 20px;
               text-align: center; cursor: pointer; transition: all 0.2s; color: #888; }
  .drop-zone.drag-over { border-color: #c0392b; background: #fff5f5; color: #c0392b; }
  .drop-zone p { margin: 8px 0; font-size: 0.95rem; }
  .drop-zone .hint { font-size: 0.82rem; }
  .btn { cursor: pointer; border: none; border-radius: 4px;
         padding: 8px 18px; font-size: 0.88rem; font-weight: 600; }
  .btn-primary { background: #c0392b; color: #fff; }
  .btn-primary:hover { background: #a93226; }
  .btn-danger  { background: #e74c3c; color: #fff; font-size: 0.8rem; padding: 3px 10px; }
  .btn-danger:hover { background: #c0392b; }
  .btn-sm { padding: 4px 12px; font-size: 0.82rem; }
  table { border-collapse: collapse; width: 100%; font-size: 0.88rem; }
  th { background: #fafafa; border-bottom: 2px solid #e0e0e0;
       padding: 8px 10px; text-align: left; }
  td { border-bottom: 1px solid #eee; padding: 8px 10px; vertical-align: middle; }
  tr:last-child td { border-bottom: none; }
  .file-link { color: #c0392b; text-decoration: none; font-weight: 500; }
  .file-link:hover { text-decoration: underline; }
  .copy-btn { cursor: pointer; background: #eee; border: none; border-radius: 3px;
              padding: 2px 8px; font-size: 0.78rem; margin-left: 6px; }
  .copy-btn:hover { background: #ddd; }
  .progress-bar { display: none; height: 6px; background: #eee; border-radius: 3px;
                  margin-top: 12px; overflow: hidden; }
  .progress-bar-fill { height: 100%; background: #c0392b; width: 0%; transition: width 0.3s; }
  #msg { font-size: 0.88rem; margin-top: 10px; min-height: 1.4em; }
  .ok  { color: #1a7a1a; }
  .err { color: #c0392b; }
  .size { color: #888; }
  .empty-state { text-align: center; padding: 40px; color: #999; }
  .preview img { max-width: 120px; max-height: 80px; border-radius: 4px;
                 border: 1px solid #eee; display: block; }
  code.url { font-size: 0.78rem; background: #f5f5f5; padding: 2px 6px;
             border-radius: 3px; word-break: break-all; }
</style>
"""

_HEADER = """
<header>
  <h1>🍲 海底捞兔子Agent加拿大片区管理后台</h1>
  <nav>
    <a href="/admin/targets">月度目标</a>
    <a href="/admin/competitors">假想敌配置</a>
    <a href="/admin/tools" class="active">工具</a>
  </nav>
  <span class="user-info">👤 {name} &nbsp;·&nbsp;
    <a href="/admin/logout" style="color:rgba(255,255,255,0.75);font-size:0.82rem">退出</a>
  </span>
</header>
"""


# ── GET /admin/tools ──────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def tools_page(request: Request, session: dict = Depends(_require_super_admin)):
    user_name = session.get("name", "管理员")

    page_html = f"""<!DOCTYPE html>
<html>
<head>
{_BASE_STYLE}
<title>工具 — 管理后台</title>
</head>
<body>
{_HEADER.format(name=user_name)}
<div class="container">
  <div class="card">
    <h2 style="margin-top:0">📁 文件上传</h2>
    <p style="color:#555;font-size:0.9rem;margin-top:0">
      上传文件后复制 Agent URL，粘贴到 GitHub Issue，Agent 可通过 localhost 直接读取。
      支持所有格式（图片、zip、Excel、PDF 等）。
    </p>
    <div class="drop-zone" id="drop-zone"
         onclick="document.getElementById('file-input').click()">
      <p>🗂 拖拽文件到此处，或点击选择文件</p>
      <p class="hint">所有格式均支持 · 可多选</p>
    </div>
    <input type="file" id="file-input" style="display:none" multiple>
    <div class="progress-bar" id="progress-bar">
      <div class="progress-bar-fill" id="progress-fill"></div>
    </div>
    <div id="msg"></div>
  </div>

  <div class="card">
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px">
      <h2 style="margin:0">已上传文件</h2>
      <button class="btn btn-primary btn-sm" onclick="loadFiles()">刷新</button>
    </div>
    <div id="file-list"><div class="empty-state">加载中…</div></div>
  </div>
</div>

<script>
function showMsg(text, ok) {{
  const el = document.getElementById('msg');
  el.textContent = text;
  el.className = ok ? 'ok' : 'err';
}}

function formatSize(bytes) {{
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / 1048576).toFixed(2) + ' MB';
}}

function formatDate(s) {{
  return new Date(s).toLocaleString('zh-CN', {{
    year:'numeric', month:'2-digit', day:'2-digit',
    hour:'2-digit', minute:'2-digit'
  }});
}}

function isImage(filename) {{
  return /\\.(png|jpg|jpeg|gif|webp|svg|bmp)$/i.test(filename);
}}

const dropZone = document.getElementById('drop-zone');

dropZone.addEventListener('dragover', e => {{
  e.preventDefault();
  dropZone.classList.add('drag-over');
}});
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-over'));
dropZone.addEventListener('drop', e => {{
  e.preventDefault();
  dropZone.classList.remove('drag-over');
  uploadFiles(e.dataTransfer.files);
}});
document.getElementById('file-input').addEventListener('change', function() {{
  uploadFiles(this.files);
  this.value = '';
}});

async function uploadFiles(files) {{
  if (!files.length) return;
  const bar  = document.getElementById('progress-bar');
  const fill = document.getElementById('progress-fill');
  bar.style.display = 'block';
  fill.style.width = '0%';

  for (let i = 0; i < files.length; i++) {{
    const file = files[i];
    showMsg('上传中: ' + file.name, true);
    fill.style.width = ((i / files.length) * 80 + 5) + '%';
    const fd = new FormData();
    fd.append('file', file);
    try {{
      const res  = await fetch('/admin/tools/upload', {{ method: 'POST', body: fd }});
      const data = await res.json();
      if (res.status === 401) {{
        showMsg('✗ 会话已过期，请重新登录后再上传', false);
        bar.style.display = 'none';
        return;
      }}
      if (!data.ok) throw new Error(data.error || '未知错误');
    }} catch(e) {{
      showMsg('✗ 上传失败: ' + e.message, false);
      bar.style.display = 'none';
      return;
    }}
  }}

  fill.style.width = '100%';
  setTimeout(() => {{ bar.style.display = 'none'; fill.style.width = '0%'; }}, 800);
  showMsg('✓ 上传成功 (' + files.length + ' 个文件)', true);
  loadFiles();
}}

async function loadFiles() {{
  const container = document.getElementById('file-list');
  try {{
    const res  = await fetch('/admin/tools/files');
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    if (!data.length) {{
      container.innerHTML = '<div class="empty-state">暂无文件</div>';
      return;
    }}
    let html = `<table>
      <thead><tr>
        <th>预览</th><th>文件名</th><th>大小</th><th>上传时间</th>
        <th>Agent URL</th><th>操作</th>
      </tr></thead><tbody>`;

    for (const f of data) {{
      const dlUrl    = '/admin/tools/files/' + encodeURIComponent(f.key);
      const agentUrl = f.agent_url || 'http://localhost:8000/api/tools/agent/' + encodeURIComponent(f.key);
      const preview  = isImage(f.filename)
        ? `<div class="preview"><img src="${{dlUrl}}" alt="${{f.filename}}" loading="lazy"></div>`
        : '<span style="font-size:1.5rem">📄</span>';

      html += `<tr>
        <td>${{preview}}</td>
        <td><a class="file-link" href="${{dlUrl}}" download="${{f.filename}}">${{f.filename}}</a></td>
        <td class="size">${{formatSize(f.size)}}</td>
        <td class="size">${{f.last_modified ? formatDate(f.last_modified) : '—'}}</td>
        <td>
          <code class="url">${{agentUrl}}</code>
          <button class="copy-btn" onclick="copyText('${{agentUrl}}', this)">复制</button>
        </td>
        <td>
          <button class="btn btn-danger" onclick="deleteFile('${{f.key}}')">删除</button>
        </td>
      </tr>`;
    }}
    html += '</tbody></table>';
    container.innerHTML = html;
  }} catch(e) {{
    container.innerHTML = '<div class="empty-state" style="color:#c0392b">加载失败: ' + e.message + '</div>';
  }}
}}

function copyText(text, btn) {{
  navigator.clipboard.writeText(text).then(() => {{
    const orig = btn.textContent;
    btn.textContent = '✓ 已复制';
    setTimeout(() => btn.textContent = orig, 1500);
  }});
}}

async function deleteFile(key) {{
  if (!confirm('确定删除此文件？此操作不可撤销。')) return;
  try {{
    const res  = await fetch('/admin/tools/files/' + encodeURIComponent(key), {{ method: 'DELETE' }});
    const data = await res.json();
    if (data.ok) {{
      showMsg('✓ 已删除', true);
      loadFiles();
    }} else {{
      showMsg('✗ ' + (data.error || '删除失败'), false);
    }}
  }} catch(e) {{
    showMsg('✗ ' + e.message, false);
  }}
}}

loadFiles();
</script>
</body>
</html>"""
    return HTMLResponse(content=page_html)


# ── POST /admin/tools/upload ──────────────────────────────────────────────────

@router.post("/upload")
async def upload_file(file: UploadFile, session: dict = Depends(_require_super_admin)):
    try:
        client = _get_minio_client()
    except HTTPException:
        raise
    try:
        data = await file.read()
        size = len(data)
        content_type = file.content_type or "application/octet-stream"
        original_filename = file.filename or "upload"
        key = f"{uuid4()}_{original_filename}"
        bucket = _get_bucket()

        client.put_object(
            bucket,
            key,
            io.BytesIO(data),
            size,
            content_type=content_type,
        )
        return {
            "ok": True,
            "key": key,
            "filename": original_filename,
            "size": size,
            "agent_url": _agent_url(key),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Upload failed")
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)


# ── GET /admin/tools/files ────────────────────────────────────────────────────

@router.get("/files")
async def list_files(session: dict = Depends(_require_super_admin)):
    try:
        client = _get_minio_client()
    except HTTPException:
        raise
    try:
        bucket = _get_bucket()
        objects = client.list_objects(bucket)
        result = []
        for obj in objects:
            key = obj.object_name
            filename = PurePosixPath(key).name
            result.append({
                "key": key,
                "filename": filename,
                "size": obj.size,
                "last_modified": obj.last_modified.isoformat() if obj.last_modified else None,
                "agent_url": _agent_url(key),
            })
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("List files failed")
        raise HTTPException(status_code=500, detail=str(exc))


# ── GET /admin/tools/files/{key} ─────────────────────────────────────────────

@router.get("/files/{key:path}")
async def download_file(key: str, session: dict = Depends(_require_super_admin)):
    try:
        client = _get_minio_client()
    except HTTPException:
        raise
    try:
        bucket = _get_bucket()
        stat = client.stat_object(bucket, key)
        content_type = stat.content_type or "application/octet-stream"
        file_size = stat.size

        response = client.get_object(bucket, key)
        data = response.read()
        response.close()
        response.release_conn()

        filename = PurePosixPath(key).name
        return StreamingResponse(
            io.BytesIO(data),
            media_type=content_type,
            headers={
                "Content-Disposition": f'inline; filename="{quote(filename)}"',
                "Content-Length": str(file_size),
            },
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Download failed for key=%s", key)
        raise HTTPException(status_code=404, detail=str(exc))


# ── DELETE /admin/tools/files/{key} ──────────────────────────────────────────

@router.delete("/files/{key:path}")
async def delete_file(key: str, session: dict = Depends(_require_super_admin)):
    try:
        client = _get_minio_client()
    except HTTPException:
        raise
    try:
        bucket = _get_bucket()
        client.remove_object(bucket, key)
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Delete failed for key=%s", key)
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)


# ── GET /api/tools/agent/{key}  (localhost-only, no auth) ────────────────────

@agent_router.get("/agent/{key:path}")
async def agent_download(key: str, request: Request):
    """Download file without auth — only accessible from localhost."""
    client_host = request.client.host if request.client else ""
    if client_host not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(status_code=403, detail="Localhost only")

    try:
        client = _get_minio_client()
    except HTTPException:
        raise
    try:
        bucket = _get_bucket()
        stat = client.stat_object(bucket, key)
        content_type = stat.content_type or "application/octet-stream"

        response = client.get_object(bucket, key)
        data = response.read()
        response.close()
        response.release_conn()

        filename = PurePosixPath(key).name
        return StreamingResponse(
            io.BytesIO(data),
            media_type=content_type,
            headers={
                "Content-Disposition": f'inline; filename="{quote(filename)}"',
                "Content-Length": str(stat.size),
            },
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Agent download failed for key=%s", key)
        raise HTTPException(status_code=404, detail=str(exc))
