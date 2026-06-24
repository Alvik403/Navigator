"""Deterministic demo dataset for HR dashboard (~100 users)."""

from __future__ import annotations

import uuid
from datetime import datetime, time, timedelta, timezone
from random import Random
from typing import Any

import asyncpg

RNG = Random(42)

STRIKE_BAN_REASON = "3 страйка"

LAST_NAMES = [
    "Иванов", "Петров", "Сидоров", "Козлов", "Новиков", "Морозов", "Волков", "Соколов",
    "Лебедев", "Кузнецов", "Попов", "Васильев", "Смирнов", "Михайлов", "Фёдоров", "Андреев",
    "Алексеев", "Романов", "Орлов", "Степанов", "Никитин", "Егоров", "Павлов", "Семёнов",
    "Голубев", "Виноградов", "Богданов", "Воробьёв", "Фролов", "Макаров", "Давыдов", "Жуков",
    "Ким", "Чен", "Пак", "Ли", "Громов", "Калинин", "Медведев", "Беляев",
]
FIRST_NAMES_M = [
    "Александр", "Дмитрий", "Максим", "Сергей", "Андрей", "Алексей", "Иван", "Михаил",
    "Никита", "Павел", "Роман", "Егор", "Кирилл", "Тимофей", "Артём", "Денис",
]
FIRST_NAMES_F = [
    "Анна", "Мария", "Елена", "Ольга", "Наталья", "Татьяна", "Ирина", "Екатерина",
    "София", "Виктория", "Алина", "Дарья", "Полина", "Юлия", "Вера", "Ксения",
]
MIDDLE_NAMES = [
    "Иванович", "Петрович", "Сергеевич", "Александрович", "Дмитриевич", "Андреевич",
    "Ивановна", "Петровна", "Сергеевна", "Александровна", "Дмитриевна", "Андреевна",
]

DIRECTIONS = ["Backend", "Frontend", "DevOps", "Data Science", "QA"]
TRACKS = [
    ("betonshchik", "Бетонщик", 12),
    ("armaturschik", "Арматурщик", 8),
    ("mixer-driver", "Водитель бетономешалки", 6),
]
GROUP_SUFFIXES = ["26-A", "26-B", "25-C"]
LESSON_TITLES = [
    "Введение", "Практика: REST API", "Code review", "Тестирование", "Деплой",
    "SQL и индексы", "React hooks", "Docker compose", "Метрики и алерты", "Итоговый разбор",
]
PLACES = ["Ауд. 301", "Ауд. 205", "Онлайн", "Лаб. 12", "Ауд. 102"]
STRIKE_REASONS = ["late", "absent", "manual", "discipline"]


def _uid(kind: str, n: int) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"max-rass-demo/{kind}/{n}")


def _gid(direction_idx: int, group_idx: int) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"max-rass-demo/dir/{direction_idx}/grp/{group_idx}")


def _lid(lesson_idx: int) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"max-rass-demo/lesson/{lesson_idx}")


def _sid(strike_idx: int) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"max-rass-demo/strike/{strike_idx}")


def _tid(track_idx: int) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"max-rass-demo/track/{track_idx}")


def _slotid(slot_idx: int) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"max-rass-demo/slot/{slot_idx}")


