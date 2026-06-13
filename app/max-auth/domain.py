import logging
import uuid
from datetime import datetime
from typing import Any

from db import get_pool, serialize_record
from bot_contact import normalize_phone_digits

logger = logging.getLogger("max-auth")


STRIKE_BAN_REASON = "3 страйка"
MANUAL_BAN_DEFAULT = "ручной бан"

LESSON_TITLE_SQL = (
    "COALESCE(l.title, CASE WHEN l.lesson_type = 'practice' THEN 'Практика' ELSE 'Лекция' END)"
)


def _profile_name(row: dict[str, Any]) -> str:
    parts = [row.get("last_name"), row.get("first_name"), row.get("middle_name")]
    return " ".join(part for part in parts if part)


def _is_strike_ban_reason(reason: str | None) -> bool:
    return reason == STRIKE_BAN_REASON


async def get_user_profile(user_id: str) -> dict[str, Any] | None:
    sql = """
        SELECT u.id, u.keycloak_user_id, u.is_active,
               p.last_name, p.first_name, p.middle_name, p.phone, p.max_id, p.status,
               p.ban_reason, p.id_curator,
               r.code AS role_code, r.name AS role_name,
               (SELECT count(*)::int FROM app.strikes s
                WHERE s.user_id = u.id AND s.status = 'active') AS strike_count
        FROM app.users u
        JOIN app.profiles p ON p.user_id = u.id
        JOIN app.roles r ON r.id = p.role_id
        WHERE u.id = $1::uuid
    """
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(sql, uuid.UUID(user_id))
    return serialize_record(row) if row else None


async def list_users(
    role_code: str | None = None,
    *,
    hr_user_id: str | None = None,
) -> list[dict[str, Any]]:
    sql = """
        SELECT DISTINCT u.id, u.is_active, p.last_name, p.first_name, p.middle_name,
               p.phone, p.max_id, p.status, p.ban_reason, p.id_curator,
               r.code AS role_code, r.name AS role_name,
               (SELECT count(*)::int FROM app.strikes s
                WHERE s.user_id = u.id AND s.status = 'active') AS strike_count
        FROM app.users u
        JOIN app.profiles p ON p.user_id = u.id
        JOIN app.roles r ON r.id = p.role_id
        LEFT JOIN app.group_members gm ON gm.user_id = u.id
        LEFT JOIN app.groups g ON g.id = gm.group_id
        WHERE ($1::text IS NULL OR r.code = $1)
          AND (
            $2::uuid IS NULL
            OR r.code != 'employee'
            OR NOT EXISTS (
                SELECT 1 FROM app.group_members gm0 WHERE gm0.user_id = u.id
            )
            OR EXISTS (
                SELECT 1 FROM app.group_members gm2
                JOIN app.groups g2 ON g2.id = gm2.group_id
                WHERE gm2.user_id = u.id AND g2.id_hr = $2::uuid
            )
          )
        ORDER BY p.last_name, p.first_name
    """
    hr_uuid = uuid.UUID(hr_user_id) if hr_user_id else None
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(sql, role_code, hr_uuid)
    return [serialize_record(row) for row in rows]


async def create_user(
    *,
    last_name: str,
    first_name: str,
    middle_name: str | None,
    role_code: str,
    phone: str | None,
    max_id: int | None,
    status: str = "active",
    id_curator: str | None = None,
) -> dict[str, Any]:
    user_id = uuid.uuid4()
    sql = """
        WITH role_row AS (
            SELECT id FROM app.roles WHERE code = $2
        ),
        new_user AS (
            INSERT INTO app.users (id, is_active)
            VALUES ($1::uuid, TRUE)
            RETURNING id
        )
        INSERT INTO app.profiles (user_id, last_name, first_name, middle_name, role_id, phone, max_id, status, id_curator)
        SELECT $1::uuid, $3, $4, $5, role_row.id, $6, $7, $8, $9::uuid
        FROM role_row
        RETURNING user_id
    """
    curator_uuid = uuid.UUID(id_curator) if id_curator else None
    async with get_pool().acquire() as conn:
        role_exists = await conn.fetchval("SELECT id FROM app.roles WHERE code = $1", role_code)
        if not role_exists:
            raise ValueError(f"Неизвестная роль: {role_code}")
        await conn.execute(
            sql,
            user_id,
            role_code,
            last_name,
            first_name,
            middle_name,
            phone,
            max_id,
            status,
            curator_uuid,
        )
    profile = await get_user_profile(str(user_id))
    return profile or {}


async def update_user_profile(
    user_id: str,
    *,
    role_code: str | None = None,
    status: str | None = None,
    ban_reason: str | None = None,
    phone: str | None = None,
    last_name: str | None = None,
    first_name: str | None = None,
    middle_name: str | None = None,
    max_id: int | None = None,
    id_curator: str | None = None,
    clear_id_curator: bool = False,
) -> dict[str, Any]:
    async with get_pool().acquire() as conn:
        if role_code:
            role_id = await conn.fetchval("SELECT id FROM app.roles WHERE code = $1", role_code)
            if not role_id:
                raise ValueError(f"Неизвестная роль: {role_code}")
            await conn.execute(
                "UPDATE app.profiles SET role_id = $2, updated_at = now() WHERE user_id = $1::uuid",
                uuid.UUID(user_id),
                role_id,
            )
        if status is not None:
            if status == "inactive":
                reason = ban_reason or MANUAL_BAN_DEFAULT
                await conn.execute(
                    """
                    UPDATE app.profiles
                    SET status = $2, ban_reason = $3, updated_at = now()
                    WHERE user_id = $1::uuid
                    """,
                    uuid.UUID(user_id),
                    status,
                    reason,
                )
            else:
                await conn.execute(
                    """
                    UPDATE app.profiles
                    SET status = $2, ban_reason = NULL, updated_at = now()
                    WHERE user_id = $1::uuid
                    """,
                    uuid.UUID(user_id),
                    status,
                )
        elif ban_reason is not None:
            await conn.execute(
                "UPDATE app.profiles SET ban_reason = $2, updated_at = now() WHERE user_id = $1::uuid",
                uuid.UUID(user_id),
                ban_reason,
            )
        if phone is not None:
            await conn.execute(
                "UPDATE app.profiles SET phone = $2, updated_at = now() WHERE user_id = $1::uuid",
                uuid.UUID(user_id),
                phone,
            )
        if last_name is not None:
            await conn.execute(
                "UPDATE app.profiles SET last_name = $2, updated_at = now() WHERE user_id = $1::uuid",
                uuid.UUID(user_id),
                last_name,
            )
        if first_name is not None:
            await conn.execute(
                "UPDATE app.profiles SET first_name = $2, updated_at = now() WHERE user_id = $1::uuid",
                uuid.UUID(user_id),
                first_name,
            )
        if middle_name is not None:
            await conn.execute(
                "UPDATE app.profiles SET middle_name = $2, updated_at = now() WHERE user_id = $1::uuid",
                uuid.UUID(user_id),
                middle_name,
            )
        if max_id is not None:
            await conn.execute(
                "UPDATE app.profiles SET max_id = $2, updated_at = now() WHERE user_id = $1::uuid",
                uuid.UUID(user_id),
                max_id,
            )
        if clear_id_curator:
            await conn.execute(
                "UPDATE app.profiles SET id_curator = NULL, updated_at = now() WHERE user_id = $1::uuid",
                uuid.UUID(user_id),
            )
        elif id_curator is not None:
            await conn.execute(
                "UPDATE app.profiles SET id_curator = $2::uuid, updated_at = now() WHERE user_id = $1::uuid",
                uuid.UUID(user_id),
                uuid.UUID(id_curator),
            )
    profile = await get_user_profile(user_id)
    if not profile:
        raise ValueError("Пользователь не найден")
    return profile


