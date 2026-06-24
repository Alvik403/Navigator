"""Test dataset for formation: employees per track, past lessons, instructors."""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import asyncpg

from demo_seed import FIRST_NAMES_F, FIRST_NAMES_M, LAST_NAMES, MIDDLE_NAMES, RNG

NS = uuid.UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")

# Сотрудников на трек (для проверки резерва при max_members=4..6)
TRACK_EMPLOYEE_COUNTS = [15, 12, 10, 8, 6, 5, 4, 3, 2, 1, 0, 0, 0]
FORMATION_MAX_MEMBERS = [4, 6, 8, 12, 4, 6, 8, 12, 4, 6, 8, 12, 4]
PAST_LESSON_COUNTS = [0, 1, 2, 3, 4, 5, 6, 2, 1, 3, 0, 4, 5]
CURATOR_WARD_COUNTS = [5, 8, 10, 7, 9]
CURATOR_PROFILES = [
    ("Каюмов", "Руслан", "Ильдарович"),
    ("Хасанова", "Алина", "Петровна"),
    ("Галеев", "Тимур", "Рафисович"),
    ("Сафина", "Диана", "Айратовна"),
    ("Нуриев", "Ильдар", "Маратович"),
]


def _eid(n: int) -> uuid.UUID:
    return uuid.uuid5(NS, f"formation-test/employee/{n}")


def _tid(n: int) -> uuid.UUID:
    return uuid.uuid5(NS, f"formation-test/teacher/{n}")


def _cid(n: int) -> uuid.UUID:
    return uuid.uuid5(NS, f"formation-test/curator/{n}")


def _wid(n: int) -> uuid.UUID:
    return uuid.uuid5(NS, f"formation-test/ward/{n}")


async def _ensure_smu_patterns(conn: asyncpg.Connection) -> list[asyncpg.Record]:
    for i in range(1, 14):
        await conn.execute(
            """
            INSERT INTO app.smu_patterns (code, name, work_days, off_days, anchor_date)
            VALUES ($1, $2, 2, 2, $3)
            ON CONFLICT (code) DO UPDATE SET
                name = EXCLUDED.name,
                work_days = EXCLUDED.work_days,
                off_days = EXCLUDED.off_days,
                anchor_date = EXCLUDED.anchor_date,
                status = 'active',
                updated_at = now()
            """,
            f"smu-{i}",
            f"СМУ-{i}",
            date(2026, 1, i),
        )
    return await conn.fetch(
        """
        SELECT id, code, name FROM app.smu_patterns
        WHERE status = 'active' AND code ~ '^smu-[0-9]+$'
        ORDER BY CAST(substring(code FROM '[0-9]+') AS int)
        """
    )


async def _smu_by_number(conn: asyncpg.Connection, number: int) -> asyncpg.Record | None:
    return await conn.fetchrow(
        "SELECT id, code, name FROM app.smu_patterns WHERE code = $1 AND status = 'active'",
        f"smu-{number}",
    )


