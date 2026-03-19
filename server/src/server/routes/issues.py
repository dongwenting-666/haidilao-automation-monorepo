"""Admin UI — Issues & Feature Requests.

Provides a Kanban-style issue tracker where admins create issues/feature
requests and the agent collaborates via threaded messages.

Routes:
    GET  /admin/issues              → issues list page
    GET  /admin/issues/{id}         → issue detail + thread page
    POST /admin/issues              → create new issue (JSON)
    POST /admin/issues/{id}/message → add thread message (JSON)
    POST /admin/issues/{id}/status  → update issue status (JSON)
    GET  /api/issues                → list issues (JSON API for agent cron)
    GET  /api/issues/{id}           → issue detail + messages (JSON API)
    POST /api/issues/{id}/message   → agent posts a message (JSON API)
    POST /api/issues/{id}/status    → agent updates status (JSON API)
"""

from __future__ import annotations

import html as html_mod
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from server.auth import require_auth, get_session
from server.db import (
    add_issue_message,
    create_issue,
    get_active_issues,
    get_issue,
    get_issue_messages,
    get_issues,
    is_db_available,
    update_issue,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["issues"])


# ── Pydantic models ──────────────────────────────────────────────────────────

class CreateIssueBody(BaseModel):
    title: str
    description: str = ""
    type: str = "bug"
    priority: str = "medium"


class MessageBody(BaseModel):
    content: str


class StatusBody(BaseModel):
    status: str


# ── Shared styles ─────────────────────────────────────────────────────────────

_BASE_STYLE = """
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  * { box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", sans-serif;
         margin: 0; background: #f5f7fa; color: #222; }
  .nav { background: #1a1a2e; padding: 0 24px; display: flex; align-items: center; gap: 24px; height: 52px; }
  .nav a { color: #fff; text-decoration: none; font-size: 0.9rem; opacity: .75; padding: 8px 0; }
  .nav a:hover, .nav a.active { opacity: 1; }
  .nav .logo { color: #fff; font-weight: 700; font-size: 1.1rem; margin-right: 16px; }
  .nav .user { margin-left: auto; color: #fff; font-size: 0.85rem; opacity: .75; }
  .nav .user a { color: #fff; opacity: .75; margin-left: 12px; }
  .container { max-width: 960px; margin: 24px auto; padding: 0 16px; }
  .card { background: #fff; border-radius: 10px; padding: 20px;
          box-shadow: 0 2px 8px rgba(0,0,0,.06); margin-bottom: 16px; }
  .btn { cursor: pointer; border: none; border-radius: 6px;
         padding: 8px 18px; font-size: 0.88rem; font-weight: 600; }
  .btn-primary { background: #c0392b; color: #fff; }
  .btn-primary:hover { background: #a93226; }
  .btn-outline { background: #fff; color: #333; border: 1px solid #ddd; }
  .btn-outline:hover { background: #f5f5f5; }
  .badge { display: inline-block; padding: 2px 10px; border-radius: 12px;
           font-size: 0.78rem; font-weight: 600; }
  .badge-open { background: #e8f5e9; color: #2e7d32; }
  .badge-planning { background: #fff3e0; color: #e65100; }
  .badge-approved { background: #e3f2fd; color: #1565c0; }
  .badge-in_progress { background: #fce4ec; color: #c62828; }
  .badge-done { background: #f3e5f5; color: #6a1b9a; }
  .badge-closed { background: #eceff1; color: #546e7a; }
  .badge-bug { background: #ffebee; color: #c62828; }
  .badge-feature { background: #e8eaf6; color: #283593; }
  .badge-urgent { background: #ff1744; color: #fff; }
  .badge-high { background: #ff6d00; color: #fff; }
  .badge-medium { background: #ffab00; color: #333; }
  .badge-low { background: #eceff1; color: #546e7a; }
  table { border-collapse: collapse; width: 100%; }
  th { background: #f0f4ff; padding: 10px 14px; text-align: left;
       font-size: 0.82rem; color: #555; font-weight: 600; border-bottom: 1px solid #e8ecf4; }
  td { padding: 10px 14px; border-bottom: 1px solid #f0f0f0; font-size: 0.88rem; }
  tr:hover td { background: #fafcff; }
  .thread-msg { padding: 14px 18px; border-radius: 10px; margin-bottom: 10px;
                max-width: 80%; position: relative; }
  .thread-msg.user { background: #e3f2fd; margin-left: auto; }
  .thread-msg.agent { background: #f5f5f5; margin-right: auto; }
  .thread-msg .sender { font-weight: 600; font-size: 0.82rem; color: #666; margin-bottom: 4px; }
  .thread-msg .time { font-size: 0.75rem; color: #999; margin-top: 6px; }
  .thread-msg .body { white-space: pre-wrap; line-height: 1.5; }
  textarea { width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 8px;
             font-size: 0.9rem; font-family: inherit; resize: vertical; min-height: 80px; }
  input[type=text], select { padding: 8px 12px; border: 1px solid #ddd; border-radius: 6px;
                              font-size: 0.9rem; font-family: inherit; }
  .form-row { display: flex; gap: 12px; align-items: center; margin-bottom: 12px; }
  .form-row label { font-weight: 600; font-size: 0.88rem; min-width: 70px; }
  .status-flow { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
  .status-flow .btn { font-size: 0.82rem; padding: 5px 14px; }
  #toast { position: fixed; bottom: 24px; right: 24px; background: #333; color: #fff;
           padding: 12px 20px; border-radius: 8px; display: none; font-size: 0.9rem; z-index: 999; }
</style>
"""