async def verify_group_hr_access(group_id: str, hr_user_id: str | None) -> None:
    if hr_user_id is None:
        return
    async with get_pool().acquire() as conn:
        owner = await conn.fetchval(
            "SELECT id_hr FROM app.groups WHERE id = $1::uuid",
            uuid.UUID(group_id),
        )
    if owner is None:
        raise ValueError("Группа не найдена")
    if str(owner) != hr_user_id:
        raise ValueError("Нет доступа к этой группе")


async def bulk_create_users(rows: list[dict[str, Any]]) -> dict[str, Any]:
    created: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for row in rows:
        try:
            profile = await create_user(
                last_name=row["last_name"],
                first_name=row["first_name"],
                middle_name=row.get("middle_name"),
                role_code=row.get("role_code", "employee"),
                phone=row.get("phone"),
                max_id=row.get("max_id"),
                status=row.get("status", "active"),
                id_curator=row.get("id_curator"),
            )
            created.append(profile)
        except Exception as error:
            skipped.append({"row": str(row), "reason": str(error)})
    return {"created": created, "skipped": skipped, "created_count": len(created), "skipped_count": len(skipped)}


async def get_group_hr_id(group_id: str) -> str | None:
    async with get_pool().acquire() as conn:
        row = await conn.fetchval(
            "SELECT id_hr FROM app.groups WHERE id = $1::uuid",
            uuid.UUID(group_id),
        )
    return str(row) if row else None


async def list_groups(*, hr_user_id: str | None = None) -> list[dict[str, Any]]:
    sql = """
        SELECT g.id, g.name, g.status, g.id_parent, g.id_hr, g.created_at,
               hr_p.last_name AS hr_last_name, hr_p.first_name AS hr_first_name,
               (SELECT count(*) FROM app.group_members gm WHERE gm.group_id = g.id) AS member_count
        FROM app.groups g
        LEFT JOIN app.profiles hr_p ON hr_p.user_id = g.id_hr
        WHERE ($1::uuid IS NULL OR g.id_hr = $1::uuid)
        ORDER BY g.name
    """
    hr_uuid = uuid.UUID(hr_user_id) if hr_user_id else None
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(sql, hr_uuid)
    result = []
    for row in rows:
        item = serialize_record(row)
        if item.get("hr_last_name"):
            item["hr_name"] = f"{item['hr_last_name']} {item['hr_first_name']}"
        result.append(item)
    return result


async def get_group_members(group_id: str) -> list[dict[str, Any]]:
    sql = """
        SELECT u.id, p.last_name, p.first_name, p.middle_name, r.code AS role_code, p.status,
               p.id_curator, p.phone, p.max_id
        FROM app.group_members gm
        JOIN app.users u ON u.id = gm.user_id
        JOIN app.profiles p ON p.user_id = u.id
        JOIN app.roles r ON r.id = p.role_id
        WHERE gm.group_id = $1::uuid
        ORDER BY p.last_name, p.first_name
    """
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(sql, uuid.UUID(group_id))
    return [serialize_record(row) for row in rows]


async def create_group(*, name: str, id_hr: str, id_parent: str | None = None) -> dict[str, Any]:
    group_id = uuid.uuid4()
    sql = """
        INSERT INTO app.groups (id, name, id_hr, id_parent, status)
        VALUES ($1::uuid, $2, $3::uuid, $4::uuid, 'active')
        RETURNING id, name, status, id_parent, id_hr, created_at
    """
    parent = uuid.UUID(id_parent) if id_parent else None
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(sql, group_id, name, uuid.UUID(id_hr), parent)
    return serialize_record(row)


async def update_group(
    group_id: str,
    *,
    name: str | None = None,
    status: str | None = None,
    id_hr: str | None = None,
    id_parent: str | None = None,
) -> dict[str, Any]:
    async with get_pool().acquire() as conn:
        if name is not None:
            await conn.execute(
                "UPDATE app.groups SET name = $2 WHERE id = $1::uuid",
                uuid.UUID(group_id),
                name,
            )
        if status is not None:
            await conn.execute(
                "UPDATE app.groups SET status = $2 WHERE id = $1::uuid",
                uuid.UUID(group_id),
                status,
            )
        if id_hr is not None:
            await conn.execute(
                "UPDATE app.groups SET id_hr = $2::uuid WHERE id = $1::uuid",
                uuid.UUID(group_id),
                uuid.UUID(id_hr),
            )
        if id_parent is not None:
            parent = uuid.UUID(id_parent) if id_parent else None
            await conn.execute(
                "UPDATE app.groups SET id_parent = $2 WHERE id = $1::uuid",
                uuid.UUID(group_id),
                parent,
            )
        row = await conn.fetchrow(
            "SELECT id, name, status, id_parent, id_hr, created_at FROM app.groups WHERE id = $1::uuid",
            uuid.UUID(group_id),
        )
    if not row:
        raise ValueError("Группа не найдена")
    return serialize_record(row)


async def add_group_member(group_id: str, user_id: str) -> None:
    async with get_pool().acquire() as conn:
        await conn.execute(
            """
            INSERT INTO app.group_members (group_id, user_id)
            VALUES ($1::uuid, $2::uuid)
            ON CONFLICT DO NOTHING
            """,
            uuid.UUID(group_id),
            uuid.UUID(user_id),
        )


async def remove_group_member(group_id: str, user_id: str) -> None:
    async with get_pool().acquire() as conn:
        await conn.execute(
            "DELETE FROM app.group_members WHERE group_id = $1::uuid AND user_id = $2::uuid",
            uuid.UUID(group_id),
            uuid.UUID(user_id),
        )


async def bulk_add_group_members(group_id: str, user_ids: list[str]) -> dict[str, Any]:
    added = 0
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            for user_id in user_ids:
                result = await conn.execute(
                    """
                    INSERT INTO app.group_members (group_id, user_id)
                    VALUES ($1::uuid, $2::uuid)
                    ON CONFLICT DO NOTHING
                    """,
                    uuid.UUID(group_id),
                    uuid.UUID(user_id),
                )
                if result.endswith("1"):
                    added += 1
    return {"added_count": added, "requested_count": len(user_ids)}


