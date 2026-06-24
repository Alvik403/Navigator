"""Background worker: auto-form lessons by track + conveyor slot + SMU/deadlines."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from domain import run_auto_formation

logger = logging.getLogger("max-auth")

APP_TIMEZONE = ZoneInfo(os.getenv("APP_TIMEZONE", "Europe/Moscow"))
FORMATION_AUTO_ENABLED = os.getenv("FORMATION_AUTO_ENABLED", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
FORMATION_AUTO_POLL_SEC = max(300, int(os.getenv("FORMATION_AUTO_POLL_SEC", "3600")))
FORMATION_DAYS_AHEAD = max(0, int(os.getenv("FORMATION_DAYS_AHEAD", "1")))
FORMATION_AUTO_HOUR_LOCAL = int(os.getenv("FORMATION_AUTO_HOUR_LOCAL", "18"))


def _target_formation_date() -> date:
    now = datetime.now(APP_TIMEZONE)
    target = now.date() + timedelta(days=FORMATION_DAYS_AHEAD)
    return target


async def process_auto_formation(*, force: bool = False) -> dict:
    now = datetime.now(APP_TIMEZONE)
    if not force and now.hour < FORMATION_AUTO_HOUR_LOCAL:
        return {"skipped": True, "reason": "before_scheduled_hour", "hour_local": now.hour}
    target = _target_formation_date()
    result = await run_auto_formation(target_date=target)
    logger.info(
        "Auto formation for %s: created=%s skipped=%s",
        target.isoformat(),
        len(result.get("created") or []),
        len(result.get("skipped") or []),
    )
    return result


async def run_formation_auto_worker() -> None:
    logger.info(
        "Formation auto worker started (tz=%s, poll=%ss, days_ahead=%s, hour>=%s)",
        APP_TIMEZONE,
        FORMATION_AUTO_POLL_SEC,
        FORMATION_DAYS_AHEAD,
        FORMATION_AUTO_HOUR_LOCAL,
    )
    while True:
        try:
            await process_auto_formation()
        except Exception:
            logger.exception("Formation auto worker tick failed")
        await asyncio.sleep(FORMATION_AUTO_POLL_SEC)
