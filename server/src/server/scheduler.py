
from __future__ import annotations
import asyncio
from datetime import datetime
import json
import subprocess

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from zoneinfo import ZoneInfo

from server.config import settings

scheduler = AsyncIOScheduler()
_ANITA_REMINDER_CHAT_ID = "oc_96dc4631d7b2ed97362bd7676437855c"
_BIRMINGHAM_LAT = 52.4862
_BIRMINGHAM_LON = -1.8904
_LARK_CLI = "/Users/mu/.nvm/versions/node/v25.9.0/bin/lark-cli"


def _weather_code_label(code: int) -> str:
    labels = {
        0: "晴",
        1: "大致晴朗",
        2: "多云",
        3: "阴",
        45: "雾",
        48: "冻雾",
        51: "小毛毛雨",
        53: "毛毛雨",
        55: "强毛毛雨",
        61: "小雨",
        63: "中雨",
        65: "大雨",
        71: "小雪",
        73: "中雪",
        75: "大雪",
        80: "阵雨",
        81: "较强阵雨",
        82: "强阵雨",
        95: "雷暴",
    }
    return labels.get(code, f"天气代码{code}")


def _build_anita_weather_message() -> str:
    """Fetch today's Birmingham weather and format the daily reminder text."""
    resp = httpx.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": _BIRMINGHAM_LAT,
            "longitude": _BIRMINGHAM_LON,
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,wind_speed_10m_max",
            "forecast_days": 1,
            "timezone": "Europe/London",
        },
        timeout=20.0,
    )
    resp.raise_for_status()
    data = resp.json()
    daily = data["daily"]
    code = int(daily["weather_code"][0])
    tmax = round(float(daily["temperature_2m_max"][0]))
    tmin = round(float(daily["temperature_2m_min"][0]))
    rain = round(float(daily["precipitation_probability_max"][0]))
    wind = round(float(daily["wind_speed_10m_max"][0]))
    weather = _weather_code_label(code)
    return (
        f"伯明翰今天天气：{weather}，{tmin}~{tmax}°C，降雨概率 {rain}%，最大风速 {wind} km/h。\n"
        "Anita，你今天有没有去拉屎？记得穿衣服，看到后回个1。\n"
        "“Brevity is the soul of wit.”"
    )


def _build_anita_followup_message() -> str:
    return (
        "Anita，上午那条看到了回个1就行。记得穿衣服。\n"
        "“Brevity is the soul of wit.”"
    )