async def list_teacher_groups(teacher_id: str) -> list[dict[str, Any]]:
    sql = """
        SELECT DISTINCT g.id, g.name, g.status, g.id_parent,
               pg.name AS parent_name,
               (SELECT count(*) FROM app.group_members gm WHERE gm.group_id = g.id) AS member_count
        FROM app.groups g
        LEFT JOIN app.groups pg ON pg.id = g.id_parent
        WHERE g.status = 'active'
          AND (
            EXISTS (SELECT 1 FROM app.lessons l WHERE l.group_id = g.id AND l.teacher_id = $1::uuid)
            OR EXISTS (
                SELECT 1 FROM app.group_members gm
                JOIN app.profiles p ON p.user_id = gm.user_id
                JOIN app.roles r ON r.id = p.role_id
                WHERE gm.group_id = g.id AND gm.user_id = $1::uuid AND r.code = 'teacher'
            )
          )
        ORDER BY g.name
    """
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(sql, uuid.UUID(teacher_id))
    return [serialize_record(row) for row in rows]


async def list_lessons(
    *,
    teacher_id: str | None = None,
    group_id: str | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
) -> list[dict[str, Any]]:
    sql = f"""
        SELECT l.id, l.group_id, l.teacher_id, l.starts_at, l.ends_at, l.place, l.lesson_type, l.title,
               {LESSON_TITLE_SQL} AS lesson_title,
               g.name AS group_name,
               tp.last_name AS teacher_last_name, tp.first_name AS teacher_first_name
        FROM app.lessons l
        JOIN app.groups g ON g.id = l.group_id
        JOIN app.profiles tp ON tp.user_id = l.teacher_id
        WHERE ($1::uuid IS NULL OR l.teacher_id = $1::uuid)
          AND ($2::uuid IS NULL OR l.group_id = $2::uuid)
          AND ($3::timestamptz IS NULL OR l.starts_at >= $3)
          AND ($4::timestamptz IS NULL OR l.starts_at <= $4)
        ORDER BY l.starts_at
    """
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            sql,
            uuid.UUID(teacher_id) if teacher_id else None,
            uuid.UUID(group_id) if group_id else None,
            from_date,
            to_date,
        )
    result = []
    for row in rows:
        item = serialize_record(row)
        item["teacher_name"] = f"{item['teacher_last_name']} {item['teacher_first_name']}"
        result.append(item)
    return result


async def get_lesson_teacher_id(lesson_id: str) -> str | None:
    async with get_pool().acquire() as conn:
        row = await conn.fetchval(
            "SELECT teacher_id FROM app.lessons WHERE id = $1::uuid",
            uuid.UUID(lesson_id),
        )
    return str(row) if row else None


async def verify_teacher_group_access(group_id: str, teacher_id: str) -> None:
    groups = await list_teacher_groups(teacher_id)
    if not any(g["id"] == group_id for g in groups):
        raise ValueError("Нет доступа к этой группе")


async def verify_teacher_lesson_access(
    lesson_id: str,
    teacher_id: str,
    *,
    require_owner: bool = False,
    is_admin: bool = False,
) -> None:
    owner = await get_lesson_teacher_id(lesson_id)
    if owner is None:
        raise ValueError("Занятие не найдено")
    if is_admin:
        return
    if require_owner:
        if owner != teacher_id:
            raise ValueError("Можно изменять только свои занятия")
        return
    async with get_pool().acquire() as conn:
        group_id = await conn.fetchval(
            "SELECT group_id FROM app.lessons WHERE id = $1::uuid",
            uuid.UUID(lesson_id),
        )
    if group_id is None:
        raise ValueError("Занятие не найдено")
    await verify_teacher_group_access(str(group_id), teacher_id)


async def verify_user_role(user_id: str, role_code: str) -> None:
    async with get_pool().acquire() as conn:
        code = await conn.fetchval(
            """
            SELECT r.code FROM app.profiles p
            JOIN app.roles r ON r.id = p.role_id
            WHERE p.user_id = $1::uuid
            """,
            uuid.UUID(user_id),
        )
    if code != role_code:
        raise ValueError(f"Пользователь не является {role_code}")


async def create_lesson(
    *,
    group_id: str,
    teacher_id: str,
    starts_at: datetime,
    ends_at: datetime,
    place: str | None,
    lesson_type: str,
    title: str | None = None,
    member_ids: list[str] | None = None,
) -> dict[str, Any]:
    lesson_id = uuid.uuid4()
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            if title is not None:
                row = await conn.fetchrow(
                    """
                    INSERT INTO app.lessons (id, group_id, teacher_id, starts_at, ends_at, place, lesson_type, title)
                    VALUES ($1::uuid, $2::uuid, $3::uuid, $4, $5, $6, $7, $8)
                    RETURNING id, group_id, teacher_id, starts_at, ends_at, place, lesson_type, title
                    """,
                    lesson_id,
                    uuid.UUID(group_id),
                    uuid.UUID(teacher_id),
                    starts_at,
                    ends_at,
                    place,
                    lesson_type,
                    title,
                )
            else:
                row = await conn.fetchrow(
                    """
                    INSERT INTO app.lessons (id, group_id, teacher_id, starts_at, ends_at, place, lesson_type)
                    VALUES ($1::uuid, $2::uuid, $3::uuid, $4, $5, $6, $7)
                    RETURNING id, group_id, teacher_id, starts_at, ends_at, place, lesson_type
                    """,
                    lesson_id,
                    uuid.UUID(group_id),
                    uuid.UUID(teacher_id),
                    starts_at,
                    ends_at,
                    place,
                    lesson_type,
                )
            ids = member_ids
            if ids is None:
                member_rows = await conn.fetch(
                    "SELECT user_id FROM app.group_members WHERE group_id = $1::uuid",
                    uuid.UUID(group_id),
                )
                ids = [str(r["user_id"]) for r in member_rows]
            for member_id in ids:
                await conn.execute(
                    """
                    INSERT INTO app.lesson_members (user_id, lesson_id)
                    VALUES ($1::uuid, $2::uuid)
                    ON CONFLICT DO NOTHING
                    """,
                    uuid.UUID(member_id),
                    lesson_id,
                )
    return serialize_record(row)