async def seed_demo_data(pool: asyncpg.Pool) -> dict[str, Any]:
    now = datetime.now(timezone.utc)

    core = {
        "hr": uuid.UUID("11111111-1111-1111-1111-111111111111"),
        "curator": uuid.UUID("22222222-2222-2222-2222-222222222222"),
        "teacher": uuid.UUID("33333333-3333-3333-3333-333333333333"),
        "employee": uuid.UUID("44444444-4444-4444-4444-444444444444"),
        "admin": uuid.UUID("55555555-5555-5555-5555-555555555555"),
    }

    async with pool.acquire() as conn:
        async with conn.transaction():
            roles = await conn.fetch("SELECT id, code FROM app.roles")
            role_id = {row["code"]: row["id"] for row in roles}

            users_touched = 0
            profiles_touched = 0

            async def upsert_user(
                user_id: uuid.UUID,
                *,
                last_name: str,
                first_name: str,
                middle_name: str | None,
                role_code: str,
                id_curator: uuid.UUID | None = None,
                phone: str | None = None,
                max_id: int | None = None,
                status: str = "active",
                ban_reason: str | None = None,
            ) -> None:
                nonlocal users_touched, profiles_touched
                await conn.execute(
                    """
                    INSERT INTO app.users (id, is_active)
                    VALUES ($1, TRUE)
                    ON CONFLICT (id) DO UPDATE SET is_active = EXCLUDED.is_active
                    """,
                    user_id,
                )
                users_touched += 1
                await conn.execute(
                    """
                    INSERT INTO app.profiles (
                        user_id, last_name, first_name, middle_name, role_id,
                        id_curator, phone, max_id, status, ban_reason
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                    ON CONFLICT (user_id) DO UPDATE SET
                        last_name = EXCLUDED.last_name,
                        first_name = EXCLUDED.first_name,
                        middle_name = EXCLUDED.middle_name,
                        role_id = EXCLUDED.role_id,
                        id_curator = EXCLUDED.id_curator,
                        phone = EXCLUDED.phone,
                        max_id = EXCLUDED.max_id,
                        status = EXCLUDED.status,
                        ban_reason = EXCLUDED.ban_reason,
                        updated_at = now()
                    """,
                    user_id,
                    last_name,
                    first_name,
                    middle_name,
                    role_id[role_code],
                    id_curator,
                    phone,
                    max_id,
                    status,
                    ban_reason,
                )
                profiles_touched += 1

            # --- Core users (Keycloak mapping) ---
            await upsert_user(
                core["hr"], last_name="Иванова", first_name="Анна", middle_name=None,
                role_code="hr", phone="+79000000001", max_id=900001,
            )
            await upsert_user(
                core["curator"], last_name="Петров", first_name="Павел", middle_name=None,
                role_code="curator", max_id=900002,
            )
            await upsert_user(
                core["teacher"], last_name="Сидоров", first_name="Пётр", middle_name=None,
                role_code="teacher", phone="+79000000003", max_id=900003,
            )
            await upsert_user(
                core["employee"], last_name="Ким", first_name="Мария", middle_name="Алексеевна",
                role_code="employee", id_curator=core["curator"], max_id=900004,
            )
            await upsert_user(
                core["admin"], last_name="Администратор", first_name="Системный", middle_name=None,
                role_code="admin", phone="+79000000005", max_id=900005,
            )

            curator_ids: list[uuid.UUID] = [core["curator"]]
            for i in range(1, 8):
                cid = _uid("curator", i)
                curator_ids.append(cid)
                is_f = i % 2 == 0
                await upsert_user(
                    cid,
                    last_name=RNG.choice(LAST_NAMES),
                    first_name=RNG.choice(FIRST_NAMES_F if is_f else FIRST_NAMES_M),
                    middle_name=RNG.choice(MIDDLE_NAMES),
                    role_code="curator",
                    phone=f"+7901{RNG.randint(1000000, 9999999)}",
                    max_id=901000 + i,
                )

            teacher_ids: list[uuid.UUID] = [core["teacher"]]
            for i in range(1, 12):
                tid = _uid("teacher", i)
                teacher_ids.append(tid)
                is_f = i % 3 == 0
                await upsert_user(
                    tid,
                    last_name=RNG.choice(LAST_NAMES),
                    first_name=RNG.choice(FIRST_NAMES_F if is_f else FIRST_NAMES_M),
                    middle_name=RNG.choice(MIDDLE_NAMES),
                    role_code="teacher",
                    phone=f"+7902{RNG.randint(1000000, 9999999)}",
                    max_id=902000 + i,
                )

            employee_ids: list[uuid.UUID] = [core["employee"]]
            for i in range(1, 76):
                eid = _uid("employee", i)
                employee_ids.append(eid)
                is_f = i % 2 == 0
                curator = RNG.choice(curator_ids)
                await upsert_user(
                    eid,
                    last_name=LAST_NAMES[i % len(LAST_NAMES)],
                    first_name=RNG.choice(FIRST_NAMES_F if is_f else FIRST_NAMES_M),
                    middle_name=RNG.choice(MIDDLE_NAMES),
                    role_code="employee",
                    id_curator=curator,
                    phone=f"+7903{RNG.randint(1000000, 9999999)}" if i % 4 else None,
                    max_id=910000 + i if i % 3 else None,
                )

            # 5 manually banned employees
            for i in range(5):
                eid = _uid("employee", 76 + i)
                employee_ids.append(eid)
                await upsert_user(
                    eid,
                    last_name=LAST_NAMES[(76 + i) % len(LAST_NAMES)],
                    first_name=RNG.choice(FIRST_NAMES_M),
                    middle_name=RNG.choice(MIDDLE_NAMES),
                    role_code="employee",
                    id_curator=RNG.choice(curator_ids),
                    status="inactive",
                    ban_reason="ручной бан",
                    max_id=920000 + i,
                )

            groups_touched = 0
            tracks_touched = 0
            user_tracks_touched = 0
            slots_touched = 0
            direction_ids: list[uuid.UUID] = []
            working_group_ids: list[uuid.UUID] = []
            track_ids: list[uuid.UUID] = []
            slot_ids: list[uuid.UUID] = []

            for di, dir_name in enumerate(DIRECTIONS):
                did = _gid(di, -1)
                direction_ids.append(did)
                await conn.execute(
                    """
                    INSERT INTO app.groups (id, name, id_hr, id_parent, status)
                    VALUES ($1, $2, $3, NULL, 'active')
                    ON CONFLICT (id) DO UPDATE SET
                        name = EXCLUDED.name, id_hr = EXCLUDED.id_hr, status = EXCLUDED.status
                    """,
                    did,
                    dir_name,
                    core["hr"],
                )
                groups_touched += 1

                for gi, suffix in enumerate(GROUP_SUFFIXES):
                    gid = _gid(di, gi)
                    working_group_ids.append(gid)
                    status = "forming" if di == 4 and gi == 2 else "active"
                    await conn.execute(
                        """
                        INSERT INTO app.groups (id, name, id_hr, id_parent, status)
                        VALUES ($1, $2, $3, $4, $5)
                        ON CONFLICT (id) DO UPDATE SET
                            name = EXCLUDED.name, id_hr = EXCLUDED.id_hr,
                            id_parent = EXCLUDED.id_parent, status = EXCLUDED.status
                        """,
                        gid,
                        f"{dir_name}-{suffix}",
                        core["hr"],
                        did,
                        status,
                    )
                    groups_touched += 1

            for ti, (code, name, practice_required) in enumerate(TRACKS):
                tid = _tid(ti)
                row = await conn.fetchrow(
                    """
                    INSERT INTO app.tracks (id, code, name, practice_required, lecture_required, id_hr, status)
                    VALUES ($1, $2, $3, $4, 0, $5, 'active')
                    ON CONFLICT (code) DO UPDATE SET
                        name = EXCLUDED.name,
                        practice_required = EXCLUDED.practice_required,
                        id_hr = EXCLUDED.id_hr,
                        status = EXCLUDED.status,
                        updated_at = now()
                    RETURNING id
                    """,
                    tid,
                    code,
                    name,
                    practice_required,
                    core["hr"],
                )
                track_ids.append(row["id"])
                tracks_touched += 1

            slot_specs = [
                ("slot-09-00", "09:00", "09:00", 60),
                ("slot-10-30", "10:30", "10:30", 60),
                ("slot-12-00", "12:00", "12:00", 60),
                ("slot-14-00", "14:00", "14:00", 60),
                ("slot-15-30", "15:30", "15:30", 60),
            ]
            for si, (code, name, starts_at_local, duration_min) in enumerate(slot_specs):
                sid = _slotid(si)
                hour, minute = (int(part) for part in starts_at_local.split(":", 1))
                row = await conn.fetchrow(
                    """
                    INSERT INTO app.conveyor_slots (id, code, name, starts_at_local, duration_min, sort_order)
                    VALUES ($1, $2, $3, $4::time, $5, $6)
                    ON CONFLICT (code) DO UPDATE SET
                        name = EXCLUDED.name,
                        starts_at_local = EXCLUDED.starts_at_local,
                        duration_min = EXCLUDED.duration_min,
                        sort_order = EXCLUDED.sort_order,
                        updated_at = now()
                    RETURNING id
                    """,
                    sid,
                    code,
                    name,
                    time(hour, minute),
                    duration_min,
                    (si + 1) * 10,
                )
                slot_ids.append(row["id"])
                slots_touched += 1

            # Assign employees to groups (1–2 groups); ~6 without group
            ungrouped = set(_uid("employee", i) for i in range(70, 76))
            group_members: dict[uuid.UUID, list[uuid.UUID]] = {g: [] for g in working_group_ids}

            assignable = [e for e in employee_ids if e not in ungrouped]
            RNG.shuffle(assignable)
            for idx, eid in enumerate(assignable):
                g1 = working_group_ids[idx % len(working_group_ids)]
                group_members[g1].append(eid)
                if idx % 5 == 0:
                    g2 = working_group_ids[(idx + 3) % len(working_group_ids)]
                    if g2 != g1:
                        group_members[g2].append(eid)

            members_touched = 0
            for gid, members in group_members.items():
                for uid in members:
                    await conn.execute(
                        """
                        INSERT INTO app.group_members (group_id, user_id)
                        VALUES ($1, $2)
                        ON CONFLICT DO NOTHING
                        """,
                        gid,
                        uid,
                    )
                    members_touched += 1

            for idx, eid in enumerate(employee_ids):
                assigned_tracks = [track_ids[idx % len(track_ids)]]
                if idx % 7 == 0:
                    assigned_tracks.append(track_ids[(idx + 1) % len(track_ids)])
                if eid == core["employee"]:
                    assigned_tracks = track_ids[:]
                for track_id in assigned_tracks:
                    await conn.execute(
                        """
                        INSERT INTO app.user_tracks (user_id, track_id, assigned_by, status)
                        VALUES ($1, $2, $3, 'active')
                        ON CONFLICT (user_id, track_id) DO UPDATE SET
                            assigned_by = EXCLUDED.assigned_by,
                            status = EXCLUDED.status,
                            completed_at = NULL,
                            updated_at = now()
                        """,
                        eid,
                        track_id,
                        core["hr"],
                    )
                    user_tracks_touched += 1

            smu_touched = 0
            smu_rows = await conn.fetch(
                "SELECT id, code FROM app.smu_patterns WHERE status = 'active' ORDER BY code"
            )
            for idx, eid in enumerate(employee_ids):
                if smu_rows:
                    pattern_id = smu_rows[idx % len(smu_rows)]["id"]
                    await conn.execute(
                        """
                        INSERT INTO app.user_smu (user_id, smu_pattern_id)
                        VALUES ($1, $2)
                        ON CONFLICT (user_id) DO UPDATE SET smu_pattern_id = EXCLUDED.smu_pattern_id, updated_at = now()
                        """,
                        eid,
                        pattern_id,
                    )
                    smu_touched += 1
                if idx < 10:
                    extra_date = (now + timedelta(days=idx % 5)).date()
                    await conn.execute(
                        """
                        INSERT INTO app.smu_extra_shifts (user_id, shift_date, note)
                        VALUES ($1, $2, $3)
                        ON CONFLICT (user_id, shift_date) DO NOTHING
                        """,
                        eid,
                        extra_date,
                        "демо допсмена",
                    )

            for gi, gid in enumerate(working_group_ids):
                teacher = teacher_ids[gi % len(teacher_ids)]
                await conn.execute(
                    "UPDATE app.groups SET instructor_id = $1 WHERE id = $2",
                    teacher,
                    gid,
                )

            lessons_touched = 0
            marks_touched = 0
            lesson_records: list[dict[str, Any]] = []
            lesson_idx = 0

            for gi, gid in enumerate(working_group_ids):
                teacher = teacher_ids[gi % len(teacher_ids)]
                members = group_members[gid]
                for li in range(4):
                    lesson_idx += 1
                    lid = _lid(lesson_idx)
                    track_id = track_ids[(gi + li) % len(track_ids)]
                    slot_id = slot_ids[li % len(slot_ids)]
                    offset_days = li - 2  # 2 past, 2 future
                    starts = now + timedelta(days=offset_days, hours=10 + li)
                    ends = starts + timedelta(hours=2)
                    ltype = "practice" if li % 2 else "lecture"
                    title = LESSON_TITLES[(gi + li) % len(LESSON_TITLES)]
                    await conn.execute(
                        """
                        INSERT INTO app.lessons (
                            id, group_id, reporting_group_id, track_id, slot_id,
                            teacher_id, starts_at, ends_at, place, lesson_type, title
                        )
                        VALUES ($1, $2, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                        ON CONFLICT (id) DO UPDATE SET
                            group_id = EXCLUDED.group_id,
                            reporting_group_id = EXCLUDED.reporting_group_id,
                            track_id = EXCLUDED.track_id,
                            slot_id = EXCLUDED.slot_id,
                            teacher_id = EXCLUDED.teacher_id,
                            starts_at = EXCLUDED.starts_at,
                            ends_at = EXCLUDED.ends_at,
                            place = EXCLUDED.place,
                            lesson_type = EXCLUDED.lesson_type,
                            title = EXCLUDED.title
                        """,
                        lid,
                        gid,
                        track_id,
                        slot_id,
                        teacher,
                        starts,
                        ends,
                        PLACES[(gi + li) % len(PLACES)],
                        ltype,
                        title,
                    )
                    lessons_touched += 1
                    lesson_records.append({"id": lid, "group_id": gid, "track_id": track_id, "teacher": teacher, "members": members, "past": offset_days < 0})

                    for uid in members:
                        await conn.execute(
                            """
                            INSERT INTO app.lesson_members (user_id, lesson_id, role_in_lesson, track_id)
                            VALUES ($1, $2, 'employee', $3)
                            ON CONFLICT (user_id, lesson_id) DO UPDATE SET
                                role_in_lesson = EXCLUDED.role_in_lesson,
                                track_id = EXCLUDED.track_id
                            """,
                            uid,
                            lid,
                            track_id,
                        )
                    await conn.execute(
                        """
                        INSERT INTO app.lesson_members (user_id, lesson_id, role_in_lesson, track_id)
                        VALUES ($1, $2, 'teacher', $3)
                        ON CONFLICT (user_id, lesson_id) DO UPDATE SET
                            role_in_lesson = 'teacher',
                            track_id = EXCLUDED.track_id
                        """,
                        teacher,
                        lid,
                        track_id,
                    )

                    if offset_days < 0 and members:
                        for uid in members:
                            roll = RNG.random()
                            if roll < 0.68:
                                status = "present"
                            elif roll < 0.84:
                                status = "late"
                            else:
                                status = "absent"
                            await conn.execute(
                                """
                                INSERT INTO app.attendance_marks (user_id, lesson_id, status, marked_by, subject_role, marked_by_role)
                                VALUES ($1, $2, $3, $4, 'employee', 'hr')
                                ON CONFLICT (user_id, lesson_id) DO UPDATE SET
                                    status = EXCLUDED.status,
                                    marked_by = EXCLUDED.marked_by,
                                    subject_role = EXCLUDED.subject_role,
                                    marked_by_role = EXCLUDED.marked_by_role,
                                    marked_at = now()
                                """,
                                uid,
                                lid,
                                status,
                                core["hr"],
                            )
                            marks_touched += 1
                        await conn.execute(
                            """
                            INSERT INTO app.attendance_marks (user_id, lesson_id, status, marked_by, subject_role, marked_by_role)
                            VALUES ($1, $2, 'present', $3, 'teacher', 'hr')
                            ON CONFLICT (user_id, lesson_id) DO UPDATE SET
                                status = EXCLUDED.status,
                                marked_by = EXCLUDED.marked_by,
                                subject_role = EXCLUDED.subject_role,
                                marked_by_role = EXCLUDED.marked_by_role,
                                marked_at = now()
                            """,
                            teacher,
                            lid,
                            core["hr"],
                        )
                        marks_touched += 1

            async def insert_lesson(
                *,
                day_offset: int,
                teacher_id: uuid.UUID,
                group_id: uuid.UUID,
                start_h: int,
                start_m: int,
                end_h: int,
                end_m: int,
                place: str,
                title: str,
                member_ids: list[uuid.UUID] | None = None,
            ) -> uuid.UUID:
                nonlocal lesson_idx, lessons_touched
                lesson_idx += 1
                lid = _lid(lesson_idx)
                track_id = track_ids[lesson_idx % len(track_ids)]
                slot_id = slot_ids[lesson_idx % len(slot_ids)]
                base = now.replace(hour=0, minute=0, second=0, microsecond=0)
                starts = base + timedelta(days=day_offset, hours=start_h, minutes=start_m)
                ends = base + timedelta(days=day_offset, hours=end_h, minutes=end_m)
                await conn.execute(
                    """
                    INSERT INTO app.lessons (
                        id, group_id, reporting_group_id, track_id, slot_id,
                        teacher_id, starts_at, ends_at, place, lesson_type, title
                    )
                    VALUES ($1, $2, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                    ON CONFLICT (id) DO UPDATE SET
                        group_id = EXCLUDED.group_id,
                        reporting_group_id = EXCLUDED.reporting_group_id,
                        track_id = EXCLUDED.track_id,
                        slot_id = EXCLUDED.slot_id,
                        teacher_id = EXCLUDED.teacher_id,
                        starts_at = EXCLUDED.starts_at,
                        ends_at = EXCLUDED.ends_at,
                        place = EXCLUDED.place,
                        lesson_type = EXCLUDED.lesson_type,
                        title = EXCLUDED.title
                    """,
                    lid,
                    group_id,
                    track_id,
                    slot_id,
                    teacher_id,
                    starts,
                    ends,
                    place,
                    "practice" if start_m else "lecture",
                    title,
                )
                lessons_touched += 1
                ids = member_ids if member_ids is not None else group_members.get(group_id, [])
                for uid in ids:
                    await conn.execute(
                        """
                        INSERT INTO app.lesson_members (user_id, lesson_id, role_in_lesson, track_id)
                        VALUES ($1, $2, 'employee', $3)
                        ON CONFLICT (user_id, lesson_id) DO UPDATE SET
                            role_in_lesson = EXCLUDED.role_in_lesson,
                            track_id = EXCLUDED.track_id
                        """,
                        uid,
                        lid,
                        track_id,
                    )
                await conn.execute(
                    """
                    INSERT INTO app.lesson_members (user_id, lesson_id, role_in_lesson, track_id)
                    VALUES ($1, $2, 'teacher', $3)
                    ON CONFLICT (user_id, lesson_id) DO UPDATE SET
                        role_in_lesson = 'teacher',
                        track_id = EXCLUDED.track_id
                    """,
                    teacher_id,
                    lid,
                    track_id,
                )
                lesson_records.append({
                    "id": lid,
                    "group_id": group_id,
                    "track_id": track_id,
                    "teacher": teacher_id,
                    "members": ids,
                    "past": day_offset < 0,
                })
                return lid

            # Time-grid demo: overlaps and conflicts for teacher.demo (this week)
            demo_group = working_group_ids[0]
            demo_subgroup = group_members[demo_group][:4]
            other_teacher = teacher_ids[1]
            schedule_specs = [
                (0, core["teacher"], demo_group, 10, 0, 11, 0, "Ауд. 301", "Пересечение A", demo_subgroup),
                (0, core["teacher"], working_group_ids[1], 10, 30, 11, 30, "Ауд. 301", "Пересечение B", None),
                (0, other_teacher, working_group_ids[2], 10, 15, 11, 15, "Ауд. 301", "Чужое в кабинете", None),
                (1, core["teacher"], demo_group, 14, 0, 15, 30, "Ауд. 205", "Группа: первое", demo_subgroup),
                (1, other_teacher, demo_group, 14, 45, 16, 0, "Лаб. 12", "Группа: второе", None),
                (0, core["teacher"], demo_group, 12, 0, 13, 0, "Онлайн", "Подгруппа 1", demo_subgroup[:2]),
                (0, core["teacher"], working_group_ids[3], 12, 30, 13, 30, "Онлайн", "Подгруппа 2", demo_subgroup[:2]),
                (2, core["teacher"], demo_group, 9, 0, 10, 0, "Ауд. 102", "Плотный день 1", None),
                (2, core["teacher"], working_group_ids[4], 9, 30, 10, 30, "Лаб. 12", "Плотный день 2", None),
                (2, teacher_ids[2], working_group_ids[5], 11, 0, 12, 0, "Ауд. 301", "Чужое утро", None),
                (2, core["teacher"], working_group_ids[6], 15, 0, 16, 0, "Ауд. 205", "Послеобед", None),
                (2, core["teacher"], working_group_ids[7], 16, 30, 17, 30, "Онлайн", "Вечер", None),
                (3, core["teacher"], demo_group, 11, 0, 12, 30, "Ауд. 301", "Четверг", None),
                (4, other_teacher, working_group_ids[8], 10, 0, 11, 0, "Ауд. 205", "Пятница чужое", None),
                (4, core["teacher"], working_group_ids[9], 10, 30, 11, 30, "Ауд. 205", "Пятница моё", None),
            ]
            for spec in schedule_specs:
                day_off, tid, gid, sh, sm, eh, em, place, title, members = spec
                await insert_lesson(
                    day_offset=day_off,
                    teacher_id=tid,
                    group_id=gid,
                    start_h=sh,
                    start_m=sm,
                    end_h=eh,
                    end_m=em,
                    place=place,
                    title=title,
                    member_ids=members,
                )

            notifications_touched = 0
            for idx, lesson in enumerate(lesson_records[:20]):
                for recipient, kind in (
                    (core["hr"], "lesson_reminder_1d"),
                    (core["curator"], "lesson_reminder_3h"),
                ):
                    if idx % 2 == 0:
                        await conn.execute(
                            """
                            INSERT INTO app.notifications (delivered_to, lesson_id, kind)
                            VALUES ($1, $2, $3)
                            ON CONFLICT (delivered_to, lesson_id, kind) DO NOTHING
                            """,
                            recipient,
                            lesson["id"],
                            kind,
                        )
                        notifications_touched += 1

            strikes_touched = 0
            strike_idx = 0

            async def insert_strike(
                user_id: uuid.UUID,
                *,
                strike_number: int,
                reason: str,
                status: str = "active",
                lesson_id: uuid.UUID | None = None,
                appeal_reason: str | None = None,
                resolved_by: uuid.UUID | None = None,
            ) -> uuid.UUID:
                nonlocal strike_idx, strikes_touched
                strike_idx += 1
                sid = _sid(strike_idx)
                appealed_at = now - timedelta(days=2) if status == "appealed" else None
                resolved_at = now - timedelta(days=1) if status == "revoked" else None
                await conn.execute(
                    """
                    WITH target_role_row AS (
                        SELECT r.code AS target_role
                        FROM app.profiles p
                        JOIN app.roles r ON r.id = p.role_id
                        WHERE p.user_id = $2
                    )
                    INSERT INTO app.strikes (
                        id, user_id, lesson_id, reason, strike_number, status,
                        appeal_reason, appealed_at, resolved_by, resolved_at, target_role
                    )
                    SELECT $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, target_role
                    FROM target_role_row
                    ON CONFLICT (id) DO UPDATE SET
                        reason = EXCLUDED.reason,
                        status = EXCLUDED.status,
                        strike_number = EXCLUDED.strike_number,
                        appeal_reason = EXCLUDED.appeal_reason,
                        appealed_at = EXCLUDED.appealed_at,
                        resolved_by = EXCLUDED.resolved_by,
                        resolved_at = EXCLUDED.resolved_at,
                        target_role = EXCLUDED.target_role
                    """,
                    sid,
                    user_id,
                    lesson_id,
                    reason,
                    strike_number,
                    status,
                    appeal_reason,
                    appealed_at,
                    resolved_by,
                    resolved_at,
                )
                strikes_touched += 1
                return sid

            strike_targets = [e for e in employee_ids if e not in ungrouped][:40]
            past_lessons = [lr for lr in lesson_records if lr["past"]]

            # 1 active strike
            for eid in strike_targets[:18]:
                lesson = RNG.choice(past_lessons) if past_lessons else None
                await insert_strike(
                    eid,
                    strike_number=1,
                    reason=RNG.choice(STRIKE_REASONS),
                    lesson_id=lesson["id"] if lesson else None,
                )

            # 2 active strikes
            for eid in strike_targets[18:26]:
                for num in (1, 2):
                    await insert_strike(eid, strike_number=num, reason=RNG.choice(STRIKE_REASONS))

            # 3 strikes → banned
            for eid in strike_targets[26:31]:
                for num in (1, 2, 3):
                    await insert_strike(eid, strike_number=num, reason=RNG.choice(STRIKE_REASONS))
                await conn.execute(
                    """
                    UPDATE app.profiles
                    SET status = 'inactive', ban_reason = $2, updated_at = now()
                    WHERE user_id = $1
                    """,
                    eid,
                    STRIKE_BAN_REASON,
                )

            # Open appeals
            for eid in strike_targets[31:36]:
                await insert_strike(
                    eid,
                    strike_number=1,
                    reason="late",
                    status="appealed",
                    appeal_reason="Уважительная причина: справка от врача",
                )

            # Revoked strikes (resolved)
            for eid in strike_targets[36:40]:
                await insert_strike(
                    eid,
                    strike_number=1,
                    reason="absent",
                    status="revoked",
                    resolved_by=core["hr"],
                )

            # Teacher strikes do not block the teacher account.
            await insert_strike(
                core["teacher"],
                strike_number=1,
                reason="late",
                lesson_id=past_lessons[0]["id"] if past_lessons else None,
            )
            await insert_strike(
                core["teacher"],
                strike_number=2,
                reason="manual",
                lesson_id=past_lessons[1]["id"] if len(past_lessons) > 1 else None,
            )

            return {
                "users_touched": users_touched,
                "profiles_touched": profiles_touched,
                "groups_touched": groups_touched,
                "tracks_touched": tracks_touched,
                "user_tracks_touched": user_tracks_touched,
                "slots_touched": slots_touched,
                "smu_assignments_touched": smu_touched,
                "group_members_touched": members_touched,
                "lessons_touched": lessons_touched,
                "marks_touched": marks_touched,
                "strikes_touched": strikes_touched,
                "notifications_touched": notifications_touched,
                "employees_total": len(employee_ids),
                "curators_total": len(curator_ids),
                "teachers_total": len(teacher_ids),
                "working_groups_total": len(working_group_ids),
            }
