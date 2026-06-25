"""Lesson push notifications: reminders, schedule changes, cancellations."""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from db import get_pool, serialize_record

logger = logging.getLogger("max-auth")

APP_TIMEZONE = ZoneInfo(os.getenv("APP_TIMEZONE", "Europe/Moscow"))
_GENERIC_LESSON_TITLES = frozenset({"Занятие", "Практика", "Лекция"})

REMINDER_SPECS: dict[str, dict[str, Any]] = {
    "lesson_reminder_1d": {
        "offset": timedelta(hours=24),
        "icon": "🔔",
        "prefix": "Напоминание о занятии",
    },
    "lesson_reminder_3h": {
        "offset": timedelta(hours=3),
        "icon": "⏰",
        "prefix": "Скоро занятие",
    },
}


def _normalize_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(ZoneInfo("UTC"))


def _place_norm(value: Any) -> str:
    return str(value or "").strip()


def format_starts_at_msk(value: Any) -> tuple[str, str]:
    if value is None:
        return "—", "—"
    local = _normalize_dt(value).astimezone(APP_TIMEZONE)
    now_local = datetime.now(APP_TIMEZONE)
    if local.date() == now_local.date():
        day_label = "Сегодня"
    elif local.date() == now_local.date() + timedelta(days=1):
        day_label = "Завтра"
    else:
        day_label = local.strftime("%d.%m.%Y")
    time_label = local.strftime("%H:%M")
    return day_label, time_label


def lesson_type_label(lesson_type: Any) -> str | None:
    if lesson_type == "practice":
        return "Практика"
    if lesson_type == "lecture":
        return "Лекция"
    return None


def teacher_display(lesson: dict[str, Any]) -> str | None:
    parts = [
        lesson.get("teacher_last_name"),
        lesson.get("teacher_first_name"),
        lesson.get("teacher_middle_name"),
    ]
    name = " ".join(str(part).strip() for part in parts if part and str(part).strip())
    return name or None


def lesson_header(lesson: dict[str, Any]) -> str:
    track = str(lesson.get("track_name") or lesson.get("group_name") or "").strip()
    type_label = lesson_type_label(lesson.get("lesson_type"))
    header_parts = [part for part in (track, type_label) if part]
    return " · ".join(header_parts) if header_parts else "Занятие"


def build_lesson_reminder_text(lesson: dict[str, Any], kind: str) -> str:
    spec = REMINDER_SPECS[kind]
    day_label, time_label = format_starts_at_msk(lesson.get("starts_at"))

    title = str(lesson.get("lesson_title") or lesson.get("title") or "").strip()
    type_label = lesson_type_label(lesson.get("lesson_type"))
    place = _place_norm(lesson.get("place"))
    teacher = teacher_display(lesson)

    lines = [
        f"{spec['icon']} {spec['prefix']}",
        "────────────────",
        "",
        lesson_header(lesson),
    ]

    if title and title not in _GENERIC_LESSON_TITLES and title != type_label:
        lines.append(title)

    lines.extend(["", f"🕐 {day_label} в {time_label} (МСК)"])
    if kind == "lesson_reminder_3h":
        lines.append("   через ~3 часа")
    elif kind == "lesson_reminder_1d" and day_label not in {"Сегодня", "Завтра"}:
        lines.append("   за сутки до начала")

    detail_lines: list[str] = []
    if place:
        detail_lines.append(f"📍 {place}")
    if teacher:
        detail_lines.append(f"👤 {teacher}")
    elif lesson.get("teacher_id"):
        detail_lines.append("👤 Инструктор уточняется")

    if detail_lines:
        lines.extend(["", *detail_lines])

    return "\n".join(lines)