async def update_lesson(
    lesson_id: str,
    *,
    teacher_id: str | None = None,
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
    place: str | None = None,
    lesson_type: str | None = None,
    title: str | None = None,
) -> dict[str, Any]:
    async with get_pool().acquire() as conn:
        if teacher_id is not None:
            await conn.execute(
                "UPDATE app.lessons SET teacher_id = $2::uuid WHERE id = $1::uuid",
                uuid.UUID(lesson_id),
                uuid.UUID(teacher_id),
            )
        if starts_at is not None:
            await conn.execute(
                "UPDATE app.lessons SET starts_at = $2 WHERE id = $1::uuid",
                uuid.UUID(lesson_id),
                starts_at,
            )
        if ends_at is not None:
            await conn.execute(
                "UPDATE app.lessons SET ends_at = $2 WHERE id = $1::uuid",
                uuid.UUID(lesson_id),
                ends_at,
            )
        if place is not None:
            await conn.execute(
                "UPDATE app.lessons SET place = $2 WHERE id = $1::uuid",
                uuid.UUID(lesson_id),
                place,
            )
        if lesson_type is not None:
            await conn.execute(
                "UPDATE app.lessons SET lesson_type = $2 WHERE id = $1::uuid",
                uuid.UUID(lesson_id),
                lesson_type,
            )
        if title is not None:
            await conn.execute(
                "UPDATE app.lessons SET title = $2 WHERE id = $1::uuid",
                uuid.UUID(lesson_id),
                title,
            )
        row = await conn.fetchrow(
            """
            SELECT l.id, l.group_id, l.teacher_id, l.starts_at, l.ends_at, l.place, l.lesson_type, l.title,
                   g.name AS group_name
            FROM app.lessons l
            JOIN app.groups g ON g.id = l.group_id
            WHERE l.id = $1::uuid
            """,
            uuid.UUID(lesson_id),
        )
    if not row:
        raise ValueError("Занятие не найдено")
    return serialize_record(row)


async def delete_lesson(lesson_id: str) -> None:
    async with get_pool().acquire() as conn:
        result = await conn.execute(
            "DELETE FROM app.lessons WHERE id = $1::uuid",
            uuid.UUID(lesson_id),
        )
    if result == "DELETE 0":
        raise ValueError("Занятие не найдено")


async def get_lesson_member_ids(lesson_id: str) -> list[str]:
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            "SELECT user_id FROM app.lesson_members WHERE lesson_id = $1::uuid",
            uuid.UUID(lesson_id),
        )
    return [str(r["user_id"]) for r in rows]


async def get_lesson_attendance(lesson_id: str) -> list[dict[str, Any]]:
    sql = """
        SELECT lm.user_id, p.last_name, p.first_name, p.middle_name,
               am.id AS mark_id, am.status AS attendance_status, am.marked_at, am.marked_by
        FROM app.lesson_members lm
        JOIN app.profiles p ON p.user_id = lm.user_id
        LEFT JOIN app.attendance_marks am ON am.user_id = lm.user_id AND am.lesson_id = lm.lesson_id
        WHERE lm.lesson_id = $1::uuid
        ORDER BY p.last_name, p.first_name
    """
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(sql, uuid.UUID(lesson_id))
    return [serialize_record(row) for row in rows]


async def save_lesson_attendance(
    lesson_id: str,
    marks: list[dict[str, str]],
    marked_by: str,
) -> list[dict[str, Any]]:
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            for mark in marks:
                existing = await conn.fetchrow(
                    """
                    SELECT id, status FROM app.attendance_marks
                    WHERE user_id = $1::uuid AND lesson_id = $2::uuid
                    """,
                    uuid.UUID(mark["user_id"]),
                    uuid.UUID(lesson_id),
                )
                row = await conn.fetchrow(
                    """
                    INSERT INTO app.attendance_marks (user_id, lesson_id, status, marked_by)
                    VALUES ($1::uuid, $2::uuid, $3::app.attendance_status, $4::uuid)
                    ON CONFLICT (user_id, lesson_id) DO UPDATE SET
                        status = EXCLUDED.status,
                        marked_by = EXCLUDED.marked_by,
                        marked_at = now()
                    RETURNING id, status
                    """,
                    uuid.UUID(mark["user_id"]),
                    uuid.UUID(lesson_id),
                    mark["status"],
                    uuid.UUID(marked_by),
                )
                old_status = existing["status"] if existing else None
                new_status = row["status"] if row else mark["status"]
                if old_status != new_status:
                    await conn.execute(
                        """
                        INSERT INTO app.attendance_mark_history
                            (mark_id, user_id, lesson_id, old_status, new_status, changed_by)
                        VALUES ($1::uuid, $2::uuid, $3::uuid, $4::app.attendance_status, $5::app.attendance_status, $6::uuid)
                        """,
                        row["id"],
                        uuid.UUID(mark["user_id"]),
                        uuid.UUID(lesson_id),
                        old_status,
                        new_status,
                        uuid.UUID(marked_by),
                    )
    return await get_lesson_attendance(lesson_id)


async def list_attendance_mark_history(
    *,
    teacher_id: str,
    lesson_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    safe_limit = max(1, min(limit, 500))
    sql = """
        SELECT h.id, h.mark_id, h.user_id, h.lesson_id, h.old_status, h.new_status,
               h.changed_by, h.changed_at,
               p.last_name, p.first_name,
               cp.last_name AS changed_by_last_name, cp.first_name AS changed_by_first_name,
               l.starts_at, g.name AS group_name,
               am.status AS current_status
        FROM app.attendance_mark_history h
        JOIN app.lessons l ON l.id = h.lesson_id
        JOIN app.groups g ON g.id = l.group_id
        JOIN app.profiles p ON p.user_id = h.user_id
        JOIN app.profiles cp ON cp.user_id = h.changed_by
        JOIN app.attendance_marks am ON am.id = h.mark_id
        WHERE l.teacher_id = $1::uuid
          AND ($2::uuid IS NULL OR h.lesson_id = $2::uuid)
        ORDER BY h.changed_at DESC
        LIMIT $3
    """
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            sql,
            uuid.UUID(teacher_id),
            uuid.UUID(lesson_id) if lesson_id else None,
            safe_limit,
        )
    return [serialize_record(row) for row in rows]


async def list_strikes(
    *,
    status: str | None = None,
    hr_user_id: str | None = None,
) -> list[dict[str, Any]]:
    sql = """
        SELECT s.id, s.user_id, s.lesson_id, s.reason, s.status, s.strike_number,
               s.appeal_reason, s.appealed_at, s.resolved_by, s.resolved_at, s.created_at,
               p.last_name, p.first_name, g.name AS group_name
        FROM app.strikes s
        JOIN app.profiles p ON p.user_id = s.user_id
        LEFT JOIN app.lessons l ON l.id = s.lesson_id
        LEFT JOIN app.groups g ON g.id = l.group_id
        WHERE ($1::app.strike_status IS NULL OR s.status = $1::app.strike_status)
          AND (
            $2::uuid IS NULL
            OR EXISTS (
                SELECT 1 FROM app.group_members gm
                JOIN app.groups g2 ON g2.id = gm.group_id
                WHERE gm.user_id = s.user_id AND g2.id_hr = $2::uuid
            )
          )
        ORDER BY s.created_at DESC
    """
    hr_uuid = uuid.UUID(hr_user_id) if hr_user_id else None
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(sql, status, hr_uuid)
    return [serialize_record(row) for row in rows]


