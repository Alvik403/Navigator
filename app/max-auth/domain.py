import logging
import uuid
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from db import get_pool, serialize_record
from bot_contact import normalize_phone_digits

logger = logging.getLogger("max-auth")


STRIKE_BAN_REASON = "3 страйка"
MANUAL_BAN_DEFAULT = "ручной бан"

LESSON_TITLE_SQL = (
    "COALESCE(l.title, CASE WHEN l.lesson_type = 'practice' THEN 'Практика' ELSE 'Лекция' END)"
)
LESSON_GROUP_SQL = "COALESCE(l.reporting_group_id, l.group_id)"


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
        SELECT DISTINCT u.id, u.keycloak_user_id, u.is_active, p.last_name, p.first_name, p.middle_name,
               p.phone, p.max_id, p.status, p.ban_reason, p.id_curator,
               r.code AS role_code, r.name AS role_name,
               (SELECT count(*)::int FROM app.strikes s
                WHERE s.user_id = u.id AND s.status = 'active') AS strike_count
        FROM app.users u
        JOIN app.profiles p ON p.user_id = u.id
        JOIN app.roles r ON r.id = p.role_id
        WHERE ($1::text IS NULL OR r.code = $1)
          AND (
            $2::uuid IS NULL
            OR r.code != 'employee'
            OR NOT EXISTS (
                SELECT 1 FROM app.user_tracks ut0
                WHERE ut0.user_id = u.id AND ut0.status = 'active'
            )
            OR EXISTS (
                SELECT 1 FROM app.user_tracks ut2
                JOIN app.tracks tr ON tr.id = ut2.track_id
                WHERE ut2.user_id = u.id AND ut2.status = 'active' AND tr.id_hr = $2::uuid
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


async def get_app_user_id_by_keycloak_id(keycloak_user_id: str) -> str | None:
    async with get_pool().acquire() as conn:
        row = await conn.fetchval(
            "SELECT id FROM app.users WHERE keycloak_user_id = $1::uuid",
            uuid.UUID(keycloak_user_id),
        )
    return str(row) if row else None


async def link_keycloak_user_id(app_user_id: str, keycloak_user_id: str) -> None:
    async with get_pool().acquire() as conn:
        await conn.execute(
            """
            UPDATE app.users
            SET keycloak_user_id = $2::uuid
            WHERE id = $1::uuid
              AND (keycloak_user_id IS NULL OR keycloak_user_id = $2::uuid)
            """,
            uuid.UUID(app_user_id),
            uuid.UUID(keycloak_user_id),
        )


async def provision_keycloak_user(
    *,
    keycloak_user_id: str,
    role_code: str,
    last_name: str,
    first_name: str,
    middle_name: str | None = None,
) -> dict[str, Any]:
    kc_uuid = uuid.UUID(keycloak_user_id)
    async with get_pool().acquire() as conn:
        existing_id = await conn.fetchval(
            "SELECT id FROM app.users WHERE keycloak_user_id = $1::uuid",
            kc_uuid,
        )
        if existing_id:
            profile = await get_user_profile(str(existing_id))
            return profile or {}

        role_id = await conn.fetchval("SELECT id FROM app.roles WHERE code = $1", role_code)
        if not role_id:
            raise ValueError(f"Неизвестная роль: {role_code}")

        user_id = uuid.uuid4()
        await conn.execute(
            """
            INSERT INTO app.users (id, keycloak_user_id, is_active)
            VALUES ($1::uuid, $2::uuid, TRUE)
            """,
            user_id,
            kc_uuid,
        )
        await conn.execute(
            """
            INSERT INTO app.profiles (user_id, last_name, first_name, middle_name, role_id, status)
            VALUES ($1::uuid, $2, $3, $4, $5, 'active')
            """,
            user_id,
            last_name,
            first_name,
            middle_name,
            role_id,
        )

    profile = await get_user_profile(str(user_id))
    logger.info(
        "Auto-provisioned app user %s for Keycloak %s (role=%s)",
        user_id,
        keycloak_user_id,
        role_code,
    )
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
    update_max_id: bool = False,
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
        if update_max_id:
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


async def verify_lesson_hr_access(lesson_id: str, hr_user_id: str | None) -> None:
    if hr_user_id is None:
        return
    async with get_pool().acquire() as conn:
        owner = await conn.fetchval(
            """
            SELECT COALESCE(t.id_hr, g.id_hr)
            FROM app.lessons l
            LEFT JOIN app.tracks t ON t.id = l.track_id
            LEFT JOIN app.groups g ON g.id = COALESCE(l.reporting_group_id, l.group_id)
            WHERE l.id = $1::uuid
            """,
            uuid.UUID(lesson_id),
        )
    if owner is None:
        raise ValueError("Занятие не найдено")
    if str(owner) != hr_user_id:
        raise ValueError("Нет доступа к этому занятию")


async def bulk_create_users(rows: list[dict[str, Any]]) -> dict[str, Any]:
    created: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for row in rows:
        try:
            track_id = await resolve_track_ref(row.get("track"))
            if row.get("track") and not track_id:
                raise ValueError(f"Трек не найден: {row.get('track')}")
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
            user_id = str(profile.get("id") or "")
            role_code = row.get("role_code", "employee")
            if track_id and user_id:
                if role_code == "student":
                    await assign_user_track(user_id=user_id, track_id=track_id)
                elif role_code == "teacher":
                    await sync_instructor_tracks(teacher_id=user_id, track_ids=[track_id])
            created.append(profile)
        except Exception as error:
            skipped.append({"row": str(row), "reason": str(error)})
    return {"created": created, "skipped": skipped, "created_count": len(created), "skipped_count": len(skipped)}


async def resolve_track_ref(track_ref: str | None) -> str | None:
    if not track_ref or not str(track_ref).strip():
        return None
    ref = str(track_ref).strip()
    try:
        track_uuid = uuid.UUID(ref)
    except ValueError:
        track_uuid = None
    async with get_pool().acquire() as conn:
        if track_uuid is not None:
            row = await conn.fetchrow(
                "SELECT id FROM app.tracks WHERE id = $1::uuid",
                track_uuid,
            )
            return str(row["id"]) if row else None
        row = await conn.fetchrow(
            """
            SELECT id FROM app.tracks
            WHERE lower(code) = lower($1) OR lower(name) = lower($1)
            ORDER BY CASE WHEN lower(code) = lower($1) THEN 0 ELSE 1 END
            LIMIT 1
            """,
            ref,
        )
        if row:
            return str(row["id"])
        row = await conn.fetchrow(
            """
            SELECT id FROM app.tracks
            WHERE lower(name) LIKE '%' || lower($1) || '%'
            ORDER BY length(name)
            LIMIT 1
            """,
            ref,
        )
        return str(row["id"]) if row else None


async def get_group_hr_id(group_id: str) -> str | None:
    async with get_pool().acquire() as conn:
        row = await conn.fetchval(
            "SELECT id_hr FROM app.groups WHERE id = $1::uuid",
            uuid.UUID(group_id),
        )
    return str(row) if row else None


async def list_groups(*, hr_user_id: str | None = None) -> list[dict[str, Any]]:
    sql = """
        SELECT g.id, g.name, g.status, g.id_parent, g.id_hr, g.instructor_id, g.created_at,
               hr_p.last_name AS hr_last_name, hr_p.first_name AS hr_first_name,
               tp.last_name AS instructor_last_name, tp.first_name AS instructor_first_name,
               (SELECT count(*) FROM app.group_members gm WHERE gm.group_id = g.id) AS member_count
        FROM app.groups g
        LEFT JOIN app.profiles hr_p ON hr_p.user_id = g.id_hr
        LEFT JOIN app.profiles tp ON tp.user_id = g.instructor_id
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


async def remove_group_member(
    group_id: str,
    user_id: str,
    *,
    actor_user_id: str | None = None,
    actor_name: str | None = None,
) -> None:
    from audit import write_audit_log

    async with get_pool().acquire() as conn:
        exists = await conn.fetchval(
            """
            SELECT 1 FROM app.group_members
            WHERE group_id = $1::uuid AND user_id = $2::uuid
            """,
            uuid.UUID(group_id),
            uuid.UUID(user_id),
        )
        if not exists:
            return
        await conn.execute(
            "DELETE FROM app.group_members WHERE group_id = $1::uuid AND user_id = $2::uuid",
            uuid.UUID(group_id),
            uuid.UUID(user_id),
        )
    await write_audit_log(
        actor_user_id=actor_user_id,
        actor_name=actor_name,
        action="delete",
        entity_type="group_member",
        entity_id=f"{group_id}:{user_id}",
        entity_label=f"участник {user_id} в группе {group_id}",
        payload={"group_id": group_id, "user_id": user_id},
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


async def list_teacher_tracks(teacher_id: str) -> list[dict[str, Any]]:
    sql = """
        SELECT DISTINCT t.id, t.name, t.code, t.status,
               (SELECT count(*)::int FROM app.user_tracks ut
                WHERE ut.track_id = t.id AND ut.status = 'active') AS member_count
        FROM app.track_teachers tt
        JOIN app.tracks t ON t.id = tt.track_id
        WHERE tt.teacher_id = $1::uuid
        ORDER BY t.name
    """
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(sql, uuid.UUID(teacher_id))
    return [serialize_record(row) for row in rows]


async def list_teacher_groups(teacher_id: str) -> list[dict[str, Any]]:
    return await list_teacher_tracks(teacher_id)


async def list_lessons(
    *,
    teacher_id: str | None = None,
    group_id: str | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    track_id: str | None = None,
    slot_id: str | None = None,
) -> list[dict[str, Any]]:
    sql = f"""
        SELECT l.id, l.group_id, l.reporting_group_id, l.track_id, l.slot_id,
               l.teacher_id, l.starts_at, l.ends_at, l.place, l.lesson_type, l.title,
               {LESSON_TITLE_SQL} AS lesson_title,
               g.name AS group_name,
               t.name AS track_name, t.code AS track_code,
               cs.name AS slot_name, cs.code AS slot_code,
               tp.last_name AS teacher_last_name, tp.first_name AS teacher_first_name
        FROM app.lessons l
        LEFT JOIN app.groups g ON g.id = {LESSON_GROUP_SQL}
        LEFT JOIN app.tracks t ON t.id = l.track_id
        LEFT JOIN app.conveyor_slots cs ON cs.id = l.slot_id
        JOIN app.profiles tp ON tp.user_id = l.teacher_id
        WHERE ($1::uuid IS NULL OR l.teacher_id = $1::uuid)
          AND ($2::uuid IS NULL OR {LESSON_GROUP_SQL} = $2::uuid)
          AND ($3::timestamptz IS NULL OR l.starts_at >= $3)
          AND ($4::timestamptz IS NULL OR l.starts_at <= $4)
          AND ($5::uuid IS NULL OR l.track_id = $5::uuid)
          AND ($6::uuid IS NULL OR l.slot_id = $6::uuid)
        ORDER BY l.starts_at
    """
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            sql,
            uuid.UUID(teacher_id) if teacher_id else None,
            uuid.UUID(group_id) if group_id else None,
            from_date,
            to_date,
            uuid.UUID(track_id) if track_id else None,
            uuid.UUID(slot_id) if slot_id else None,
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


async def verify_teacher_track_access(track_id: str, teacher_id: str) -> None:
    async with get_pool().acquire() as conn:
        allowed = await conn.fetchval(
            """
            SELECT 1
            FROM app.track_teachers tt
            WHERE tt.track_id = $1::uuid AND tt.teacher_id = $2::uuid
            UNION
            SELECT 1
            FROM app.lessons l
            WHERE l.track_id = $1::uuid AND l.teacher_id = $2::uuid
            LIMIT 1
            """,
            uuid.UUID(track_id),
            uuid.UUID(teacher_id),
        )
    if not allowed:
        raise ValueError("Нет доступа к этому треку")


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
    if owner == teacher_id:
        return
    async with get_pool().acquire() as conn:
        track_id = await conn.fetchval(
            "SELECT track_id FROM app.lessons WHERE id = $1::uuid",
            uuid.UUID(lesson_id),
        )
    if track_id is None:
        raise ValueError("Нет доступа к этому занятию")
    await verify_teacher_track_access(str(track_id), teacher_id)


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


async def get_user_role_code(user_id: str) -> str | None:
    async with get_pool().acquire() as conn:
        code = await conn.fetchval(
            """
            SELECT r.code
            FROM app.profiles p
            JOIN app.roles r ON r.id = p.role_id
            WHERE p.user_id = $1::uuid
            """,
            uuid.UUID(user_id),
        )
    return str(code) if code else None


async def list_tracks(*, hr_user_id: str | None = None) -> list[dict[str, Any]]:
    sql = """
        SELECT id, code, name, description, practice_required, lecture_required,
               completion_days, id_hr, status, created_at, updated_at,
               formation_auto_enabled, formation_max_members, formation_min_members,
               formation_lock_days, formation_weight_penalty, formation_lesson_type,
               formation_default_place
        FROM app.tracks
        WHERE ($1::uuid IS NULL OR id_hr IS NULL OR id_hr = $1::uuid)
        ORDER BY name
    """
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(sql, uuid.UUID(hr_user_id) if hr_user_id else None)
    return [serialize_record(row) for row in rows]


async def create_track(
    *,
    code: str,
    name: str,
    description: str | None = None,
    practice_required: int = 0,
    lecture_required: int = 0,
    completion_days: int = 90,
    id_hr: str | None = None,
) -> dict[str, Any]:
    sql = """
        INSERT INTO app.tracks (code, name, description, practice_required, lecture_required, completion_days, id_hr)
        VALUES ($1, $2, $3, $4, $5, $6, $7::uuid)
        ON CONFLICT (code) DO UPDATE SET
            name = EXCLUDED.name,
            description = EXCLUDED.description,
            practice_required = EXCLUDED.practice_required,
            lecture_required = EXCLUDED.lecture_required,
            completion_days = EXCLUDED.completion_days,
            id_hr = COALESCE(EXCLUDED.id_hr, app.tracks.id_hr),
            updated_at = now()
        RETURNING id, code, name, description, practice_required, lecture_required,
                  completion_days, id_hr, status, created_at, updated_at
    """
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            sql,
            code,
            name,
            description,
            practice_required,
            lecture_required,
            completion_days,
            uuid.UUID(id_hr) if id_hr else None,
        )
    return serialize_record(row)


async def assign_user_track(
    *,
    user_id: str,
    track_id: str,
    assigned_by: str | None = None,
    status: str = "active",
    due_date: date | None = None,
) -> dict[str, Any]:
    async with get_pool().acquire() as conn:
        if due_date is None:
            completion_days = await conn.fetchval(
                "SELECT completion_days FROM app.tracks WHERE id = $1::uuid",
                uuid.UUID(track_id),
            )
            if completion_days:
                due_date = date.today() + timedelta(days=int(completion_days))
        row = await conn.fetchrow(
            """
            INSERT INTO app.user_tracks (user_id, track_id, assigned_by, status, due_date)
            VALUES ($1::uuid, $2::uuid, $3::uuid, $4, $5)
            ON CONFLICT (user_id, track_id) DO UPDATE SET
                status = EXCLUDED.status,
                assigned_by = COALESCE(EXCLUDED.assigned_by, app.user_tracks.assigned_by),
                due_date = COALESCE(EXCLUDED.due_date, app.user_tracks.due_date),
                completed_at = CASE WHEN EXCLUDED.status = 'completed' THEN CURRENT_DATE ELSE NULL END,
                updated_at = now()
            RETURNING user_id, track_id, status, started_at, completed_at, due_date,
                      assigned_by, created_at, updated_at
            """,
            uuid.UUID(user_id),
            uuid.UUID(track_id),
            uuid.UUID(assigned_by) if assigned_by else None,
            status,
            due_date,
        )
    return serialize_record(row)


async def list_user_tracks(user_id: str) -> list[dict[str, Any]]:
    sql = """
        SELECT ut.user_id, ut.track_id, ut.status, ut.started_at, ut.completed_at, ut.due_date,
               t.code, t.name, t.description, t.practice_required, t.lecture_required
        FROM app.user_tracks ut
        JOIN app.tracks t ON t.id = ut.track_id
        WHERE ut.user_id = $1::uuid
        ORDER BY t.name
    """
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(sql, uuid.UUID(user_id))
    return [serialize_record(row) for row in rows]


async def list_conveyor_slots(*, active_only: bool = False) -> list[dict[str, Any]]:
    sql = """
        SELECT id, code, name, starts_at_local, duration_min, timezone, status, sort_order
        FROM app.conveyor_slots
        WHERE ($1::bool = FALSE OR status = 'active')
        ORDER BY sort_order, starts_at_local
    """
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(sql, active_only)
    return [serialize_record(row) for row in rows]


async def create_conveyor_slot(
    *,
    code: str,
    name: str,
    starts_at_local: str,
    duration_min: int = 60,
    timezone: str = "Europe/Moscow",
    sort_order: int = 0,
) -> dict[str, Any]:
    sql = """
        INSERT INTO app.conveyor_slots (code, name, starts_at_local, duration_min, timezone, sort_order)
        VALUES ($1, $2, $3::time, $4, $5, $6)
        ON CONFLICT (code) DO UPDATE SET
            name = EXCLUDED.name,
            starts_at_local = EXCLUDED.starts_at_local,
            duration_min = EXCLUDED.duration_min,
            timezone = EXCLUDED.timezone,
            sort_order = EXCLUDED.sort_order,
            updated_at = now()
        RETURNING id, code, name, starts_at_local, duration_min, timezone, status, sort_order
    """
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(sql, code, name, starts_at_local, duration_min, timezone, sort_order)
    return serialize_record(row)


FORMATION_LOCK_DAYS = 14
FORMATION_WEIGHT_PENALTY = 50.0

TRACK_FORMATION_RETURN = """
    formation_auto_enabled, formation_max_members, formation_min_members,
    formation_lock_days, formation_weight_penalty, formation_lesson_type,
    formation_default_place
"""


def formation_settings_from_track(track: dict[str, Any]) -> dict[str, Any]:
    max_members = int(track.get("formation_max_members") or 12)
    min_members = int(track.get("formation_min_members") or 1)
    if min_members > max_members:
        min_members = max_members
    return {
        "auto_enabled": track.get("formation_auto_enabled") is not False,
        "max_members": max_members,
        "min_members": min_members,
        "lock_days": int(track.get("formation_lock_days") if track.get("formation_lock_days") is not None else FORMATION_LOCK_DAYS),
        "weight_penalty": float(track.get("formation_weight_penalty") if track.get("formation_weight_penalty") is not None else FORMATION_WEIGHT_PENALTY),
        "lesson_type": str(track.get("formation_lesson_type") or "practice"),
        "default_place": track.get("formation_default_place"),
    }


async def get_track(track_id: str) -> dict[str, Any] | None:
    sql = f"""
        SELECT id, code, name, description, practice_required, lecture_required,
               completion_days, id_hr, status, created_at, updated_at,
               {TRACK_FORMATION_RETURN.strip()}
        FROM app.tracks WHERE id = $1::uuid
    """
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(sql, uuid.UUID(track_id))
    return serialize_record(row) if row else None


async def list_track_formation_slot_ids(track_id: str) -> list[str]:
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT slot_id FROM app.track_formation_slots
            WHERE track_id = $1::uuid
            ORDER BY slot_id
            """,
            uuid.UUID(track_id),
        )
    return [str(row["slot_id"]) for row in rows]


async def set_track_formation_slots(track_id: str, slot_ids: list[str]) -> list[str]:
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "DELETE FROM app.track_formation_slots WHERE track_id = $1::uuid",
                uuid.UUID(track_id),
            )
            for slot_id in slot_ids:
                await conn.execute(
                    """
                    INSERT INTO app.track_formation_slots (track_id, slot_id)
                    VALUES ($1::uuid, $2::uuid)
                    ON CONFLICT DO NOTHING
                    """,
                    uuid.UUID(track_id),
                    uuid.UUID(slot_id),
                )
    return await list_track_formation_slot_ids(track_id)


