"""Admin UI for the per-store BOM (用料配方) table.

Provides a single HTML page at ``/admin/bom`` with:
  - werks selector (CA01..CA08)
  - search by 菜品 / 物料
  - inline table with edit + delete buttons
  - "新增条目" form that appends a row

All mutations go through JSON POST endpoints. The page reuses the
existing admin header/nav and base style so it inherits look-and-feel
from /admin/targets etc.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from server.auth import is_super_admin, require_auth
from server.db import (
    count_bom,
    delete_bom_entry,
    get_bom_entry,
    is_db_available,
    list_bom,
    list_bom_werks,
    upsert_bom_entry,
)
from server.routes.admin import _BASE_STYLE, _db_warning, _header

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

# Werks codes the inventory-check pipeline ships per CLAUDE.md
WERKS_CODES = ["CA01", "CA02", "CA03", "CA04", "CA05", "CA06", "CA07", "CA08"]


@router.get("/bom", response_class=HTMLResponse)
async def bom_page(
    request: Request,
    werks: str | None = None,
    dish: str | None = None,
    material: str | None = None,
    session: dict = Depends(require_auth),
):
    db_ok = is_db_available()

    selected_werks = werks or (list_bom_werks() or ["CA08"])[0] if db_ok else ""
    dish_filter = (dish or "").strip()
    material_filter = (material or "").strip()

    rows: list[dict] = []
    total = 0
    if db_ok and selected_werks:
        rows = list_bom(
            selected_werks,
            dish_filter=dish_filter or None,
            material_filter=material_filter or None,
            limit=500,
        )
        total = count_bom(
            selected_werks,
            dish_filter=dish_filter or None,
            material_filter=material_filter or None,
        )

    werks_options = "".join(
        f'<option value="{w}" {"selected" if w == selected_werks else ""}>{w}</option>'
        for w in WERKS_CODES
    )

    def _fmt(v):
        if v is None:
            return ""
        if isinstance(v, float) and v.is_integer():
            return str(int(v))
        return str(v)

    table_rows = ""
    for r in rows:
        rid = r["id"]
        table_rows += f"""
        <tr data-id="{rid}">
          <td>{_fmt(r['dish_code'])}</td>
          <td>{_fmt(r['dish_short_code'])}</td>
          <td>{_fmt(r['dish_name'])}</td>
          <td>{_fmt(r['spec'])}</td>
          <td>{_fmt(r['material_code'])}</td>
          <td>{_fmt(r['material_name'])}</td>
          <td class="num">{_fmt(r['portion'])}</td>
          <td class="num">{_fmt(r['loss_factor'])}</td>
          <td>{_fmt(r['unit'])}</td>
          <td class="num">{_fmt(r['packaging_factor'])}</td>
          <td>{_fmt(r['notes'])}</td>
          <td class="actions">
            <button class="btn btn-sm" onclick="editRow({rid})">编辑</button>
            <button class="btn btn-sm btn-danger" onclick="deleteRow({rid})">删除</button>
          </td>
        </tr>"""

    db_section = _db_warning() if not db_ok else ""
    user_name = session.get("name", "管理员")
    _is_super = is_super_admin(session.get("open_id", ""))

    dish_filter_esc = dish_filter.replace('"', "&quot;")
    material_filter_esc = material_filter.replace('"', "&quot;")

    page_html = f"""<!DOCTYPE html>