async def create_strike(
    *,
    user_id: str,
    reason: str,
    lesson_id: str | None = None,
    strike_number: int | None = None,
) -> dict[str, Any]:
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            if strike_number is None:
                strike_number = await conn.fetchval(
                    """
                    SELECT COALESCE(MAX(strike_number), 0) + 1
                    FROM app.strikes
                    WHERE user_id = $1::uuid AND status != 'revoked'
                    """,
                    uuid.UUID(user_id),
                )
                strike_number = min(int(strike_number), 3)
            strike_id = uuid.uuid4()
            row = await conn.fetchrow(
                """
                INSERT INTO app.strikes (id, user_id, lesson_id, reason, strike_number)
                VALUES ($1::uuid, $2::uuid, $3::uuid, $4, $5)
                RETURNING id, user_id, lesson_id, reason, status, strike_number, created_at
                """,
                strike_id,
                uuid.UUID(user_id),
                uuid.UUID(lesson_id) if lesson_id else None,
                reason,
                strike_number,
            )
            active_count = await conn.fetchval(
                """
                SELECT count(*)::int FROM app.strikes
                WHERE user_id = $1::uuid AND status = 'active'
                """,
                uuid.UUID(user_id),
            )
            if active_count >= 3:
                await conn.execute(
                    """
                    UPDATE app.profiles
                    SET status = 'inactive', ban_reason = $2, updated_at = now()
                    WHERE user_id = $1::uuid
                    """,
                    uuid.UUID(user_id),
                    STRIKE_BAN_REASON,
                )
    result = serialize_record(row)
    result["active_strike_count"] = active_count
    result["auto_banned"] = active_count >= 3
    try:
        from bot_notify import notify_strike_issued

        await notify_strike_issued(result)
    except Exception:
        logger.exception("Failed to send strike MAX notification")
    return result


async def revoke_latest_strike(
    user_id: str,
    *,
    resolved_by: str | None = None,
    comment: str | None = None,
) -> dict[str, Any]:
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            strike = await conn.fetchrow(
                """
                SELECT id, reason FROM app.strikes
                WHERE user_id = $1::uuid AND status = 'active'
                ORDER BY created_at DESC, strike_number DESC
                LIMIT 1
                """,
                uuid.UUID(user_id),
            )
            if not strike:
                raise ValueError("Нет активных страйков для отмены")
            resolver = uuid.UUID(resolved_by) if resolved_by else None
            reason_sql = "reason"
            params: list[Any] = [strike["id"], resolver]
            if comment and comment.strip():
                reason_sql = "reason || ' · снят: ' || $3"
                params.append(comment.strip())
            await conn.execute(
                f"""
                UPDATE app.strikes
                SET status = 'revoked', resolved_by = $2::uuid, resolved_at = now(),
                    reason = {reason_sql}
                WHERE id = $1::uuid
                """,
                *params,
            )
            active_count = await conn.fetchval(
                """
                SELECT count(*)::int FROM app.strikes
                WHERE user_id = $1::uuid AND status = 'active'
                """,
                uuid.UUID(user_id),
            )
            if active_count < 3:
                ban_reason = await conn.fetchval(
                    "SELECT ban_reason FROM app.profiles WHERE user_id = $1::uuid",
                    uuid.UUID(user_id),
                )
                if _is_strike_ban_reason(ban_reason):
                    await conn.execute(
                        """
                        UPDATE app.profiles
                        SET status = 'active', ban_reason = NULL, updated_at = now()
                        WHERE user_id = $1::uuid AND status = 'inactive'
                        """,
                        uuid.UUID(user_id),
                    )
    profile = await get_user_profile(user_id)
    return {
        "user_id": user_id,
        "active_strike_count": active_count,
        "profile": profile,
    }


