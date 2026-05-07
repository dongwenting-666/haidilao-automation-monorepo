from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

from dotenv import load_dotenv

from sap_gui.export import SAPExporter
from sap_gui.errors import SAPConnectionError, SAPExportError, SAPNavigationError
from sap_gui.navigation import SAPNavigator
from sap_gui.session import SAPSession
from vpn.connect import ensure_vpn

log = logging.getLogger(__name__)

COMPANY_LABELS = {
    "9451": "加拿大海底捞",
    "9452": "Hi Bowl",
}

FIELD_COMPANY = (
    "wnd[0]/usr/ctxtS_BUKRS-LOW",
    "wnd[0]/usr/ctxtBUKRS-LOW",
    "wnd[0]/usr/ctxtSO_BUKRS-LOW",
    "wnd[0]/usr/ctxtP_BUKRS",
)
FIELD_FISCAL_YEAR = (
    "wnd[0]/usr/txtS_GJAHR-LOW",
    "wnd[0]/usr/txtGJAHR-LOW",
    "wnd[0]/usr/ctxtP_GJAHR",
    "wnd[0]/usr/txtP_GJAHR",
)
FIELD_PERIOD_LOW = (
    "wnd[0]/usr/txtS_MONAT-LOW",
    "wnd[0]/usr/txtMONAT-LOW",
    "wnd[0]/usr/txtSO_MONAT-LOW",
    "wnd[0]/usr/txtP_MONAT",
)
FIELD_PERIOD_HIGH = (
    "wnd[0]/usr/txtS_MONAT-HIGH",
    "wnd[0]/usr/txtMONAT-HIGH",
    "wnd[0]/usr/txtSO_MONAT-HIGH",
)
FIELD_GL_LOW = (
    "wnd[0]/usr/ctxtS_HKONT-LOW",
    "wnd[0]/usr/ctxtHKONT-LOW",
    "wnd[0]/usr/ctxtSO_HKONT-LOW",
)
FIELD_GL_HIGH = (
    "wnd[0]/usr/ctxtS_HKONT-HIGH",
    "wnd[0]/usr/ctxtHKONT-HIGH",
    "wnd[0]/usr/ctxtSO_HKONT-HIGH",
)
FIELD_MAX_HITS = (
    "wnd[0]/usr/txtN",
    "wnd[0]/usr/txtP_MAXSEL",
    "wnd[0]/usr/txtP_MAXHIT",
    "wnd[0]/usr/txtMAXSEL",
    "wnd[0]/usr/txtMAXSEL-LOW",
    "wnd[0]/usr/txtMAXHIT-LOW",
    "wnd[0]/usr/txtP_MAX",
    "wnd[0]/usr/txtPA_MAXSEL",
    "wnd[0]/usr/txtPA_MAXHIT",
    "wnd[0]/usr/txtS_MAXSEL-LOW",
    "wnd[0]/usr/txtS_MAXHIT-LOW",
    "wnd[0]/usr/txtSO_MAXSEL-LOW",
    "wnd[0]/usr/txtSO_MAXHIT-LOW",
    "wnd[0]/usr/txtP_ANZSN",
    "wnd[0]/usr/txtANZSN",
    "wnd[0]/usr/txtS_ANZSN-LOW",
    "wnd[0]/usr/txtSO_ANZSN-LOW",
    "wnd[0]/usr/txtKAEP_SETT-MAXSEL",
)

FIELD_MAX_HITS_DIALOG = (
    "wnd[1]/usr/txtKAEP_SETT-MAXSEL",
    "wnd[1]/usr/txtP_MAXSEL",
    "wnd[1]/usr/txtP_MAXHIT",
    "wnd[1]/usr/txtMAXSEL",
    "wnd[1]/usr/txtP_MAX",
)


def _find_repo_root() -> Path:
    current = Path(__file__).resolve().parent
    for parent in [current, *current.parents]:
        if (parent / ".git").exists():
            return parent
    return current


REPO_ROOT = _find_repo_root()
DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "zfi0049-report"
DEFAULT_MAPPING_PATH = Path("/Users/mu/Downloads/报表科目对照表20260402.xlsx")
DEFAULT_SKILL_SCRIPT = Path("/Users/mu/.codex/skills/canada-pnl-report/scripts/generate_canada_pnl.py")


def _set_first_existing(session: object, candidates: Iterable[str], value: str, *, required: bool = True) -> str | None:
    for field_id in candidates:
        try:
            session.findById(field_id).text = value
            return field_id
        except Exception:
            continue
    if required:
        raise RuntimeError(f"Required SAP field not found. Candidates: {list(candidates)}")
    return None