async def update_track_formation_settings(
    track_id: str,
    *,
    formation_auto_enabled: bool | None = None,
    formation_max_members: int | None = None,
    formation_min_members: int | None = None,
    formation_lock_days: int | None = None,
    formation_weight_penalty: float | None = None,
    formation_lesson_type: str | None = None,
    formation_default_place: str | None = None,
    clear_default_place: bool = False,
    slot_ids: list[str] | None = None,
) -> dict[str, Any]:
    fields: list[str] = []
    values: list[Any] = []
    idx = 2
    mapping = {
        "formation_auto_enabled": formation_auto_enabled,
        "formation_max_members": formation_max_members,
        "formation_min_members": formation_min_members,
        "formation_lock_days": formation_lock_days,
        "formation_weight_penalty": formation_weight_penalty,
        "formation_lesson_type": formation_lesson_type,
    }
    for key, val in mapping.items():
        if val is not None:
            fields.append(f"{key} = ${idx}")
            values.append(val)
            idx += 1
    if clear_default_place:
        fields.append("formation_default_place = NULL")
    elif formation_default_place is not None:
        fields.append(f"formation_default_place = ${idx}")
        values.append(formation_default_place)
        idx += 1
    if fields:
        fields.append("updated_at = now()")
        sql = f"""
            UPDATE app.tracks SET {", ".join(fields)}
            WHERE id = $1::uuid
            RETURNING id, code, name, description, practice_required, lecture_required,
                      completion_days, id_hr, status, created_at, updated_at,
                      {TRACK_FORMATION_RETURN.strip()}
        """
        async with get_pool().acquire() as conn:
            row = await conn.fetchrow(sql, uuid.UUID(track_id), *values)
        if not row:
            raise ValueError("Трек не найден")
        track = serialize_record(row)
    else:
        track = await get_track(track_id)
        if not track:
            raise ValueError("Трек не найден")
    if slot_ids is not None:
        await set_track_formation_slots(track_id, slot_ids)
    track["formation_slot_ids"] = await list_track_formation_slot_ids(track_id)
    return track


def _smu_is_work_day(work_days: int, off_days: int, anchor: date, target: date) -> bool:
    cycle = work_days + off_days
    if cycle <= 0:
        return False
    delta = (target - anchor).days
    pos = delta % cycle
    return pos < work_days


CYCLE_222 = 6
CYCLE_222_HALF = 3


def _smu_period_for_shift(shift_number: int) -> str:
    return "night" if int(shift_number or 1) in (2, 4) else "day"


def _smu_shift_anchor_222(anchor: date, shift_number: int) -> date:
    sn = int(shift_number or 1)
    if sn in (3, 4):
        return anchor + timedelta(days=CYCLE_222_HALF)
    return anchor


def _smu_cycle_position_222(anchor: date, shift_number: int, target: date) -> int:
    shift_anchor = _smu_shift_anchor_222(anchor, shift_number)
    return (target - shift_anchor).days % CYCLE_222


def _smu_is_work_day_222(
    anchor: date,
    shift_number: int,
    target: date,
    period: str,
) -> bool:
    pos = _smu_cycle_position_222(anchor, shift_number, target)
    if period == "day":
        return pos < 2
    if period == "night":
        return pos >= 4
    return False


async def list_smu_patterns(*, active_only: bool = False) -> list[dict[str, Any]]:
    sql = """
        SELECT id, code, name, work_days, off_days, anchor_date, status,
               shift_count, target_shift1, target_shift2, target_shift3, target_shift4,
               created_at, updated_at
        FROM app.smu_patterns
        WHERE ($1::bool = FALSE OR status = 'active')
        ORDER BY CAST(substring(code FROM '[0-9]+') AS int) NULLS LAST, name
    """
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(sql, active_only)
    return [serialize_record(row) for row in rows]


async def create_smu_pattern(
    *,
    code: str,
    name: str,
    work_days: int = 0,
    off_days: int = 0,
    anchor_date: date | None = None,
) -> dict[str, Any]:
    sql = """
        INSERT INTO app.smu_patterns (code, name, work_days, off_days, anchor_date)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (code) DO UPDATE SET
            name = EXCLUDED.name,
            work_days = EXCLUDED.work_days,
            off_days = EXCLUDED.off_days,
            anchor_date = EXCLUDED.anchor_date,
            updated_at = now()
        RETURNING id, code, name, work_days, off_days, anchor_date, status,
                  shift_count, target_shift1, target_shift2, target_shift3, target_shift4,
                  created_at, updated_at
    """
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            sql,
            code,
            name,
            work_days,
            off_days,
            anchor_date or date.today(),
        )
    return serialize_record(row)


async def update_smu_pattern(
    pattern_id: str,
    *,
    name: str | None = None,
    work_days: int | None = None,
    off_days: int | None = None,
    anchor_date: date | None = None,
    target_shift1: int | None = None,
    target_shift2: int | None = None,
    target_shift3: int | None = None,
    target_shift4: int | None = None,
    clear_target_shift1: bool = False,
    clear_target_shift2: bool = False,
    clear_target_shift3: bool = False,
    clear_target_shift4: bool = False,
    status: str | None = None,
) -> dict[str, Any]:
    fields: list[str] = []
    values: list[Any] = []
    idx = 1
    if name is not None:
        fields.append(f"name = ${idx}")
        values.append(name)
        idx += 1
    if work_days is not None:
        fields.append(f"work_days = ${idx}")
        values.append(work_days)
        idx += 1
    if off_days is not None:
        fields.append(f"off_days = ${idx}")
        values.append(off_days)
        idx += 1
    if anchor_date is not None:
        fields.append(f"anchor_date = ${idx}")
        values.append(anchor_date)
        idx += 1
    if clear_target_shift1:
        fields.append("target_shift1 = NULL")
    elif target_shift1 is not None:
        fields.append(f"target_shift1 = ${idx}")
        values.append(target_shift1)
        idx += 1
    if clear_target_shift2:
        fields.append("target_shift2 = NULL")
    elif target_shift2 is not None:
        fields.append(f"target_shift2 = ${idx}")
        values.append(target_shift2)
        idx += 1
    if clear_target_shift3:
        fields.append("target_shift3 = NULL")
    elif target_shift3 is not None:
        fields.append(f"target_shift3 = ${idx}")
        values.append(target_shift3)
        idx += 1
    if clear_target_shift4:
        fields.append("target_shift4 = NULL")
    elif target_shift4 is not None:
        fields.append(f"target_shift4 = ${idx}")
        values.append(target_shift4)
        idx += 1
    if status is not None:
        fields.append(f"status = ${idx}")
        values.append(status)
        idx += 1
    if not fields:
        patterns = await list_smu_patterns()
        row = next((p for p in patterns if str(p["id"]) == pattern_id), None)
        if not row:
            raise ValueError("СМУ не найдена")
        return row
    fields.append("updated_at = now()")
    sql = f"""
        UPDATE app.smu_patterns
        SET {", ".join(fields)}
        WHERE id = ${idx}::uuid
        RETURNING id, code, name, work_days, off_days, anchor_date, status,
                  shift_count, target_shift1, target_shift2, target_shift3, target_shift4,
                  created_at, updated_at
    """
    values.append(uuid.UUID(pattern_id))
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(sql, *values)
    if not row:
        raise ValueError("СМУ не найдена")
    return serialize_record(row)


async def delete_smu_pattern(pattern_id: str) -> dict[str, Any]:
    pid = uuid.UUID(pattern_id)
    async with get_pool().acquire() as conn:
        pattern = await conn.fetchrow(
            """
            SELECT id, code, name
            FROM app.smu_patterns
            WHERE id = $1::uuid
            """,
            pid,
        )
        if not pattern:
            raise ValueError("СМУ не найдена")
        assigned_count = await conn.fetchval(
            """
            SELECT COUNT(*)::int
            FROM app.user_smu
            WHERE smu_pattern_id = $1::uuid
            """,
            pid,
        )
        if assigned_count:
            raise ValueError(
                f"Нельзя удалить СМУ: назначено сотрудников — {assigned_count}. Сначала снимите их с этой СМУ."
            )
        await conn.execute(
            """
            DELETE FROM app.smu_patterns
            WHERE id = $1::uuid
            """,
            pid,
        )
    return serialize_record(pattern)


async def assign_user_smu(
    *,
    user_id: str,
    smu_pattern_id: str,
    shift_number: int = 1,
) -> dict[str, Any]:
    if shift_number not in (1, 2, 3, 4):
        raise ValueError("Номер смены должен быть от 1 до 4")
    sql = """
        INSERT INTO app.user_smu (user_id, smu_pattern_id, shift_number)
        VALUES ($1::uuid, $2::uuid, $3)
        ON CONFLICT (user_id) DO UPDATE SET
            smu_pattern_id = EXCLUDED.smu_pattern_id,
            shift_number = EXCLUDED.shift_number,
            updated_at = now()
        RETURNING user_id, smu_pattern_id, shift_number, started_at, created_at, updated_at
    """
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            sql,
            uuid.UUID(user_id),
            uuid.UUID(smu_pattern_id),
            shift_number,
        )
    return serialize_record(row)