def _nav(active: str, user_name: str) -> str:
    return f"""
<nav class="nav">
  <span class="logo">🍲 管理后台</span>
  <a href="/admin/targets">月度目标</a>
  <a href="/admin/competitors">假想敌</a>
  <a href="/admin/issues" class="{"active" if active == "issues" else ""}">问题与需求</a>
  <a href="/admin/users">用户管理</a>
  <span class="user">👤 {html_mod.escape(user_name)} · <a href="/admin/logout">退出</a></span>
</nav>
"""


_STATUS_LABELS = {
    "open": "待处理",
    "planning": "规划中",
    "approved": "已批准",
    "in_progress": "进行中",
    "done": "已完成",
    "closed": "已关闭",
}

_TYPE_LABELS = {"bug": "Bug", "feature": "需求"}
_PRIORITY_LABELS = {"urgent": "紧急", "high": "高", "medium": "中", "low": "低"}


# ── GET /admin/issues ─────────────────────────────────────────────────────────


@router.get("/admin/issues", response_class=HTMLResponse)
async def issues_list_page(
    request: Request,
    status: str | None = None,
    session: dict = Depends(require_auth),
):
    issues = get_issues(status)
    user_name = session.get("name", "管理员")

    # Filter tabs
    tabs = ""
    for s, label in [("", "全部"), *_STATUS_LABELS.items()]:
        active = "active" if (status or "") == s else ""
        tabs += f'<a href="/admin/issues{"?status=" + s if s else ""}" class="btn btn-outline {active}" style="{"font-weight:700;border-color:#333" if active else ""}">{label}</a> '

    rows = ""
    for iss in issues:
        sid = iss["id"]
        st = iss["status"]
        tp = iss["type"]
        pr = iss["priority"]
        title_esc = html_mod.escape(iss["title"])
        created = str(iss["created_at"])[:16].replace("T", " ")
        updated = str(iss["updated_at"])[:16].replace("T", " ")
        creator = html_mod.escape(iss["created_by"] or "—")
        rows += f"""<tr style="cursor:pointer" onclick="window.location='/admin/issues/{sid}'">
            <td><strong>#{sid}</strong></td>
            <td><strong>{title_esc}</strong></td>
            <td><span class="badge badge-{tp}">{_TYPE_LABELS.get(tp, tp)}</span></td>
            <td><span class="badge badge-{pr}">{_PRIORITY_LABELS.get(pr, pr)}</span></td>
            <td><span class="badge badge-{st}">{_STATUS_LABELS.get(st, st)}</span></td>
            <td>{creator}</td>
            <td>{updated}</td>
        </tr>"""

    if not rows:
        rows = '<tr><td colspan="7" style="text-align:center;color:#999;padding:32px">暂无问题</td></tr>'

    page_html = f"""<!DOCTYPE html><html><head>
{_BASE_STYLE}
<title>问题与需求 — 管理后台</title>
</head><body>
{_nav("issues", user_name)}
<div class="container">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
    <h2 style="margin:0">问题与需求</h2>
    <button class="btn btn-primary" onclick="document.getElementById('new-issue').style.display='block'">＋ 新建</button>
  </div>
  <div style="display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap">{tabs}</div>

  <!-- New issue form (hidden by default) -->
  <div id="new-issue" class="card" style="display:none">
    <h3 style="margin-top:0">新建问题</h3>
    <div class="form-row">
      <label>标题</label>
      <input type="text" id="ni-title" style="flex:1" placeholder="简述问题或需求">
    </div>
    <div class="form-row">
      <label>类型</label>
      <select id="ni-type"><option value="bug">Bug</option><option value="feature">需求</option></select>
      <label style="margin-left:12px">优先级</label>
      <select id="ni-priority">
        <option value="low">低</option>
        <option value="medium" selected>中</option>
        <option value="high">高</option>
        <option value="urgent">紧急</option>
      </select>
    </div>
    <div class="form-row" style="align-items:flex-start">
      <label>描述</label>
      <textarea id="ni-desc" style="flex:1" rows="4" placeholder="详细描述问题、复现步骤、期望效果等..."></textarea>
    </div>
    <div style="display:flex;gap:8px;justify-content:flex-end">
      <button class="btn btn-outline" onclick="document.getElementById('new-issue').style.display='none'">取消</button>
      <button class="btn btn-primary" onclick="createIssue()">提交</button>
    </div>
  </div>

  <div class="card" style="padding:0;overflow:hidden">
    <table>
      <thead><tr>
        <th>#</th><th>标题</th><th>类型</th><th>优先级</th><th>状态</th><th>创建人</th><th>更新时间</th>
      </tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </div>
</div>
<div id="toast"></div>
<script>
function toast(msg) {{
  const t = document.getElementById('toast');
  t.textContent = msg; t.style.display = 'block';
  setTimeout(() => t.style.display = 'none', 2000);
}}

async function createIssue() {{
  const title = document.getElementById('ni-title').value.trim();
  if (!title) {{ alert('请输入标题'); return; }}
  const body = {{
    title,
    description: document.getElementById('ni-desc').value,
    type: document.getElementById('ni-type').value,
    priority: document.getElementById('ni-priority').value,
  }};
  const r = await fetch('/admin/issues', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify(body),
  }});
  const d = await r.json();
  if (d.ok) {{ toast('✓ 已创建'); setTimeout(() => location.reload(), 800); }}
  else {{ toast('创建失败: ' + (d.error || '')); }}
}}
</script>
</body></html>"""

    return HTMLResponse(content=page_html)