def _execute_report(
    *,
    username: str,
    password: str,
    company_code: str,
    fiscal_year: int,
    posting_period: int,
    gl_low: str,
    gl_high: str,
    max_hits: int,
    output_path: Path,
    language: str,
) -> Path:
    def _connect_sap(*, force_clean: bool = False) -> SAPSession:
        # Prefer reusing the current SAP GUI session on macOS, but fall back to
        # auto-launch when the Scripting Console cannot reach the current session.
        if force_clean:
            log.info("Re-launching SAP GUI for a clean session...")
            ctx = SAPSession(auto_launch=True, quit_after=True)
            ctx.connect()
            return ctx
        try:
            ctx = SAPSession()
            ctx.connect()
            return ctx
        except SAPConnectionError:
            log.info("Current SAP session is not reachable; falling back to auto-launch mode...")
            ctx = SAPSession(auto_launch=True, quit_after=True)
            ctx.connect()
            return ctx

    def _is_company_field_error(exc: Exception) -> bool:
        return "company field not found" in str(exc).lower()

    sap_ctx: SAPSession = _connect_sap()

    try:
        while True:
            nav = SAPNavigator(sap_ctx.session)
            exporter = SAPExporter(sap_ctx.session, nav)

            log.info("Logging in as %s...", username)
            nav.login(username, password, language)

            if sys.platform == "darwin":
                log.info("Running transaction ZFI0049...")
                js = (
                "(function() {"
                '  ses.startTransaction("ZFI0049");'
                "  function tryResetSelection() {"
                '    try { ses.findById("wnd[0]/tbar[1]/btn[16]").press(); return "btn16"; } catch (e) {}'
                '    try { ses.findById("wnd[0]").sendVKey(15); return "vkey15"; } catch (e) {}'
                "    return null;"
                "  }"
                "  function tryPress(ids) {"
                "    for (var i = 0; i < ids.length; i++) {"
                "      try { ses.findById(ids[i]).press(); return ids[i]; } catch (e) {}"
                "    }"
                "    return null;"
                "  }"
                "  function trySet(ids, value) {"
                "    for (var i = 0; i < ids.length; i++) {"
                "      try {"
                "        var f = ses.findById(ids[i]);"
                "        f.text = value;"
                "        return {id: ids[i], value: '' + f.text};"
                "      } catch (e) {}"
                "    }"
                "    return null;"
                "  }"
                "  function waitSet(ids, value, attempts) {"
                "    for (var i = 0; i < attempts; i++) {"
                "      var r = trySet(ids, value);"
                "      if (r) return r;"
                "      try { java.lang.Thread.sleep(300); } catch (e) {}"
                "    }"
                "    return null;"
                "  }"
                "  function waitAny(ids, attempts) {"
                "    for (var i = 0; i < attempts; i++) {"
                "      for (var j = 0; j < ids.length; j++) {"
                "        try { return ses.findById(ids[j]); } catch (e) {}"
                "      }"
                "      try { java.lang.Thread.sleep(300); } catch (e) {}"
                "    }"
                "    return null;"
                "  }"
                f"  var companyIds = {json.dumps(list(FIELD_COMPANY))};"
                f"  var yearIds = {json.dumps(list(FIELD_FISCAL_YEAR))};"
                f"  var periodLowIds = {json.dumps(list(FIELD_PERIOD_LOW))};"
                f"  var periodHighIds = {json.dumps(list(FIELD_PERIOD_HIGH))};"
                f"  var glLowIds = {json.dumps(list(FIELD_GL_LOW))};"
                f"  var glHighIds = {json.dumps(list(FIELD_GL_HIGH))};"
                f"  var maxHitIds = {json.dumps(list(FIELD_MAX_HITS))};"
                f"  var maxHitDialogIds = {json.dumps(list(FIELD_MAX_HITS_DIALOG))};"
                '  var maxHitButtonIds = ["wnd[0]/usr/btnBUT1","wnd[0]/usr/btn%_BUT1_%_APP_%-VALU_PUSH"];'
                "  var reset = null;"
                "  var ready = waitAny(companyIds, 20);"
                "  if (!ready) {"
                "    reset = tryResetSelection();"
                "    if (reset) { try { java.lang.Thread.sleep(500); } catch (e) {} }"
                "    ready = waitAny(companyIds, 20);"
                "  }"
                "  if (!ready) throw 'company field not found';"
                f'  var company = waitSet(companyIds, {json.dumps(company_code)}, 20); if (!company) throw "company field not found";'
                f'  var year = waitSet(yearIds, {json.dumps(str(fiscal_year))}, 20); if (!year) throw "fiscal year field not found";'
                f'  var periodLow = waitSet(periodLowIds, {json.dumps(f"{posting_period:02d}")}, 20); if (!periodLow) throw "period low field not found";'
                f'  var periodHigh = waitSet(periodHighIds, {json.dumps(f"{posting_period:02d}")}, 20);'
                f'  var glLow = waitSet(glLowIds, {json.dumps(gl_low)}, 20); if (!glLow) throw "gl low field not found";'
                f'  var glHigh = waitSet(glHighIds, {json.dumps(gl_high)}, 20); if (!glHigh) throw "gl high field not found";'
                f'  var maxHit = waitSet(maxHitIds, {json.dumps(str(max_hits))}, 20);'
                "  var maxHitButton = null;"
                "  if (!maxHit) {"
                "    maxHitButton = tryPress(maxHitButtonIds);"
                "    if (maxHitButton) {"
                "      try { java.lang.Thread.sleep(300); } catch (e) {}"
                f'      maxHit = waitSet(maxHitDialogIds, {json.dumps(str(max_hits))}, 20);'
                '      try { ses.findById("wnd[1]/tbar[0]/btn[0]").press(); } catch (e) {}'
                "    }"
                "  }"
                f'  if (periodHigh && ((""+periodHigh.value).replace(/^0+/, "") !== {json.dumps(f"{posting_period:02d}")}.replace(/^0+/, ""))) throw "period high write mismatch: " + periodHigh.value;'
                f'  if ((""+glLow.value).replace(/^0+/, "") !== {json.dumps(gl_low)}.replace(/^0+/, "")) throw "gl low write mismatch: " + glLow.value;'
                f'  if ((""+glHigh.value).replace(/^0+/, "") !== {json.dumps(gl_high)}.replace(/^0+/, "")) throw "gl high write mismatch: " + glHigh.value;'
                f'  if (maxHit && ((""+maxHit.value).replace(/,/g, "") !== {json.dumps(str(max_hits))})) throw "max hits write mismatch: " + maxHit.value;'
                '  ses.findById("wnd[0]").sendVKey(0);'
                '  ses.findById("wnd[0]").sendVKey(8);'
                '  try { ses.findById("wnd[1]").sendVKey(0); } catch(e) {}'
                "  return JSON.stringify({"
                "    fields: {"
                "      reset: reset,"
                "      company: company,"
                "      year: year,"
                "      periodLow: periodLow,"
                "      periodHigh: periodHigh,"
                "      glLow: glLow,"
                "      glHigh: glHigh,"
                "      maxHitButton: maxHitButton,"
                "      maxHit: maxHit"
                "    }"
                "  });"
                "})()"
                )
                try:
                    result_raw = sap_ctx.session.execute_js(js, timeout=360.0)
                except SAPConnectionError as exc:
                    if _is_company_field_error(exc):
                        log.warning("Company field not found in current SAP state; retrying with a clean SAP session...")
                        sap_ctx.disconnect()
                        sap_ctx = _connect_sap(force_clean=True)
                        continue
                    raise
                if not result_raw:
                    raise RuntimeError("SAP did not return a save directory (DY_PATH)")
                result = json.loads(result_raw)
                log.info(
                    "ZFI0049 fields confirmed: company=%s year=%s period=%s-%s gl=%s-%s max_hits=%s",
                    (result.get("fields", {}).get("company") or {}).get("value"),
                    (result.get("fields", {}).get("year") or {}).get("value"),
                    (result.get("fields", {}).get("periodLow") or {}).get("value"),
                    (result.get("fields", {}).get("periodHigh") or {}).get("value"),
                    (result.get("fields", {}).get("glLow") or {}).get("value"),
                    (result.get("fields", {}).get("glHigh") or {}).get("value"),
                    (result.get("fields", {}).get("maxHit") or {}).get("value"),
                )
                try:
                    log.info("Exporting report via classic list export...")
                    exported = exporter.export_list_to_file(output_path, timeout=60.0)
                except (SAPExportError, SAPNavigationError):
                    log.warning("Classic list export did not trigger; falling back to ALV export...")
                    exported = exporter.export_alv_to_file(output_path, timeout=60.0)
                try:
                    nav.run_transaction("SESSION_MANAGER")
                except Exception:
                    log.debug("Best-effort cleanup to SESSION_MANAGER failed", exc_info=True)
                return exported

            log.info("Running transaction ZFI0049...")
            nav.run_transaction("ZFI0049")

            period_text = f"{posting_period:02d}"
            log.info("Setting company code: %s", company_code)
            _set_first_existing(sap_ctx.session, FIELD_COMPANY, company_code)
            log.info("Setting fiscal year: %s", fiscal_year)
            _set_first_existing(sap_ctx.session, FIELD_FISCAL_YEAR, str(fiscal_year))
            log.info("Setting posting period: %s", period_text)
            _set_first_existing(sap_ctx.session, FIELD_PERIOD_LOW, period_text)
            _set_first_existing(sap_ctx.session, FIELD_PERIOD_HIGH, period_text, required=False)
            log.info("Setting GL range: %s - %s", gl_low, gl_high)
            _set_first_existing(sap_ctx.session, FIELD_GL_LOW, gl_low)
            _set_first_existing(sap_ctx.session, FIELD_GL_HIGH, gl_high, required=False)
            log.info("Setting max hits: %s", max_hits)
            _set_first_existing(sap_ctx.session, FIELD_MAX_HITS, str(max_hits), required=False)

            log.info("Confirming selection screen...")
            nav.send_vkey(0)
            log.info("Executing report...")
            nav.press_button("wnd[0]/tbar[1]/btn[8]")
            log.info("Dismissing possible popup...")
            nav.dismiss_popup(window=1, vkey=0)

            log.info("Exporting report via list export...")
            exported = exporter.export_list_to_file(output_path, timeout=30.0)

            return exported
    finally:
        sap_ctx.disconnect()