async def list_user_smu_assignments() -> list[dict[str, Any]]:
    sql = """
        SELECT us.user_id, us.smu_pattern_id, us.shift_number, us.started_at,
               sp.code AS smu_code, sp.name AS smu_name,
               sp.work_days, sp.off_days, sp.anchor_date,
               p.last_name, p.first_name
        FROM app.user_smu us
        JOIN app.smu_patterns sp ON sp.id = us.smu_pattern_id
        JOIN app.profiles p ON p.user_id = us.user_id
        ORDER BY sp.name, p.last_name, p.first_name
    """
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(sql)
    return [serialize_record(row) for row in rows]


async def add_smu_extra_shift(
    *,
    user_id: str,
    shift_date: date,
    shift_number: int = 1,
    note: str | None = None,
) -> dict[str, Any]:
    if shift_number not in (1, 2, 3, 4):
        raise ValueError("Номер смены должен быть от 1 до 4")
    sql = """
        INSERT INTO app.smu_extra_shifts (user_id, shift_date, shift_number, note)
        VALUES ($1::uuid, $2, $3, $4)
        ON CONFLICT (user_id, shift_date) DO UPDATE SET
            shift_number = EXCLUDED.shift_number,
            note = EXCLUDED.note
        RETURNING id, user_id, shift_date, shift_number, note, created_at
    """
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(sql, uuid.UUID(user_id), shift_date, shift_number, note)
    return serialize_record(row)


async def update_smu_extra_shift(
    *,
    shift_id: str,
    shift_date: date | None = None,
    shift_number: int | None = None,
    note: str | None = None,
    clear_note: bool = False,
) -> dict[str, Any]:
    if shift_number is not None and shift_number not in (1, 2, 3, 4):
        raise ValueError("Номер смены должен быть от 1 до 4")
    fields: list[str] = []
    values: list[Any] = []
    idx = 1
    if shift_date is not None:
        fields.append(f"shift_date = ${idx}")
        values.append(shift_date)
        idx += 1
    if shift_number is not None:
        fields.append(f"shift_number = ${idx}")
        values.append(shift_number)
        idx += 1
    if clear_note:
        fields.append("note = NULL")
    elif note is not None:
        fields.append(f"note = ${idx}")
        values.append(note)
        idx += 1
    if not fields:
        raise ValueError("Нечего обновлять")
    sql = f"""
        UPDATE app.smu_extra_shifts
        SET {", ".join(fields)}
        WHERE id = ${idx}::uuid
        RETURNING id, user_id, shift_date, shift_number, note, created_at
    """
    values.append(uuid.UUID(shift_id))
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(sql, *values)
    if not row:
        raise ValueError("Допсмена не найдена")
    return serialize_record(row)


async def list_smu_extra_shifts(*, from_date: date | None = None, to_date: date | None = None) -> list[dict[str, Any]]:
    sql = """
        SELECT es.id, es.user_id, es.shift_date, es.shift_number, es.note, es.created_at,
               p.last_name, p.first_name,
               us.smu_pattern_id, sp.name AS smu_name, sp.code AS smu_code
        FROM app.smu_extra_shifts es
        JOIN app.profiles p ON p.user_id = es.user_id
        LEFT JOIN app.user_smu us ON us.user_id = es.user_id
        LEFT JOIN app.smu_patterns sp ON sp.id = us.smu_pattern_id
        WHERE ($1::date IS NULL OR es.shift_date >= $1)
          AND ($2::date IS NULL OR es.shift_date <= $2)
        ORDER BY es.shift_date, es.shift_number, p.last_name
    """
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(sql, from_date, to_date)
    return [serialize_record(row) for row in rows]


async def remove_user_smu(
    *,
    user_id: str,
    actor_user_id: str | None = None,
    actor_name: str | None = None,
) -> dict[str, Any]:
    from audit import write_audit_log

    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            """
            DELETE FROM app.user_smu
            WHERE user_id = $1::uuid
            RETURNING user_id, smu_pattern_id, started_at, shift_number
            """,
            uuid.UUID(user_id),
        )
    if not row:
        raise ValueError("Сотрудник не назначен на СМУ")
    payload = serialize_record(row)
    await write_audit_log(
        actor_user_id=actor_user_id,
        actor_name=actor_name,
        action="delete",
        entity_type="user_smu",
        entity_id=str(user_id),
        entity_label=f"СМУ пользователя {user_id}",
        payload=payload,
    )
    return payload


async def remove_smu_extra_shift(
    *,
    shift_id: str,
    actor_user_id: str | None = None,
    actor_name: str | None = None,
) -> dict[str, Any]:
    from audit import write_audit_log

    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            """
            DELETE FROM app.smu_extra_shifts
            WHERE id = $1::uuid
            RETURNING id, user_id, shift_date, shift_number, note
            """,
            uuid.UUID(shift_id),
        )
    if not row:
        raise ValueError("Допсмена не найдена")
    payload = serialize_record(row)
    await write_audit_log(
        actor_user_id=actor_user_id,
        actor_name=actor_name,
        action="delete",
        entity_type="smu_extra_shift",
        entity_id=str(shift_id),
        entity_label=f"допсмена {payload.get('shift_date')}",
        payload=payload,
    )
    return payload


def _smu_shift_anchor(anchor: date, work_days: int, off_days: int, shift_number: int) -> date:
    cycle = int(work_days or 0) + int(off_days or 0)
    sn = int(shift_number or 1)
    if sn in (1, 2):
        return anchor
    if sn in (3, 4):
        half = cycle // 2 if cycle > 0 else int(work_days or 0)
        return anchor + timedelta(days=half)
    return anchor


def _smu_formula_state_222(anchor: date, shift_number: int, target: date) -> str:
    pos = _smu_cycle_position_222(anchor, shift_number, target)
    if pos < 2:
        return "day"
    if pos >= 4:
        return "night"
    return "off"


def _smu_is_working_state(state: str | None) -> bool:
    if not state:
        return False
    return state in ("day", "night", "extra_day", "extra_night", "work", "extra")


def _smu_effective_work_day(
    *,
    work_days: int,
    off_days: int,
    anchor: date,
    shift_number: int,
    target: date,
    override_state: str | None,
    period: str | None = None,
) -> bool:
    del period
    if override_state == "off":
        return False
    if _smu_is_working_state(override_state):
        return True
    cycle = int(work_days or 0) + int(off_days or 0)
    if cycle <= 0:
        return False
    return _smu_formula_state_222(anchor, shift_number, target) != "off"


async def list_smu_pattern_overrides(
    pattern_id: str,
    *,
    from_date: date | None = None,
    to_date: date | None = None,
) -> list[dict[str, Any]]:
    sql = """
        SELECT id, smu_pattern_id, shift_date, shift_number, period, state, note, created_at, updated_at
        FROM app.smu_pattern_day_overrides
        WHERE smu_pattern_id = $1::uuid
          AND ($2::date IS NULL OR shift_date >= $2)
          AND ($3::date IS NULL OR shift_date <= $3)
        ORDER BY shift_date, shift_number, period
    """
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            sql,
            uuid.UUID(pattern_id),
            from_date,
            to_date,
        )
    return [serialize_record(row) for row in rows]


async def set_smu_pattern_override(
    pattern_id: str,
    *,
    shift_date: date,
    shift_number: int,
    period: str = "day",
    state: str | None,
    note: str | None = None,
) -> dict[str, Any] | None:
    if shift_number not in (1, 2, 3, 4):
        raise ValueError("Номер смены должен быть от 1 до 4")
    del period
    allowed = ("day", "night", "extra_day", "extra_night", "off")
    async with get_pool().acquire() as conn:
        if state is None or state == "auto":
            row = await conn.fetchrow(
                """
                DELETE FROM app.smu_pattern_day_overrides
                WHERE smu_pattern_id = $1::uuid
                  AND shift_date = $2
                  AND shift_number = $3
                RETURNING id, smu_pattern_id, shift_date, shift_number, period, state, note, created_at, updated_at
                """,
                uuid.UUID(pattern_id),
                shift_date,
                shift_number,
            )
            return serialize_record(row) if row else None
        if state not in allowed:
            raise ValueError("state должен быть day, night, extra_day, extra_night, off или auto")
        row = await conn.fetchrow(
            """
            INSERT INTO app.smu_pattern_day_overrides
                (smu_pattern_id, shift_date, shift_number, period, state, note)
            VALUES ($1::uuid, $2, $3, 'day', $4, $5)
            ON CONFLICT (smu_pattern_id, shift_date, shift_number) DO UPDATE SET
                state = EXCLUDED.state,
                period = 'day',
                note = COALESCE(EXCLUDED.note, app.smu_pattern_day_overrides.note),
                updated_at = now()
            RETURNING id, smu_pattern_id, shift_date, shift_number, period, state, note, created_at, updated_at
            """,
            uuid.UUID(pattern_id),
            shift_date,
            shift_number,
            state,
            note,
        )
    return serialize_record(row)


async def clear_smu_pattern_overrides(
    pattern_id: str,
    *,
    from_date: date | None = None,
    to_date: date | None = None,
) -> int:
    sql = """
        DELETE FROM app.smu_pattern_day_overrides
        WHERE smu_pattern_id = $1::uuid
          AND ($2::date IS NULL OR shift_date >= $2)
          AND ($3::date IS NULL OR shift_date <= $3)
    """
    async with get_pool().acquire() as conn:
        result = await conn.execute(sql, uuid.UUID(pattern_id), from_date, to_date)
    try:
        return int(str(result).split()[-1])
    except (ValueError, IndexError):
        return 0


async def apply_smu_pattern_preset(
    pattern_id: str,
    *,
    preset: str,
    anchor_date: date | None = None,
    clear_overrides: bool = True,
) -> dict[str, Any]:
    presets = {
        "2-2": (2, 2),
        "3-3": (3, 3),
    }
    if preset not in presets:
        raise ValueError(f"Неизвестный пресет: {preset}")
    work_days, off_days = presets[preset]
    pattern = await update_smu_pattern(
        pattern_id,
        work_days=work_days,
        off_days=off_days,
        anchor_date=anchor_date,
    )
    if clear_overrides:
        await clear_smu_pattern_overrides(pattern_id)
    return pattern


async def is_user_working_on_date(user_id: str, target: date) -> bool:
    async with get_pool().acquire() as conn:
        extra = await conn.fetchval(
            "SELECT 1 FROM app.smu_extra_shifts WHERE user_id = $1::uuid AND shift_date = $2",
            uuid.UUID(user_id),
            target,
        )
        if extra:
            return True
        row = await conn.fetchrow(
            """
            SELECT sp.work_days, sp.off_days, sp.anchor_date, us.shift_number,
                   ov.state AS override_state
            FROM app.user_smu us
            JOIN app.smu_patterns sp ON sp.id = us.smu_pattern_id
            LEFT JOIN app.smu_pattern_day_overrides ov
                ON ov.smu_pattern_id = us.smu_pattern_id
               AND ov.shift_date = $2
               AND ov.shift_number = us.shift_number
            WHERE us.user_id = $1::uuid AND sp.status = 'active'
            """,
            uuid.UUID(user_id),
            target,
        )
    if not row:
        return True
    anchor = row["anchor_date"]
    if isinstance(anchor, datetime):
        anchor = anchor.date()
    shift_number = int(row["shift_number"] or 1)
    return _smu_effective_work_day(
        work_days=int(row["work_days"] or 0),
        off_days=int(row["off_days"] or 0),
        anchor=anchor,
        shift_number=shift_number,
        target=target,
        override_state=row["override_state"],
    )


async def get_user_track_progress(user_id: str, track_id: str) -> dict[str, Any]:
    sql = """
        SELECT t.practice_required, t.lecture_required,
               count(am.id) FILTER (
                   WHERE am.status IN ('present', 'late') AND l.lesson_type = 'practice'
               ) AS practice_done,
               count(am.id) FILTER (
                   WHERE am.status IN ('present', 'late') AND l.lesson_type = 'lecture'
               ) AS lecture_done,
               count(DISTINCT lm.lesson_id) FILTER (
                   WHERE l.starts_at > now() AND lm.user_id = $1::uuid
               ) AS upcoming_count,
               count(DISTINCT lm.lesson_id) FILTER (
                   WHERE l.starts_at > now() AND lm.user_id = $1::uuid AND l.lesson_type = 'practice'
               ) AS upcoming_practice,
               count(DISTINCT lm.lesson_id) FILTER (
                   WHERE l.starts_at > now() AND lm.user_id = $1::uuid AND l.lesson_type = 'lecture'
               ) AS upcoming_lecture
        FROM app.tracks t
        JOIN app.user_tracks ut ON ut.track_id = t.id AND ut.user_id = $1::uuid
        LEFT JOIN app.lessons l ON l.track_id = t.id
        LEFT JOIN app.lesson_members lm ON lm.lesson_id = l.id AND lm.user_id = $1::uuid
        LEFT JOIN app.attendance_marks am ON am.lesson_id = l.id AND am.user_id = $1::uuid
        WHERE t.id = $2::uuid
        GROUP BY t.practice_required, t.lecture_required
    """
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(sql, uuid.UUID(user_id), uuid.UUID(track_id))
    if not row:
        return {
            "practice_done": 0,
            "lecture_done": 0,
            "practice_required": 0,
            "lecture_required": 0,
            "upcoming_count": 0,
            "upcoming_practice": 0,
            "upcoming_lecture": 0,
        }
    upcoming_count = int(row["upcoming_count"] or 0)
    upcoming_practice = int(row["upcoming_practice"] or 0)
    upcoming_lecture = int(row["upcoming_lecture"] or 0)
    return {
        "practice_done": int(row["practice_done"] or 0),
        "lecture_done": int(row["lecture_done"] or 0),
        "practice_required": int(row["practice_required"] or 0),
        "lecture_required": int(row["lecture_required"] or 0),
        "upcoming_count": upcoming_count,
        "upcoming_practice": upcoming_practice,
        "upcoming_lecture": upcoming_lecture,
    }


def _formation_remaining(progress: dict[str, Any], lesson_type: str) -> int:
    if lesson_type == "practice":
        return (
            progress["practice_required"]
            - progress["practice_done"]
            - progress.get("upcoming_practice", progress.get("upcoming_count", 0))
        )
    return (
        progress["lecture_required"]
        - progress["lecture_done"]
        - progress.get("upcoming_lecture", 0)
    )


