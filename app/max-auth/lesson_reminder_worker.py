"""Background worker: lesson reminders 24h and 3h before start (Europe/Moscow in messages)."""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from db import get_pool, serialize_record

logger = logging.getLogger("max-auth")

APP_TIMEZONE = ZoneInfo(os.getenv("APP_TIMEZONE", "Europe/Moscow"))
LESSON_REMINDER_POLL_SEC = max(15, int(os.getenv("LESSON_REMINDER_POLL_SEC", "60")))
LESSON_REMINDER_WINDOW_MIN = max(1, int(os.getenv("LESSON_REMINDER_WINDOW_MIN", "2")))
LESSON_REMINDER_ENABLED = os.getenv("LESSON_REMINDER_ENABLED", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

REMINDER_SPECS: dict[str, dict[str, Any]] = {
    "lesson_reminder_1d": {
        "offset": timedelta(hours=24),
        "lead_label": "Завтра",
        "prefix": "Напоминание о занятии",
    },
    "lesson_reminder_3h": {
        "offset": timedelta(hours=3),
        "lead_label": "Через 3 часа",
        "prefix": "Скоро занятие",
    },
}


def _format_starts_at_msk(value: Any) -> tuple[str, str]:
    if value is None:
        return "—", "—"
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    local = dt.astimezone(APP_TIMEZONE)
    now_local = datetime.now(APP_TIMEZONE)
    day_label = "Сегодня" if local.date() == now_local.date() else "Завтра" if local.date() == now_local.date() + timedelta(days=1) else local.strftime("%d.%m.%Y")
    time_label = local.strftime("%H:%M")
    return day_label, time_label


def build_lesson_reminder_text(lesson: dict[str, Any], kind: str) -> str:
    spec = REMINDER_SPECS[kind]
    day_label, time_label = _format_starts_at_msk(lesson.get("starts_at"))
    title = lesson.get("lesson_title") or "Занятие"
    group = lesson.get("track_name") or lesson.get("group_name") or "—"
    place = lesson.get("place") or "—"
    teacher = f"{lesson.get('teacher_last_name', '')} {lesson.get('teacher_first_name', '')}".strip() or "—"
    lead = spec["lead_label"]
    if kind == "lesson_reminder_1d":
        when_line = f"📅 {day_label}, {time_label} (МСК)"
    else:
        when_line = f"📅 {lead}: {day_label}, {time_label} (МСК)"
    return (
        f"{spec['prefix']}\n\n"
        f"📁 {group}\n"
        f"📚 {title}\n"
        f"{when_line}\n"
        f"📍 {place}\n"
        f"👤 Преподаватель: {teacher}"
    )


async def _notification_exists(user_id: str, lesson_id: str, kind: str) -> bool:
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT 1
            FROM app.notifications
            WHERE delivered_to = $1::uuid AND lesson_id = $2::uuid AND kind = $3::app.notification_kind
            """,
            uuid.UUID(user_id),
            uuid.UUID(lesson_id),
            kind,
        )
    return row is not None


async def _insert_notification(user_id: str, lesson_id: str, kind: str) -> bool:
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO app.notifications (delivered_to, lesson_id, kind)
            VALUES ($1::uuid, $2::uuid, $3::app.notification_kind)
            ON CONFLICT (delivered_to, lesson_id, kind) DO NOTHING
            RETURNING id
            """,
            uuid.UUID(user_id),
            uuid.UUID(lesson_id),
            kind,
        )
    return row is not None


async def _list_due_lessons(kind: str) -> list[dict[str, Any]]:
    spec = REMINDER_SPECS[kind]
    offset: timedelta = spec["offset"]
    window = timedelta(minutes=LESSON_REMINDER_WINDOW_MIN)
    sql = """
        SELECT l.id::text AS lesson_id, l.starts_at, l.ends_at, l.place, l.lesson_type, l.title,
               t.name AS track_name, COALESCE(t.id_hr, g.id_hr)::text AS hr_user_id,
               g.name AS group_name, cs.name AS slot_name,
               tp.last_name AS teacher_last_name, tp.first_name AS teacher_first_name,
               COALESCE(l.title, CASE WHEN l.lesson_type = 'practice' THEN 'Практика' ELSE 'Лекция' END)
                   AS lesson_title
        FROM app.lessons l
        LEFT JOIN app.tracks t ON t.id = l.track_id
        LEFT JOIN app.groups g ON g.id = COALESCE(l.reporting_group_id, l.group_id)
        LEFT JOIN app.conveyor_slots cs ON cs.id = l.slot_id
        JOIN app.profiles tp ON tp.user_id = l.teacher_id
        WHERE l.starts_at > now()
          AND (t.id IS NOT NULL OR g.id IS NOT NULL)
          AND COALESCE(t.status, g.status, 'active') = 'active'
          AND l.starts_at >= now() + $1::interval - $2::interval
          AND l.starts_at <= now() + $1::interval + $2::interval
        ORDER BY l.starts_at
    """
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(sql, offset, window)
    return [serialize_record(row) for row in rows]


async def _list_lesson_employees(lesson_id: str) -> list[dict[str, Any]]:
    sql = """
        SELECT p.user_id::text, p.max_id, p.status, p.first_name, p.last_name
        FROM app.lesson_members lm
        JOIN app.profiles p ON p.user_id = lm.user_id
        JOIN app.roles r ON r.id = p.role_id
        WHERE lm.lesson_id = $1::uuid
          AND r.code = 'employee'
          AND p.status = 'active'
    """
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(sql, uuid.UUID(lesson_id))
    return [serialize_record(row) for row in rows]


async def _process_kind(kind: str) -> dict[str, int]:
    from bot_notify import notify_lesson_reminder

    stats = {"lessons": 0, "employees_sent": 0, "employees_skipped": 0, "hr_recorded": 0}
    lessons = await _list_due_lessons(kind)
    stats["lessons"] = len(lessons)

    for lesson in lessons:
        lesson_id = str(lesson["lesson_id"])
        text = build_lesson_reminder_text(lesson, kind)

        hr_user_id = lesson.get("hr_user_id")
        if hr_user_id and not await _notification_exists(hr_user_id, lesson_id, kind):
            if await _insert_notification(hr_user_id, lesson_id, kind):
                stats["hr_recorded"] += 1

        for employee in await _list_lesson_employees(lesson_id):
            user_id = str(employee["user_id"])
            if await _notification_exists(user_id, lesson_id, kind):
                stats["employees_skipped"] += 1
                continue
            sent = await notify_lesson_reminder(user_id, text)
            if sent and await _insert_notification(user_id, lesson_id, kind):
                stats["employees_sent"] += 1
            else:
                stats["employees_skipped"] += 1

    return stats


async def process_lesson_reminders() -> dict[str, dict[str, int]]:
    results: dict[str, dict[str, int]] = {}
    for kind in REMINDER_SPECS:
        results[kind] = await _process_kind(kind)
    return results


async def run_lesson_reminder_worker() -> None:
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
                item["employees_sent"] + item["hr_recorded"]
                for item in results.values()
            )
            if touched:
                logger.info("Lesson reminders tick: %s", results)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Lesson reminder worker tick failed")
        await asyncio.sleep(LESSON_REMINDER_POLL_SEC)