def build_lesson_changed_text(
    lesson: dict[str, Any],
    *,
    old_starts_at: Any,
    new_starts_at: Any,
    old_place: Any,
    new_place: Any,
    old_teacher_name: str | None = None,
    new_teacher_name: str | None = None,
) -> str:
    lines = [
        "📝 Занятие изменено",
        "────────────────",
        "",
        lesson_header(lesson),
    ]

    title = str(lesson.get("lesson_title") or lesson.get("title") or "").strip()
    type_label = lesson_type_label(lesson.get("lesson_type"))
    if title and title not in _GENERIC_LESSON_TITLES and title != type_label:
        lines.append(title)

    change_lines: list[str] = []
    if _normalize_dt(old_starts_at) != _normalize_dt(new_starts_at):
        old_day, old_time = format_starts_at_msk(old_starts_at)
        new_day, new_time = format_starts_at_msk(new_starts_at)
        change_lines.extend([
            "",
            f"🕐 Было: {old_day} в {old_time} (МСК)",
            f"🕐 Стало: {new_day} в {new_time} (МСК)",
        ])

    if _place_norm(old_place) != _place_norm(new_place):
        old_p = _place_norm(old_place) or "—"
        new_p = _place_norm(new_place) or "—"
        change_lines.extend(["", f"📍 Было: {old_p}", f"📍 Стало: {new_p}"])

    old_teacher = (old_teacher_name or "").strip()
    new_teacher = (new_teacher_name or teacher_display(lesson) or "").strip()
    if old_teacher != new_teacher and (old_teacher or new_teacher):
        change_lines.extend(["", f"👤 Было: {old_teacher or '—'}", f"👤 Стало: {new_teacher or '—'}"])
    elif new_teacher and not change_lines:
        change_lines.extend(["", f"👤 {new_teacher}"])
    elif teacher_display(lesson) and not change_lines:
        change_lines.extend(["", f"👤 {teacher_display(lesson)}"])

    lines.extend(change_lines)
    return "\n".join(lines)


def build_lesson_cancelled_text(lesson: dict[str, Any]) -> str:
    day_label, time_label = format_starts_at_msk(lesson.get("starts_at"))
    place = _place_norm(lesson.get("place"))
    teacher = teacher_display(lesson)

    lines = [
        "❌ Занятие отменено",
        "────────────────",
        "",
        lesson_header(lesson),
        "",
        f"🕐 {day_label} в {time_label} (МСК)",
    ]
    if place:
        lines.append(f"📍 {place}")
    if teacher:
        lines.append(f"👤 {teacher}")
    return "\n".join(lines)


def schedule_fields_changed(old: dict[str, Any], new: dict[str, Any]) -> bool:
    if _normalize_dt(old.get("starts_at")) != _normalize_dt(new.get("starts_at")):
        return True
    if _place_norm(old.get("place")) != _place_norm(new.get("place")):
        return True
    return str(old.get("teacher_id") or "") != str(new.get("teacher_id") or "")


async def fetch_lesson_for_notify(lesson_id: str) -> dict[str, Any] | None:
    sql = """
        SELECT l.id::text AS lesson_id, l.starts_at, l.ends_at, l.place, l.lesson_type, l.title,
               l.teacher_id::text AS teacher_id,
               t.name AS track_name, g.name AS group_name, cs.name AS slot_name,
               tp.last_name AS teacher_last_name, tp.first_name AS teacher_first_name,
               tp.middle_name AS teacher_middle_name,
               COALESCE(l.title, CASE WHEN l.lesson_type = 'practice' THEN 'Практика' ELSE 'Лекция' END)
                   AS lesson_title
        FROM app.lessons l
        LEFT JOIN app.tracks t ON t.id = l.track_id
        LEFT JOIN app.groups g ON g.id = COALESCE(l.reporting_group_id, l.group_id)
        LEFT JOIN app.conveyor_slots cs ON cs.id = l.slot_id
        LEFT JOIN app.profiles tp ON tp.user_id = l.teacher_id
        WHERE l.id = $1::uuid
    """
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(sql, uuid.UUID(lesson_id))
    return serialize_record(row) if row else None