async def list_track_assignments(track_id: str) -> list[dict[str, Any]]:
    sql = """
        SELECT ut.user_id, ut.track_id, ut.status, ut.started_at, ut.completed_at, ut.due_date,
               p.last_name, p.first_name, p.phone,
               fw.weight, fw.assigned_count, fw.last_assigned_at, fw.lock_until,
               sp.name AS smu_name, sp.code AS smu_code
        FROM app.user_tracks ut
        JOIN app.profiles p ON p.user_id = ut.user_id
        LEFT JOIN app.track_formation_weights fw
            ON fw.user_id = ut.user_id AND fw.track_id = ut.track_id
        LEFT JOIN app.user_smu us ON us.user_id = ut.user_id
        LEFT JOIN app.smu_patterns sp ON sp.id = us.smu_pattern_id
        WHERE ut.track_id = $1::uuid
        ORDER BY p.last_name, p.first_name
    """
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(sql, uuid.UUID(track_id))
    result = []
    for row in rows:
        item = serialize_record(row)
        progress = await get_user_track_progress(str(row["user_id"]), track_id)
        item.update(progress)
        result.append(item)
    return result


async def update_track(
    track_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
    practice_required: int | None = None,
    lecture_required: int | None = None,
    completion_days: int | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    fields: list[str] = []
    values: list[Any] = []
    idx = 2
    if name is not None:
        fields.append(f"name = ${idx}")
        values.append(name)
        idx += 1
    if description is not None:
        fields.append(f"description = ${idx}")
        values.append(description)
        idx += 1
    if practice_required is not None:
        fields.append(f"practice_required = ${idx}")
        values.append(practice_required)
        idx += 1
    if lecture_required is not None:
        fields.append(f"lecture_required = ${idx}")
        values.append(lecture_required)
        idx += 1
    if completion_days is not None:
        fields.append(f"completion_days = ${idx}")
        values.append(completion_days)
        idx += 1
    if status is not None:
        fields.append(f"status = ${idx}")
        values.append(status)
        idx += 1
    if not fields:
        async with get_pool().acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM app.tracks WHERE id = $1::uuid",
                uuid.UUID(track_id),
            )
        return serialize_record(row)
    fields.append("updated_at = now()")
    sql = f"""
        UPDATE app.tracks SET {", ".join(fields)}
        WHERE id = $1::uuid
        RETURNING id, code, name, description, practice_required, lecture_required,
                  completion_days, id_hr, status, created_at, updated_at
    """
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(sql, uuid.UUID(track_id), *values)
    if not row:
        raise ValueError("Трек не найден")
    return serialize_record(row)


async def delete_track(track_id: str) -> dict[str, Any]:
    tid = uuid.UUID(track_id)
    async with get_pool().acquire() as conn:
        track = await conn.fetchrow(
            """
            SELECT id, code, name
            FROM app.tracks
            WHERE id = $1::uuid
            """,
            tid,
        )
        if not track:
            raise ValueError("Трек не найден")
        employee_count = await conn.fetchval(
            """
            SELECT COUNT(*)::int
            FROM app.user_tracks
            WHERE track_id = $1::uuid
            """,
            tid,
        )
        instructor_count = await conn.fetchval(
            """
            SELECT COUNT(*)::int
            FROM app.track_teachers
            WHERE track_id = $1::uuid
            """,
            tid,
        )
        await conn.execute(
            """
            DELETE FROM app.tracks
            WHERE id = $1::uuid
            """,
            tid,
        )
    payload = serialize_record(track)
    payload["employee_count"] = int(employee_count or 0)
    payload["instructor_count"] = int(instructor_count or 0)
    return payload


async def recalculate_track_weights(track_id: str, *, force: bool = False) -> list[dict[str, Any]]:
    today = date.today()
    async with get_pool().acquire() as conn:
        track = await conn.fetchrow(
            "SELECT practice_required, lecture_required FROM app.tracks WHERE id = $1::uuid",
            uuid.UUID(track_id),
        )
        if not track:
            raise ValueError("Трек не найден")
        members = await conn.fetch(
            """
            SELECT ut.user_id
            FROM app.user_tracks ut
            JOIN app.profiles p ON p.user_id = ut.user_id
            JOIN app.roles r ON r.id = p.role_id
            WHERE ut.track_id = $1::uuid AND ut.status = 'active' AND r.code = 'employee'
            """,
            uuid.UUID(track_id),
        )
        updated = []
        for member in members:
            user_id = str(member["user_id"])
            existing = await conn.fetchrow(
                """
                SELECT weight, lock_until FROM app.track_formation_weights
                WHERE user_id = $1::uuid AND track_id = $2::uuid
                """,
                member["user_id"],
                uuid.UUID(track_id),
            )
            if (
                not force
                and existing
                and existing["lock_until"]
                and existing["lock_until"] > today
            ):
                continue
            progress = await get_user_track_progress(user_id, track_id)
            practice_remaining = max(
                0,
                progress["practice_required"] - progress["practice_done"] - progress["upcoming_count"],
            )
            lecture_remaining = max(
                0,
                progress["lecture_required"] - progress["lecture_done"],
            )
            remaining = practice_remaining + lecture_remaining
            if remaining <= 0:
                weight = 0.0
            else:
                assigned_penalty = float(existing["weight"] if existing else 0) * 0.1
                weight = float(remaining * 100) - assigned_penalty
            row = await conn.fetchrow(
                """
                INSERT INTO app.track_formation_weights (user_id, track_id, weight, updated_at)
                VALUES ($1::uuid, $2::uuid, $3, now())
                ON CONFLICT (user_id, track_id) DO UPDATE SET
                    weight = EXCLUDED.weight,
                    updated_at = now()
                RETURNING user_id, track_id, weight, assigned_count, last_assigned_at, lock_until, updated_at
                """,
                member["user_id"],
                uuid.UUID(track_id),
                weight,
            )
            updated.append(serialize_record(row))
    return updated


async def select_formation_members(
    *,
    track_id: str,
    lesson_date: date,
    lesson_type: str,
    max_members: int | None = None,
    apply_weights: bool = True,
    lock_days: int | None = None,
    weight_penalty: float | None = None,
    exclude_user_ids: set[str] | None = None,
) -> list[str]:
    track = await get_track(track_id)
    if not track:
        raise ValueError("Трек не найден")
    settings = formation_settings_from_track(track)
    effective_max = max_members if max_members is not None else settings["max_members"]
    effective_lock = lock_days if lock_days is not None else settings["lock_days"]
    effective_penalty = weight_penalty if weight_penalty is not None else settings["weight_penalty"]
    preview = await preview_formation_members(
        track_id=track_id,
        lesson_date=lesson_date,
        lesson_type=lesson_type,
        max_members=effective_max,
        exclude_user_ids=exclude_user_ids,
    )
    selected = [item["user_id"] for item in preview["selected"]]
    if apply_weights and selected:
        lock_until = lesson_date + timedelta(days=effective_lock)
        async with get_pool().acquire() as conn:
            for user_id in selected:
                await conn.execute(
                    """
                    INSERT INTO app.track_formation_weights (user_id, track_id, weight, assigned_count, last_assigned_at, lock_until, updated_at)
                    VALUES ($1::uuid, $2::uuid, 0, 1, now(), $3, now())
                    ON CONFLICT (user_id, track_id) DO UPDATE SET
                        assigned_count = app.track_formation_weights.assigned_count + 1,
                        last_assigned_at = now(),
                        lock_until = GREATEST(app.track_formation_weights.lock_until, EXCLUDED.lock_until),
                        weight = GREATEST(app.track_formation_weights.weight - $4, 0),
                        updated_at = now()
                    """,
                    uuid.UUID(user_id),
                    uuid.UUID(track_id),
                    lock_until,
                    effective_penalty,
                )
    return selected


async def preview_formation_members(
    *,
    track_id: str,
    lesson_date: date,
    lesson_type: str,
    max_members: int | None = None,
    exclude_user_ids: set[str] | None = None,
) -> dict[str, Any]:
    track = await get_track(track_id)
    if not track:
        raise ValueError("Трек не найден")
    settings = formation_settings_from_track(track)
    effective_max = max_members if max_members is not None else settings["max_members"]
    track_name = track["name"]
    await recalculate_track_weights(track_id)
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT ut.user_id, COALESCE(fw.weight, 0) AS weight, fw.lock_until, ut.due_date,
                   p.last_name, p.first_name
            FROM app.user_tracks ut
            JOIN app.profiles p ON p.user_id = ut.user_id
            JOIN app.roles r ON r.id = p.role_id
            LEFT JOIN app.track_formation_weights fw
                ON fw.user_id = ut.user_id AND fw.track_id = ut.track_id
            WHERE ut.track_id = $1::uuid
              AND ut.status = 'active'
              AND r.code = 'employee'
            ORDER BY ut.due_date NULLS LAST, fw.weight DESC NULLS LAST, p.last_name, p.first_name
            """,
            uuid.UUID(track_id),
        )
        tz = ZoneInfo("Europe/Moscow")
        day_start = datetime.combine(lesson_date, time.min, tzinfo=tz).astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
        day_end = day_start + timedelta(days=1)
        scheduled_rows = await conn.fetch(
            """
            SELECT DISTINCT lm.user_id
            FROM app.lesson_members lm
            JOIN app.lessons l ON l.id = lm.lesson_id
            WHERE l.track_id = $1::uuid
              AND l.starts_at >= $2
              AND l.starts_at < $3
            """,
            uuid.UUID(track_id),
            day_start,
            day_end,
        )
    scheduled_today = {str(r["user_id"]) for r in scheduled_rows}

    candidates: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for row in rows:
        user_id = str(row["user_id"])
        name = f"{row['last_name']} {row['first_name']}".strip()
        due = row["due_date"]
        if isinstance(due, datetime):
            due = due.date()
        lock_until = row["lock_until"]
        if isinstance(lock_until, datetime):
            lock_until = lock_until.date()

        if due and due < lesson_date:
            excluded.append({"user_id": user_id, "name": name, "reason": "просрочен срок программы"})
            continue
        if lock_until and lock_until > lesson_date:
            excluded.append({"user_id": user_id, "name": name, "reason": "недавно назначен (lock)"})
            continue

        progress = await get_user_track_progress(user_id, track_id)
        if lesson_type == "practice":
            remaining = progress["practice_required"] - progress["practice_done"] - progress["upcoming_count"]
        else:
            remaining = progress["lecture_required"] - progress["lecture_done"]
        if remaining <= 0:
            excluded.append({"user_id": user_id, "name": name, "reason": "программа завершена"})
            continue
        if not await is_user_working_on_date(user_id, lesson_date):
            excluded.append({"user_id": user_id, "name": name, "reason": "выходной по СМУ"})
            continue
        if user_id in scheduled_today:
            excluded.append({"user_id": user_id, "name": name, "reason": "уже записан на этот день"})
            continue
        if exclude_user_ids and user_id in exclude_user_ids:
            excluded.append({"user_id": user_id, "name": name, "reason": "уже назначен в этом пакете"})
            continue

        urgency = (due - lesson_date).days if due else 9999
        candidates.append({
            "user_id": user_id,
            "name": name,
            "weight": float(row["weight"] or 0),
            "urgency": urgency,
            "due_date": due.isoformat() if due else None,
            "remaining": remaining,
        })

    candidates.sort(key=lambda item: (item["urgency"], -item["weight"], item["name"]))
    selected = candidates[:effective_max]
    reserve = candidates[effective_max:]
    instructor_ids = await list_track_instructors(track_id)
    instructor_names = await list_track_instructor_names(track_id)
    teacher_id = instructor_ids[0] if instructor_ids else None
    teacher_name = ", ".join(instructor_names) if instructor_names else None
    return {
        "track_id": track_id,
        "track_name": track_name,
        "lesson_date": lesson_date.isoformat(),
        "lesson_type": lesson_type,
        "teacher_id": teacher_id,
        "teacher_ids": instructor_ids,
        "teacher_name": teacher_name,
        "instructor_count": len(instructor_ids),
        "selected": selected,
        "reserve": reserve,
        "excluded": excluded,
        "total_candidates": len(candidates),
        "reserve_count": len(reserve),
        "max_members": effective_max,
        "min_members": settings["min_members"],
        "settings": settings,
    }


def _parse_slot_time(value: Any) -> time:
    if isinstance(value, time):
        return value
    text = str(value)
    parts = text.split(":")
    return time(int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)


def slot_starts_at(lesson_date: date, slot: dict[str, Any]) -> datetime:
    tz = ZoneInfo(slot.get("timezone") or "Europe/Moscow")
    local_time = _parse_slot_time(slot.get("starts_at_local"))
    local_dt = datetime.combine(lesson_date, local_time, tzinfo=tz)
    return local_dt.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)


async def lesson_exists_for_slot(*, track_id: str, slot_id: str, lesson_date: date, slot: dict[str, Any] | None = None) -> bool:
    if slot is None:
        async with get_pool().acquire() as conn:
            slot_row = await conn.fetchrow(
                "SELECT starts_at_local, duration_min, timezone FROM app.conveyor_slots WHERE id = $1::uuid",
                uuid.UUID(slot_id),
            )
        if not slot_row:
            return False
        slot = serialize_record(slot_row)
    starts_at = slot_starts_at(lesson_date, slot)
    ends_at = starts_at + timedelta(minutes=int(slot.get("duration_min") or 60))
    async with get_pool().acquire() as conn:
        found = await conn.fetchval(
            """
            SELECT 1 FROM app.lessons
            WHERE track_id = $1::uuid
              AND slot_id = $2::uuid
              AND starts_at >= $3
              AND starts_at < $4
            LIMIT 1
            """,
            uuid.UUID(track_id),
            uuid.UUID(slot_id),
            starts_at,
            ends_at,
        )
    return bool(found)


async def _lesson_day_bounds(lesson_date: date) -> tuple[datetime, datetime]:
    tz = ZoneInfo("Europe/Moscow")
    day_start = datetime.combine(lesson_date, time.min, tzinfo=tz).astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
    day_end = day_start + timedelta(days=1)
    return day_start, day_end


async def list_track_instructors(track_id: str) -> list[str]:
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT tt.teacher_id
            FROM app.track_teachers tt
            JOIN app.profiles p ON p.user_id = tt.teacher_id
            JOIN app.roles r ON r.id = p.role_id
            WHERE tt.track_id = $1::uuid
              AND p.status = 'active'
              AND r.code = 'teacher'
            ORDER BY tt.created_at, tt.teacher_id
            """,
            uuid.UUID(track_id),
        )
    return [str(row["teacher_id"]) for row in rows]