async def seed_formation_test_data(pool: asyncpg.Pool) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    today = now.date()

    async with pool.acquire() as conn:
        async with conn.transaction():
            roles = await conn.fetch("SELECT id, code FROM app.roles")
            role_id = {row["code"]: row["id"] for row in roles}

            hr_id = await conn.fetchval(
                """
                SELECT p.user_id FROM app.profiles p
                JOIN app.roles r ON r.id = p.role_id
                WHERE r.code = 'hr' AND p.status = 'active'
                ORDER BY p.user_id LIMIT 1
                """
            )
            if not hr_id:
                raise ValueError("Нет активного HR для seed")

            smu_patterns = await _ensure_smu_patterns(conn)
            slot_row = await conn.fetchrow(
                "SELECT id, starts_at_local, duration_min FROM app.conveyor_slots WHERE status = 'active' ORDER BY sort_order LIMIT 1"
            )
            if not slot_row:
                raise ValueError("Нет активных слотов конвейера")
            slot_id = slot_row["id"]
            slot_time: time = slot_row["starts_at_local"]

            tracks = await conn.fetch(
                """
                SELECT id, code, name, practice_required
                FROM app.tracks
                WHERE status = 'active'
                ORDER BY name
                """
            )
            if not tracks:
                raise ValueError("Нет активных треков")

            curators_created = 0
            curator_ids: list[uuid.UUID] = []
            curator_summaries: list[dict[str, Any]] = []
            ward_user_tracks = 0

            for ci, (last_name, first_name, middle_name) in enumerate(CURATOR_PROFILES):
                cid = _cid(ci)
                curator_ids.append(cid)
                await conn.execute(
                    "INSERT INTO app.users (id, is_active) VALUES ($1, TRUE) ON CONFLICT (id) DO UPDATE SET is_active = TRUE",
                    cid,
                )
                await conn.execute(
                    """
                    INSERT INTO app.profiles (
                        user_id, last_name, first_name, middle_name, role_id, phone, max_id, status
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, 'active')
                    ON CONFLICT (user_id) DO UPDATE SET
                        last_name = EXCLUDED.last_name,
                        first_name = EXCLUDED.first_name,
                        middle_name = EXCLUDED.middle_name,
                        role_id = EXCLUDED.role_id,
                        phone = EXCLUDED.phone,
                        max_id = EXCLUDED.max_id,
                        status = 'active',
                        updated_at = now()
                    """,
                    cid,
                    last_name,
                    first_name,
                    middle_name,
                    role_id["curator"],
                    f"+7930{RNG.randint(1000000, 9999999)}",
                    951000 + ci,
                )
                curators_created += 1
                ward_count = CURATOR_WARD_COUNTS[ci]
                smu_row = await _smu_by_number(conn, ci + 1)
                if not smu_row:
                    smu_row = smu_patterns[ci % len(smu_patterns)]
                for wi in range(ward_count):
                    wid = _wid(ci * 20 + wi)
                    is_f = wi % 2 == 0
                    await conn.execute(
                        "INSERT INTO app.users (id, is_active) VALUES ($1, TRUE) ON CONFLICT (id) DO UPDATE SET is_active = TRUE",
                        wid,
                    )
                    await conn.execute(
                        """
                        INSERT INTO app.profiles (
                            user_id, last_name, first_name, middle_name, role_id,
                            id_curator, phone, max_id, status
                        )
                        VALUES ($1, $2, $3, $4, $5, $6, NULL, NULL, 'active')
                        ON CONFLICT (user_id) DO UPDATE SET
                            last_name = EXCLUDED.last_name,
                            first_name = EXCLUDED.first_name,
                            role_id = EXCLUDED.role_id,
                            id_curator = EXCLUDED.id_curator,
                            phone = NULL,
                            max_id = NULL,
                            status = 'active',
                            updated_at = now()
                        """,
                        wid,
                        LAST_NAMES[(ci * 3 + wi) % len(LAST_NAMES)],
                        RNG.choice(FIRST_NAMES_F if is_f else FIRST_NAMES_M),
                        RNG.choice(MIDDLE_NAMES),
                        role_id["employee"],
                        cid,
                    )
                    await conn.execute(
                        """
                        INSERT INTO app.user_smu (user_id, smu_pattern_id, shift_number)
                        VALUES ($1, $2, $3)
                        ON CONFLICT (user_id) DO UPDATE SET
                            smu_pattern_id = EXCLUDED.smu_pattern_id,
                            shift_number = EXCLUDED.shift_number,
                            updated_at = now()
                        """,
                        wid,
                        smu_row["id"],
                        (wi % 4) + 1,
                    )
                    track = tracks[(ci + wi) % len(tracks)]
                    await conn.execute(
                        """
                        INSERT INTO app.user_tracks (user_id, track_id, assigned_by, status, due_date, started_at)
                        VALUES ($1, $2, $3, 'active', $4, $5)
                        ON CONFLICT (user_id, track_id) DO UPDATE SET
                            status = 'active',
                            due_date = EXCLUDED.due_date,
                            assigned_by = EXCLUDED.assigned_by,
                            updated_at = now()
                        """,
                        wid,
                        track["id"],
                        hr_id,
                        today + timedelta(days=21 + wi),
                        today - timedelta(days=14),
                    )
                    ward_user_tracks += 1
                curator_summaries.append({
                    "name": f"{last_name} {first_name}",
                    "wards": ward_count,
                    "smu": smu_row["name"],
                    "max_id": 951000 + ci,
                })

            teachers_created = 0
            teacher_ids: list[uuid.UUID] = []
            existing_teachers = await conn.fetch(
                """
                SELECT p.user_id FROM app.profiles p
                JOIN app.roles r ON r.id = p.role_id
                WHERE r.code = 'teacher' AND p.status = 'active'
                ORDER BY p.last_name, p.first_name
                """
            )
            for row in existing_teachers:
                teacher_ids.append(row["user_id"])

            need = max(len(tracks) - len(teacher_ids), 0)
            for i in range(need):
                tid = _tid(i)
                teacher_ids.append(tid)
                await conn.execute(
                    "INSERT INTO app.users (id, is_active) VALUES ($1, TRUE) ON CONFLICT (id) DO UPDATE SET is_active = TRUE",
                    tid,
                )
                is_f = i % 3 == 0
                await conn.execute(
                    """
                    INSERT INTO app.profiles (user_id, last_name, first_name, middle_name, role_id, phone, max_id, status)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, 'active')
                    ON CONFLICT (user_id) DO UPDATE SET
                        last_name = EXCLUDED.last_name,
                        first_name = EXCLUDED.first_name,
                        role_id = EXCLUDED.role_id,
                        status = 'active',
                        updated_at = now()
                    """,
                    tid,
                    LAST_NAMES[i % len(LAST_NAMES)],
                    RNG.choice(FIRST_NAMES_F if is_f else FIRST_NAMES_M),
                    RNG.choice(MIDDLE_NAMES),
                    role_id["teacher"],
                    f"+7910{RNG.randint(1000000, 9999999)}",
                    930000 + i,
                )
                teachers_created += 1

            employees_created = 0
            employee_ids: list[uuid.UUID] = []
            for i in range(1, 56):
                eid = _eid(i)
                employee_ids.append(eid)
                is_f = i % 2 == 0
                await conn.execute(
                    "INSERT INTO app.users (id, is_active) VALUES ($1, TRUE) ON CONFLICT (id) DO UPDATE SET is_active = TRUE",
                    eid,
                )
                await conn.execute(
                    """
                    INSERT INTO app.profiles (
                        user_id, last_name, first_name, middle_name, role_id,
                        id_curator, phone, max_id, status
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'active')
                    ON CONFLICT (user_id) DO UPDATE SET
                        last_name = EXCLUDED.last_name,
                        first_name = EXCLUDED.first_name,
                        role_id = EXCLUDED.role_id,
                        id_curator = EXCLUDED.id_curator,
                        phone = EXCLUDED.phone,
                        max_id = EXCLUDED.max_id,
                        status = 'active',
                        updated_at = now()
                    """,
                    eid,
                    LAST_NAMES[i % len(LAST_NAMES)],
                    RNG.choice(FIRST_NAMES_F if is_f else FIRST_NAMES_M),
                    RNG.choice(MIDDLE_NAMES),
                    role_id["employee"],
                    curator_ids[(i - 1) % len(curator_ids)],
                    f"+7920{RNG.randint(1000000, 9999999)}" if i % 2 == 0 else None,
                    940000 + i if i % 3 == 0 else None,
                )
                employees_created += 1
                if smu_patterns:
                    smu_row = await _smu_by_number(conn, ((i - 1) % 13) + 1)
                    if not smu_row:
                        smu_row = smu_patterns[(i - 1) % len(smu_patterns)]
                    await conn.execute(
                        """
                        INSERT INTO app.user_smu (user_id, smu_pattern_id, shift_number)
                        VALUES ($1, $2, $3)
                        ON CONFLICT (user_id) DO UPDATE SET
                            smu_pattern_id = EXCLUDED.smu_pattern_id,
                            shift_number = EXCLUDED.shift_number,
                            updated_at = now()
                        """,
                        eid,
                        smu_row["id"],
                        (i % 4) + 1,
                    )

            user_tracks_touched = ward_user_tracks
            emp_cursor = 0
            track_summaries: list[dict[str, Any]] = []

            for ti, track in enumerate(tracks):
                track_id = track["id"]
                want = TRACK_EMPLOYEE_COUNTS[ti % len(TRACK_EMPLOYEE_COUNTS)]
                max_members = FORMATION_MAX_MEMBERS[ti % len(FORMATION_MAX_MEMBERS)]
                past_lessons = PAST_LESSON_COUNTS[ti % len(PAST_LESSON_COUNTS)]

                await conn.execute(
                    """
                    UPDATE app.tracks SET
                        formation_auto_enabled = TRUE,
                        formation_max_members = $2,
                        formation_min_members = 1,
                        formation_lesson_type = 'practice',
                        formation_default_place = $3,
                        updated_at = now()
                    WHERE id = $1::uuid
                    """,
                    track_id,
                    max_members,
                    f"Площадка · {track['name'][:20]}",
                )

                teacher_id = teacher_ids[ti % len(teacher_ids)]
                await conn.execute(
                    """
                    INSERT INTO app.track_teachers (track_id, teacher_id)
                    VALUES ($1, $2)
                    ON CONFLICT DO NOTHING
                    """,
                    track_id,
                    teacher_id,
                )

                assigned: list[uuid.UUID] = []
                for _ in range(want):
                    if emp_cursor >= len(employee_ids):
                        break
                    eid = employee_ids[emp_cursor]
                    emp_cursor += 1
                    assigned.append(eid)
                    due = today + timedelta(days=14 + (ti % 5) * 7)
                    await conn.execute(
                        """
                        INSERT INTO app.user_tracks (user_id, track_id, assigned_by, status, due_date, started_at)
                        VALUES ($1, $2, $3, 'active', $4, $5)
                        ON CONFLICT (user_id, track_id) DO UPDATE SET
                            status = 'active',
                            due_date = EXCLUDED.due_date,
                            completed_at = NULL,
                            assigned_by = EXCLUDED.assigned_by,
                            updated_at = now()
                        """,
                        eid,
                        track_id,
                        hr_id,
                        due,
                        today - timedelta(days=30),
                    )
                    user_tracks_touched += 1

                lessons_created = 0
                marks_created = 0
                for li in range(past_lessons):
                    day_offset = -(past_lessons - li) * 7 - 3
                    lesson_date = today + timedelta(days=day_offset)
                    tz = ZoneInfo("Europe/Moscow")
                    local_dt = datetime.combine(lesson_date, slot_time, tzinfo=tz)
                    starts = local_dt.astimezone(timezone.utc).replace(tzinfo=None)
                    ends = starts + timedelta(minutes=int(slot_row["duration_min"] or 60))
                    lesson_id = uuid.uuid5(NS, f"formation-test/lesson/{track_id}/{li}")
                    await conn.execute(
                        """
                        INSERT INTO app.lessons (
                            id, track_id, slot_id, teacher_id, starts_at, ends_at,
                            place, lesson_type, title
                        )
                        VALUES ($1, $2, $3, $4, $5, $6, $7, 'practice', $8)
                        ON CONFLICT (id) DO UPDATE SET
                            track_id = EXCLUDED.track_id,
                            slot_id = EXCLUDED.slot_id,
                            teacher_id = EXCLUDED.teacher_id,
                            starts_at = EXCLUDED.starts_at,
                            ends_at = EXCLUDED.ends_at,
                            place = EXCLUDED.place,
                            lesson_type = EXCLUDED.lesson_type,
                            title = EXCLUDED.title
                        """,
                        lesson_id,
                        track_id,
                        slot_id,
                        teacher_id,
                        starts,
                        ends,
                        f"Площадка · {track['name'][:20]}",
                        f"{track['name']} · занятие {li + 1}",
                    )
                    lessons_created += 1
                    await conn.execute(
                        """
                        INSERT INTO app.lesson_members (user_id, lesson_id, role_in_lesson, track_id)
                        VALUES ($1, $2, 'teacher', $3)
                        ON CONFLICT (user_id, lesson_id) DO NOTHING
                        """,
                        teacher_id,
                        lesson_id,
                        track_id,
                    )
                    attendees = assigned[: min(len(assigned), max_members)]
                    for uid in attendees:
                        await conn.execute(
                            """
                            INSERT INTO app.lesson_members (user_id, lesson_id, role_in_lesson, track_id)
                            VALUES ($1, $2, 'employee', $3)
                            ON CONFLICT (user_id, lesson_id) DO NOTHING
                            """,
                            uid,
                            lesson_id,
                            track_id,
                        )
                        await conn.execute(
                            """
                            INSERT INTO app.attendance_marks (user_id, lesson_id, status, marked_by, subject_role, marked_by_role)
                            VALUES ($1, $2, 'present', $3, 'employee', 'hr')
                            ON CONFLICT (user_id, lesson_id) DO UPDATE SET status = 'present', marked_at = now()
                            """,
                            uid,
                            lesson_id,
                            hr_id,
                        )
                        marks_created += 1

                track_summaries.append({
                    "track": track["name"],
                    "employees": len(assigned),
                    "formation_max_members": max_members,
                    "past_lessons": past_lessons,
                    "teacher_id": str(teacher_id),
                })

            return {
                "tracks": len(tracks),
                "smu_patterns": len(smu_patterns),
                "curators_created": curators_created,
                "curator_summaries": curator_summaries,
                "ward_employees": sum(CURATOR_WARD_COUNTS),
                "teachers_created": teachers_created,
                "employees_created": employees_created,
                "user_tracks_touched": user_tracks_touched,
                "track_summaries": track_summaries,
            }