# ── POST /admin/issues (create) ──────────────────────────────────────────────


@router.post("/admin/issues")
async def create_issue_route(body: CreateIssueBody, session: dict = Depends(require_auth)):
    if not is_db_available():
        return JSONResponse({"ok": False, "error": "DB not available"}, status_code=503)
    creator = session.get("name", "admin")
    issue = create_issue(
        title=body.title,
        description=body.description,
        type_=body.type,
        priority=body.priority,
        created_by=creator,
    )
    if issue is None:
        return JSONResponse({"ok": False, "error": "Failed to create issue"}, status_code=500)
    # Auto-post the description as first thread message if non-empty
    if body.description.strip():
        add_issue_message(issue["id"], creator, body.description, role="user")
    return {"ok": True, "issue_id": issue["id"]}


# ── GET /admin/issues/{id} (detail + thread) ─────────────────────────────────


@router.get("/admin/issues/{issue_id}", response_class=HTMLResponse)
async def issue_detail_page(issue_id: int, request: Request, session: dict = Depends(require_auth)):
    issue = get_issue(issue_id)
    if not issue:
        return HTMLResponse("<h2>Issue not found</h2>", status_code=404)

    messages = get_issue_messages(issue_id)
    user_name = session.get("name", "管理员")

    title_esc = html_mod.escape(issue["title"])
    desc_esc = html_mod.escape(issue["description"])
    st = issue["status"]
    tp = issue["type"]
    pr = issue["priority"]
    created = str(issue["created_at"])[:16].replace("T", " ")
    creator = html_mod.escape(issue["created_by"] or "—")

    # Thread messages HTML
    msgs_html = ""
    for msg in messages:
        role = msg["role"]
        sender = html_mod.escape(msg["sender"])
        content = html_mod.escape(msg["content"])
        time_str = str(msg["created_at"])[:16].replace("T", " ")
        icon = "🤖" if role == "agent" else "👤"
        msgs_html += f"""
        <div class="thread-msg {role}">
          <div class="sender">{icon} {sender}</div>
          <div class="body">{content}</div>
          <div class="time">{time_str}</div>
        </div>"""

    if not msgs_html:
        msgs_html = '<p style="color:#999;text-align:center;padding:24px">暂无消息</p>'

    # Status transition buttons
    status_btns = ""
    transitions = {
        "open": [("planning", "开始规划"), ("closed", "关闭")],
        "planning": [("approved", "✓ 批准方案"), ("open", "退回"), ("closed", "关闭")],
        "approved": [("in_progress", "开始执行"), ("planning", "退回规划")],
        "in_progress": [("done", "✓ 完成"), ("planning", "退回规划")],
        "done": [("closed", "关闭"), ("open", "重新打开")],
        "closed": [("open", "重新打开")],
    }
    for next_st, label in transitions.get(st, []):
        style = 'background:#27ae60;color:#fff' if '批准' in label or '完成' in label else ''
        status_btns += f'<button class="btn btn-outline" style="{style}" onclick="setStatus(\'{next_st}\')">{label}</button>'

    page_html = f"""<!DOCTYPE html><html><head>
{_BASE_STYLE}
<title>#{issue_id} {title_esc} — 管理后台</title>
</head><body>
{_nav("issues", user_name)}
<div class="container">
  <a href="/admin/issues" style="color:#666;text-decoration:none;font-size:0.88rem">← 返回列表</a>
  <div class="card" style="margin-top:12px">
    <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:16px">
      <div>
        <h2 style="margin:0 0 8px">#{issue_id} · {title_esc}</h2>
        <div style="display:flex;gap:8px;flex-wrap:wrap">
          <span class="badge badge-{tp}">{_TYPE_LABELS.get(tp, tp)}</span>
          <span class="badge badge-{pr}">{_PRIORITY_LABELS.get(pr, pr)}</span>
          <span class="badge badge-{st}">{_STATUS_LABELS.get(st, st)}</span>
        </div>
      </div>
      <div style="text-align:right;font-size:0.82rem;color:#888">
        <div>创建: {creator} · {created}</div>
        <div>指派: {html_mod.escape(issue["assignee"] or "agent")}</div>
      </div>
    </div>
    {f'<div style="margin-top:16px;padding:14px;background:#f9f9f9;border-radius:8px;white-space:pre-wrap;line-height:1.5">{desc_esc}</div>' if desc_esc else ''}
    <div class="status-flow">{status_btns}</div>
  </div>

  <div class="card">
    <h3 style="margin-top:0">💬 讨论</h3>
    <div id="thread" style="max-height:500px;overflow-y:auto;padding:4px 0">
      {msgs_html}
    </div>
    <div style="margin-top:16px">
      <textarea id="msg-input" placeholder="输入消息..."></textarea>
      <div style="display:flex;justify-content:flex-end;margin-top:8px">
        <button class="btn btn-primary" onclick="sendMsg()">发送</button>
      </div>
    </div>
  </div>
</div>
<div id="toast"></div>
<script>
const ISSUE_ID = {issue_id};
function toast(msg) {{
  const t = document.getElementById('toast');
  t.textContent = msg; t.style.display = 'block';
  setTimeout(() => t.style.display = 'none', 2000);
}}

async function setStatus(s) {{
  const r = await fetch(`/admin/issues/${{ISSUE_ID}}/status`, {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{status: s}}),
  }});
  const d = await r.json();
  if (d.ok) {{ toast('✓ 状态已更新'); setTimeout(() => location.reload(), 800); }}
  else {{ toast('失败: ' + (d.error || '')); }}
}}

async function sendMsg() {{
  const input = document.getElementById('msg-input');
  const content = input.value.trim();
  if (!content) return;
  const r = await fetch(`/admin/issues/${{ISSUE_ID}}/message`, {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{content}}),
  }});
  const d = await r.json();
  if (d.ok) {{ input.value = ''; location.reload(); }}
  else {{ toast('发送失败: ' + (d.error || '')); }}
}}

// Scroll thread to bottom
document.getElementById('thread').scrollTop = document.getElementById('thread').scrollHeight;
</script>
</body></html>"""

    return HTMLResponse(content=page_html)