async def list_track_instructor_names(track_id: str) -> list[str]:
    names: list[str] = []
    for teacher_id in await list_track_instructors(track_id):
        profile = await get_user_profile(teacher_id)
        if not profile:
            continue
        name = f"{profile.get('last_name', '')} {profile.get('first_name', '')}".strip()
        if name:
            names.append(name)
    return names


async def get_scheduled_member_ids_on_track_date(*, track_id: str, lesson_date: date) -> set[str]:
    day_start, day_end = await _lesson_day_bounds(lesson_date)
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT lm.user_id
            FROM app.lesson_members lm
            JOIN app.lessons l ON l.id = lm.lesson_id
            JOIN app.profiles p ON p.user_id = lm.user_id
            JOIN app.roles r ON r.id = p.role_id
            WHERE l.track_id = $1::uuid
              AND l.starts_at >= $2
              AND l.starts_at < $3
              AND r.code = 'employee'
            """,
            uuid.UUID(track_id),
            day_start,
            day_end,
        )
    return {str(row["user_id"]) for row in rows}


async def get_busy_teacher_ids_on_track_slot(
    *,
    track_id: str,
    slot_id: str,
    lesson_date: date,
) -> set[str]:
    slot_row = None
    async with get_pool().acquire() as conn:
        slot_row = await conn.fetchrow(
            "SELECT id, starts_at_local, duration_min FROM app.conveyor_slots WHERE id = $1::uuid",
            uuid.UUID(slot_id),
        )
    if not slot_row:
        return set()
    slot = serialize_record(slot_row)
    starts_at = slot_starts_at(lesson_date, slot)
    ends_at = starts_at + timedelta(minutes=int(slot.get("duration_min") or 60))
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT l.teacher_id
            FROM app.lessons l
            WHERE l.track_id = $1::uuid
              AND l.slot_id = $2::uuid
              AND l.starts_at >= $3
              AND l.starts_at < $4
              AND l.teacher_id IS NOT NULL
            """,
            uuid.UUID(track_id),
            uuid.UUID(slot_id),
            starts_at,
            ends_at,
        )
    return {str(row["teacher_id"]) for row in rows}


async def lesson_exists_for_track_on_date(*, track_id: str, lesson_date: date) -> bool:
    day_start, day_end = await _lesson_day_bounds(lesson_date)
    async with get_pool().acquire() as conn:
        found = await conn.fetchval(
            """
            SELECT 1 FROM app.lessons
            WHERE track_id = $1::uuid
              AND starts_at >= $2
              AND starts_at < $3
            LIMIT 1
            """,
            uuid.UUID(track_id),
            day_start,
            day_end,
        )
    return bool(found)


async def resolve_track_instructor(
    track_id: str,
    *,
    lesson_date: date | None = None,
    slot_id: str | None = None,
    exclude_teacher_ids: set[str] | None = None,
) -> str | None:
    instructors = await list_track_instructors(track_id)
    if not instructors:
        return None

    excluded = exclude_teacher_ids or set()
    candidates = [teacher_id for teacher_id in instructors if teacher_id not in excluded]
    if not candidates:
        return None

    if lesson_date and slot_id:
        busy = await get_busy_teacher_ids_on_track_slot(
            track_id=track_id,
            slot_id=slot_id,
            lesson_date=lesson_date,
        )
        candidates = [teacher_id for teacher_id in candidates if teacher_id not in busy]
        if not candidates:
            return None

    if not lesson_date:
        return candidates[0]

    day_start, day_end = await _lesson_day_bounds(lesson_date)
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT l.teacher_id, COUNT(*)::int AS lesson_count
            FROM app.lessons l
            WHERE l.track_id = $1::uuid
              AND l.teacher_id = ANY($2::uuid[])
              AND l.starts_at >= $3
              AND l.starts_at < $4
            GROUP BY l.teacher_id
            """,
            uuid.UUID(track_id),
            [uuid.UUID(teacher_id) for teacher_id in candidates],
            day_start,
            day_end,
        )
    counts = {str(row["teacher_id"]): int(row["lesson_count"]) for row in rows}
    return min(candidates, key=lambda teacher_id: (counts.get(teacher_id, 0), teacher_id))


async def _log_auto_formation(
    *,
    track_id: str,
    slot_id: str | None,
    lesson_date: date,
    status: str,
    lesson_id: str | None = None,
    detail: str | None = None,
) -> None:
    async with get_pool().acquire() as conn:
        await conn.execute(
            """
            INSERT INTO app.formation_auto_log (track_id, slot_id, lesson_id, lesson_date, status, detail)
            VALUES ($1::uuid, $2::uuid, $3::uuid, $4, $5, $6)
            """,
            uuid.UUID(track_id),
            uuid.UUID(slot_id) if slot_id else None,
            uuid.UUID(lesson_id) if lesson_id else None,
            lesson_date,
            status,
            detail,
        )


async def _formation_slots_for_track(track_id: str, all_slots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not all_slots:
        return []
    slot_ids = await list_track_formation_slot_ids(track_id)
    if slot_ids:
        allowed = set(slot_ids)
        candidates = [slot for slot in all_slots if str(slot["id"]) in allowed]
    else:
        candidates = list(all_slots)
    if not candidates:
        return []
    candidates.sort(key=lambda s: int(s.get("sort_order") or 0))
    return [candidates[0]]


async def _formation_plan_item_status(
    *,
    track: dict[str, Any],
    slot: dict[str, Any],
    lesson_day: date,
    lesson_type: str,
    include_disabled: bool,
) -> dict[str, Any]:
    track_id = str(track["id"])
    slot_id = str(slot["id"])
    settings = formation_settings_from_track(track)
    lt = lesson_type or settings["lesson_type"]
    instructor_ids = await list_track_instructors(track_id)
    instructor_names = await list_track_instructor_names(track_id)
    scheduled_members = await get_scheduled_member_ids_on_track_date(
        track_id=track_id,
        lesson_date=lesson_day,
    )
    busy_teachers = await get_busy_teacher_ids_on_track_slot(
        track_id=track_id,
        slot_id=slot_id,
        lesson_date=lesson_day,
    )
    free_instructors = [teacher_id for teacher_id in instructor_ids if teacher_id not in busy_teachers]
    teacher_id = await resolve_track_instructor(
        track_id,
        lesson_date=lesson_day,
        slot_id=slot_id,
    )

    item: dict[str, Any] = {
        "track_id": track_id,
        "track_name": track.get("name"),
        "slot_id": slot_id,
        "slot_name": slot.get("name"),
        "slot_starts_at": str(slot.get("starts_at_local") or "")[:5],
        "lesson_date": lesson_day.isoformat(),
        "lesson_type": lt,
        "teacher_id": teacher_id,
        "teacher_ids": instructor_ids,
        "teacher_name": ", ".join(instructor_names) if instructor_names else None,
        "instructor_count": len(instructor_ids),
        "free_instructor_count": len(free_instructors),
        "scheduled_member_count": len(scheduled_members),
        "status": "ready",
        "reason": None,
        "selected_count": 0,
        "selected": [],
        "excluded": [],
        "max_members": settings["max_members"],
        "min_members": settings["min_members"],
        "auto_enabled": settings["auto_enabled"],
        "default_place": settings["default_place"],
    }

    if not settings["auto_enabled"] and not include_disabled:
        item["status"] = "disabled"
        item["reason"] = "auto_disabled"
        return item
    if not instructor_ids:
        item["status"] = "blocked"
        item["reason"] = "no_instructor"
        return item
    if not free_instructors:
        item["status"] = "scheduled"
        item["reason"] = "all_instructors_busy" if scheduled_members else "already_scheduled_today"
        return item

    preview = await preview_formation_members(
        track_id=track_id,
        lesson_date=lesson_day,
        lesson_type=lt,
        max_members=settings["max_members"],
        exclude_user_ids=scheduled_members,
    )
    item["selected"] = preview["selected"]
    item["reserve"] = preview.get("reserve") or []
    item["excluded"] = preview["excluded"]
    item["selected_count"] = len(preview["selected"])
    item["reserve_count"] = len(item["reserve"])
    item["teacher_id"] = teacher_id or preview.get("teacher_id")
    item["teacher_name"] = preview.get("teacher_name") or item["teacher_name"]

    if item["selected_count"] == 0:
        item["status"] = "scheduled" if scheduled_members else "blocked"
        item["reason"] = "groups_formed" if scheduled_members else "no_members"
    elif item["selected_count"] < settings["min_members"]:
        item["status"] = "blocked"
        item["reason"] = "below_min_members"
    return item


async def preview_formation_plan(
    *,
    target_date: date,
    lesson_type: str | None = None,
    include_disabled: bool = False,
    track_ids: list[str] | None = None,
) -> dict[str, Any]:
    tracks = [t for t in await list_tracks() if t.get("status") == "active"]
    if track_ids:
        allowed = set(track_ids)
        tracks = [t for t in tracks if str(t["id"]) in allowed]
    all_slots = await list_conveyor_slots(active_only=True)
    items: list[dict[str, Any]] = []
    for track in tracks:
        settings = formation_settings_from_track(track)
        if not settings["auto_enabled"] and not include_disabled:
            continue
        slots = await _formation_slots_for_track(str(track["id"]), all_slots)
        if not slots:
            continue
        lt = lesson_type or settings["lesson_type"]
        items.append(
            await _formation_plan_item_status(
                track=track,
                slot=slots[0],
                lesson_day=target_date,
                lesson_type=lt,
                include_disabled=include_disabled,
            )
        )
    ready = sum(1 for i in items if i["status"] == "ready")
    return {
        "target_date": target_date.isoformat(),
        "items": items,
        "summary": {
            "total": len(items),
            "ready": ready,
            "scheduled": sum(1 for i in items if i["status"] == "scheduled"),
            "blocked": sum(1 for i in items if i["status"] == "blocked"),
            "disabled": sum(1 for i in items if i["status"] == "disabled"),
        },
    }


def _parse_month_bounds(month: str) -> tuple[date, date]:
    parts = month.split("-")
    if len(parts) != 2:
        raise ValueError("month должен быть в формате YYYY-MM")
    year = int(parts[0])
    month_num = int(parts[1])
    if month_num < 1 or month_num > 12:
        raise ValueError("Некорректный месяц")
    from_date = date(year, month_num, 1)
    if month_num == 12:
        to_date = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        to_date = date(year, month_num + 1, 1) - timedelta(days=1)
    return from_date, to_date


async def preview_formation_plan_month(
    *,
    month: str,
    lesson_type: str | None = None,
    include_disabled: bool = False,
    track_ids: list[str] | None = None,
) -> dict[str, Any]:
    from_date, to_date = _parse_month_bounds(month)
    days: list[dict[str, Any]] = []
    summary = {"total": 0, "ready": 0, "scheduled": 0, "blocked": 0, "disabled": 0}
    day = from_date
    while day <= to_date:
        plan = await preview_formation_plan(
            target_date=day,
            lesson_type=lesson_type,
            include_disabled=include_disabled,
            track_ids=track_ids,
        )
        day_summary = plan["summary"]
        days.append({"date": day.isoformat(), "summary": day_summary})
        for key in summary:
            summary[key] += int(day_summary.get(key) or 0)
        day += timedelta(days=1)
    return {
        "month": month,
        "from_date": from_date.isoformat(),
        "to_date": to_date.isoformat(),
        "days": days,
        "summary": summary,
    }


async def create_formation_plan_lessons(
    *,
    target_date: date,
    items: list[dict[str, str]] | None = None,
    lesson_type: str | None = None,
    reserved_user_ids: set[str] | None = None,
) -> dict[str, Any]:
    plan = await preview_formation_plan(
        target_date=target_date,
        lesson_type=lesson_type,
        include_disabled=True,
    )
    plan_items = plan["items"]
    if items:
        keys = {(i["track_id"], i["slot_id"]) for i in items if i.get("track_id") and i.get("slot_id")}
        plan_items = [p for p in plan_items if (p["track_id"], p["slot_id"]) in keys]

    created: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    all_slots = {str(s["id"]): s for s in await list_conveyor_slots(active_only=True)}
    reserved = reserved_user_ids if reserved_user_ids is not None else set()

    for entry in plan_items:
        if entry["status"] != "ready":
            skipped.append({
                "track_id": entry["track_id"],
                "track_name": entry["track_name"],
                "slot_id": entry["slot_id"],
                "slot_name": entry["slot_name"],
                "lesson_date": target_date.isoformat(),
                "reason": entry["reason"] or entry["status"],
            })
            continue
        track_id = entry["track_id"]
        slot_id = entry["slot_id"]
        slot = all_slots.get(slot_id)
        if not slot:
            skipped.append({"track_id": track_id, "slot_id": slot_id, "reason": "slot_not_found"})
            continue

        used_teachers: set[str] = set()
        groups_created = 0
        while True:
            teacher_id = await resolve_track_instructor(
                track_id,
                lesson_date=target_date,
                slot_id=slot_id,
                exclude_teacher_ids=used_teachers,
            )
            if not teacher_id:
                break

            scheduled_today = await get_scheduled_member_ids_on_track_date(
                track_id=track_id,
                lesson_date=target_date,
            )
            member_ids = await select_formation_members(
                track_id=track_id,
                lesson_date=target_date,
                lesson_type=entry["lesson_type"],
                max_members=entry["max_members"],
                exclude_user_ids=reserved | scheduled_today,
            )
            if len(member_ids) < entry["min_members"]:
                break

            starts_at = slot_starts_at(target_date, slot)
            duration = int(slot.get("duration_min") or 60)
            ends_at = starts_at + timedelta(minutes=duration)
            track = await get_track(track_id)
            place = (track or {}).get("formation_default_place")
            lesson = await create_lesson(
                track_id=track_id,
                slot_id=slot_id,
                teacher_id=str(teacher_id),
                starts_at=starts_at,
                ends_at=ends_at,
                place=place,
                lesson_type=entry["lesson_type"],
                member_ids=member_ids,
                title=f"{entry.get('track_name')} · {slot.get('name')}",
            )
            payload = {
                "lesson_id": lesson.get("id"),
                "track_id": track_id,
                "track_name": entry.get("track_name"),
                "slot_id": slot_id,
                "slot_name": slot.get("name"),
                "lesson_date": target_date.isoformat(),
                "starts_at": lesson.get("starts_at"),
                "members": len(member_ids),
                "teacher_id": teacher_id,
                "group_number": groups_created + 1,
            }
            created.append(payload)
            reserved.update(member_ids)
            used_teachers.add(str(teacher_id))
            groups_created += 1
            await _log_auto_formation(
                track_id=track_id,
                slot_id=slot_id,
                lesson_date=target_date,
                status="created",
                lesson_id=str(lesson.get("id")),
                detail=f"members={len(member_ids)} teacher={teacher_id}",
            )

        if groups_created == 0:
            scheduled_today = await get_scheduled_member_ids_on_track_date(
                track_id=track_id,
                lesson_date=target_date,
            )
            busy_teachers = await get_busy_teacher_ids_on_track_slot(
                track_id=track_id,
                slot_id=slot_id,
                lesson_date=target_date,
            )
            instructors = await list_track_instructors(track_id)
            free_instructors = [tid for tid in instructors if tid not in busy_teachers]
            if not instructors:
                reason = "no_instructor"
            elif not free_instructors:
                reason = "all_instructors_busy" if scheduled_today else "already_scheduled_today"
            elif scheduled_today:
                reason = "groups_formed"
            else:
                preview = await preview_formation_members(
                    track_id=track_id,
                    lesson_date=target_date,
                    lesson_type=entry["lesson_type"],
                    max_members=entry["max_members"],
                )
                reason = "below_min_members" if preview["selected"] else "no_members"
            skipped.append({
                "track_id": track_id,
                "track_name": entry.get("track_name"),
                "slot_id": slot_id,
                "slot_name": entry.get("slot_name"),
                "lesson_date": target_date.isoformat(),
                "reason": reason,
            })
            if reason in {"no_members", "below_min_members"}:
                await _log_auto_formation(
                    track_id=track_id,
                    slot_id=slot_id,
                    lesson_date=target_date,
                    status="skipped",
                    detail=reason,
                )
    return {
        "target_date": target_date.isoformat(),
        "created": created,
        "skipped": skipped,
    }


async def create_formation_plan_range(
    *,
    month: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    dates: list[date] | None = None,
    items: list[dict[str, str]] | None = None,
    lesson_type: str | None = None,
) -> dict[str, Any]:
    if month:
        range_from, range_to = _parse_month_bounds(month)
    elif from_date and to_date:
        range_from, range_to = from_date, to_date
    else:
        raise ValueError("Укажите month или from_date и to_date")

    if dates:
        day_list = sorted({d for d in dates if range_from <= d <= range_to})
    else:
        day_list = []
        day = range_from
        while day <= range_to:
            day_list.append(day)
            day += timedelta(days=1)

    reserved: set[str] = set()
    all_created: list[dict[str, Any]] = []
    all_skipped: list[dict[str, Any]] = []
    for day in day_list:
        day_items: list[dict[str, str]] | None = None
        if items:
            day_items = [
                {key: value for key, value in entry.items() if key != "lesson_date"}
                for entry in items
                if entry.get("lesson_date") in (None, "", day.isoformat())
                and entry.get("track_id")
                and entry.get("slot_id")
            ]
            if not day_items:
                continue
        result = await create_formation_plan_lessons(
            target_date=day,
            items=day_items if items else None,
            lesson_type=lesson_type,
            reserved_user_ids=reserved,
        )
        all_created.extend(result.get("created") or [])
        all_skipped.extend(result.get("skipped") or [])

    return {
        "month": month,
        "from_date": range_from.isoformat(),
        "to_date": range_to.isoformat(),
        "created": all_created,
        "skipped": all_skipped,
    }


async def list_formation_auto_log(
    *,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    sql = """
        SELECT l.id, l.track_id, l.slot_id, l.lesson_id, l.lesson_date, l.status, l.detail, l.created_at,
               t.name AS track_name, cs.name AS slot_name
        FROM app.formation_auto_log l
        JOIN app.tracks t ON t.id = l.track_id
        LEFT JOIN app.conveyor_slots cs ON cs.id = l.slot_id
        WHERE ($1::date IS NULL OR l.lesson_date >= $1)
          AND ($2::date IS NULL OR l.lesson_date <= $2)
        ORDER BY l.created_at DESC
        LIMIT $3
    """
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            sql,
            from_date,
            to_date,
            min(max(limit, 1), 500),
        )
    return [serialize_record(row) for row in rows]


async def run_auto_formation(
    *,
    target_date: date | None = None,
    lesson_type: str | None = None,
    max_members: int | None = None,
) -> dict[str, Any]:
    lesson_day = target_date or (date.today() + timedelta(days=1))
    return await create_formation_plan_lessons(
        target_date=lesson_day,
        items=None,
        lesson_type=lesson_type,
    )


async def resolve_group_instructor(group_id: str) -> str | None:
    async with get_pool().acquire() as conn:
        instructor_id = await conn.fetchval(
            "SELECT instructor_id FROM app.groups WHERE id = $1::uuid",
            uuid.UUID(group_id),
        )
    return str(instructor_id) if instructor_id else None


async def set_group_instructor(group_id: str, teacher_id: str | None) -> dict[str, Any]:
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE app.groups SET instructor_id = $2::uuid
            WHERE id = $1::uuid
            RETURNING id, name, instructor_id
            """,
            uuid.UUID(group_id),
            uuid.UUID(teacher_id) if teacher_id else None,
        )
    if not row:
        raise ValueError("Группа не найдена")
    return serialize_record(row)