def _send_via_chloe_dong(text: str) -> None:
    """Send a text message with the Chloe Dong bot via lark-cli."""
    proc = subprocess.run(
        [
            _LARK_CLI,
            "im",
            "+messages-send",
            "--as",
            "bot",
            "--chat-id",
            _ANITA_REMINDER_CHAT_ID,
            "--text",
            text,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "lark-cli send failed")
    payload = json.loads(proc.stdout)
    if not payload.get("ok"):
        raise RuntimeError(proc.stdout.strip())


def _anita_replied_today() -> bool:
    """Return True if a user has replied with '1' in the chat after 08:00 London time today."""
    london_now = datetime.now(ZoneInfo("Europe/London"))
    start = london_now.replace(hour=8, minute=0, second=0, microsecond=0).isoformat()
    proc = subprocess.run(
        [
            _LARK_CLI,
            "im",
            "+chat-messages-list",
            "--as",
            "bot",
            "--chat-id",
            _ANITA_REMINDER_CHAT_ID,
            "--start",
            start,
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "lark-cli list failed")
    payload = json.loads(proc.stdout)
    if not payload.get("ok"):
        raise RuntimeError(proc.stdout.strip())
    for msg in payload.get("data", {}).get("messages", []):
        sender = msg.get("sender", {}) or {}
        if sender.get("sender_type") != "user":
            continue
        if str(msg.get("content", "")).strip() in {"1", "１"}:
            return True
    return False


def _parse_cron(expr: str) -> dict[str, str]:
    """Parse a 5-field cron expression into CronTrigger kwargs."""
    parts = expr.split()
    if len(parts) != 5:
        raise ValueError(f"Expected 5-field cron expression, got: {expr!r}")
    return dict(
        minute=parts[0],
        hour=parts[1],
        day=parts[2],
        month=parts[3],
        day_of_week=parts[4],
    )


async def _run_daily_report() -> None:
    """Trigger daily-report command via the run system."""
    from server.routes.runs import create_run
    create_run("daily-report", {}, notify_chat="production_accounting_report_chat")


async def _run_competitor_takeout_report() -> None:
    """Trigger weekly competitor takeout comparison export."""
    from server.routes.runs import create_run
    create_run("competitor-takeout-report", {}, notify_chat="production_accounting_report_chat")


async def _run_treasury_loan_watch() -> None:
    """Trigger treasury-loan-watch command via the run system."""
    from server.routes.runs import create_run
    create_run("treasury-loan-watch", {}, notify_chat="hongming")


async def _run_f13_clearing() -> None:
    """Trigger F.13 automatic clearing via the run system (1st of each month)."""
    from server.routes.runs import create_run
    create_run("f13-clearing", {}, notify_chat="hongming")


async def _run_store_hours_collect() -> None:
    """Trigger store-hours-collect command via the run system."""
    from server.routes.runs import create_run
    # Run-complete card (data-fill summary) goes to admin (hongming).
    # The store_hours group receives the unfilled-store alert sent directly by store_hours_collect.main.
    create_run("store-hours-collect", {}, notify_chat="hongming")


async def _run_anita_poop_reminder() -> None:
    """Send the daily Birmingham weather reminder via Chloe Dong."""
    text = await asyncio.to_thread(_build_anita_weather_message)
    await asyncio.to_thread(_send_via_chloe_dong, text)


async def _run_anita_weather_followup() -> None:
    """Send a single noon follow-up only if no user has replied '1' today."""
    replied = await asyncio.to_thread(_anita_replied_today)
    if replied:
        return
    text = _build_anita_followup_message()
    await asyncio.to_thread(_send_via_chloe_dong, text)


def setup_default_jobs() -> None:
    """Register the default cron jobs."""
    # Daily store operation report — default: 6:00 AM Vancouver time.
    # The cron expression in settings is interpreted as Vancouver time so that
    # the T-2 data reliability constraint is evaluated against the same clock
    # that main.py uses (ZoneInfo("America/Vancouver")).
    trigger = CronTrigger(**_parse_cron(settings.daily_report_cron), timezone="America/Vancouver")
    scheduler.add_job(
        _run_daily_report,
        trigger=trigger,
        id="daily-report-cron",
        name="Daily store operation report",
        replace_existing=True,
    )

    scheduler.add_job(
        _run_competitor_takeout_report,
        CronTrigger(**_parse_cron(settings.competitor_takeout_report_cron), timezone="America/Vancouver"),
        id="competitor-takeout-report-cron",
        name="Weekly competitor takeout revenue comparison export",
        replace_existing=True,
    )

    # Treasury loan maturity watch — 6:00 AM Vancouver time
    scheduler.add_job(
        _run_treasury_loan_watch,
        CronTrigger(hour=6, minute=0, timezone="America/Vancouver"),
        id="treasury-loan-watch-cron",
        name="Treasury loan maturity watch",
        replace_existing=True,
    )

    # F.13 automatic clearing — 1st of every month, 7:00 AM Vancouver time
    scheduler.add_job(
        _run_f13_clearing,
        CronTrigger(day=10, hour=7, minute=0, timezone="America/Vancouver"),
        id="f13-clearing-cron",
        name="F.13 automatic clearing (monthly)",
        replace_existing=True,
    )

    # Store working-hour data collection — 6:30 AM Vancouver time
    scheduler.add_job(
        _run_store_hours_collect,
        CronTrigger(hour=6, minute=30, timezone="America/Vancouver"),
        id="store-hours-collect-cron",
        name="Store working-hour data collection",
        replace_existing=True,
    )

    scheduler.add_job(
        _run_anita_poop_reminder,
        CronTrigger(**_parse_cron(settings.anita_weather_reminder_cron), timezone="Europe/London"),
        id="anita-poop-reminder-cron",
        name="Anita daily Birmingham weather reminder",
        replace_existing=True,
    )

    scheduler.add_job(
        _run_anita_weather_followup,
        CronTrigger(**_parse_cron(settings.anita_weather_followup_cron), timezone="Europe/London"),
        id="anita-weather-followup-cron",
        name="Anita noon follow-up reminder",
        replace_existing=True,
    )