# ── POST /admin/issues/{id}/message ──────────────────────────────────────────


@router.post("/admin/issues/{issue_id}/message")
async def post_message_admin(issue_id: int, body: MessageBody, session: dict = Depends(require_auth)):
    issue = get_issue(issue_id)
    if not issue:
        return JSONResponse({"ok": False, "error": "Issue not found"}, status_code=404)
    sender = session.get("name", "admin")
    msg = add_issue_message(issue_id, sender, body.content, role="user")
    if msg is None:
        return JSONResponse({"ok": False, "error": "Failed to add message"}, status_code=500)
    return {"ok": True, "message_id": msg["id"]}


# ── POST /admin/issues/{id}/status ───────────────────────────────────────────


@router.post("/admin/issues/{issue_id}/status")
async def update_status_admin(issue_id: int, body: StatusBody, session: dict = Depends(require_auth)):
    valid = {"open", "planning", "approved", "in_progress", "done", "closed"}
    if body.status not in valid:
        return JSONResponse({"ok": False, "error": f"Invalid status: {body.status}"}, status_code=400)
    issue = update_issue(issue_id, status=body.status)
    if issue is None:
        return JSONResponse({"ok": False, "error": "Issue not found"}, status_code=404)
    # Auto-post a status change message
    name = session.get("name", "admin")
    label = _STATUS_LABELS.get(body.status, body.status)
    add_issue_message(issue_id, name, f"状态变更 → {label}", role="user")
    return {"ok": True}