def parse_args() -> argparse.Namespace:
    today = date.today()
    default_period = today.month - 1 if today.month > 1 else 12
    default_year = today.year - 1 if today.month <= 3 else today.year

    parser = argparse.ArgumentParser(description="Export SAP ZFI0049 report")
    parser.add_argument("--company-code", required=True, choices=sorted(COMPANY_LABELS))
    parser.add_argument("--fiscal-year", type=int, default=default_year)
    parser.add_argument("--posting-period", type=int, default=default_period, choices=range(1, 13))
    parser.add_argument("--gl-low", default="50000000")
    parser.add_argument("--gl-high", default="69999999")
    parser.add_argument("--max-hits", type=int, default=10_000_000)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING_PATH)
    parser.add_argument("--skill-script", type=Path, default=DEFAULT_SKILL_SCRIPT)
    parser.add_argument("--language", default="ZH")
    parser.add_argument("--store-name", default="", help="Single store to export; empty means all stores")
    return parser.parse_args()


def _generate_pnl(source_path: Path, mapping_path: Path, skill_script: Path, output_dir: Path, company_code: str, fiscal_year: int, posting_period: int, store_name: str = "") -> Path:
    if not mapping_path.is_file():
        raise FileNotFoundError(f"Mapping workbook not found: {mapping_path}")
    if not skill_script.is_file():
        raise FileNotFoundError(f"Canada PnL skill script not found: {skill_script}")

    timestamp = datetime.now().strftime("%H%M%S")
    store_suffix = f"_{store_name}" if store_name else ""
    output_path = output_dir / f"canada_pnl_{company_code}_{fiscal_year}_{posting_period:02d}{store_suffix}_{timestamp}.xlsx"
    cmd = [
        sys.executable,
        str(skill_script),
        "--source", str(source_path),
        "--mapping", str(mapping_path),
        "--output", str(output_path),
    ]
    if store_name:
        cmd.extend(["--store", store_name])
    log.info("Generating Canada PnL workbook...")
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.stdout:
        log.info(proc.stdout.strip())
    if proc.stderr:
        log.warning(proc.stderr.strip())
    if proc.returncode != 0:
        raise RuntimeError(f"Canada PnL generation failed with exit code {proc.returncode}")
    return output_path