async def create_lesson(
    *,
    group_id: str | None = None,
    teacher_id: str,
    starts_at: datetime,
    ends_at: datetime,
    place: str | None,
    lesson_type: str,
    title: str | None = None,
    member_ids: list[str] | None = None,
    track_id: str | None = None,
    slot_id: str | None = None,
    reporting_group_id: str | None = None,
    include_teacher_member: bool = True,
) -> dict[str, Any]:
    lesson_id = uuid.uuid4()
    primary_group_id = group_id or reporting_group_id
    if not track_id and not primary_group_id:
        raise ValueError("Укажите трек для занятия")
    group_uuid = uuid.UUID(primary_group_id) if primary_group_id else None
    reporting_uuid = uuid.UUID(reporting_group_id or primary_group_id) if (reporting_group_id or primary_group_id) else None
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                INSERT INTO app.lessons (
                    id, group_id, reporting_group_id, track_id, slot_id,
                    teacher_id, starts_at, ends_at, place, lesson_type, title
                )
                VALUES ($1::uuid, $2::uuid, $3::uuid, $4::uuid, $5::uuid, $6::uuid, $7, $8, $9, $10, $11)
                RETURNING id, group_id, reporting_group_id, track_id, slot_id,
                          teacher_id, starts_at, ends_at, place, lesson_type, title
                """,
                lesson_id,
                group_uuid,
                reporting_uuid,
                uuid.UUID(track_id) if track_id else None,
                uuid.UUID(slot_id) if slot_id else None,
                uuid.UUID(teacher_id),
                starts_at,
                ends_at,
                place,
                lesson_type,
                title,
            )
            if track_id:
                await conn.execute(
                    """
                    INSERT INTO app.track_teachers (track_id, teacher_id)
                    VALUES ($1::uuid, $2::uuid)
                    ON CONFLICT DO NOTHING
                    """,
                    uuid.UUID(track_id),
                    uuid.UUID(teacher_id),
                )
            ids = member_ids
            if ids is None and track_id:
                member_rows = await conn.fetch(
                    """
                    SELECT ut.user_id
                    FROM app.user_tracks ut
                    JOIN app.profiles p ON p.user_id = ut.user_id
                    JOIN app.roles r ON r.id = p.role_id
                    WHERE ut.track_id = $1::uuid
                      AND ut.status = 'active'
                      AND r.code = 'employee'
                    """,
                    uuid.UUID(track_id),
                )
                ids = [str(r["user_id"]) for r in member_rows]
            if not ids:
                raise ValueError("Нет участников для занятия")
            for member_id in ids:
                role_code = await conn.fetchval(
                    """
                    SELECT r.code FROM app.profiles p
                    JOIN app.roles r ON r.id = p.role_id
                    WHERE p.user_id = $1::uuid
                    """,
                    uuid.UUID(member_id),
                )
                await conn.execute(
                    """
                    INSERT INTO app.lesson_members (user_id, lesson_id, role_in_lesson, track_id)
                    VALUES ($1::uuid, $2::uuid, $3, $4::uuid)
                    ON CONFLICT (user_id, lesson_id) DO UPDATE SET
                        role_in_lesson = EXCLUDED.role_in_lesson,
                        track_id = COALESCE(EXCLUDED.track_id, app.lesson_members.track_id)
                    """,
                    uuid.UUID(member_id),
                    lesson_id,
                    role_code or "employee",
                    uuid.UUID(track_id) if track_id else None,
                )
            if include_teacher_member:
                await conn.execute(
                    """
                    INSERT INTO app.lesson_members (user_id, lesson_id, role_in_lesson, track_id)
                    VALUES ($1::uuid, $2::uuid, 'teacher', $3::uuid)
                    ON CONFLICT (user_id, lesson_id) DO UPDATE SET role_in_lesson = 'teacher'
                    """,
                    uuid.UUID(teacher_id),
                    lesson_id,
                    uuid.UUID(track_id) if track_id else None,
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
    from lesson_notifications import _normalize_dt

    async with get_pool().acquire() as conn:
        old_row = await conn.fetchrow(
            """
            SELECT id, teacher_id, starts_at, ends_at, place, lesson_type, title
            FROM app.lessons WHERE id = $1::uuid
            """,
            uuid.UUID(lesson_id),
        )
        if not old_row:
            raise ValueError("Занятие не найдено")
        old_lesson = serialize_record(old_row)

        new_start = _normalize_dt(starts_at) if starts_at is not None else _normalize_dt(old_lesson.get("starts_at"))
        old_start = _normalize_dt(old_lesson.get("starts_at"))
        old_end = _normalize_dt(old_lesson.get("ends_at"))
        duration = (old_end - old_start) if old_start and old_end and old_end > old_start else timedelta(hours=1)

        if ends_at is not None:
            new_end = _normalize_dt(ends_at)
        elif starts_at is not None and new_start:
            new_end = new_start + duration
        else:
            new_end = old_end

        if not new_start or not new_end:
            raise ValueError("Некорректное время занятия")
        if new_end <= new_start:
            raise ValueError("Время окончания должно быть позже начала")

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
                new_start,
            )
        if starts_at is not None or ends_at is not None:
            await conn.execute(
                "UPDATE app.lessons SET ends_at = $2 WHERE id = $1::uuid",
                uuid.UUID(lesson_id),
                new_end,
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
            f"""
            SELECT l.id, l.group_id, l.reporting_group_id, l.track_id, l.slot_id,
                   l.teacher_id, l.starts_at, l.ends_at, l.place, l.lesson_type, l.title,
                   {LESSON_TITLE_SQL} AS lesson_title,
                   g.name AS group_name, t.name AS track_name, cs.name AS slot_name,
                   tp.last_name AS teacher_last_name, tp.first_name AS teacher_first_name
            FROM app.lessons l
            LEFT JOIN app.tracks t ON t.id = l.track_id
            LEFT JOIN app.groups g ON g.id = COALESCE(l.reporting_group_id, l.group_id)
            LEFT JOIN app.conveyor_slots cs ON cs.id = l.slot_id
            LEFT JOIN app.profiles tp ON tp.user_id = l.teacher_id
            WHERE l.id = $1::uuid
            """,
            uuid.UUID(lesson_id),
        )
    if not row:
        raise ValueError("Занятие не найдено")
    new_lesson = serialize_record(row)
    if new_lesson.get("teacher_last_name") or new_lesson.get("teacher_first_name"):
        new_lesson["teacher_name"] = (
            f"{new_lesson.get('teacher_last_name', '')} {new_lesson.get('teacher_first_name', '')}".strip()
        )
    from lesson_notifications import notify_lesson_schedule_changed, schedule_fields_changed

    if schedule_fields_changed(old_lesson, new_lesson):
        await notify_lesson_schedule_changed(
            lesson_id,
            old_lesson=old_lesson,
            new_lesson=new_lesson,
        )
    return new_lesson


async def delete_lesson(
    lesson_id: str,
    *,
    actor_user_id: str | None = None,
    actor_name: str | None = None,
) -> None:
    from audit import write_audit_log
    from lesson_notifications import fetch_lesson_for_notify, notify_lesson_cancelled

    async with get_pool().acquire() as conn:
        lesson = await conn.fetchrow(
            """
            SELECT id, group_id, reporting_group_id, track_id, slot_id,
                   teacher_id, starts_at, ends_at, place, lesson_type, title
            FROM app.lessons WHERE id = $1::uuid
            """,
            uuid.UUID(lesson_id),
        )
        if not lesson:
            raise ValueError("Занятие не найдено")
        members = await conn.fetch(
            "SELECT user_id FROM app.lesson_members WHERE lesson_id = $1::uuid",
            uuid.UUID(lesson_id),
        )
        payload = {
            "lesson": serialize_record(lesson),
            "member_ids": [str(m["user_id"]) for m in members],
        }

    lesson_snapshot = await fetch_lesson_for_notify(lesson_id) or payload["lesson"]
    await notify_lesson_cancelled(lesson_snapshot)

    async with get_pool().acquire() as conn:
        result = await conn.execute(
            "DELETE FROM app.lessons WHERE id = $1::uuid",
            uuid.UUID(lesson_id),
        )
    if result == "DELETE 0":
        raise ValueError("Занятие не найдено")
    await write_audit_log(
        actor_user_id=actor_user_id,
        actor_name=actor_name,
        action="delete",
        entity_type="lesson",
        entity_id=lesson_id,
        entity_label=lesson["title"] or str(lesson_id),
        payload=payload,
    )


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
               r.code AS role_code, lm.role_in_lesson,
               am.id AS mark_id, am.status AS attendance_status,
               am.subject_role, am.marked_by_role, am.marked_at, am.marked_by
        FROM app.lesson_members lm
        JOIN app.profiles p ON p.user_id = lm.user_id
        JOIN app.roles r ON r.id = p.role_id
        LEFT JOIN app.attendance_marks am ON am.user_id = lm.user_id AND am.lesson_id = lm.lesson_id
        WHERE lm.lesson_id = $1::uuid
        ORDER BY CASE WHEN lm.role_in_lesson = 'teacher' THEN 0 ELSE 1 END, p.last_name, p.first_name
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
            marker_role = await conn.fetchval(
                """
                SELECT r.code FROM app.profiles p
                JOIN app.roles r ON r.id = p.role_id
                WHERE p.user_id = $1::uuid
                """,
                uuid.UUID(marked_by),
            )
            for mark in marks:
                subject_role = await conn.fetchval(
                    """
                    SELECT COALESCE(lm.role_in_lesson, r.code)
                    FROM app.lesson_members lm
                    JOIN app.profiles p ON p.user_id = lm.user_id
                    JOIN app.roles r ON r.id = p.role_id
                    WHERE lm.user_id = $1::uuid AND lm.lesson_id = $2::uuid
                    """,
                    uuid.UUID(mark["user_id"]),
                    uuid.UUID(lesson_id),
                )
                if not subject_role:
                    raise ValueError("Пользователь не является участником занятия")
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
                    INSERT INTO app.attendance_marks (user_id, lesson_id, status, marked_by, subject_role, marked_by_role)
                    VALUES ($1::uuid, $2::uuid, $3::app.attendance_status, $4::uuid, $5, $6)
                    ON CONFLICT (user_id, lesson_id) DO UPDATE SET
                        status = EXCLUDED.status,
                        marked_by = EXCLUDED.marked_by,
                        subject_role = EXCLUDED.subject_role,
                        marked_by_role = EXCLUDED.marked_by_role,
                        marked_at = now()
                    RETURNING id, status
                    """,
                    uuid.UUID(mark["user_id"]),
                    uuid.UUID(lesson_id),
                    mark["status"],
                    uuid.UUID(marked_by),
                    subject_role,
                    marker_role,
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
               l.starts_at, g.name AS group_name, t.name AS track_name,
               am.status AS current_status
        FROM app.attendance_mark_history h
        JOIN app.lessons l ON l.id = h.lesson_id
        LEFT JOIN app.groups g ON g.id = COALESCE(l.reporting_group_id, l.group_id)
        LEFT JOIN app.tracks t ON t.id = l.track_id
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
        SELECT s.id, s.user_id, s.lesson_id, s.reason, s.status, s.strike_number, s.target_role,
               s.appeal_reason, s.appealed_at, s.resolved_by, s.resolved_at, s.created_at,
               p.last_name, p.first_name, g.name AS group_name,
               t.name AS track_name
        FROM app.strikes s
        JOIN app.profiles p ON p.user_id = s.user_id
        LEFT JOIN app.lessons l ON l.id = s.lesson_id
        LEFT JOIN app.groups g ON g.id = COALESCE(l.reporting_group_id, l.group_id)
        LEFT JOIN app.tracks t ON t.id = l.track_id
        WHERE ($1::app.strike_status IS NULL OR s.status = $1::app.strike_status)
          AND (
            $2::uuid IS NULL
            OR EXISTS (
                SELECT 1 FROM app.user_tracks ut
                JOIN app.tracks tr ON tr.id = ut.track_id
                WHERE ut.user_id = s.user_id AND ut.status = 'active' AND tr.id_hr = $2::uuid
            )
            OR EXISTS (
                SELECT 1 FROM app.lessons l2
                JOIN app.tracks tr ON tr.id = l2.track_id
                WHERE l2.id = s.lesson_id AND tr.id_hr = $2::uuid
            )
            OR EXISTS (
                SELECT 1 FROM app.profiles p3
                JOIN app.roles r3 ON r3.id = p3.role_id
                WHERE p3.user_id = s.user_id AND r3.code != 'employee'
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
            target_role = await conn.fetchval(
                """
                SELECT r.code
                FROM app.profiles p
                JOIN app.roles r ON r.id = p.role_id
                WHERE p.user_id = $1::uuid
                """,
                uuid.UUID(user_id),
            )
            if not target_role:
                raise ValueError("Пользователь не найден")
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
                INSERT INTO app.strikes (id, user_id, lesson_id, reason, strike_number, target_role)
                VALUES ($1::uuid, $2::uuid, $3::uuid, $4, $5, $6)
                RETURNING id, user_id, lesson_id, reason, status, strike_number, target_role, created_at
                """,
                strike_id,
                uuid.UUID(user_id),
                uuid.UUID(lesson_id) if lesson_id else None,
                reason,
                strike_number,
                target_role,
            )
            active_count = await conn.fetchval(
                """
                SELECT count(*)::int FROM app.strikes
                WHERE user_id = $1::uuid AND status = 'active'
                """,
                uuid.UUID(user_id),
            )
            auto_banned = target_role == "employee" and active_count >= 3
            if auto_banned:
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
    result["auto_banned"] = auto_banned
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
            (SELECT count(DISTINCT ut.user_id)
             FROM app.user_tracks ut
             JOIN app.tracks t ON t.id = ut.track_id
             JOIN app.profiles p ON p.user_id = ut.user_id
             JOIN app.roles r ON r.id = p.role_id
             WHERE r.code = 'employee' AND ut.status = 'active'
               AND ($1::uuid IS NULL OR t.id_hr = $1::uuid)) AS users_total,
            (SELECT count(*) FROM app.tracks
             WHERE status = 'active' AND ($1::uuid IS NULL OR id_hr = $1::uuid)) AS tracks_active,
            (SELECT count(*) FROM app.strikes s
             WHERE s.status = 'active'
               AND ($1::uuid IS NULL OR EXISTS (
                   SELECT 1 FROM app.user_tracks ut
                   JOIN app.tracks t ON t.id = ut.track_id
                   WHERE ut.user_id = s.user_id AND ut.status = 'active' AND t.id_hr = $1::uuid
               ) OR EXISTS (
                   SELECT 1 FROM app.lessons l
                   JOIN app.tracks t ON t.id = l.track_id
                   WHERE l.id = s.lesson_id AND t.id_hr = $1::uuid
               ))) AS strikes_active,
            (SELECT count(*) FROM app.strikes s
             WHERE s.status = 'appealed'
               AND ($1::uuid IS NULL OR EXISTS (
                   SELECT 1 FROM app.user_tracks ut
                   JOIN app.tracks t ON t.id = ut.track_id
                   WHERE ut.user_id = s.user_id AND ut.status = 'active' AND t.id_hr = $1::uuid
               ) OR EXISTS (
                   SELECT 1 FROM app.lessons l
                   JOIN app.tracks t ON t.id = l.track_id
                   WHERE l.id = s.lesson_id AND t.id_hr = $1::uuid
               ))) AS appeals_pending,
            (SELECT count(*) FROM app.lessons l
             JOIN app.tracks t ON t.id = l.track_id
             WHERE l.starts_at >= now() - interval '7 days'
               AND ($1::uuid IS NULL OR t.id_hr = $1::uuid)) AS lessons_week
    """
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(sql, hr_uuid)
    return serialize_record(row) if row else {}


async def attendance_report_by_tracks(
    track_id: str | None = None,
    *,
    hr_user_id: str | None = None,
    teacher_user_id: str | None = None,
) -> list[dict[str, Any]]:
    hr_uuid = uuid.UUID(hr_user_id) if hr_user_id else None
    teacher_uuid = uuid.UUID(teacher_user_id) if teacher_user_id else None
    sql = """
        SELECT t.id AS track_id, t.name AS track_name,
               count(am.id) FILTER (WHERE am.status = 'present') AS present_count,
               count(am.id) FILTER (WHERE am.status = 'late') AS late_count,
               count(am.id) FILTER (WHERE am.status = 'absent') AS absent_count,
               count(am.id) AS marks_total
        FROM app.tracks t
        LEFT JOIN app.lessons l ON l.track_id = t.id
            AND ($3::uuid IS NULL OR l.teacher_id = $3::uuid)
        LEFT JOIN app.attendance_marks am ON am.lesson_id = l.id
        WHERE ($1::uuid IS NULL OR t.id = $1::uuid)
          AND ($2::uuid IS NULL OR t.id_hr = $2::uuid)
          AND (
            $3::uuid IS NULL
            OR EXISTS (
                SELECT 1 FROM app.track_teachers tt
                WHERE tt.track_id = t.id AND tt.teacher_id = $3::uuid
            )
            OR EXISTS (
                SELECT 1 FROM app.lessons l2
                WHERE l2.track_id = t.id AND l2.teacher_id = $3::uuid
            )
          )
        GROUP BY t.id, t.name
        ORDER BY t.name
    """
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            sql,
            uuid.UUID(track_id) if track_id else None,
            hr_uuid,
            teacher_uuid,
        )
    return [serialize_record(row) for row in rows]


async def attendance_report_by_groups(
    group_id: str | None = None,
    *,
    hr_user_id: str | None = None,
    teacher_user_id: str | None = None,
) -> list[dict[str, Any]]:
    return await attendance_report_by_tracks(group_id, hr_user_id=hr_user_id, teacher_user_id=teacher_user_id)


async def attendance_report_by_users(
    track_id: str | None = None,
    *,
    hr_user_id: str | None = None,
    teacher_user_id: str | None = None,
) -> list[dict[str, Any]]:
    hr_uuid = uuid.UUID(hr_user_id) if hr_user_id else None
    teacher_uuid = uuid.UUID(teacher_user_id) if teacher_user_id else None
    sql = """
        SELECT u.id AS user_id, p.last_name, p.first_name,
               t.name AS track_name, t.id AS track_id,
               t.name AS group_name, t.id AS group_id,
               count(DISTINCT l.id) AS lessons_total,
               count(am.id) FILTER (WHERE am.status = 'present') AS present_count,
               count(am.id) FILTER (WHERE am.status = 'late') AS late_count,
               count(am.id) FILTER (WHERE am.status = 'absent') AS absent_count
        FROM app.user_tracks ut
        JOIN app.users u ON u.id = ut.user_id
        JOIN app.profiles p ON p.user_id = u.id
        JOIN app.roles r ON r.id = p.role_id
        JOIN app.tracks t ON t.id = ut.track_id
        LEFT JOIN app.lessons l ON l.track_id = t.id
            AND ($3::uuid IS NULL OR l.teacher_id = $3::uuid)
        LEFT JOIN app.lesson_members lm ON lm.lesson_id = l.id AND lm.user_id = u.id
        LEFT JOIN app.attendance_marks am ON am.user_id = u.id AND am.lesson_id = l.id
        WHERE r.code = 'employee' AND ut.status = 'active'
          AND ($1::uuid IS NULL OR t.id = $1::uuid)
          AND ($2::uuid IS NULL OR t.id_hr = $2::uuid)
          AND (
            $3::uuid IS NULL
            OR EXISTS (
                SELECT 1 FROM app.track_teachers tt
                WHERE tt.track_id = t.id AND tt.teacher_id = $3::uuid
            )
            OR EXISTS (
                SELECT 1 FROM app.lessons l2
                WHERE l2.track_id = t.id AND l2.teacher_id = $3::uuid
            )
          )
          AND ($3::uuid IS NULL OR lm.user_id IS NOT NULL OR l.id IS NULL)
        GROUP BY u.id, p.last_name, p.first_name, t.name, t.id
        ORDER BY p.last_name, p.first_name
    """
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            sql,
            uuid.UUID(track_id) if track_id else None,
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
               t.id AS track_id, t.name AS track_name,
               p.last_name, p.first_name
        FROM app.attendance_marks am
        JOIN app.lessons l ON l.id = am.lesson_id
        LEFT JOIN app.groups g ON g.id = COALESCE(l.reporting_group_id, l.group_id)
        LEFT JOIN app.tracks t ON t.id = l.track_id
        JOIN app.profiles p ON p.user_id = am.user_id
        WHERE am.user_id = $1::uuid
          AND am.status != 'present'
          AND ($2::uuid IS NULL OR COALESCE(t.id_hr, g.id_hr) = $2::uuid)
        ORDER BY l.starts_at DESC
    """
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(sql, uuid.UUID(user_id), hr_uuid)
    return [serialize_record(row) for row in rows]


async def list_hr_lessons(
    *,
    hr_user_id: str | None = None,
    track_id: str | None = None,
) -> list[dict[str, Any]]:
    hr_uuid = uuid.UUID(hr_user_id) if hr_user_id else None
    sql = f"""
        SELECT l.id, l.group_id, l.reporting_group_id, l.track_id, l.slot_id,
               l.teacher_id, l.starts_at, l.ends_at, l.place, l.lesson_type, l.title,
               {LESSON_TITLE_SQL} AS lesson_title,
               g.name AS group_name,
               t.name AS track_name, t.code AS track_code,
               cs.name AS slot_name, cs.code AS slot_code,
               tp.last_name AS teacher_last_name, tp.first_name AS teacher_first_name
        FROM app.lessons l
        LEFT JOIN app.tracks t ON t.id = l.track_id
        LEFT JOIN app.groups g ON g.id = COALESCE(l.reporting_group_id, l.group_id)
        LEFT JOIN app.conveyor_slots cs ON cs.id = l.slot_id
        JOIN app.profiles tp ON tp.user_id = l.teacher_id
        WHERE ($1::uuid IS NULL OR COALESCE(t.id_hr, g.id_hr) = $1::uuid)
          AND ($2::uuid IS NULL OR l.track_id = $2::uuid)
        ORDER BY l.starts_at DESC
    """
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            sql,
            hr_uuid,
            uuid.UUID(track_id) if track_id else None,
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
        FROM app.track_teachers tt
        JOIN app.tracks t ON t.id = tt.track_id
        JOIN app.users u ON u.id = tt.teacher_id
        JOIN app.profiles p ON p.user_id = u.id
        JOIN app.roles r ON r.id = p.role_id
        WHERE ($1::uuid IS NULL OR t.id_hr = $1::uuid)
        ORDER BY p.last_name, p.first_name
    """
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(sql, hr_uuid)
        result = []
        for row in rows:
            item = serialize_record(row)
            teacher_id = item["id"]
            tracks_sql = """
                SELECT DISTINCT t.id, t.name, t.code
                FROM app.track_teachers tt
                JOIN app.tracks t ON t.id = tt.track_id
                WHERE tt.teacher_id = $1::uuid
                  AND ($2::uuid IS NULL OR t.id_hr = $2::uuid)
                ORDER BY t.name
            """
            track_rows = await conn.fetch(tracks_sql, uuid.UUID(teacher_id), hr_uuid)
            item["tracks"] = [serialize_record(t) for t in track_rows]
            item["groups"] = []
            result.append(item)
    return result


async def list_hr_notifications(*, hr_user_id: str) -> list[dict[str, Any]]:
    hr_uuid = uuid.UUID(hr_user_id)
    db_sql = """
        SELECT n.id::text, n.delivered_to, n.lesson_id, n.kind, n.sent_at,
               l.starts_at, l.place, l.lesson_type,
               g.name AS group_name, t.name AS track_name,
               tp.last_name AS teacher_last_name, tp.first_name AS teacher_first_name
        FROM app.notifications n
        JOIN app.lessons l ON l.id = n.lesson_id
        LEFT JOIN app.groups g ON g.id = COALESCE(l.reporting_group_id, l.group_id)
        LEFT JOIN app.tracks t ON t.id = l.track_id
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
               g.name AS group_name, t.name AS track_name,
               p.last_name, p.first_name
        FROM app.attendance_marks am
        JOIN app.lessons l ON l.id = am.lesson_id
        JOIN app.groups g ON g.id = COALESCE(l.reporting_group_id, l.group_id)
        LEFT JOIN app.tracks t ON t.id = l.track_id
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
               g.name AS group_name, t.name AS track_name,
               p.last_name, p.first_name
        FROM app.strikes s
        JOIN app.profiles p ON p.user_id = s.user_id
        LEFT JOIN app.lessons l ON l.id = s.lesson_id
        LEFT JOIN app.groups g ON g.id = COALESCE(l.reporting_group_id, l.group_id)
        LEFT JOIN app.tracks t ON t.id = l.track_id
        WHERE s.status = 'active'
          AND EXISTS (
              SELECT 1 FROM app.group_members gm
              JOIN app.groups g2 ON g2.id = gm.group_id
              WHERE gm.user_id = s.user_id AND g2.id_hr = $1::uuid
              UNION ALL
              SELECT 1 FROM app.lessons l2
              JOIN app.groups g3 ON g3.id = COALESCE(l2.reporting_group_id, l2.group_id)
              WHERE l2.id = s.lesson_id AND g3.id_hr = $1::uuid
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
    return await update_user_profile(user_id, max_id=max_id, update_max_id=True)


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
    """Per-track attendance summary and upcoming lesson count for a non-HR user."""
    sql = f"""
        SELECT t.id AS track_id, t.name AS track_name, t.code AS track_code,
               t.practice_required, t.lecture_required, ut.status AS track_status, ut.due_date,
               count(DISTINCT l.id) FILTER (
                   WHERE l.starts_at <= now() AND lm.user_id IS NOT NULL
               ) AS lessons_past,
               count(am.id) FILTER (WHERE am.status = 'present') AS present_count,
               count(am.id) FILTER (WHERE am.status = 'late') AS late_count,
               count(am.id) FILTER (WHERE am.status = 'absent') AS absent_count,
               count(DISTINCT l.id) FILTER (
                   WHERE l.starts_at > now() AND lm.user_id IS NOT NULL
               ) AS lessons_upcoming
        FROM app.user_tracks ut
        JOIN app.tracks t ON t.id = ut.track_id
        LEFT JOIN app.lessons l ON l.track_id = t.id
        LEFT JOIN app.lesson_members lm ON lm.lesson_id = l.id AND lm.user_id = ut.user_id
        LEFT JOIN app.attendance_marks am ON am.user_id = ut.user_id AND am.lesson_id = l.id
        WHERE ut.user_id = $1::uuid
        GROUP BY t.id, t.name, t.code, t.practice_required, t.lecture_required, ut.status, ut.due_date
        ORDER BY t.name
    """
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(sql, uuid.UUID(user_id))
    result = [serialize_record(row) for row in rows]
    if result:
        return result

    # Compatibility fallback for existing data before tracks are assigned.
    fallback_sql = f"""
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
        LEFT JOIN app.lessons l ON COALESCE(l.reporting_group_id, l.group_id) = g.id
        LEFT JOIN app.lesson_members lm ON lm.lesson_id = l.id AND lm.user_id = gm.user_id
        LEFT JOIN app.attendance_marks am ON am.user_id = gm.user_id AND am.lesson_id = l.id
        WHERE gm.user_id = $1::uuid
        GROUP BY g.id, g.name
        ORDER BY g.name
    """
    async with get_pool().acquire() as conn:
        fallback_rows = await conn.fetch(fallback_sql, uuid.UUID(user_id))
    return [serialize_record(row) for row in fallback_rows]


async def list_employee_upcoming_lessons(user_id: str, *, limit: int = 7) -> list[dict[str, Any]]:
    safe_limit = max(1, min(limit, 20))
    sql = f"""
        SELECT l.id, l.starts_at, l.ends_at, l.place, l.lesson_type, l.title,
               {LESSON_TITLE_SQL} AS lesson_title,
               g.name AS group_name, t.name AS track_name, t.code AS track_code,
               cs.name AS slot_name, cs.code AS slot_code,
               tp.last_name AS teacher_last_name, tp.first_name AS teacher_first_name
        FROM app.lesson_members lm
        JOIN app.lessons l ON l.id = lm.lesson_id
        LEFT JOIN app.groups g ON g.id = COALESCE(l.reporting_group_id, l.group_id)
        LEFT JOIN app.tracks t ON t.id = l.track_id
        LEFT JOIN app.conveyor_slots cs ON cs.id = l.slot_id
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
               g.name AS group_name, t.name AS track_name,
               l.starts_at AS lesson_starts_at,
               COALESCE(l.title, CASE WHEN l.lesson_type = 'practice' THEN 'Практика' ELSE 'Лекция' END) AS lesson_title
        FROM app.strikes s
        LEFT JOIN app.lessons l ON l.id = s.lesson_id
        LEFT JOIN app.groups g ON g.id = COALESCE(l.reporting_group_id, l.group_id)
        LEFT JOIN app.tracks t ON t.id = l.track_id
        WHERE s.user_id = $1::uuid
          AND s.status != 'revoked'
        ORDER BY s.created_at DESC
        LIMIT 20
    """
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(sql, uuid.UUID(user_id))
    return [serialize_record(row) for row in rows]


async def list_staff_remarks(user_id: str) -> list[dict[str, Any]]:
    sql = """
        SELECT r.id, r.user_id, r.text, r.issued_by, r.created_at,
               ip.last_name AS issuer_last_name, ip.first_name AS issuer_first_name
        FROM app.staff_remarks r
        LEFT JOIN app.profiles ip ON ip.user_id = r.issued_by
        WHERE r.user_id = $1::uuid
        ORDER BY r.created_at DESC
        LIMIT 100
    """
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(sql, uuid.UUID(user_id))
    return [serialize_record(row) for row in rows]


async def create_staff_remark(
    user_id: str,
    text: str,
    *,
    issued_by: str | None = None,
) -> dict[str, Any]:
    remark_text = text.strip()
    if len(remark_text) < 3:
        raise ValueError("Текст замечания слишком короткий")
    issuer_uuid = uuid.UUID(issued_by) if issued_by else None
    async with get_pool().acquire() as conn:
        role_code = await conn.fetchval(
            """
            SELECT r.code
            FROM app.profiles p
            JOIN app.roles r ON r.id = p.role_id
            WHERE p.user_id = $1::uuid
            """,
            uuid.UUID(user_id),
        )
        if role_code not in {"teacher", "curator"}:
            raise ValueError("Замечания можно выписывать только инструкторам и кураторам")
        row = await conn.fetchrow(
            """
            INSERT INTO app.staff_remarks (user_id, text, issued_by)
            VALUES ($1::uuid, $2, $3::uuid)
            RETURNING id, user_id, text, issued_by, created_at
            """,
            uuid.UUID(user_id),
            remark_text,
            issuer_uuid,
        )
    return serialize_record(row)


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


async def list_curator_subordinates(curator_user_id: str) -> list[dict[str, Any]]:
    sql = """
        SELECT u.id, u.is_active, p.last_name, p.first_name, p.middle_name,
               p.phone, p.max_id, p.status, p.ban_reason, p.id_curator,
               r.code AS role_code, r.name AS role_name,
               (SELECT count(*)::int FROM app.strikes s
                WHERE s.user_id = u.id AND s.status = 'active') AS strike_count
        FROM app.profiles p
        JOIN app.users u ON u.id = p.user_id
        JOIN app.roles r ON r.id = p.role_id
        WHERE p.id_curator = $1::uuid
          AND r.code = 'employee'
        ORDER BY p.last_name, p.first_name
    """
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(sql, uuid.UUID(curator_user_id))
    return [serialize_record(row) for row in rows]


async def sync_curator_wards(curator_id: str, user_ids: list[str]) -> dict[str, Any]:
    await verify_user_role(curator_id, "curator")
    curator_uuid = uuid.UUID(curator_id)
    target_uuids = [uuid.UUID(uid) for uid in user_ids]

    async with get_pool().acquire() as conn:
        async with conn.transaction():
            if target_uuids:
                employee_count = await conn.fetchval(
                    """
                    SELECT count(*)::int
                    FROM app.profiles p
                    JOIN app.roles r ON r.id = p.role_id
                    WHERE p.user_id = ANY($1::uuid[]) AND r.code = 'employee'
                    """,
                    target_uuids,
                )
                if employee_count != len(target_uuids):
                    raise ValueError("Можно назначать только существующих сотрудников")

                reassigned_from_other = await conn.fetchval(
                    """
                    SELECT count(*)::int
                    FROM app.profiles p
                    JOIN app.roles r ON r.id = p.role_id
                    WHERE p.user_id = ANY($1::uuid[])
                      AND r.code = 'employee'
                      AND p.id_curator IS NOT NULL
                      AND p.id_curator <> $2::uuid
                    """,
                    target_uuids,
                    curator_uuid,
                )
            else:
                reassigned_from_other = 0

            removed_rows = await conn.fetch(
                """
                UPDATE app.profiles
                SET id_curator = NULL, updated_at = now()
                WHERE id_curator = $1::uuid
                  AND (
                    cardinality($2::uuid[]) = 0
                    OR user_id <> ALL($2::uuid[])
                  )
                RETURNING user_id
                """,
                curator_uuid,
                target_uuids,
            )

            assigned = 0
            if target_uuids:
                assigned_rows = await conn.fetch(
                    """
                    UPDATE app.profiles p
                    SET id_curator = $1::uuid, updated_at = now()
                    FROM app.roles r
                    WHERE p.user_id = ANY($2::uuid[])
                      AND r.id = p.role_id
                      AND r.code = 'employee'
                    RETURNING p.user_id
                    """,
                    curator_uuid,
                    target_uuids,
                )
                assigned = len(assigned_rows)

    return {
        "assigned": assigned,
        "removed": len(removed_rows),
        "reassigned_from_other": int(reassigned_from_other or 0),
    }


async def list_instructor_tracks(teacher_id: str) -> list[dict[str, Any]]:
    sql = """
        SELECT t.id, t.code, t.name, t.description, t.practice_required, t.lecture_required,
               t.status,
               (SELECT count(*)::int FROM app.user_tracks ut
                WHERE ut.track_id = t.id AND ut.status = 'active') AS employee_count
        FROM app.track_teachers tt
        JOIN app.tracks t ON t.id = tt.track_id
        WHERE tt.teacher_id = $1::uuid
        ORDER BY t.name
    """
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(sql, uuid.UUID(teacher_id))
    return [serialize_record(row) for row in rows]


async def list_all_track_teacher_links() -> list[dict[str, Any]]:
    sql = """
        SELECT tt.track_id, tt.teacher_id,
               t.code AS track_code, t.name AS track_name,
               p.last_name AS teacher_last_name, p.first_name AS teacher_first_name
        FROM app.track_teachers tt
        JOIN app.tracks t ON t.id = tt.track_id
        JOIN app.profiles p ON p.user_id = tt.teacher_id
        ORDER BY t.name, p.last_name, p.first_name
    """
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(sql)
    return [serialize_record(row) for row in rows]


async def sync_instructor_tracks(
    teacher_id: str,
    track_ids: list[str],
    *,
    actor_user_id: str | None = None,
    actor_name: str | None = None,
) -> dict[str, Any]:
    from audit import write_audit_log

    await verify_user_role(teacher_id, "teacher")
    teacher_uuid = uuid.UUID(teacher_id)
    target_uuids = [uuid.UUID(tid) for tid in track_ids]

    async with get_pool().acquire() as conn:
        async with conn.transaction():
            if target_uuids:
                track_count = await conn.fetchval(
                    """
                    SELECT count(*)::int FROM app.tracks
                    WHERE id = ANY($1::uuid[])
                    """,
                    target_uuids,
                )
                if track_count != len(target_uuids):
                    raise ValueError("Один или несколько треков не найдены")

            removed_rows = await conn.fetch(
                """
                DELETE FROM app.track_teachers
                WHERE teacher_id = $1::uuid
                  AND (
                    cardinality($2::uuid[]) = 0
                    OR track_id <> ALL($2::uuid[])
                  )
                RETURNING track_id
                """,
                teacher_uuid,
                target_uuids,
            )

            assigned = 0
            if target_uuids:
                assigned_rows = await conn.fetch(
                    """
                    INSERT INTO app.track_teachers (track_id, teacher_id)
                    SELECT unnest($1::uuid[]), $2::uuid
                    ON CONFLICT DO NOTHING
                    RETURNING track_id
                    """,
                    target_uuids,
                    teacher_uuid,
                )
                assigned = len(assigned_rows)

    for removed in removed_rows:
        track_id = str(removed["track_id"])
        await write_audit_log(
            actor_user_id=actor_user_id,
            actor_name=actor_name,
            action="delete",
            entity_type="track_teacher",
            entity_id=f"{track_id}:{teacher_id}",
            entity_label=f"инструктор {teacher_id} с трека {track_id}",
            payload={"track_id": track_id, "teacher_id": teacher_id},
        )

    return {
        "assigned": assigned,
        "removed": len(removed_rows),
    }


async def verify_curator_subordinate(curator_user_id: str, subordinate_user_id: str) -> None:
    async with get_pool().acquire() as conn:
        exists = await conn.fetchval(
            """
            SELECT EXISTS (
                SELECT 1
                FROM app.profiles p
                JOIN app.roles r ON r.id = p.role_id
                WHERE p.user_id = $2::uuid
                  AND p.id_curator = $1::uuid
                  AND r.code = 'employee'
            )
            """,
            uuid.UUID(curator_user_id),
            uuid.UUID(subordinate_user_id),
        )
    if not exists:
        raise ValueError("Подопечный не найден или недоступен")
