"""Audit log: record actions and restore deleted entities from snapshots."""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from typing import Any

from db import get_pool, serialize_record

ACTION_LABELS = {
    "create": "Создание",
    "update": "Изменение",
    "delete": "Удаление",
    "restore": "Восстановление",
}

ENTITY_LABELS = {
    "user": "Пользователь",
    "group": "Группа",
    "group_member": "Участник группы",
    "track": "Трек",
    "lesson": "Занятие",
    "user_smu": "Назначение СМУ",
    "smu_extra_shift": "Допсмена",
    "track_teacher": "Инструктор на треке",
}


def actor_from_user(user: Any) -> tuple[str | None, str]:
    profile = getattr(user, "app_profile", None) or getattr(user, "profile", None) or {}
    parts = [profile.get("last_name"), profile.get("first_name"), profile.get("middle_name")]
    name = " ".join(p for p in parts if p) or getattr(user, "username", "") or "—"
    actor_id = getattr(user, "app_user_id", None)
    return actor_id, name


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


async def write_audit_log(
    *,
    actor_user_id: str | None,
    actor_name: str | None,
    action: str,
    entity_type: str,
    entity_id: str | None = None,
    entity_label: str | None = None,
    payload: dict[str, Any] | list[Any] | None = None,
) -> dict[str, Any]:
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO app.audit_log (
                actor_user_id, actor_name, action, entity_type, entity_id, entity_label, payload
            )
            VALUES ($1::uuid, $2, $3, $4, $5, $6, $7::jsonb)
            RETURNING id, actor_user_id, actor_name, action, entity_type, entity_id,
                      entity_label, payload, created_at, restored_at, restored_by
            """,
            uuid.UUID(actor_user_id) if actor_user_id else None,
            actor_name,
            action,
            entity_type,
            entity_id,
            entity_label,
            json.dumps(_json_safe(payload)) if payload is not None else None,
        )
    item = serialize_record(row)
    if isinstance(item.get("payload"), str):
        item["payload"] = json.loads(item["payload"])
    return item


async def list_audit_logs(
    *,
    actor_user_id: str | None = None,
    action: str | None = None,
    entity_type: str | None = None,
    restorable_only: bool = False,
    limit: int = 200,
    offset: int = 0,
) -> list[dict[str, Any]]:
    sql = """
        SELECT id, actor_user_id, actor_name, action, entity_type, entity_id,
               entity_label, payload, created_at, restored_at, restored_by
        FROM app.audit_log
        WHERE ($1::uuid IS NULL OR actor_user_id = $1::uuid)
          AND ($2::text IS NULL OR action = $2)
          AND ($3::text IS NULL OR entity_type = $3)
          AND (NOT $4::boolean OR (action = 'delete' AND restored_at IS NULL))
        ORDER BY created_at DESC
        LIMIT $5 OFFSET $6
    """
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            sql,
            uuid.UUID(actor_user_id) if actor_user_id else None,
            action,
            entity_type,
            restorable_only,
            min(max(limit, 1), 500),
            max(offset, 0),
        )
    result = []
    for row in rows:
        item = serialize_record(row)
        if isinstance(item.get("payload"), str):
            item["payload"] = json.loads(item["payload"])
        item["action_label"] = ACTION_LABELS.get(item.get("action"), item.get("action"))
        item["entity_type_label"] = ENTITY_LABELS.get(item.get("entity_type"), item.get("entity_type"))
        item["can_restore"] = item.get("action") == "delete" and not item.get("restored_at")
        result.append(item)
    return result


async def restore_audit_entry(
    entry_id: str,
    *,
    actor_user_id: str | None,
    actor_name: str | None,
) -> dict[str, Any]:
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, action, entity_type, entity_id, entity_label, payload, restored_at
            FROM app.audit_log
            WHERE id = $1::uuid
            """,
            uuid.UUID(entry_id),
        )
        if not row:
            raise ValueError("Запись журнала не найдена")
        if row["action"] != "delete":
            raise ValueError("Восстановление доступно только для удалений")
        if row["restored_at"]:
            raise ValueError("Запись уже восстановлена")

        payload = row["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        if not payload:
            raise ValueError("Нет данных для восстановления")

        entity_type = row["entity_type"]
        async with conn.transaction():
            if entity_type == "group_member":
                await conn.execute(
                    """
                    INSERT INTO app.group_members (group_id, user_id)
                    VALUES ($1::uuid, $2::uuid)
                    ON CONFLICT DO NOTHING
                    """,
                    uuid.UUID(str(payload["group_id"])),
                    uuid.UUID(str(payload["user_id"])),
                )
            elif entity_type == "user_smu":
                await conn.execute(
                    """
                    INSERT INTO app.user_smu (user_id, smu_pattern_id, started_at, shift_number)
                    VALUES ($1::uuid, $2::uuid, $3::date, $4)
                    ON CONFLICT (user_id) DO UPDATE SET
                        smu_pattern_id = EXCLUDED.smu_pattern_id,
                        started_at = EXCLUDED.started_at,
                        shift_number = EXCLUDED.shift_number,
                        updated_at = now()
                    """,
                    uuid.UUID(str(payload["user_id"])),
                    uuid.UUID(str(payload["smu_pattern_id"])),
                    payload.get("started_at"),
                    int(payload.get("shift_number") or 1),
                )
            elif entity_type == "smu_extra_shift":
                await conn.execute(
                    """
                    INSERT INTO app.smu_extra_shifts (id, user_id, shift_date, shift_number, note)
                    VALUES ($1::uuid, $2::uuid, $3::date, COALESCE($4, 1), $5)
                    ON CONFLICT (user_id, shift_date) DO UPDATE SET
                        shift_number = EXCLUDED.shift_number,
                        note = EXCLUDED.note
                    """,
                    uuid.UUID(str(payload["id"])),
                    uuid.UUID(str(payload["user_id"])),
                    payload["shift_date"],
                    payload.get("shift_number"),
                    payload.get("note"),
                )
            elif entity_type == "track_teacher":
                await conn.execute(
                    """
                    INSERT INTO app.track_teachers (track_id, teacher_id)
                    VALUES ($1::uuid, $2::uuid)
                    ON CONFLICT DO NOTHING
                    """,
                    uuid.UUID(str(payload["track_id"])),
                    uuid.UUID(str(payload["teacher_id"])),
                )
            elif entity_type == "lesson":
                lesson = payload.get("lesson") or payload
                member_ids = payload.get("member_ids") or []
                await conn.execute(
                    """
                    INSERT INTO app.lessons (
                        id, group_id, reporting_group_id, track_id, slot_id,
                        teacher_id, starts_at, ends_at, place, lesson_type, title
                    )
                    VALUES ($1::uuid, $2::uuid, $3::uuid, $4::uuid, $5::uuid, $6::uuid, $7, $8, $9, $10, $11)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    uuid.UUID(str(lesson["id"])),
                    uuid.UUID(str(lesson["group_id"])) if lesson.get("group_id") else None,
                    uuid.UUID(str(lesson["reporting_group_id"])) if lesson.get("reporting_group_id") else None,
                    uuid.UUID(str(lesson["track_id"])) if lesson.get("track_id") else None,
                    uuid.UUID(str(lesson["slot_id"])) if lesson.get("slot_id") else None,
                    uuid.UUID(str(lesson["teacher_id"])),
                    lesson["starts_at"],
                    lesson["ends_at"],
                    lesson.get("place"),
                    lesson["lesson_type"],
                    lesson.get("title"),
                )
                for mid in member_ids:
                    await conn.execute(
                        """
                        INSERT INTO app.lesson_members (user_id, lesson_id)
                        VALUES ($1::uuid, $2::uuid)
                        ON CONFLICT DO NOTHING
                        """,
                        uuid.UUID(str(mid)),
                        uuid.UUID(str(lesson["id"])),
                    )
            else:
                raise ValueError(f"Восстановление типа «{entity_type}» не поддерживается")

            await conn.execute(
                """
                UPDATE app.audit_log
                SET restored_at = now(), restored_by = $2::uuid
                WHERE id = $1::uuid
                """,
                uuid.UUID(entry_id),
                uuid.UUID(actor_user_id) if actor_user_id else None,
            )

    await write_audit_log(
        actor_user_id=actor_user_id,
        actor_name=actor_name,
        action="restore",
        entity_type=row["entity_type"],
        entity_id=row["entity_id"],
        entity_label=row["entity_label"],
        payload={"restored_from": entry_id},
    )

    refreshed = await list_audit_logs(limit=500)
    for item in refreshed:
        if str(item["id"]) == entry_id:
            return item
    return {"id": entry_id, "restored_at": datetime.utcnow().isoformat()}