# ── JSON API endpoints (for agent cron) ───────────────────────────────────────


@router.get("/api/issues")
async def api_list_issues(status: str | None = None, active: bool = False):
    """List issues. ?active=true returns only actionable issues for the agent."""
    if active:
        return get_active_issues()
    return get_issues(status)


@router.get("/api/issues/{issue_id}")
async def api_get_issue(issue_id: int):
    issue = get_issue(issue_id)
    if not issue:
        return JSONResponse({"error": "Not found"}, status_code=404)
    messages = get_issue_messages(issue_id)
    return {"issue": issue, "messages": messages}


@router.post("/api/issues/{issue_id}/message")
async def api_post_message(issue_id: int, body: MessageBody):
    """Agent posts a message to an issue thread."""
    issue = get_issue(issue_id)
    if not issue:
        return JSONResponse({"ok": False, "error": "Not found"}, status_code=404)
    msg = add_issue_message(issue_id, "agent", body.content, role="agent")
    if msg is None:
        return JSONResponse({"ok": False, "error": "Failed"}, status_code=500)
    return {"ok": True, "message_id": msg["id"]}


@router.post("/api/issues/{issue_id}/status")
async def api_update_status(issue_id: int, body: StatusBody):
    """Agent updates issue status."""
    valid = {"open", "planning", "approved", "in_progress", "done", "closed"}
    if body.status not in valid:
        return JSONResponse({"ok": False, "error": f"Invalid status"}, status_code=400)
    issue = update_issue(issue_id, status=body.status)
    if issue is None:
        return JSONResponse({"ok": False, "error": "Not found"}, status_code=404)
    label = _STATUS_LABELS.get(body.status, body.status)
    add_issue_message(issue_id, "agent", f"状态变更 → {label}", role="agent")
    return {"ok": True}