def main() -> Path:
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = parse_args()

    username = os.getenv("SAP_USERNAME", "")
    password = os.getenv("SAP_PASSWORD", "")
    if not username or not password:
        raise SystemExit("SAP_USERNAME and SAP_PASSWORD are required")

    log.info("Ensuring VPN is connected...")
    ensure_vpn()

    company_label = COMPANY_LABELS.get(args.company_code, args.company_code)
    output_dir = args.output_dir / f"{args.fiscal_year}-{args.posting_period:02d}"
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%H%M%S")
    raw_output_path = output_dir / (
        f"zfi0049_{args.company_code}_{company_label}_{args.fiscal_year}_{args.posting_period:02d}_{timestamp}.xlsx"
    )

    exported = _execute_report(
        username=username,
        password=password,
        company_code=args.company_code,
        fiscal_year=args.fiscal_year,
        posting_period=args.posting_period,
        gl_low=args.gl_low,
        gl_high=args.gl_high,
        max_hits=args.max_hits,
        output_path=raw_output_path,
        language=args.language,
    )
    log.info("Raw export saved to %s", exported)

    pnl_path = _generate_pnl(
        source_path=exported,
        mapping_path=args.mapping,
        skill_script=args.skill_script,
        output_dir=output_dir,
        company_code=args.company_code,
        fiscal_year=args.fiscal_year,
        posting_period=args.posting_period,
        store_name=args.store_name,
    )
    log.info("Report saved to %s", pnl_path)
    return pnl_path


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
