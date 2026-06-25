"""Background worker: lesson reminders 24h and 3h before start (Europe/Moscow in messages)."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import timedelta
from typing import Any

from db import get_pool, serialize_record
from lesson_notifications import (
    REMINDER_SPECS,
    _insert_notification,
    _notification_exists,
    build_lesson_reminder_text,
    list_lesson_notify_user_ids,
)

logger = logging.getLogger("max-auth")

LESSON_REMINDER_POLL_SEC = max(15, int(os.getenv("LESSON_REMINDER_POLL_SEC", "60")))
LESSON_REMINDER_WINDOW_MIN = max(1, int(os.getenv("LESSON_REMINDER_WINDOW_MIN", "2")))
LESSON_REMINDER_ENABLED = os.getenv("LESSON_REMINDER_ENABLED", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}


async def _list_due_lessons(kind: str) -> list[dict[str, Any]]:
    spec = REMINDER_SPECS[kind]
    offset = spec["offset"]
    window_min = LESSON_REMINDER_WINDOW_MIN
    sql = """
        SELECT l.id::text AS lesson_id, l.starts_at, l.ends_at, l.place, l.lesson_type, l.title,
               l.teacher_id::text AS teacher_id,
               t.name AS track_name, COALESCE(t.id_hr, g.id_hr)::text AS hr_user_id,
               g.name AS group_name, cs.name AS slot_name,
               tp.last_name AS teacher_last_name, tp.first_name AS teacher_first_name,
               tp.middle_name AS teacher_middle_name,
               COALESCE(l.title, CASE WHEN l.lesson_type = 'practice' THEN 'Практика' ELSE 'Лекция' END)
                   AS lesson_title
        FROM app.lessons l
        LEFT JOIN app.tracks t ON t.id = l.track_id
        LEFT JOIN app.groups g ON g.id = COALESCE(l.reporting_group_id, l.group_id)
        LEFT JOIN app.conveyor_slots cs ON cs.id = l.slot_id
        LEFT JOIN app.profiles tp ON tp.user_id = l.teacher_id
        WHERE l.starts_at > now()
          AND (t.id IS NOT NULL OR g.id IS NOT NULL)
          AND COALESCE(t.status, g.status, 'active') = 'active'
          AND l.starts_at >= now() + $1::interval - $2::interval
          AND l.starts_at <= now() + $1::interval + $2::interval
        ORDER BY l.starts_at
    """
    async with get_pool().acquire() as conn:
        window = timedelta(minutes=window_min)
        rows = await conn.fetch(sql, offset, window)
    return [serialize_record(row) for row in rows]


async def _process_kind(kind: str) -> dict[str, int]:
    from bot_notify import notify_lesson_reminder

    stats = {"lessons": 0, "sent": 0, "skipped": 0, "hr_recorded": 0}
    lessons = await _list_due_lessons(kind)
    stats["lessons"] = len(lessons)

    for lesson in lessons:
        lesson_id = str(lesson["lesson_id"])
        text = build_lesson_reminder_text(lesson, kind)
        teacher_id = lesson.get("teacher_id")

        hr_user_id = lesson.get("hr_user_id")
        if hr_user_id and not await _notification_exists(hr_user_id, lesson_id, kind):
            if await _insert_notification(hr_user_id, lesson_id, kind):
                stats["hr_recorded"] += 1

        user_ids = await list_lesson_notify_user_ids(lesson_id, teacher_id)
        for user_id in user_ids:
            if await _notification_exists(user_id, lesson_id, kind):
                stats["skipped"] += 1
                continue
            sent = await notify_lesson_reminder(user_id, text)
            if sent and await _insert_notification(user_id, lesson_id, kind):
                stats["sent"] += 1
            else:
                stats["skipped"] += 1

    return stats


async def process_lesson_reminders() -> dict[str, dict[str, int]]:
    results: dict[str, dict[str, int]] = {}
    for kind in REMINDER_SPECS:
        results[kind] = await _process_kind(kind)
    return results


async def run_lesson_reminder_worker() -> None:
    from lesson_notifications import APP_TIMEZONE

    logger.info(
        "Lesson reminder worker started (tz=%s, poll=%ss, window=±%smin)",
        APP_TIMEZONE.key,
        LESSON_REMINDER_POLL_SEC,
        LESSON_REMINDER_WINDOW_MIN,
    )
    while True:
        try:
            results = await process_lesson_reminders()
            touched = sum(
                item["sent"] + item["hr_recorded"]
                for item in results.values()
            )
            if touched:
                logger.info("Lesson reminders tick: %s", results)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Lesson reminder worker tick failed")
        await asyncio.sleep(LESSON_REMINDER_POLL_SEC)
