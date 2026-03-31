"""Admin web UI — targets & competitor config.

Routes:
    GET  /admin              → redirect to /admin/targets
    GET  /admin/login        → login page (Lark OAuth)
    GET  /admin/oauth/callback → OAuth callback
    GET  /admin/logout       → clear session, redirect to login
    GET  /admin/targets      → targets admin page (HTML)  [auth required]
    POST /admin/targets      → save targets (JSON API)    [auth required]
    GET  /admin/competitors  → competitors admin page (HTML)  [auth required]
    GET  /admin/api-keys     → API key management page (HTML) [super-admin]
    POST /admin/competitors  → save competitors (JSON API)    [auth required]
"""

from __future__ import annotations

import html
import logging
from urllib.parse import quote, unquote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

from server.db import upsert_admin_user
from server.auth import (
    clear_session_cookie,
    exchange_code,
    get_lark_auth_url,
    get_session,
    is_super_admin,
    is_whitelisted,
    require_auth,
    set_session_cookie,
)
from server.db import (
    get_all_months,
    get_competitors,
    get_targets,
    has_targets,
    is_db_available,
    set_competitor,
    set_targets,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

STORES = [
    "加拿大一店",
    "加拿大二店",
    "加拿大三店",
    "加拿大四店",
    "加拿大五店",
    "加拿大六店",
    "加拿大七店",
    "加拿大八店",
]

SLOTS = ["08:00-13:59", "14:00-16:59", "17:00-21:59", "22:00-(次)07:59"]

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
  .warning { background: #fff3cd; border: 1px solid #ffc107; border-radius: 6px;
             padding: 14px 18px; color: #856404; }
  table { border-collapse: collapse; width: 100%; font-size: 0.88rem; }
  th { background: #fafafa; border-bottom: 2px solid #e0e0e0;
       padding: 8px 10px; text-align: left; white-space: nowrap; }
  td { border-bottom: 1px solid #eee; padding: 6px 10px; }
  tr:last-child td { border-bottom: none; }
  input[type=number], select { padding: 5px 8px; border: 1px solid #ccc;
    border-radius: 4px; font-size: 0.88rem; width: 100%; }
  input[type=number] { text-align: right; min-width: 80px; }
  select { min-width: 100px; }
  .btn { cursor: pointer; border: none; border-radius: 4px;
         padding: 8px 18px; font-size: 0.88rem; font-weight: 600; }
  .btn-primary { background: #c0392b; color: #fff; }
  .btn-primary:hover { background: #a93226; }
  .btn-sm { padding: 4px 12px; font-size: 0.82rem; }
  .toolbar { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; }
  label { font-weight: 600; font-size: 0.9rem; }
  #msg { font-size: 0.88rem; }
  .ok  { color: #1a7a1a; }
  .err { color: #c0392b; }
</style>
"""

_HEADER_TMPL = """
<header>
  <h1>🍲 海底捞兔子Agent加拿大片区管理后台</h1>
  <nav>
    <a href="/admin/targets" class="{t_active}">月度目标</a>
    <a href="/admin/competitors" class="{c_active}">假想敌配置</a>
    {tools_link}
  </nav>
  <span class="user-info">👤 {name} &nbsp;·&nbsp; <a href="/admin/logout" style="color:rgba(255,255,255,0.75);font-size:0.82rem">退出</a></span>
</header>
"""

_TOOLS_NAV_LINK = '<a href="/admin/tools" class="{tools_active}">工具</a>'
_APIKEYS_NAV_LINK = '<a href="/admin/api-keys" class="{ak_active}">API密钥</a>'
_KSB1_NAV_LINK = '<a href="/admin/ksb1" class="{ksb1_active}">KSB1核查</a>'


def _header(page: str, name: str = "", super_admin: bool = False) -> str:
    tools_link = _TOOLS_NAV_LINK.format(
        tools_active="active" if page == "tools" else ""
    ) if super_admin else ""
    apikeys_link = _APIKEYS_NAV_LINK.format(
        ak_active="active" if page == "api-keys" else ""
    ) if super_admin else ""
    ksb1_link = _KSB1_NAV_LINK.format(
        ksb1_active="active" if page == "ksb1" else ""
    )
    return _HEADER_TMPL.format(
        t_active="active" if page == "targets" else "",
        c_active="active" if page == "competitors" else "",
        tools_link=ksb1_link + tools_link + apikeys_link,
        name=name or "管理员",
    )


def _db_warning() -> str:
    return (
        '<div class="warning">⚠️ <strong>数据库未配置</strong> — '
        "DATABASE_URL not set。目标和假想敌数据仅从 JSON 文件读取，无法在此界面保存。</div>"
    )


def _get_redirect_uri() -> str:
    from server.config import settings
    return settings.lark_oauth_redirect_uri


# ── GET /admin/login ──────────────────────────────────────────────────────────


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, next: str = "/admin/targets"):
    # Already logged in → redirect
    if get_session(request):
        return RedirectResponse(url=next, status_code=302)

    redirect_uri = _get_redirect_uri()
    state = quote(next)  # store next URL in state param
    auth_url = get_lark_auth_url(redirect_uri, state)

    page_html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>登录 — 海底捞兔子Agent加拿大片区管理后台</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    margin: 0; background: #f5f5f5; color: #222;
    display: flex; align-items: center; justify-content: center;
    min-height: 100vh;
  }}
  .login-card {{
    background: #fff; border-radius: 12px; padding: 48px 40px;
    box-shadow: 0 4px 20px rgba(0,0,0,.12); text-align: center;
    max-width: 380px; width: 100%;
  }}
  .logo {{ font-size: 3rem; margin-bottom: 8px; }}
  h1 {{ margin: 0 0 6px; font-size: 1.4rem; color: #222; }}
  .subtitle {{ color: #888; font-size: 0.9rem; margin-bottom: 36px; }}
  .btn-lark {{
    display: inline-flex; align-items: center; gap: 10px;
    background: #00C8FF; color: #fff; text-decoration: none;
    padding: 13px 28px; border-radius: 8px; font-size: 1rem;
    font-weight: 600; transition: background 0.2s;
  }}
  .btn-lark:hover {{ background: #00aee0; }}
  .lark-icon {{ width: 22px; height: 22px; }}
  .footer {{ margin-top: 28px; color: #bbb; font-size: 0.78rem; }}
</style>
</head>
<body>
<div class="login-card">
  <div class="logo">🍲</div>
  <h1>海底捞兔子Agent加拿大片区管理后台</h1>
  <p class="subtitle">请使用飞书账号登录</p>
  <a href="{auth_url}" class="btn-lark">
    <svg class="lark-icon" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2z" fill="white" opacity="0.3"/>
      <path d="M8 12l4-4 4 4-4 4-4-4z" fill="white"/>
    </svg>
    使用飞书扫码登录
  </a>
  <p class="footer">仅限授权用户访问</p>
</div>
</body>
</html>"""
    return HTMLResponse(content=page_html)


# ── GET /admin/oauth/callback ─────────────────────────────────────────────────


@router.get("/oauth/callback")
async def oauth_callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None):
    if error:
        return HTMLResponse(
            content=f"<h2>授权失败</h2><p>{html.escape(str(error))}</p><a href='/admin/login'>重新登录</a>",
            status_code=400,
        )

    if not code:
        return RedirectResponse(url="/admin/login", status_code=302)

    redirect_uri = _get_redirect_uri()
    next_url = unquote(state) if state else "/admin/targets"
    # Sanitize next_url — only allow relative paths starting with /admin
    if not next_url.startswith("/admin"):
        next_url = "/admin/targets"

    try:
        user_info = await exchange_code(code, redirect_uri)
    except Exception as exc:
        logger.exception("OAuth code exchange failed")
        return HTMLResponse(
            content=f"<h2>登录失败</h2><p>无法获取用户信息：{html.escape(str(exc))}</p><a href='/admin/login'>重新登录</a>",
            status_code=500,
        )

    open_id = user_info["open_id"]
    name = user_info["name"]
    avatar_url = user_info.get("avatar_url", "")

    # Record this user in DB (creates row if new, updates last_seen if existing)
    try:
        upsert_admin_user(open_id, name, avatar_url)
    except Exception:
        logger.exception("Failed to record admin user in DB")

    if not is_whitelisted(open_id):
        logger.warning("Blocked non-whitelisted user: open_id=%s name=%s", open_id, name)
        return HTMLResponse(
            content=f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>访问被拒绝</title>
<style>body{{font-family:sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;background:#f5f5f5}}
.card{{background:#fff;padding:40px;border-radius:12px;box-shadow:0 4px 20px rgba(0,0,0,.1);text-align:center;max-width:400px}}
h2{{color:#c0392b}}p{{color:#666}}a{{color:#c0392b}}</style></head>
<body><div class="card">
<h2>🚫 访问被拒绝</h2>
<p>您的账号（{html.escape(name)}）没有访问权限。</p>
<p style="font-size:0.85rem;color:#aaa">open_id: {html.escape(open_id)}</p>
<a href="/admin/login">返回登录</a>
</div></body></html>""",
            status_code=403,
        )

    logger.info("Admin login: open_id=%s name=%s", open_id, name)
    response = RedirectResponse(url=next_url, status_code=302)
    set_session_cookie(response, open_id, name)
    return response


# ── GET /admin/logout ─────────────────────────────────────────────────────────


@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/admin/login", status_code=302)
    clear_session_cookie(response)
    return response


# ── GET /admin ────────────────────────────────────────────────────────────────


@router.get("/", response_class=RedirectResponse)
async def admin_index(request: Request):
    session = get_session(request)
    if session is None:
        return RedirectResponse(url="/admin/login", status_code=302)
    return RedirectResponse(url="/admin/targets")


# ── GET /admin/targets ────────────────────────────────────────────────────────


@router.get("/targets", response_class=HTMLResponse)
async def targets_page(request: Request, month: str | None = None, session: dict = Depends(require_auth)):
    db_ok = is_db_available()

    months = get_all_months() if db_ok else []

    # Determine selected month
    selected = month or (months[0] if months else "")

    # Load existing data for selected month (if any)
    existing: dict = {}
    if db_ok and selected and has_targets(selected):
        existing = get_targets(selected)

    # Build month selector
    month_options = ""
    for m in months:
        sel = 'selected' if m == selected else ''
        month_options += f'<option value="{m}" {sel}>{m}</option>\n'

    # Table rows
    table_rows = ""
    revenue_data = existing.get("revenue", {})
    tr_data = existing.get("turnover_rate", {})

    for store in STORES:
        rev = revenue_data.get(store, 0)
        tr = tr_data.get(store, {})
        s1 = tr.get(SLOTS[0], 0)
        s2 = tr.get(SLOTS[1], 0)
        s3 = tr.get(SLOTS[2], 0)
        s4 = tr.get(SLOTS[3], 0)
        tot = tr.get("total", 0)

        table_rows += f"""
        <tr>
          <td><strong>{store}</strong></td>
          <td><input type="number" step="0.01" min="0" name="revenue" data-store="{store}" value="{rev}"></td>
          <td><input type="number" step="0.0001" min="0" name="tr_slot_1" data-store="{store}" value="{s1}"></td>
          <td><input type="number" step="0.0001" min="0" name="tr_slot_2" data-store="{store}" value="{s2}"></td>
          <td><input type="number" step="0.0001" min="0" name="tr_slot_3" data-store="{store}" value="{s3}"></td>
          <td><input type="number" step="0.0001" min="0" name="tr_slot_4" data-store="{store}" value="{s4}"></td>
          <td><input type="number" step="0.0001" min="0" name="tr_total" data-store="{store}" value="{tot}"></td>
        </tr>"""

    db_section = _db_warning() if not db_ok else ""
    user_name = session.get("name", "管理员")
    _is_super = is_super_admin(session.get("open_id", ""))

    page_html = f"""<!DOCTYPE html>
<html>
<head>
{_BASE_STYLE}
<title>月度目标 — 管理后台</title>
</head>
<body>
{_header("targets", user_name, super_admin=_is_super)}
<div class="container">
{db_section}
<div class="card">
  <div class="toolbar">
    <label for="month-sel">选择月份：</label>
    <select id="month-sel" onchange="window.location='/admin/targets?month='+this.value">
      <option value="">-- 选择月份 --</option>
      {month_options}
    </select>
    <button class="btn btn-primary btn-sm" onclick="showAddMonth()">＋ 新增月份</button>
    <span id="msg"></span>
  </div>

  <div id="add-month-row" style="display:none; margin-bottom:12px; display:none">
    <input type="text" id="new-month-input" placeholder="YYYY-MM" maxlength="7"
           style="padding:5px 8px; border:1px solid #ccc; border-radius:4px; margin-right:8px; width:120px">
    <button class="btn btn-primary btn-sm" onclick="loadNewMonth()">载入</button>
    <button class="btn btn-sm" style="background:#eee" onclick="hideAddMonth()">取消</button>
  </div>

  {'<table>' if db_ok and selected else '<p style="color:#888">请先选择或新增一个月份</p><table style="display:none">' }
    <thead>
      <tr>
        <th>门店</th>
        <th>营收目标 (万元)</th>
        <th>翻台率 08:00-13:59</th>
        <th>翻台率 14:00-16:59</th>
        <th>翻台率 17:00-21:59</th>
        <th>翻台率 22:00-(次)07:59</th>
        <th>翻台率合计</th>
      </tr>
    </thead>
    <tbody id="targets-body">
      {table_rows}
    </tbody>
  </table>

  {'<div style="margin-top:14px"><button class="btn btn-primary" onclick="saveAll()" ' + ('disabled' if not db_ok else '') + '>保存全部</button></div>' if db_ok else ''}
</div>
</div>

<script>
const SELECTED_MONTH = {repr(selected)};

function showMsg(text, ok) {{
  const el = document.getElementById('msg');
  el.textContent = text;
  el.className = ok ? 'ok' : 'err';
}}

function showAddMonth() {{
  document.getElementById('add-month-row').style.display = 'flex';
  document.getElementById('add-month-row').style.alignItems = 'center';
}}

function hideAddMonth() {{
  document.getElementById('add-month-row').style.display = 'none';
}}

function loadNewMonth() {{
  const m = document.getElementById('new-month-input').value.trim();
  if (!/^\\d{{4}}-\\d{{2}}$/.test(m)) {{
    alert('格式须为 YYYY-MM，如 2026-04');
    return;
  }}
  window.location = '/admin/targets?month=' + m;
}}

async function saveAll() {{
  const month = document.getElementById('month-sel').value || SELECTED_MONTH;
  if (!month) {{ alert('请先选择月份'); return; }}

  const stores = {repr(STORES)};
  const targets = stores.map(store => {{
    const get = (name) => {{
      const el = document.querySelector(`input[name="${{name}}"][data-store="${{store}}"]`);
      return el ? parseFloat(el.value) || 0 : 0;
    }};
    return {{
      store,
      revenue:   get('revenue'),
      tr_slot_1: get('tr_slot_1'),
      tr_slot_2: get('tr_slot_2'),
      tr_slot_3: get('tr_slot_3'),
      tr_slot_4: get('tr_slot_4'),
      tr_total:  get('tr_total'),
    }};
  }});

  showMsg('保存中…', true);
  try {{
    const res = await fetch('/admin/targets', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{ month_key: month, targets }}),
    }});
    const data = await res.json();
    if (data.ok) {{
      showMsg('✓ 保存成功', true);
      // Refresh month selector if new month
      setTimeout(() => window.location = '/admin/targets?month=' + month, 800);
    }} else {{
      showMsg('✗ 保存失败: ' + (data.error || '未知错误'), false);
    }}
  }} catch(e) {{
    showMsg('✗ 网络错误: ' + e.message, false);
  }}
}}
</script>
</body>
</html>"""

    return HTMLResponse(content=page_html)


# ── POST /admin/targets ───────────────────────────────────────────────────────


class TargetRow(BaseModel):
    store: str
    revenue: float
    tr_slot_1: float
    tr_slot_2: float
    tr_slot_3: float
    tr_slot_4: float
    tr_total: float


class SaveTargetsBody(BaseModel):
    month_key: str
    targets: list[TargetRow]


@router.post("/targets")
async def save_targets(body: SaveTargetsBody, session: dict = Depends(require_auth)):
    if not is_db_available():
        return JSONResponse({"ok": False, "error": "DATABASE_URL not set"}, status_code=503)
    try:
        for row in body.targets:
            set_targets(
                body.month_key,
                row.store,
                row.revenue,
                row.tr_slot_1,
                row.tr_slot_2,
                row.tr_slot_3,
                row.tr_slot_4,
                row.tr_total,
            )
        return {"ok": True}
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)


# ── GET /admin/competitors ────────────────────────────────────────────────────


@router.get("/competitors", response_class=HTMLResponse)
async def competitors_page(request: Request, session: dict = Depends(require_auth)):
    db_ok = is_db_available()
    existing = get_competitors() if db_ok else {}

    table_rows = ""
    for store in STORES:
        current = existing.get(store, STORES[0])
        options = "".join(
            f'<option value="{s}" {"selected" if s == current else ""}>{s}</option>'
            for s in STORES
        )
        table_rows += f"""
        <tr>
          <td><strong>{store}</strong></td>
          <td>
            <select name="competitor" data-store="{store}">
              {options}
            </select>
          </td>
        </tr>"""

    db_section = _db_warning() if not db_ok else ""
    user_name = session.get("name", "管理员")
    _is_super = is_super_admin(session.get("open_id", ""))

    page_html = f"""<!DOCTYPE html>
<html>
<head>
{_BASE_STYLE}
<title>假想敌配置 — 管理后台</title>
</head>
<body>
{_header("competitors", user_name, super_admin=_is_super)}
<div class="container">
{db_section}
<div class="card">
  <p style="margin-top:0; color:#555; font-size:0.9rem">
    为每家门店选择一个"假想敌"门店（翻台率对标基准）。
  </p>
  <table>
    <thead>
      <tr>
        <th style="width:200px">门店</th>
        <th>假想敌门店</th>
      </tr>
    </thead>
    <tbody>
      {table_rows}
    </tbody>
  </table>
  <div style="margin-top:14px; display:flex; align-items:center; gap:12px">
    <button class="btn btn-primary" onclick="saveAll()" {"disabled" if not db_ok else ""}>保存全部</button>
    <span id="msg"></span>
  </div>
</div>
</div>

<script>
function showMsg(text, ok) {{
  const el = document.getElementById('msg');
  el.textContent = text;
  el.className = ok ? 'ok' : 'err';
}}

async function saveAll() {{
  const stores = {repr(STORES)};
  const competitors = stores.map(store => {{
    const el = document.querySelector(`select[name="competitor"][data-store="${{store}}"]`);
    return {{ store, competitor: el ? el.value : store }};
  }});

  showMsg('保存中…', true);
  try {{
    const res = await fetch('/admin/competitors', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{ competitors }}),
    }});
    const data = await res.json();
    if (data.ok) {{
      showMsg('✓ 保存成功', true);
    }} else {{
      showMsg('✗ 保存失败: ' + (data.error || '未知错误'), false);
    }}
  }} catch(e) {{
    showMsg('✗ 网络错误: ' + e.message, false);
  }}
}}
</script>
</body>
</html>"""

    return HTMLResponse(content=page_html)


# ── POST /admin/competitors ───────────────────────────────────────────────────


class CompetitorRow(BaseModel):
    store: str
    competitor: str


class SaveCompetitorsBody(BaseModel):
    competitors: list[CompetitorRow]


@router.post("/competitors")
async def save_competitors(body: SaveCompetitorsBody, session: dict = Depends(require_auth)):
    if not is_db_available():
        return JSONResponse({"ok": False, "error": "DATABASE_URL not set"}, status_code=503)
    try:
        for row in body.competitors:
            set_competitor(row.store, row.competitor)
        return {"ok": True}
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)


# ── GET /admin/users ──────────────────────────────────────────────────────────


@router.get("/users")
async def users_page(request: Request, session: dict = Depends(require_auth)):
    from server.db import get_admin_users
    users = get_admin_users()

    rows = ""
    for u in users:
        wl = u["whitelisted"]
        badge = '<span style="color:#27ae60;font-weight:bold">✓ 已授权</span>' if wl \
            else '<span style="color:#c0392b">✗ 未授权</span>'
        btn_label = "撤销" if wl else "授权"
        btn_color = "#c0392b" if wl else "#27ae60"
        last = str(u["last_seen_at"])[:16].replace("T", " ") if u["last_seen_at"] else "—"
        first = str(u["first_seen_at"])[:16].replace("T", " ") if u["first_seen_at"] else "—"
        avatar = f'<img src="{u["avatar_url"]}" style="width:28px;height:28px;border-radius:50%;vertical-align:middle;margin-right:6px">' if u["avatar_url"] else "👤"
        rows += f"""<tr>
            <td>{avatar}{u["name"]}</td>
            <td style="font-family:monospace;font-size:0.85em">{u["open_id"]}</td>
            <td>{badge}</td>
            <td>{first}</td>
            <td>{last}</td>
            <td><button onclick="toggleUser('{u["open_id"]}',{str(not wl).lower()})"
                style="background:{btn_color};color:#fff;border:none;padding:4px 12px;border-radius:4px;cursor:pointer">{btn_label}</button></td>
        </tr>"""

    if not rows:
        rows = '<tr><td colspan="6" style="text-align:center;color:#999;padding:24px">暂无登录记录</td></tr>'

    name = session.get("name", "")
    page_html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>用户管理 — Haidilao Admin</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'PingFang SC',sans-serif;background:#f5f7fa;color:#333}}
.nav{{background:#1a1a2e;padding:0 24px;display:flex;align-items:center;gap:24px;height:52px}}
.nav a{{color:#fff;text-decoration:none;font-size:0.9rem;opacity:.75;padding:8px 0}}
.nav a:hover,.nav a.active{{opacity:1}}
.nav .logo{{color:#fff;font-weight:700;font-size:1.1rem;margin-right:16px}}
.nav .user{{margin-left:auto;color:#fff;font-size:0.85rem;opacity:.75}}
.nav .user a{{color:#fff;opacity:.75;margin-left:12px}}
.container{{max-width:960px;margin:32px auto;padding:0 16px}}
h1{{font-size:1.4rem;margin-bottom:20px;color:#1a1a2e}}
table{{width:100%;background:#fff;border-radius:10px;box-shadow:0 2px 8px rgba(0,0,0,.06);border-collapse:collapse}}
th{{background:#f0f4ff;padding:12px 16px;text-align:left;font-size:0.82rem;color:#555;font-weight:600;border-bottom:1px solid #e8ecf4}}
td{{padding:11px 16px;border-bottom:1px solid #f0f0f0;font-size:0.88rem;vertical-align:middle}}
tr:last-child td{{border-bottom:none}}
#toast{{position:fixed;bottom:24px;right:24px;background:#333;color:#fff;padding:12px 20px;border-radius:8px;display:none;font-size:0.9rem}}
</style></head>
<body>
<nav class="nav">
  <span class="logo">🔧 管理后台</span>
  <a href="/admin/targets">目标数据</a>
  <a href="/admin/competitors">假想敌</a>
  <a href="/admin/users" class="active">用户管理</a>
  <span class="user">{name} · <a href="/admin/logout">退出</a></span>
</nav>
<div class="container">
  <h1>用户管理</h1>
  <table>
    <thead><tr>
      <th>用户</th><th>open_id</th><th>状态</th><th>首次登录</th><th>最近登录</th><th>操作</th>
    </tr></thead>
    <tbody>{rows}</tbody>
  </table>
</div>
<div id="toast"></div>
<script>
async function toggleUser(openId, grant) {{
  const r = await fetch('/admin/users/whitelist', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{open_id: openId, whitelisted: grant}})
  }});
  const d = await r.json();
  const toast = document.getElementById('toast');
  toast.textContent = d.ok ? (grant ? '✓ 已授权' : '✓ 已撤销') : '操作失败: ' + (d.error || '');
  toast.style.display = 'block';
  setTimeout(() => {{ toast.style.display = 'none'; location.reload(); }}, 1200);
}}
</script>
</body></html>"""
    return HTMLResponse(content=page_html)


@router.post("/users/whitelist")
async def set_whitelist(request: Request, session: dict = Depends(require_auth)):
    from server.db import set_admin_whitelist
    body = await request.json()
    open_id = body.get("open_id", "")
    whitelisted = bool(body.get("whitelisted", False))
    if not open_id:
        return {"ok": False, "error": "open_id required"}
    from server.db import get_admin_users
    known_ids = {u["open_id"] for u in get_admin_users()}
    if open_id not in known_ids:
        return {"ok": False, "error": "user not found"}
    try:
        set_admin_whitelist(open_id, whitelisted)
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ── KSB1 Accounting Check ─────────────────────────────────────────────────


@router.get("/ksb1", response_class=HTMLResponse)
async def ksb1_page(request: Request, session: dict = Depends(require_auth)):
    from datetime import date

    today = date.today()
    # Default to previous month
    if today.month == 1:
        default_month, default_year = 12, today.year - 1
    else:
        default_month, default_year = today.month - 1, today.year

    # Build month options
    month_options = "".join(
        f'<option value="{m}"{" selected" if m == default_month else ""}>{m:02d} 月</option>'
        for m in range(1, 13)
    )
    year_options = "".join(
        f'<option value="{y}"{" selected" if y == default_year else ""}>{y}</option>'
        for y in range(today.year - 2, today.year + 1)
    )

    name = session.get("name", "管理员")
    open_id = session.get("open_id", "")

    page_html = f"""<!DOCTYPE html>
<html>
<head>
{_BASE_STYLE}
<title>KSB1核查 — 管理后台</title>
<style>
  .status-box {{
    background: #f8f9fa; border: 1px solid #dee2e6; border-radius: 6px;
    padding: 14px 16px; font-family: monospace; font-size: 0.85rem;
    white-space: pre-wrap; max-height: 320px; overflow-y: auto;
    color: #333; display: none;
  }}
  .status-box.visible {{ display: block; }}
  .run-badge {{
    display: inline-block; padding: 3px 10px; border-radius: 12px;
    font-size: 0.8rem; font-weight: 600;
  }}
  .badge-pending  {{ background: #fff3cd; color: #856404; }}
  .badge-running  {{ background: #cff4fc; color: #0c5460; }}
  .badge-success  {{ background: #d1e7dd; color: #155724; }}
  .badge-failed   {{ background: #f8d7da; color: #721c24; }}
  .spinner {{
    display: inline-block; width: 14px; height: 14px;
    border: 2px solid #ccc; border-top-color: #333;
    border-radius: 50%; animation: spin 0.7s linear infinite;
    vertical-align: middle; margin-right: 6px;
  }}
  @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
</style>
</head>
<body>
{_header("ksb1", name, super_admin=is_super_admin(open_id))}
<div class="container">
  <div class="card">
    <h2 style="margin:0 0 6px;font-size:1.15rem">📊 KSB1 账务核查</h2>
    <p style="color:#666;font-size:0.9rem;margin:0 0 20px">
      导出 SAP KSB1 数据并生成逐店科目对比报告，完成后自动发送至生产群并 @ 您。
    </p>

    <div class="toolbar" style="flex-wrap:wrap;gap:16px">
      <div style="display:flex;align-items:center;gap:8px">
        <label for="sel-month">月份</label>
        <select id="sel-month" style="width:90px">{month_options}</select>
      </div>
      <div style="display:flex;align-items:center;gap:8px">
        <label for="sel-year">年份</label>
        <select id="sel-year" style="width:90px">{year_options}</select>
      </div>
      <div style="display:flex;align-items:center;gap:8px">
        <label>
          <input type="checkbox" id="chk-skip-dl">
          跳过下载（使用已有 KSB1 文件）
        </label>
      </div>
    </div>

    <div style="margin-top:18px;display:flex;align-items:center;gap:14px">
      <button class="btn btn-primary" id="run-btn" onclick="triggerRun()">▶ 立即运行</button>
      <span id="run-status"></span>
    </div>

    <div id="log-box" class="status-box" style="margin-top:16px"></div>
  </div>

  <div class="card" style="margin-top:0">
    <h3 style="margin:0 0 12px;font-size:0.95rem;color:#666">说明</h3>
    <ul style="margin:0;padding-left:20px;color:#555;font-size:0.88rem;line-height:1.8">
      <li>运行前请确保 VPN 已连接，SAP 账号已在 <code>.env</code> 中配置</li>
      <li>报告生成后将以 XLSX 附件形式发送至 <strong>生产核算群</strong></li>
      <li>飞书群内将 @ 您（当前登录用户：<strong>{html.escape(name)}</strong>）</li>
      <li>若 SAP 自动化未启用（<code>HAIDILAO_SAP_ENABLED=1</code>），运行将直接失败</li>
    </ul>
  </div>
</div>

<script>
let _pollTimer = null;

async function triggerRun() {{
  const month = parseInt(document.getElementById('sel-month').value, 10);
  const year  = parseInt(document.getElementById('sel-year').value, 10);
  const skipDl = document.getElementById('chk-skip-dl').checked;

  document.getElementById('run-btn').disabled = true;
  setStatus('pending', '⏳ 正在提交...');
  document.getElementById('log-box').classList.remove('visible');
  document.getElementById('log-box').textContent = '';

  try {{
    const resp = await fetch('/admin/ksb1/run', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{ month, year, skip_download: skipDl }}),
    }});
    const data = await resp.json();
    if (!data.ok) {{
      setStatus('failed', '✗ 提交失败: ' + (data.error || '未知错误'));
      document.getElementById('run-btn').disabled = false;
      return;
    }}
    setStatus('running', '<span class="spinner"></span> 运行中 · Run ID: ' + data.run_id);
    pollRun(data.run_id);
  }} catch (e) {{
    setStatus('failed', '✗ 网络错误: ' + e.message);
    document.getElementById('run-btn').disabled = false;
  }}
}}

function setStatus(state, html) {{
  const el = document.getElementById('run-status');
  const cls = {{ pending: 'badge-pending', running: 'badge-running', success: 'badge-success', failed: 'badge-failed' }};
  el.innerHTML = `<span class="run-badge ${{cls[state] || ''}}">${{html}}</span>`;
}}

async function pollRun(runId) {{
  if (_pollTimer) clearTimeout(_pollTimer);
  try {{
    const resp = await fetch('/api/runs/' + runId);
    const data = await resp.json();
    const status = data.status || 'unknown';

    if (status === 'success') {{
      setStatus('success', '✅ 完成！报告已发送至生产群');
      showLogs(data.logs || '');
      document.getElementById('run-btn').disabled = false;
    }} else if (status === 'failed') {{
      setStatus('failed', '❌ 运行失败');
      showLogs(data.logs || '（无输出）');
      document.getElementById('run-btn').disabled = false;
    }} else {{
      // still running / pending — poll again
      _pollTimer = setTimeout(() => pollRun(runId), 3000);
    }}
  }} catch (e) {{
    _pollTimer = setTimeout(() => pollRun(runId), 5000);
  }}
}}

function showLogs(text) {{
  const box = document.getElementById('log-box');
  box.textContent = text;
  box.classList.add('visible');
}}
</script>
</body>
</html>"""
    return HTMLResponse(content=page_html)


@router.post("/ksb1/run")
async def ksb1_run(request: Request, session: dict = Depends(require_auth)):
    """Trigger a KSB1 run — sends result to production group and @mentions the caller."""
    body = await request.json()
    month = body.get("month")
    year = body.get("year")
    skip_download = bool(body.get("skip_download", False))

    params: dict = {}
    if month:
        params["month"] = int(month)
    if year:
        params["year"] = int(year)
    if skip_download:
        params["skip_download"] = True

    # Embed caller identity so _notify_run can @mention them
    params["triggered_by_open_id"] = session.get("open_id", "")
    params["triggered_by_name"] = session.get("name", "")

    try:
        from server.routes.runs import create_run
        run = create_run("ksb1", params, notify_chat="production_accounting_report_chat")
        return {"ok": True, "run_id": run.id, "status": run.status.value}
    except Exception as exc:
        logger.exception("Failed to create KSB1 run")
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)


# ── API Key Management (super-admin only) ─────────────────────────────────


@router.get("/api-keys", response_class=HTMLResponse)
async def list_api_keys_page(request: Request, session: dict = Depends(require_auth)):
    if not is_super_admin(session["open_id"]):
        return HTMLResponse("<h2>403 — Super admin required</h2>", status_code=403)

    from server.api_keys import list_api_keys
    from server.db import get_admin_users

    keys = list_api_keys()
    users = {u["open_id"]: u["name"] for u in get_admin_users() if u["whitelisted"]}

    key_rows = ""
    for k in keys:
        revoked = k.get("revoked")
        status = '<span style="color:#c0392b">已撤销</span>' if revoked \
            else '<span style="color:#27ae60">有效</span>'
        created = str(k.get("created_at", ""))[:16].replace("T", " ")
        last_used = str(k.get("last_used_at", ""))[:16].replace("T", " ") if k.get("last_used_at") else "—"
        owner = k.get("open_id", "")
        if owner.startswith("agent:"):
            owner_name = f"🤖 {owner[6:]}"  # strip "agent:" prefix for display
        else:
            owner_name = users.get(owner, owner)
        scopes = k.get("scopes", "")
        label = html.escape(k.get("label", ""))
        key_id = k.get("id", "")
        revoke_btn = "" if revoked else f'<button class="btn btn-sm" style="background:#c0392b;color:#fff" onclick="revokeKey({key_id}, this)">撤销</button>'
        key_rows += f"""<tr>
            <td>{key_id}</td>
            <td>{label}</td>
            <td>{owner_name}</td>
            <td style="font-size:0.8rem;color:#666">{scopes}</td>
            <td>{status}</td>
            <td>{created}</td>
            <td>{last_used}</td>
            <td>{revoke_btn}</td>
        </tr>"""

    if not key_rows:
        key_rows = '<tr><td colspan="8" style="text-align:center;color:#999;padding:24px">暂无API密钥</td></tr>'

    # Build user options for the create form — blank value = standalone key
    user_options = '<option value="">— 独立密钥（不关联用户）—</option>' + "".join(
        f'<option value="{oid}">{name}</option>'
        for oid, name in users.items()
    )

    user_name = session.get("name", "管理员")

    page_html = f"""<!DOCTYPE html>
<html>
<head>
{_BASE_STYLE}
<title>API密钥管理 — 管理后台</title>
<style>
  .modal-bg {{ display:none; position:fixed; inset:0; background:rgba(0,0,0,.45); z-index:100; align-items:center; justify-content:center; }}
  .modal-bg.open {{ display:flex; }}
  .modal {{ background:#fff; border-radius:10px; padding:28px 32px; min-width:400px; max-width:520px; width:90%; box-shadow:0 8px 32px rgba(0,0,0,.2); }}
  .modal h3 {{ margin:0 0 18px; font-size:1.1rem; }}
  .form-row {{ margin-bottom:14px; }}
  .form-row label {{ display:block; font-size:0.85rem; font-weight:600; margin-bottom:4px; color:#555; }}
  .form-row input, .form-row select {{ width:100%; padding:8px 10px; border:1px solid #ccc; border-radius:6px; font-size:0.9rem; }}
  .key-reveal {{ background:#f0fdf4; border:1px solid #bbf7d0; border-radius:8px; padding:16px; margin-top:16px; display:none; }}
  .key-reveal code {{ font-family:monospace; font-size:0.95rem; word-break:break-all; color:#166534; }}
  .key-reveal .warn {{ color:#b45309; font-size:0.82rem; margin-top:8px; }}
  .copy-btn {{ margin-top:8px; }}
</style>
</head>
<body>
{_header("api-keys", user_name, super_admin=True)}
<div class="container">
  <div class="card">
    <div class="toolbar">
      <h2 style="margin:0;font-size:1.1rem">API 密钥管理</h2>
      <button class="btn btn-primary btn-sm" onclick="openModal()">＋ 生成新密钥</button>
      <span id="msg"></span>
    </div>
    <table>
      <thead>
        <tr>
          <th>ID</th><th>标签</th><th>所属用户</th><th>权限范围</th>
          <th>状态</th><th>创建时间</th><th>最后使用</th><th>操作</th>
        </tr>
      </thead>
      <tbody id="keys-body">{key_rows}</tbody>
    </table>
  </div>
</div>

<!-- Create key modal -->
<div class="modal-bg" id="modal">
  <div class="modal">
    <h3>🔑 生成新 API 密钥</h3>
    <div class="form-row">
      <label>所属用户</label>
      <select id="f-user">{user_options}</select>
    </div>
    <div class="form-row">
      <label>标签（备注）</label>
      <input type="text" id="f-label" placeholder="例：张三-报表访问">
    </div>
    <div class="form-row">
      <label>权限范围</label>
      <select id="f-scopes">
        <option value="reports:read,files:read">报表只读 (reports:read, files:read)</option>
        <option value="runs:trigger">触发运行 (runs:trigger)</option>
        <option value="reports:read,files:read,runs:trigger">报表只读 + 触发运行</option>
        <option value="admin">管理员 (admin)</option>
      </select>
    </div>

    <div class="key-reveal" id="key-reveal">
      <strong style="color:#166534">✅ 密钥已生成，请立即复制保存：</strong><br>
      <code id="key-text"></code>
      <div class="warn">⚠️ 此密钥仅显示一次，关闭后无法再次获取。</div>
      <button class="btn btn-sm copy-btn" onclick="copyKey()">📋 复制密钥</button>
    </div>

    <div style="display:flex;gap:10px;margin-top:20px">
      <button class="btn btn-primary" id="create-btn" onclick="createKey()">生成密钥</button>
      <button class="btn" style="background:#eee" onclick="closeModal()">关闭</button>
    </div>
  </div>
</div>

<script>
function showMsg(text, ok) {{
  const el = document.getElementById('msg');
  el.textContent = text;
  el.className = ok ? 'ok' : 'err';
}}

function openModal() {{
  document.getElementById('key-reveal').style.display = 'none';
  document.getElementById('key-text').textContent = '';
  document.getElementById('f-label').value = '';
  document.getElementById('create-btn').disabled = false;
  document.getElementById('modal').classList.add('open');
}}

function closeModal() {{
  document.getElementById('modal').classList.remove('open');
  location.reload();
}}

async function createKey() {{
  const open_id = document.getElementById('f-user').value;
  const label = document.getElementById('f-label').value.trim();
  const scopes = document.getElementById('f-scopes').value;

  if (!label) {{ alert('请填写标签'); return; }}

  document.getElementById('create-btn').disabled = true;

  const r = await fetch('/admin/api-keys/create', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{ open_id, label, scopes }})
  }});
  const d = await r.json();

  if (d.ok) {{
    document.getElementById('key-text').textContent = d.key;
    document.getElementById('key-reveal').style.display = 'block';
  }} else {{
    alert('生成失败: ' + (d.error || '未知错误'));
    document.getElementById('create-btn').disabled = false;
  }}
}}

function copyKey() {{
  const key = document.getElementById('key-text').textContent;
  navigator.clipboard.writeText(key).then(() => {{
    showMsg('✓ 已复制到剪贴板', true);
  }});
}}

async function revokeKey(id, btn) {{
  if (!confirm('确认撤销此密钥？操作不可逆。')) return;
  btn.disabled = true;
  const r = await fetch('/admin/api-keys/revoke', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{ id }})
  }});
  const d = await r.json();
  if (d.ok) {{
    showMsg('✓ 已撤销', true);
    setTimeout(() => location.reload(), 800);
  }} else {{
    showMsg('✗ 失败: ' + (d.error || ''), false);
    btn.disabled = false;
  }}
}}

// Close modal on backdrop click
document.getElementById('modal').addEventListener('click', function(e) {{
  if (e.target === this) closeModal();
}});
</script>
</body>
</html>"""
    return HTMLResponse(content=page_html)


@router.post("/api-keys/create")
async def create_api_key_route(request: Request, session: dict = Depends(require_auth)):
    from server.auth import is_super_admin
    if not is_super_admin(session["open_id"]):
        return JSONResponse({"ok": False, "error": "Super admin required"}, status_code=403)

    body = await request.json()
    open_id = body.get("open_id", "").strip()
    label = body.get("label", "").strip()
    scopes = body.get("scopes", "reports:read,files:read")

    if not label:
        return JSONResponse({"ok": False, "error": "label required"}, status_code=400)

    if open_id:
        # Linked to a real user — verify they exist and are whitelisted
        from server.db import get_admin_users
        users = {u["open_id"]: u for u in get_admin_users()}
        if open_id not in users:
            return JSONResponse({"ok": False, "error": "User not found"}, status_code=404)
        if not users[open_id].get("whitelisted"):
            return JSONResponse({"ok": False, "error": "User must be whitelisted first"}, status_code=400)
    else:
        # Standalone key — use a synthetic agent identifier from the label
        import re
        from server.db import upsert_admin_user
        slug = re.sub(r"[^a-z0-9_-]", "-", label.lower())[:40]
        open_id = f"agent:{slug}"
        # Satisfy the FK constraint: upsert a synthetic admin_users row for this agent
        upsert_admin_user(open_id, f"🤖 {label}", avatar_url="")

    try:
        from server.api_keys import create_api_key
        raw_key, record = create_api_key(open_id, label, scopes)
        return JSONResponse({
            "ok": True,
            "key": raw_key,  # shown ONCE — never stored or returned again
            "record": record,
            "warning": "Save this key now. It cannot be retrieved later.",
        })
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)


@router.post("/api-keys/revoke")
async def revoke_api_key_route(request: Request, session: dict = Depends(require_auth)):
    from server.auth import is_super_admin
    if not is_super_admin(session["open_id"]):
        return JSONResponse({"ok": False, "error": "Super admin required"}, status_code=403)

    body = await request.json()
    key_id = body.get("id")
    if not key_id:
        return JSONResponse({"ok": False, "error": "Key id required"}, status_code=400)

    from server.api_keys import revoke_api_key
    revoked = revoke_api_key(int(key_id))
    return JSONResponse({"ok": True, "revoked": revoked})
