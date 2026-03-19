"""Admin web UI — targets & competitor config.

Routes:
    GET  /admin              → redirect to /admin/targets
    GET  /admin/login        → login page (Lark OAuth)
    GET  /admin/oauth/callback → OAuth callback
    GET  /admin/logout       → clear session, redirect to login
    GET  /admin/targets      → targets admin page (HTML)  [auth required]
    POST /admin/targets      → save targets (JSON API)    [auth required]
    GET  /admin/competitors  → competitors admin page (HTML)  [auth required]
    POST /admin/competitors  → save competitors (JSON API)    [auth required]
"""

from __future__ import annotations

import logging
import os
from urllib.parse import quote, unquote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

from server.auth import (
    LoginRequired,
    clear_session_cookie,
    exchange_code,
    get_lark_auth_url,
    get_session,
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
  <h1>🍲 海底捞管理后台</h1>
  <nav>
    <a href="/admin/targets" class="{t_active}">月度目标</a>
    <a href="/admin/competitors" class="{c_active}">假想敌配置</a>
  </nav>
  <span class="user-info">👤 {name} &nbsp;·&nbsp; <a href="/admin/logout" style="color:rgba(255,255,255,0.75);font-size:0.82rem">退出</a></span>
</header>
"""


def _header(page: str, name: str = "") -> str:
    return _HEADER_TMPL.format(
        t_active="active" if page == "targets" else "",
        c_active="active" if page == "competitors" else "",
        name=name or "管理员",
    )


def _db_warning() -> str:
    return (
        '<div class="warning">⚠️ <strong>数据库未配置</strong> — '
        "DATABASE_URL not set。目标和假想敌数据仅从 JSON 文件读取，无法在此界面保存。</div>"
    )


def _get_redirect_uri() -> str:
    return os.environ.get(
        "LARK_OAUTH_REDIRECT_URI",
        "https://haidilao.wanghongming.xyz/admin/oauth/callback",
    )


# ── GET /admin/login ──────────────────────────────────────────────────────────


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, next: str = "/admin/targets"):
    # Already logged in → redirect
    if get_session(request):
        return RedirectResponse(url=next, status_code=302)

    redirect_uri = _get_redirect_uri()
    state = quote(next)  # store next URL in state param
    auth_url = get_lark_auth_url(redirect_uri, state)

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>登录 — 海底捞管理后台</title>
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
  <h1>海底捞管理后台</h1>
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
    return HTMLResponse(content=html)


# ── GET /admin/oauth/callback ─────────────────────────────────────────────────


@router.get("/oauth/callback")
async def oauth_callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None):
    if error:
        return HTMLResponse(
            content=f"<h2>授权失败</h2><p>{error}</p><a href='/admin/login'>重新登录</a>",
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
            content=f"<h2>登录失败</h2><p>无法获取用户信息：{exc}</p><a href='/admin/login'>重新登录</a>",
            status_code=500,
        )

    open_id = user_info["open_id"]
    name = user_info["name"]

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
<p>您的账号（{name}）没有访问权限。</p>
<p style="font-size:0.85rem;color:#aaa">open_id: {open_id}</p>
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

    html = f"""<!DOCTYPE html>
<html>
<head>
{_BASE_STYLE}
<title>月度目标 — 管理后台</title>
</head>
<body>
{_header("targets", user_name)}
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

    return HTMLResponse(content=html)


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

    html = f"""<!DOCTYPE html>
<html>
<head>
{_BASE_STYLE}
<title>假想敌配置 — 管理后台</title>
</head>
<body>
{_header("competitors", user_name)}
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

    return HTMLResponse(content=html)


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