<html>
<head>
{_BASE_STYLE}
<style>
  .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .actions {{ white-space: nowrap; }}
  .btn-danger {{ background:#e74c3c; color:#fff; }}
  .btn-danger:hover {{ background:#c0392b; }}
  .filters {{ display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin-bottom:14px; }}
  .filters input, .filters select {{ padding:6px 8px; border:1px solid #ccc; border-radius:4px; }}
  .summary {{ color:#666; font-size:0.9em; margin-left:10px; }}
  .form-grid {{ display:grid; grid-template-columns:repeat(4,1fr); gap:8px 12px; }}
  .form-grid label {{ font-size:0.85em; color:#555; display:flex; flex-direction:column; gap:3px; }}
  .form-grid input {{ padding:5px 8px; border:1px solid #ccc; border-radius:4px; }}
  .form-grid label.span2 {{ grid-column: span 2; }}
  .form-grid label.span4 {{ grid-column: span 4; }}
  table {{ font-size:0.9em; }}
  th {{ position: sticky; top: 0; background: #f5f5f5; z-index: 1; }}
</style>
<title>用料配方 — 管理后台</title>
</head>
<body>
{_header("bom", user_name, super_admin=_is_super)}
<div class="container">
{db_section}
<div class="card">
  <form method="GET" action="/admin/bom" class="filters">
    <label>门店：
      <select name="werks">
        {werks_options}
      </select>
    </label>
    <label>菜品(名称/编码)：
      <input type="text" name="dish" value="{dish_filter_esc}" placeholder="清油 / 1060061">
    </label>
    <label>物料(名称/编码)：
      <input type="text" name="material" value="{material_filter_esc}" placeholder="底料 / 3000759">
    </label>
    <button type="submit" class="btn btn-primary btn-sm">筛选</button>
    <a href="/admin/bom?werks={selected_werks}" class="btn btn-sm" style="background:#eee">重置</a>
    <span class="summary">共 {total} 条（最多显示 500）</span>
  </form>

  <details style="margin: 12px 0;">
    <summary style="cursor:pointer; padding:6px; background:#f8f8f8; border-radius:4px;">＋ 新增条目</summary>
    <div style="padding:12px 4px;">
      <form id="add-form" class="form-grid" onsubmit="return submitAdd(event)">
        <input type="hidden" name="entry_id" value="">
        <input type="hidden" name="werks" value="{selected_werks}">
        <label>菜品编码 *<input type="number" name="dish_code" required></label>
        <label>菜品短编码<input type="number" name="dish_short_code"></label>
        <label class="span2">菜品名称<input type="text" name="dish_name"></label>
        <label>规格<input type="text" name="spec" placeholder="单锅/常温/..."></label>
        <label>物料编码 *<input type="number" name="material_code" required></label>
        <label class="span2">物料名称<input type="text" name="material_name"></label>
        <label>单位物料用量<input type="number" step="0.000001" name="portion"></label>
        <label>损耗(默认1)<input type="number" step="0.0001" name="loss_factor" value="1"></label>
        <label>库存单位<input type="text" name="unit" placeholder="公斤/听/瓶"></label>
        <label>包装换算<input type="number" step="0.000001" name="packaging_factor"></label>
        <label class="span4">备注<input type="text" name="notes"></label>
        <div class="span4">
          <button type="submit" class="btn btn-primary btn-sm">保存</button>
          <button type="button" class="btn btn-sm" style="background:#eee" onclick="resetForm()">清空</button>
          <span id="form-msg" style="margin-left:10px;"></span>
        </div>
      </form>
    </div>
  </details>

  <div style="overflow:auto; max-height:65vh;">
  <table>
    <thead>
      <tr>
        <th>菜品编码</th><th>短编码</th><th>菜品名称</th><th>规格</th>
        <th>物料编码</th><th>物料名称</th>
        <th>用量</th><th>损耗</th><th>单位</th><th>包装换算</th>
        <th>备注</th><th>操作</th>
      </tr>
    </thead>
    <tbody id="bom-body">
      {table_rows or '<tr><td colspan="12" style="text-align:center; color:#888; padding:20px;">无数据</td></tr>'}
    </tbody>
  </table>
  </div>
</div>
</div>

<script>
async function submitAdd(ev) {{
  ev.preventDefault();
  const form = document.getElementById('add-form');
  const fd = new FormData(form);
  const data = {{}};
  for (const [k, v] of fd.entries()) {{
    if (v === '' || v === null) continue;
    data[k] = v;
  }}
  // entry_id is hidden — present only when editing.
  if (!data.entry_id) delete data.entry_id;
  const msg = document.getElementById('form-msg');
  msg.textContent = '保存中…';
  try {{
    const r = await fetch('/admin/bom/save', {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify(data),
    }});
    const j = await r.json();
    if (j.ok) {{
      msg.textContent = '保存成功';
      msg.style.color = 'green';
      setTimeout(() => location.reload(), 600);
    }} else {{
      msg.textContent = '失败: ' + (j.error || '未知错误');
      msg.style.color = 'red';
    }}
  }} catch (e) {{
    msg.textContent = '请求失败: ' + e.message;
    msg.style.color = 'red';
  }}
  return false;
}}
function resetForm() {{
  const f = document.getElementById('add-form');
  f.reset();
  f.elements.entry_id.value = '';
  f.elements.werks.value = '{selected_werks}';
  document.getElementById('form-msg').textContent = '';
}}
async function editRow(id) {{
  const r = await fetch('/admin/bom/get?id=' + id);
  const j = await r.json();
  if (!j.ok) {{ alert(j.error || '加载失败'); return; }}
  const e = j.entry;
  const f = document.getElementById('add-form');
  f.elements.entry_id.value = e.id;
  f.elements.dish_code.value = e.dish_code ?? '';
  f.elements.dish_short_code.value = e.dish_short_code ?? '';
  f.elements.dish_name.value = e.dish_name ?? '';
  f.elements.spec.value = e.spec ?? '';
  f.elements.material_code.value = e.material_code ?? '';
  f.elements.material_name.value = e.material_name ?? '';
  f.elements.portion.value = e.portion ?? '';
  f.elements.loss_factor.value = e.loss_factor ?? 1;
  f.elements.unit.value = e.unit ?? '';
  f.elements.packaging_factor.value = e.packaging_factor ?? '';
  f.elements.notes.value = e.notes ?? '';
  // Expand the details so the form is visible.
  f.closest('details').open = true;
  f.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
  document.getElementById('form-msg').textContent = '编辑模式 (id=' + id + ')';
  document.getElementById('form-msg').style.color = '#888';
}}
async function deleteRow(id) {{
  if (!confirm('确认删除该条目? id=' + id)) return;
  const r = await fetch('/admin/bom/delete', {{
    method: 'POST',
    headers: {{ 'Content-Type': 'application/json' }},
    body: JSON.stringify({{ entry_id: id }}),
  }});
  const j = await r.json();
  if (j.ok) location.reload();
  else alert('删除失败: ' + (j.error || '未知'));
}}
</script>
</body>
</html>"""
    return HTMLResponse(page_html)


# ── JSON endpoints ────────────────────────────────────────────────────────────

class BomSaveBody(BaseModel):
    werks: str
    dish_code: int
    material_code: int
    entry_id: int | None = None
    dish_name: str | None = None
    dish_short_code: int | None = None
    spec: str | None = None
    material_name: str | None = None
    portion: float | None = None
    loss_factor: float | None = None
    unit: str | None = None
    packaging_factor: float | None = None
    notes: str | None = None


class BomDeleteBody(BaseModel):
    entry_id: int


@router.post("/bom/save")
async def save_bom(body: BomSaveBody, session: dict = Depends(require_auth)):
    if not is_db_available():
        return JSONResponse({"ok": False, "error": "DATABASE_URL not set"}, status_code=503)
    try:
        new_id = upsert_bom_entry(
            werks=body.werks,
            dish_code=body.dish_code,
            spec=body.spec,
            material_code=body.material_code,
            entry_id=body.entry_id,
            dish_name=body.dish_name,
            dish_short_code=body.dish_short_code,
            material_name=body.material_name,
            portion=body.portion,
            loss_factor=body.loss_factor,
            unit=body.unit,
            packaging_factor=body.packaging_factor,
            notes=body.notes,
            created_by=session.get("name") or session.get("open_id", ""),
        )
        return {"ok": True, "id": new_id}
    except Exception as exc:
        logger.exception("save_bom failed")
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)


@router.post("/bom/delete")
async def delete_bom(body: BomDeleteBody, session: dict = Depends(require_auth)):
    if not is_db_available():
        return JSONResponse({"ok": False, "error": "DATABASE_URL not set"}, status_code=503)
    ok = delete_bom_entry(body.entry_id)
    if not ok:
        return JSONResponse({"ok": False, "error": "条目不存在"}, status_code=404)
    return {"ok": True}


@router.get("/bom/get")
async def get_bom(id: int, session: dict = Depends(require_auth)):
    if not is_db_available():
        return JSONResponse({"ok": False, "error": "DATABASE_URL not set"}, status_code=503)
    entry = get_bom_entry(id)
    if entry is None:
        return JSONResponse({"ok": False, "error": "条目不存在"}, status_code=404)
    # JSON-friendly types: convert Decimal/datetime to str
    out = {}
    for k, v in entry.items():
        if v is None:
            out[k] = None
        elif hasattr(v, "isoformat"):
            out[k] = v.isoformat()
        elif isinstance(v, (int, float, str, bool)):
            out[k] = v
        else:
            try:
                out[k] = float(v)
            except (TypeError, ValueError):
                out[k] = str(v)
    return {"ok": True, "entry": out}