async def submit_strike_appeal(strike_id: str, appeal_reason: str) -> dict[str, Any]:
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE app.strikes
            SET status = 'appealed', appeal_reason = $2, appealed_at = now()
            WHERE id = $1::uuid AND status = 'active'
            RETURNING id, user_id, status, appeal_reason, appealed_at
            """,
            uuid.UUID(strike_id),
            appeal_reason,
        )
    if not row:
        raise ValueError("Страйк не найден или уже рассмотрен")
    return serialize_record(row)


async def resolve_strike_appeal(
    strike_id: str,
    *,
    approved: bool,
    resolved_by: str,
) -> dict[str, Any]:
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            if approved:
                row = await conn.fetchrow(
                    """
                    UPDATE app.strikes
                    SET status = 'revoked',
                        appeal_reason = NULL,
                        appealed_at = NULL,
                        resolved_by = $2::uuid,
                        resolved_at = now()
                    WHERE id = $1::uuid AND status = 'appealed'
                    RETURNING id, user_id, status, strike_number, resolved_by, resolved_at
                    """,
                    uuid.UUID(strike_id),
                    uuid.UUID(resolved_by),
                )
            else:
                row = await conn.fetchrow(
                    """
                    UPDATE app.strikes
                    SET status = 'active', appeal_reason = NULL, appealed_at = NULL
                    WHERE id = $1::uuid AND status = 'appealed'
                    RETURNING id, user_id, status, strike_number
                    """,
                    uuid.UUID(strike_id),
                )
            if not row:
                raise ValueError("Апелляция не найдена")
            if approved:
                active_count = await conn.fetchval(
                    """
                    SELECT count(*)::int FROM app.strikes
                    WHERE user_id = $1::uuid AND status = 'active'
                    """,
                    row["user_id"],
                )
                if active_count < 3:
                    ban_reason = await conn.fetchval(
                        "SELECT ban_reason FROM app.profiles WHERE user_id = $1::uuid",
                        row["user_id"],
                    )
                    if _is_strike_ban_reason(ban_reason):
                        await conn.execute(
                            """
                            UPDATE app.profiles
                            SET status = 'active', ban_reason = NULL, updated_at = now()
                            WHERE user_id = $1::uuid AND status = 'inactive'
                            """,
                            row["user_id"],
                        )
    result = serialize_record(row)
    try:
        from bot_notify import notify_appeal_resolved

        await notify_appeal_resolved(
            user_id=str(result["user_id"]),
            strike_number=int(result.get("strike_number") or 0),
            approved=approved,
        )
    except Exception:
        logger.exception("Failed to send appeal resolution MAX notification")
    return result


async def hr_summary_report(*, hr_user_id: str | None = None) -> dict[str, Any]:
    hr_uuid = uuid.UUID(hr_user_id) if hr_user_id else None
    sql = """
        SELECT
            (SELECT count(DISTINCT gm.user_id)
             FROM app.group_members gm
             JOIN app.groups g ON g.id = gm.group_id
             JOIN app.profiles p ON p.user_id = gm.user_id
             JOIN app.roles r ON r.id = p.role_id
             WHERE r.code = 'employee'
               AND ($1::uuid IS NULL OR g.id_hr = $1::uuid)) AS users_total,
            (SELECT count(*) FROM app.groups
             WHERE status = 'active' AND ($1::uuid IS NULL OR id_hr = $1::uuid)) AS groups_active,
            (SELECT count(*) FROM app.strikes s
             WHERE s.status = 'active'
               AND ($1::uuid IS NULL OR EXISTS (
                   SELECT 1 FROM app.group_members gm
                   JOIN app.groups g ON g.id = gm.group_id
                   WHERE gm.user_id = s.user_id AND g.id_hr = $1::uuid
               ))) AS strikes_active,
            (SELECT count(*) FROM app.strikes s
             WHERE s.status = 'appealed'
               AND ($1::uuid IS NULL OR EXISTS (
                   SELECT 1 FROM app.group_members gm
                   JOIN app.groups g ON g.id = gm.group_id
                   WHERE gm.user_id = s.user_id AND g.id_hr = $1::uuid
               ))) AS appeals_pending,
            (SELECT count(*) FROM app.lessons l
             JOIN app.groups g ON g.id = l.group_id
             WHERE l.starts_at >= now() - interval '7 days'
               AND ($1::uuid IS NULL OR g.id_hr = $1::uuid)) AS lessons_week
    """
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(sql, hr_uuid)
    return serialize_record(row) if row else {}


async def attendance_report_by_groups(
    group_id: str | None = None,
    *,
    hr_user_id: str | None = None,
    teacher_user_id: str | None = None,
) -> list[dict[str, Any]]:
    hr_uuid = uuid.UUID(hr_user_id) if hr_user_id else None
    teacher_uuid = uuid.UUID(teacher_user_id) if teacher_user_id else None
    sql = """
        SELECT g.id AS group_id, g.name AS group_name,
               count(am.id) FILTER (WHERE am.status = 'present') AS present_count,
               count(am.id) FILTER (WHERE am.status = 'late') AS late_count,
               count(am.id) FILTER (WHERE am.status = 'absent') AS absent_count,
               count(am.id) AS marks_total
        FROM app.groups g
        LEFT JOIN app.lessons l ON l.group_id = g.id
            AND ($3::uuid IS NULL OR l.teacher_id = $3::uuid)
        LEFT JOIN app.attendance_marks am ON am.lesson_id = l.id
        WHERE ($1::uuid IS NULL OR g.id = $1::uuid)
          AND ($2::uuid IS NULL OR g.id_hr = $2::uuid)
          AND (
            $3::uuid IS NULL
            OR EXISTS (
                SELECT 1 FROM app.lessons l2
                WHERE l2.group_id = g.id AND l2.teacher_id = $3::uuid
            )
            OR EXISTS (
                SELECT 1 FROM app.group_members gm
                JOIN app.profiles p ON p.user_id = gm.user_id
                JOIN app.roles r ON r.id = p.role_id
                WHERE gm.group_id = g.id AND gm.user_id = $3::uuid AND r.code = 'teacher'
            )
          )
        GROUP BY g.id, g.name
        ORDER BY g.name
    """
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            sql,
            uuid.UUID(group_id) if group_id else None,
            hr_uuid,
            teacher_uuid,
        )
    return [serialize_record(row) for row in rows]


async def attendance_report_by_users(
    group_id: str | None = None,
    *,
    hr_user_id: str | None = None,
    teacher_user_id: str | None = None,
) -> list[dict[str, Any]]:
    hr_uuid = uuid.UUID(hr_user_id) if hr_user_id else None
    teacher_uuid = uuid.UUID(teacher_user_id) if teacher_user_id else None
    sql = """
        SELECT u.id AS user_id, p.last_name, p.first_name, g.name AS group_name, g.id AS group_id,
               count(DISTINCT l.id) AS lessons_total,
               count(am.id) FILTER (WHERE am.status = 'present') AS present_count,
               count(am.id) FILTER (WHERE am.status = 'late') AS late_count,
               count(am.id) FILTER (WHERE am.status = 'absent') AS absent_count
        FROM app.group_members gm
        JOIN app.users u ON u.id = gm.user_id
        JOIN app.profiles p ON p.user_id = u.id
        JOIN app.roles r ON r.id = p.role_id
        JOIN app.groups g ON g.id = gm.group_id
        LEFT JOIN app.lessons l ON l.group_id = g.id
            AND ($3::uuid IS NULL OR l.teacher_id = $3::uuid)
        LEFT JOIN app.lesson_members lm ON lm.lesson_id = l.id AND lm.user_id = u.id
        LEFT JOIN app.attendance_marks am ON am.user_id = u.id AND am.lesson_id = l.id
        WHERE r.code = 'employee'
          AND ($1::uuid IS NULL OR g.id = $1::uuid)
          AND ($2::uuid IS NULL OR g.id_hr = $2::uuid)
          AND (
            $3::uuid IS NULL
            OR EXISTS (
                SELECT 1 FROM app.lessons l2
                WHERE l2.group_id = g.id AND l2.teacher_id = $3::uuid
            )
            OR EXISTS (
                SELECT 1 FROM app.group_members gm2
                JOIN app.profiles p2 ON p2.user_id = gm2.user_id
                JOIN app.roles r2 ON r2.id = p2.role_id
                WHERE gm2.group_id = g.id AND gm2.user_id = $3::uuid AND r2.code = 'teacher'
            )
          )
          AND ($3::uuid IS NULL OR lm.user_id IS NOT NULL OR l.id IS NULL)
        GROUP BY u.id, p.last_name, p.first_name, g.name, g.id
        ORDER BY p.last_name, p.first_name
    """
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            sql,
            uuid.UUID(group_id) if group_id else None,
            hr_uuid,
            teacher_uuid,
        )
    return [serialize_record(row) for row in rows]


async def list_user_attendance_issues(
    user_id: str,
    *,
    hr_user_id: str | None = None,
) -> list[dict[str, Any]]:
    hr_uuid = uuid.UUID(hr_user_id) if hr_user_id else None
    sql = f"""
        SELECT am.id AS mark_id, am.status AS attendance_status, am.marked_at,
               am.user_id,
               l.id AS lesson_id, l.starts_at, l.ends_at, l.place, l.lesson_type, l.title,
               {LESSON_TITLE_SQL} AS lesson_title,
               g.id AS group_id, g.name AS group_name,
               p.last_name, p.first_name
        FROM app.attendance_marks am
        JOIN app.lessons l ON l.id = am.lesson_id
        JOIN app.groups g ON g.id = l.group_id
        JOIN app.profiles p ON p.user_id = am.user_id
        WHERE am.user_id = $1::uuid
          AND am.status != 'present'
          AND ($2::uuid IS NULL OR g.id_hr = $2::uuid)
        ORDER BY l.starts_at DESC
    """
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(sql, uuid.UUID(user_id), hr_uuid)
    return [serialize_record(row) for row in rows]


async def list_hr_lessons(
    *,
    hr_user_id: str | None = None,
    group_id: str | None = None,
) -> list[dict[str, Any]]:
    hr_uuid = uuid.UUID(hr_user_id) if hr_user_id else None
    sql = f"""
        SELECT l.id, l.group_id, l.teacher_id, l.starts_at, l.ends_at, l.place, l.lesson_type, l.title,
               {LESSON_TITLE_SQL} AS lesson_title,
               g.name AS group_name,
               tp.last_name AS teacher_last_name, tp.first_name AS teacher_first_name
        FROM app.lessons l
        JOIN app.groups g ON g.id = l.group_id
        JOIN app.profiles tp ON tp.user_id = l.teacher_id
        WHERE ($1::uuid IS NULL OR g.id_hr = $1::uuid)
          AND ($2::uuid IS NULL OR l.group_id = $2::uuid)
        ORDER BY l.starts_at DESC
    """
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            sql,
            hr_uuid,
            uuid.UUID(group_id) if group_id else None,
        )
    result = []
    for row in rows:
        item = serialize_record(row)
        item["teacher_name"] = f"{item['teacher_last_name']} {item['teacher_first_name']}"
        result.append(item)
    return result


async def list_hr_teachers(*, hr_user_id: str | None = None) -> list[dict[str, Any]]:
    hr_uuid = uuid.UUID(hr_user_id) if hr_user_id else None
    sql = """
        SELECT DISTINCT u.id, p.last_name, p.first_name, p.middle_name,
               p.phone, p.max_id, p.status, r.code AS role_code,
               (SELECT count(*)::int FROM app.strikes s
                WHERE s.user_id = u.id AND s.status = 'active') AS strike_count
        FROM app.lessons l
        JOIN app.groups g ON g.id = l.group_id
        JOIN app.users u ON u.id = l.teacher_id
        JOIN app.profiles p ON p.user_id = u.id
        JOIN app.roles r ON r.id = p.role_id
        WHERE ($1::uuid IS NULL OR g.id_hr = $1::uuid)
        ORDER BY p.last_name, p.first_name
    """
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(sql, hr_uuid)
        result = []
        for row in rows:
            item = serialize_record(row)
            teacher_id = item["id"]
            groups_sql = """
                SELECT DISTINCT g.id, g.name, g.id_parent
                FROM app.lessons l
                JOIN app.groups g ON g.id = l.group_id
                WHERE l.teacher_id = $1::uuid
                  AND ($2::uuid IS NULL OR g.id_hr = $2::uuid)
                ORDER BY g.name
            """
            group_rows = await conn.fetch(groups_sql, uuid.UUID(teacher_id), hr_uuid)
            item["groups"] = [serialize_record(g) for g in group_rows]
            result.append(item)
    return result


async def list_hr_notifications(*, hr_user_id: str) -> list[dict[str, Any]]:
    hr_uuid = uuid.UUID(hr_user_id)
    db_sql = """
        SELECT n.id::text, n.delivered_to, n.lesson_id, n.kind, n.sent_at,
               l.starts_at, l.place, l.lesson_type,
               g.name AS group_name,
               tp.last_name AS teacher_last_name, tp.first_name AS teacher_first_name
        FROM app.notifications n
        JOIN app.lessons l ON l.id = n.lesson_id
        JOIN app.groups g ON g.id = l.group_id
        JOIN app.profiles tp ON tp.user_id = l.teacher_id
        WHERE n.delivered_to = $1::uuid
        ORDER BY n.sent_at DESC
        LIMIT 50
    """
    absent_sql = f"""
        SELECT am.id::text AS mark_id, am.status AS attendance_status, am.marked_at AS sent_at,
               am.user_id,
               l.id AS lesson_id, l.starts_at, l.place,
               {LESSON_TITLE_SQL} AS lesson_title,
               g.name AS group_name,
               p.last_name, p.first_name
        FROM app.attendance_marks am
        JOIN app.lessons l ON l.id = am.lesson_id
        JOIN app.groups g ON g.id = l.group_id
        JOIN app.profiles p ON p.user_id = am.user_id
        WHERE g.id_hr = $1::uuid
          AND am.status IN ('absent', 'late')
          AND am.marked_at >= now() - interval '30 days'
        ORDER BY am.marked_at DESC
        LIMIT 50
    """
    strike_sql = """
        SELECT s.id::text AS strike_id, s.reason, s.strike_number, s.status, s.created_at AS sent_at,
               s.user_id,
               g.name AS group_name,
               p.last_name, p.first_name
        FROM app.strikes s
        JOIN app.profiles p ON p.user_id = s.user_id
        LEFT JOIN app.lessons l ON l.id = s.lesson_id
        LEFT JOIN app.groups g ON g.id = l.group_id
        WHERE s.status = 'active'
          AND EXISTS (
              SELECT 1 FROM app.group_members gm
              JOIN app.groups g2 ON g2.id = gm.group_id
              WHERE gm.user_id = s.user_id AND g2.id_hr = $1::uuid
          )
        ORDER BY s.created_at DESC
        LIMIT 50
    """
    kind_labels = {
        "lesson_reminder_1d": "Напоминание за 1 день",
        "lesson_reminder_3h": "Напоминание за 3 часа",
        "lesson_changed": "Занятие изменено",
        "student_absent": "Пропуск",
        "student_late": "Опоздание",
        "student_strike": "Страйк",
    }
    async with get_pool().acquire() as conn:
        db_rows = await conn.fetch(db_sql, hr_uuid)
        absent_rows = await conn.fetch(absent_sql, hr_uuid)
        strike_rows = await conn.fetch(strike_sql, hr_uuid)
    result: list[dict[str, Any]] = []
    for row in db_rows:
        item = serialize_record(row)
        kind = item.get("kind", "")
        group_name = item.get("group_name", "")
        starts = item.get("starts_at", "")
        item["source"] = "db"
        item["type"] = kind
        item["category"] = "lesson"
        item["text"] = f"{kind_labels.get(kind, kind)} · {group_name} · {starts}"
        result.append(item)
    for row in absent_rows:
        item = serialize_record(row)
        status = item.get("attendance_status", "absent")
        kind = "student_late" if status == "late" else "student_absent"
        name = _profile_name(item)
        lesson_title = item.get("lesson_title", "Занятие")
        group_name = item.get("group_name", "")
        item["id"] = f"virt-absent-{item.get('mark_id', '')}"
        item["source"] = "virtual"
        item["type"] = kind
        item["category"] = "attendance"
        item["text"] = (
            f"{kind_labels[kind]} · {name} · {lesson_title} · {group_name} · {item.get('sent_at', '')}"
        )
        result.append(item)
    for row in strike_rows:
        item = serialize_record(row)
        name = _profile_name(item)
        group_name = item.get("group_name") or "—"
        item["id"] = f"virt-strike-{item.get('strike_id', '')}"
        item["source"] = "virtual"
        item["type"] = "student_strike"
        item["category"] = "strike"
        item["text"] = (
            f"Страйк №{item.get('strike_number', '?')} · {name} · {group_name} · {item.get('reason', '')}"
        )
        result.append(item)
    result.sort(key=lambda x: x.get("sent_at") or "", reverse=True)
    return result


async def get_profile_by_max_id(max_id: int) -> dict[str, Any] | None:
    sql = """
        SELECT u.id, u.keycloak_user_id, u.is_active,
               p.last_name, p.first_name, p.middle_name, p.phone, p.max_id, p.status,
               p.ban_reason, p.id_curator,
               r.code AS role_code, r.name AS role_name,
               (SELECT count(*)::int FROM app.strikes s
                WHERE s.user_id = u.id AND s.status = 'active') AS strike_count
        FROM app.profiles p
        JOIN app.users u ON u.id = p.user_id
        JOIN app.roles r ON r.id = p.role_id
        WHERE p.max_id = $1
    """
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(sql, max_id)
    return serialize_record(row) if row else None


async def get_profile_by_phone(phone: str) -> dict[str, Any] | None:
    digits = normalize_phone_digits(phone)
    if not digits:
        return None
    alt_digits = "8" + digits[1:] if digits.startswith("7") else None
    sql = """
        SELECT u.id, u.keycloak_user_id, u.is_active,
               p.last_name, p.first_name, p.middle_name, p.phone, p.max_id, p.status,
               p.ban_reason, p.id_curator,
               r.code AS role_code, r.name AS role_name,
               (SELECT count(*)::int FROM app.strikes s
                WHERE s.user_id = u.id AND s.status = 'active') AS strike_count
        FROM app.profiles p
        JOIN app.users u ON u.id = p.user_id
        JOIN app.roles r ON r.id = p.role_id
        WHERE p.phone IS NOT NULL
          AND regexp_replace(p.phone, '[^0-9]', '', 'g') IN ($1, $2)
        LIMIT 1
    """
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(sql, digits, alt_digits or digits)
    return serialize_record(row) if row else None


async def link_profile_max_id(user_id: str, max_id: int) -> dict[str, Any]:
    existing = await get_profile_by_max_id(max_id)
    if existing and str(existing["id"]) != user_id:
        raise ValueError("Этот MAX-аккаунт уже привязан к другому пользователю")
    profile = await get_user_profile(user_id)
    if not profile:
        raise ValueError("Пользователь не найден")
    current_max = profile.get("max_id")
    if current_max is not None and int(current_max) != max_id:
        raise ValueError("У вашего профиля уже указан другой MAX ID. Обратитесь к HR.")
    return await update_user_profile(user_id, max_id=max_id)


async def list_user_groups(user_id: str) -> list[dict[str, Any]]:
    sql = """
        SELECT g.id, g.name, g.status, g.created_at,
               hr_p.last_name AS hr_last_name, hr_p.first_name AS hr_first_name
        FROM app.group_members gm
        JOIN app.groups g ON g.id = gm.group_id
        LEFT JOIN app.profiles hr_p ON hr_p.user_id = g.id_hr
        WHERE gm.user_id = $1::uuid
        ORDER BY g.name
    """
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(sql, uuid.UUID(user_id))
    result = []
    for row in rows:
        item = serialize_record(row)
        if item.get("hr_last_name"):
            item["hr_name"] = f"{item['hr_last_name']} {item['hr_first_name']}"
        result.append(item)
    return result


async def get_employee_progress(user_id: str) -> list[dict[str, Any]]:
    """Per-group attendance summary and upcoming lesson count for an employee."""
    sql = f"""
        SELECT g.id AS group_id, g.name AS group_name,
               count(DISTINCT l.id) FILTER (
                   WHERE l.starts_at <= now() AND lm.user_id IS NOT NULL
               ) AS lessons_past,
               count(am.id) FILTER (WHERE am.status = 'present') AS present_count,
               count(am.id) FILTER (WHERE am.status = 'late') AS late_count,
               count(am.id) FILTER (WHERE am.status = 'absent') AS absent_count,
               count(DISTINCT l.id) FILTER (
                   WHERE l.starts_at > now() AND lm.user_id IS NOT NULL
               ) AS lessons_upcoming
        FROM app.group_members gm
        JOIN app.groups g ON g.id = gm.group_id
        LEFT JOIN app.lessons l ON l.group_id = g.id
        LEFT JOIN app.lesson_members lm ON lm.lesson_id = l.id AND lm.user_id = gm.user_id
        LEFT JOIN app.attendance_marks am ON am.user_id = gm.user_id AND am.lesson_id = l.id
        WHERE gm.user_id = $1::uuid
        GROUP BY g.id, g.name
        ORDER BY g.name
    """
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(sql, uuid.UUID(user_id))
    return [serialize_record(row) for row in rows]


async def list_employee_upcoming_lessons(user_id: str, *, limit: int = 7) -> list[dict[str, Any]]:
    safe_limit = max(1, min(limit, 20))
    sql = f"""
        SELECT l.id, l.starts_at, l.ends_at, l.place, l.lesson_type, l.title,
               {LESSON_TITLE_SQL} AS lesson_title,
               g.name AS group_name,
               tp.last_name AS teacher_last_name, tp.first_name AS teacher_first_name
        FROM app.lesson_members lm
        JOIN app.lessons l ON l.id = lm.lesson_id
        JOIN app.groups g ON g.id = l.group_id
        JOIN app.profiles tp ON tp.user_id = l.teacher_id
        WHERE lm.user_id = $1::uuid
          AND l.starts_at > now()
        ORDER BY l.starts_at
        LIMIT $2
    """
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(sql, uuid.UUID(user_id), safe_limit)
    return [serialize_record(row) for row in rows]


async def list_user_strikes(user_id: str) -> list[dict[str, Any]]:
    sql = """
        SELECT s.id, s.user_id, s.lesson_id, s.reason, s.status, s.strike_number,
               s.appeal_reason, s.appealed_at, s.created_at,
               g.name AS group_name,
               l.starts_at AS lesson_starts_at,
               COALESCE(l.title, CASE WHEN l.lesson_type = 'practice' THEN 'Практика' ELSE 'Лекция' END) AS lesson_title
        FROM app.strikes s
        LEFT JOIN app.lessons l ON l.id = s.lesson_id
        LEFT JOIN app.groups g ON g.id = l.group_id
        WHERE s.user_id = $1::uuid
          AND s.status != 'revoked'
        ORDER BY s.created_at DESC
        LIMIT 20
    """
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(sql, uuid.UUID(user_id))
    return [serialize_record(row) for row in rows]


async def submit_user_strike_appeal(user_id: str, strike_id: str, appeal_reason: str) -> dict[str, Any]:
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE app.strikes
            SET status = 'appealed', appeal_reason = $3, appealed_at = now()
            WHERE id = $1::uuid AND user_id = $2::uuid AND status = 'active'
            RETURNING id, user_id, status, appeal_reason, appealed_at, strike_number
            """,
            uuid.UUID(strike_id),
            uuid.UUID(user_id),
            appeal_reason,
        )
    if not row:
        raise ValueError("Страйк не найден, уже подана апелляция или страйк не ваш")
    return serialize_record(row)