async def _profile_short_name(user_id: Any) -> str | None:
    if not user_id:
        return None
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT last_name, first_name
            FROM app.profiles
            WHERE user_id = $1::uuid
            """,
            uuid.UUID(str(user_id)),
        )
    if not row:
        return None
    return f"{row['last_name']} {row['first_name']}".strip() or None


async def list_lesson_notify_user_ids(lesson_id: str, teacher_id: str | None) -> list[str]:
    sql = """
        SELECT DISTINCT uid::text AS user_id
        FROM (
            SELECT lm.user_id AS uid
            FROM app.lesson_members lm
            JOIN app.profiles p ON p.user_id = lm.user_id
            WHERE lm.lesson_id = $1::uuid
              AND p.status = 'active'
            UNION
            SELECT p.id_curator AS uid
            FROM app.lesson_members lm
            JOIN app.profiles p ON p.user_id = lm.user_id
            JOIN app.profiles cp ON cp.user_id = p.id_curator
            WHERE lm.lesson_id = $1::uuid
              AND p.status = 'active'
              AND p.id_curator IS NOT NULL
              AND cp.status = 'active'
            UNION
            SELECT $2::uuid AS uid
            WHERE $2::uuid IS NOT NULL
        ) recipients
        WHERE uid IS NOT NULL
    """
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            sql,
            uuid.UUID(lesson_id),
            uuid.UUID(teacher_id) if teacher_id else None,
        )
    return sorted({str(row["user_id"]) for row in rows})


async def _clear_notification(user_id: str, lesson_id: str, kind: str) -> None:
    async with get_pool().acquire() as conn:
        await conn.execute(
            """
            DELETE FROM app.notifications
            WHERE delivered_to = $1::uuid AND lesson_id = $2::uuid AND kind = $3::app.notification_kind
            """,
            uuid.UUID(user_id),
            uuid.UUID(lesson_id),
            kind,
        )


async def _insert_notification(user_id: str, lesson_id: str, kind: str) -> bool:
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO app.notifications (delivered_to, lesson_id, kind)
            VALUES ($1::uuid, $2::uuid, $3::app.notification_kind)
            RETURNING id
            """,
            uuid.UUID(user_id),
            uuid.UUID(lesson_id),
            kind,
        )
    return row is not None


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


async def _push_to_users(
    *,
    lesson_id: str,
    user_ids: list[str],
    text: str,
    kind: str,
    persist: bool,
    replace_existing: bool,
) -> int:
    from bot_notify import notify_lesson_reminder

    sent = 0
    for user_id in user_ids:
        if persist and replace_existing:
            await _clear_notification(user_id, lesson_id, kind)
        elif persist and await _notification_exists(user_id, lesson_id, kind):
            continue

        if not await notify_lesson_reminder(user_id, text):
            logger.info("Lesson notify skipped for user %s (lesson %s)", user_id, lesson_id)
            continue

        if persist:
            if await _insert_notification(user_id, lesson_id, kind):
                sent += 1
        else:
            sent += 1
    return sent


async def notify_lesson_schedule_changed(
    lesson_id: str,
    *,
    old_lesson: dict[str, Any],
    new_lesson: dict[str, Any],
) -> int:
    if not schedule_fields_changed(old_lesson, new_lesson):
        return 0

    enriched = await fetch_lesson_for_notify(lesson_id)
    if not enriched:
        enriched = new_lesson

    text = build_lesson_changed_text(
        enriched,
        old_starts_at=old_lesson.get("starts_at"),
        new_starts_at=new_lesson.get("starts_at"),
        old_place=old_lesson.get("place"),
        new_place=new_lesson.get("place"),
        old_teacher_name=await _profile_short_name(old_lesson.get("teacher_id")),
        new_teacher_name=(
            teacher_display(enriched)
            or await _profile_short_name(new_lesson.get("teacher_id"))
        ),
    )
    user_ids = await list_lesson_notify_user_ids(
        lesson_id,
        str(enriched.get("teacher_id") or new_lesson.get("teacher_id") or ""),
    )
    if not user_ids:
        return 0

    sent = await _push_to_users(
        lesson_id=lesson_id,
        user_ids=user_ids,
        text=text,
        kind="lesson_changed",
        persist=True,
        replace_existing=True,
    )
    if sent:
        logger.info("Lesson changed notifications sent: lesson=%s users=%s", lesson_id, sent)
    return sent


async def notify_lesson_cancelled(lesson: dict[str, Any], member_ids: list[str] | None = None) -> int:
    lesson_id = str(lesson.get("id") or lesson.get("lesson_id") or "")
    if not lesson_id:
        return 0

    text = build_lesson_cancelled_text(lesson)
    teacher_id = str(lesson.get("teacher_id") or "")
    user_ids = await list_lesson_notify_user_ids(lesson_id, teacher_id or None)
    if not user_ids:
        return 0

    sent = await _push_to_users(
        lesson_id=lesson_id,
        user_ids=user_ids,
        text=text,
        kind="lesson_changed",
        persist=False,
        replace_existing=False,
    )
    if sent:
        logger.info("Lesson cancelled notifications sent: lesson=%s users=%s", lesson_id, sent)
    return sent
