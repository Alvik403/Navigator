from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from audit import actor_from_user, write_audit_log
from auth_deps import AuthUser, require_hr
from domain import (
    add_smu_extra_shift,
    apply_smu_pattern_preset,
    assign_user_smu,
    assign_user_track,
    attendance_report_by_tracks,
    attendance_report_by_users,
    bulk_create_users,
    create_conveyor_slot,
    create_lesson,
    create_smu_pattern,
    create_strike,
    create_staff_remark,
    clear_smu_pattern_overrides,
    delete_smu_pattern,
    create_track,
    create_user,
    delete_lesson,
    delete_track,
    get_lesson_attendance,
    get_user_profile,
    hr_summary_report,
    list_conveyor_slots,
    list_hr_lessons,
    list_hr_notifications,
    list_hr_teachers,
    list_instructor_tracks,
    list_all_track_teacher_links,
    list_smu_extra_shifts,
    list_smu_pattern_overrides,
    list_smu_patterns,
    list_strikes,
    list_staff_remarks,
    list_track_assignments,
    list_tracks,
    list_user_attendance_issues,
    list_user_smu_assignments,
    list_users,
    recalculate_track_weights,
    remove_smu_extra_shift,
    remove_user_smu,
    set_smu_pattern_override,
    resolve_strike_appeal,
    revoke_latest_strike,
    save_lesson_attendance,
    select_formation_members,
    submit_strike_appeal,
    sync_curator_wards,
    sync_instructor_tracks,
    preview_formation_members,
    preview_formation_plan,
    preview_formation_plan_month,
    create_formation_plan_lessons,
    create_formation_plan_range,
    list_formation_auto_log,
    get_track,
    update_track_formation_settings,
    list_track_formation_slot_ids,
    run_auto_formation,
    resolve_track_instructor,
    update_lesson,
    update_track,
    update_smu_extra_shift,
    update_smu_pattern,
    update_user_profile,
    verify_lesson_hr_access,
    verify_user_role,
)

router = APIRouter(prefix="/api/v1/hr", tags=["HR"])


def _hr_scope(user: AuthUser) -> str | None:
    """Единая область данных для всех HR; личные уведомления — отдельно по app_user_id."""
    return None


class CreateUserBody(BaseModel):
    last_name: str = Field(min_length=1, max_length=255)
    first_name: str = Field(min_length=1, max_length=255)
    middle_name: str | None = None
    role_code: str = Field(default="employee")
    phone: str | None = None
    max_id: int | None = None
    status: str = "active"
    id_curator: str | None = None


class BulkUserRow(BaseModel):
    last_name: str = Field(min_length=1, max_length=255)
    first_name: str = Field(min_length=1, max_length=255)
    middle_name: str | None = None
    role_code: str = Field(default="employee")
    phone: str | None = None
    max_id: int | None = None
    status: str = "active"
    id_curator: str | None = None
    track: str | None = None


class BulkUsersBody(BaseModel):
    items: list[BulkUserRow] = Field(min_length=1)


class UpdateUserBody(BaseModel):
    role_code: str | None = None
    status: str | None = None
    ban_reason: str | None = None
    phone: str | None = None
    last_name: str | None = None
    first_name: str | None = None
    middle_name: str | None = None
    max_id: int | None = None
    id_curator: str | None = None
    clear_id_curator: bool = False


class CreateStrikeBody(BaseModel):
    user_id: str
    reason: str = Field(min_length=1)
    lesson_id: str | None = None
    strike_number: int | None = Field(default=None, ge=1, le=3)


class ResolveAppealBody(BaseModel):
    approved: bool


class AppealBody(BaseModel):
    appeal_reason: str = Field(min_length=1)


class HrCreateLessonBody(BaseModel):
    track_id: str
    slot_id: str | None = None
    teacher_id: str | None = None
    starts_at: datetime
    ends_at: datetime | None = None
    place: str | None = None
    lesson_type: str = Field(default="lecture", pattern="^(lecture|practice)$")
    title: str | None = Field(default=None, max_length=255)
    member_ids: list[str] | None = None
    auto_form: bool = False
    max_members: int = Field(default=12, ge=1, le=50)


class HrUpdateLessonBody(BaseModel):
    teacher_id: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    place: str | None = None
    lesson_type: str | None = Field(default=None, pattern="^(lecture|practice)$")
    title: str | None = Field(default=None, max_length=255)


class SmuPatternBody(BaseModel):
    code: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=255)
    work_days: int = Field(default=0, ge=0)
    off_days: int = Field(default=0, ge=0)
    anchor_date: date | None = None


class SmuPatternUpdateBody(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    work_days: int | None = Field(default=None, ge=0)
    off_days: int | None = Field(default=None, ge=0)
    anchor_date: date | None = None
    target_shift1: int | None = Field(default=None, ge=0)
    target_shift2: int | None = Field(default=None, ge=0)
    target_shift3: int | None = Field(default=None, ge=0)
    target_shift4: int | None = Field(default=None, ge=0)
    clear_target_shift1: bool = False
    clear_target_shift2: bool = False
    clear_target_shift3: bool = False
    clear_target_shift4: bool = False
    status: str | None = None


class AssignSmuBody(BaseModel):
    smu_pattern_id: str
    shift_number: int = Field(default=1, ge=1, le=4)


class SmuExtraShiftBody(BaseModel):
    user_id: str
    shift_date: date
    shift_number: int = Field(default=1, ge=1, le=4)
    note: str | None = None


class SmuExtraShiftUpdateBody(BaseModel):
    shift_date: date | None = None
    shift_number: int | None = Field(default=None, ge=1, le=4)
    note: str | None = None
    clear_note: bool = False


class SmuPatternOverrideBody(BaseModel):
    shift_date: date
    shift_number: int = Field(ge=1, le=4)
    period: str = Field(default="day", pattern="^(day|night)$")
    state: str = Field(pattern="^(day|night|extra_day|extra_night|off|auto)$")
    note: str | None = None


class SmuPatternPresetBody(BaseModel):
    preset: str = Field(pattern="^(2-2|3-3)$")
    anchor_date: date | None = None
    clear_overrides: bool = True


class TrackUpdateBody(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    practice_required: int | None = Field(default=None, ge=0)
    lecture_required: int | None = Field(default=None, ge=0)
    completion_days: int | None = Field(default=None, ge=1)
    status: str | None = None


class SyncCuratorWardsBody(BaseModel):
    user_ids: list[str] = Field(default_factory=list)


class SyncInstructorTracksBody(BaseModel):
    track_ids: list[str] = Field(default_factory=list)


class TrackBody(BaseModel):
    code: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    practice_required: int = Field(default=0, ge=0)
    lecture_required: int = Field(default=0, ge=0)
    completion_days: int = Field(default=90, ge=1)
    id_hr: str | None = None


class AssignTrackBody(BaseModel):
    track_id: str
    status: str = "active"
    due_date: date | None = None


class FormationPreviewBody(BaseModel):
    track_id: str
    lesson_date: date
    lesson_type: str = Field(default="practice", pattern="^(lecture|practice)$")
    max_members: int = Field(default=12, ge=1, le=50)


class FormationAutoRunBody(BaseModel):
    target_date: date | None = None
    lesson_type: str | None = Field(default=None, pattern="^(lecture|practice)$")
    max_members: int | None = Field(default=None, ge=1, le=50)


class FormationPlanBody(BaseModel):
    target_date: date
    lesson_type: str | None = Field(default=None, pattern="^(lecture|practice)$")
    include_disabled: bool = False


class FormationPlanMonthBody(BaseModel):
    month: str = Field(pattern=r"^\d{4}-\d{2}$")
    lesson_type: str | None = Field(default=None, pattern="^(lecture|practice)$")
    include_disabled: bool = False


class FormationPlanCreateBody(BaseModel):
    target_date: date
    items: list[dict[str, str]] = Field(default_factory=list)
    lesson_type: str | None = Field(default=None, pattern="^(lecture|practice)$")


class FormationPlanMonthCreateBody(BaseModel):
    month: str = Field(pattern=r"^\d{4}-\d{2}$")
    dates: list[date] | None = None
    items: list[dict[str, str]] = Field(default_factory=list)
    lesson_type: str | None = Field(default=None, pattern="^(lecture|practice)$")


class TrackFormationSettingsBody(BaseModel):
    formation_auto_enabled: bool | None = None
    formation_max_members: int | None = Field(default=None, ge=1, le=50)
    formation_min_members: int | None = Field(default=None, ge=1, le=50)
    formation_lock_days: int | None = Field(default=None, ge=0, le=90)
    formation_weight_penalty: float | None = Field(default=None, ge=0)
    formation_lesson_type: str | None = Field(default=None, pattern="^(lecture|practice)$")
    formation_default_place: str | None = None
    clear_default_place: bool = False
    slot_ids: list[str] | None = None


class ConveyorSlotBody(BaseModel):
    code: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=255)
    starts_at_local: str
    duration_min: int = Field(default=60, gt=0)
    timezone: str = "Europe/Moscow"
    sort_order: int = 0


class AttendanceMarkBody(BaseModel):
    user_id: str
    status: str = Field(pattern="^(present|late|absent)$")


class SaveAttendanceBody(BaseModel):
    marks: list[AttendanceMarkBody] = Field(min_length=1)


@router.get("/me")
async def hr_me(user: AuthUser = Depends(require_hr)) -> dict[str, Any]:
    profile = await get_user_profile(user.app_user_id or "")
    return {"username": user.username, "roles": user.roles, "profile": profile}


@router.get("/users")
async def hr_list_users(
    role: str | None = None,
    user: AuthUser = Depends(require_hr),
) -> dict[str, Any]:
    scope = _hr_scope(user)
    return {"items": await list_users(role, hr_user_id=scope)}


@router.post("/users")
async def hr_create_user(body: CreateUserBody, user: AuthUser = Depends(require_hr)) -> dict[str, Any]:
    try:
        profile = await create_user(
            last_name=body.last_name,
            first_name=body.first_name,
            middle_name=body.middle_name,
            role_code=body.role_code,
            phone=body.phone,
            max_id=body.max_id,
            status=body.status,
            id_curator=body.id_curator,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    actor_id, actor_name = actor_from_user(user)
    label = " ".join(filter(None, [profile.get("last_name"), profile.get("first_name")]))
    await write_audit_log(
        actor_user_id=actor_id,
        actor_name=actor_name,
        action="create",
        entity_type="user",
        entity_id=str(profile.get("id")),
        entity_label=label or str(profile.get("id")),
        payload=profile,
    )
    return profile


@router.post("/users/bulk")
async def hr_bulk_create_users(body: BulkUsersBody, user: AuthUser = Depends(require_hr)) -> dict[str, Any]:
    rows = [item.model_dump() for item in body.items]
    return await bulk_create_users(rows)


@router.patch("/users/{user_id}")
async def hr_update_user(
    user_id: str,
    body: UpdateUserBody,
    user: AuthUser = Depends(require_hr),
) -> dict[str, Any]:
    try:
        profile = await update_user_profile(
            user_id,
            role_code=body.role_code,
            status=body.status,
            ban_reason=body.ban_reason,
            phone=body.phone,
            last_name=body.last_name,
            first_name=body.first_name,
            middle_name=body.middle_name,
            max_id=body.max_id,
            update_max_id="max_id" in body.model_fields_set,
            id_curator=body.id_curator,
            clear_id_curator=body.clear_id_curator,
        )
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    actor_id, actor_name = actor_from_user(user)
    label = " ".join(filter(None, [profile.get("last_name"), profile.get("first_name")]))
    await write_audit_log(
        actor_user_id=actor_id,
        actor_name=actor_name,
        action="update",
        entity_type="user",
        entity_id=user_id,
        entity_label=label or user_id,
        payload=body.model_dump(exclude_unset=True),
    )
    return profile


@router.post("/curators/{curator_id}/wards/sync")
async def hr_sync_curator_wards(
    curator_id: str,
    body: SyncCuratorWardsBody,
    user: AuthUser = Depends(require_hr),
) -> dict[str, Any]:
    try:
        return await sync_curator_wards(curator_id, body.user_ids)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/instructors/track-links")
async def hr_list_track_teacher_links(user: AuthUser = Depends(require_hr)) -> dict[str, Any]:
    return {"items": await list_all_track_teacher_links()}


@router.get("/instructors/{teacher_id}/tracks")
async def hr_list_instructor_tracks(
    teacher_id: str,
    user: AuthUser = Depends(require_hr),
) -> dict[str, Any]:
    try:
        await verify_user_role(teacher_id, "teacher")
        return {"items": await list_instructor_tracks(teacher_id)}
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/instructors/{teacher_id}/tracks/sync")
async def hr_sync_instructor_tracks(
    teacher_id: str,
    body: SyncInstructorTracksBody,
    user: AuthUser = Depends(require_hr),
) -> dict[str, Any]:
    try:
        actor_id, actor_name = actor_from_user(user)
        return await sync_instructor_tracks(
            teacher_id,
            body.track_ids,
            actor_user_id=actor_id,
            actor_name=actor_name,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


class RevokeStrikeBody(BaseModel):
    comment: str = Field(min_length=1)


class UserStrikeBody(BaseModel):
    reason: str = Field(min_length=1, default="manual")


class StaffRemarkBody(BaseModel):
    text: str = Field(min_length=3)


@router.post("/users/{user_id}/strikes")
async def hr_add_user_strike(
    user_id: str,
    body: UserStrikeBody | None = None,
    user: AuthUser = Depends(require_hr),
) -> dict[str, Any]:
    try:
        reason = body.reason if body else "manual"
        return await create_strike(user_id=user_id, reason=reason)
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/users/{user_id}/strikes/revoke")
async def hr_revoke_user_strike(
    user_id: str,
    body: RevokeStrikeBody,
    user: AuthUser = Depends(require_hr),
) -> dict[str, Any]:
    try:
        return await revoke_latest_strike(
            user_id,
            resolved_by=user.app_user_id or "",
            comment=body.comment,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/users/{user_id}/remarks")
async def hr_list_user_remarks(
    user_id: str,
    user: AuthUser = Depends(require_hr),
) -> dict[str, Any]:
    return {"items": await list_staff_remarks(user_id)}


@router.post("/users/{user_id}/remarks")
async def hr_create_user_remark(
    user_id: str,
    body: StaffRemarkBody,
    user: AuthUser = Depends(require_hr),
) -> dict[str, Any]:
    try:
        return await create_staff_remark(
            user_id,
            body.text,
            issued_by=user.app_user_id or "",
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/teachers")
async def hr_list_teachers(user: AuthUser = Depends(require_hr)) -> dict[str, Any]:
    return {"items": await list_hr_teachers(hr_user_id=_hr_scope(user))}


@router.get("/tracks")
async def hr_list_tracks(user: AuthUser = Depends(require_hr)) -> dict[str, Any]:
    return {"items": await list_tracks(hr_user_id=_hr_scope(user))}


@router.post("/tracks")
async def hr_create_track(body: TrackBody, user: AuthUser = Depends(require_hr)) -> dict[str, Any]:
    if user.app_role_code != "admin" and body.id_hr and body.id_hr != user.app_user_id:
        raise HTTPException(status_code=403, detail="Нельзя создать трек для другого HR")
    track = await create_track(
        code=body.code,
        name=body.name,
        description=body.description,
        practice_required=body.practice_required,
        lecture_required=body.lecture_required,
        completion_days=body.completion_days,
        id_hr=body.id_hr or user.app_user_id,
    )
    actor_id, actor_name = actor_from_user(user)
    await write_audit_log(
        actor_user_id=actor_id,
        actor_name=actor_name,
        action="create",
        entity_type="track",
        entity_id=str(track.get("id")),
        entity_label=track.get("name"),
        payload=track,
    )
    return track


@router.post("/users/{user_id}/tracks")
async def hr_assign_user_track(
    user_id: str,
    body: AssignTrackBody,
    user: AuthUser = Depends(require_hr),
) -> dict[str, Any]:
    try:
        await verify_user_role(user_id, "employee")
        return await assign_user_track(
            user_id=user_id,
            track_id=body.track_id,
            assigned_by=user.app_user_id,
            status=body.status,
            due_date=body.due_date,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.patch("/tracks/{track_id}")
async def hr_update_track(
    track_id: str,
    body: TrackUpdateBody,
    user: AuthUser = Depends(require_hr),
) -> dict[str, Any]:
    try:
        return await update_track(
            track_id,
            name=body.name,
            description=body.description,
            practice_required=body.practice_required,
            lecture_required=body.lecture_required,
            completion_days=body.completion_days,
            status=body.status,
        )
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.delete("/tracks/{track_id}")
async def hr_delete_track(
    track_id: str,
    user: AuthUser = Depends(require_hr),
) -> dict[str, Any]:
    try:
        item = await delete_track(track_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    actor_id, actor_name = actor_from_user(user)
    await write_audit_log(
        actor_user_id=actor_id,
        actor_name=actor_name,
        action="delete",
        entity_type="track",
        entity_id=str(item.get("id")),
        entity_label=item.get("name"),
        payload=item,
    )
    return {"deleted": True, "item": item}


@router.get("/tracks/{track_id}/assignments")
async def hr_track_assignments(track_id: str, user: AuthUser = Depends(require_hr)) -> dict[str, Any]:
    return {"items": await list_track_assignments(track_id)}


@router.post("/tracks/{track_id}/recalculate-weights")
async def hr_recalculate_weights(
    track_id: str,
    force: bool = False,
    user: AuthUser = Depends(require_hr),
) -> dict[str, Any]:
    try:
        items = await recalculate_track_weights(track_id, force=force)
        return {"items": items, "updated": len(items)}
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/smu-patterns")
async def hr_list_smu_patterns(active_only: bool = False, user: AuthUser = Depends(require_hr)) -> dict[str, Any]:
    return {"items": await list_smu_patterns(active_only=active_only)}


@router.post("/smu-patterns")
async def hr_create_smu_pattern(body: SmuPatternBody, user: AuthUser = Depends(require_hr)) -> dict[str, Any]:
    return await create_smu_pattern(
        code=body.code,
        name=body.name,
        work_days=body.work_days,
        off_days=body.off_days,
        anchor_date=body.anchor_date,
    )


@router.patch("/smu-patterns/{pattern_id}")
async def hr_update_smu_pattern(
    pattern_id: str,
    body: SmuPatternUpdateBody,
    user: AuthUser = Depends(require_hr),
) -> dict[str, Any]:
    try:
        return await update_smu_pattern(
            pattern_id,
            name=body.name,
            work_days=body.work_days,
            off_days=body.off_days,
            anchor_date=body.anchor_date,
            target_shift1=body.target_shift1,
            target_shift2=body.target_shift2,
            target_shift3=body.target_shift3,
            target_shift4=body.target_shift4,
            clear_target_shift1=body.clear_target_shift1,
            clear_target_shift2=body.clear_target_shift2,
            clear_target_shift3=body.clear_target_shift3,
            clear_target_shift4=body.clear_target_shift4,
            status=body.status,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.delete("/smu-patterns/{pattern_id}")
async def hr_delete_smu_pattern(
    pattern_id: str,
    user: AuthUser = Depends(require_hr),
) -> dict[str, Any]:
    try:
        item = await delete_smu_pattern(pattern_id)
        return {"deleted": True, "item": item}
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/smu-patterns/{pattern_id}/overrides")
async def hr_list_smu_pattern_overrides(
    pattern_id: str,
    from_date: date | None = None,
    to_date: date | None = None,
    user: AuthUser = Depends(require_hr),
) -> dict[str, Any]:
    return {
        "items": await list_smu_pattern_overrides(
            pattern_id,
            from_date=from_date,
            to_date=to_date,
        )
    }


@router.put("/smu-patterns/{pattern_id}/overrides")
async def hr_set_smu_pattern_override(
    pattern_id: str,
    body: SmuPatternOverrideBody,
    user: AuthUser = Depends(require_hr),
) -> dict[str, Any]:
    try:
        state = None if body.state == "auto" else body.state
        item = await set_smu_pattern_override(
            pattern_id,
            shift_date=body.shift_date,
            shift_number=body.shift_number,
            period=body.period,
            state=state,
            note=body.note,
        )
        return {"item": item, "cleared": item is None and state is None}
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        if error.__class__.__name__ == "CheckViolationError":
            detail = str(error)
            if "shift_number" in detail:
                raise HTTPException(
                    status_code=400,
                    detail="Смены 3–4 не поддерживаются схемой БД — перезапустите max-auth для применения миграции 014",
                ) from error
            raise HTTPException(
                status_code=400,
                detail="Состояние «extra» не поддерживается схемой БД — перезапустите max-auth для применения миграции 013",
            ) from error
        raise


@router.delete("/smu-patterns/{pattern_id}/overrides")
async def hr_clear_smu_pattern_overrides(
    pattern_id: str,
    from_date: date | None = None,
    to_date: date | None = None,
    user: AuthUser = Depends(require_hr),
) -> dict[str, Any]:
    deleted = await clear_smu_pattern_overrides(
        pattern_id,
        from_date=from_date,
        to_date=to_date,
    )
    return {"deleted": deleted}


@router.post("/smu-patterns/{pattern_id}/apply-preset")
async def hr_apply_smu_pattern_preset(
    pattern_id: str,
    body: SmuPatternPresetBody,
    user: AuthUser = Depends(require_hr),
) -> dict[str, Any]:
    try:
        pattern = await apply_smu_pattern_preset(
            pattern_id,
            preset=body.preset,
            anchor_date=body.anchor_date,
            clear_overrides=body.clear_overrides,
        )
        return {"item": pattern}
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/smu-assignments")
async def hr_list_smu_assignments(user: AuthUser = Depends(require_hr)) -> dict[str, Any]:
    return {"items": await list_user_smu_assignments()}


@router.post("/users/{user_id}/smu")
async def hr_assign_user_smu(
    user_id: str,
    body: AssignSmuBody,
    user: AuthUser = Depends(require_hr),
) -> dict[str, Any]:
    try:
        await verify_user_role(user_id, "employee")
        return await assign_user_smu(
            user_id=user_id,
            smu_pattern_id=body.smu_pattern_id,
            shift_number=body.shift_number,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.delete("/users/{user_id}/smu")
async def hr_remove_user_smu(
    user_id: str,
    user: AuthUser = Depends(require_hr),
) -> dict[str, Any]:
    try:
        actor_id, actor_name = actor_from_user(user)
        return await remove_user_smu(
            user_id=user_id,
            actor_user_id=actor_id,
            actor_name=actor_name,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/smu-extra-shifts")
async def hr_list_extra_shifts(
    from_date: date | None = None,
    to_date: date | None = None,
    user: AuthUser = Depends(require_hr),
) -> dict[str, Any]:
    return {"items": await list_smu_extra_shifts(from_date=from_date, to_date=to_date)}


@router.post("/smu-extra-shifts")
async def hr_add_extra_shift(body: SmuExtraShiftBody, user: AuthUser = Depends(require_hr)) -> dict[str, Any]:
    try:
        await verify_user_role(body.user_id, "employee")
        return await add_smu_extra_shift(
            user_id=body.user_id,
            shift_date=body.shift_date,
            shift_number=body.shift_number,
            note=body.note,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.patch("/smu-extra-shifts/{shift_id}")
async def hr_update_extra_shift(
    shift_id: str,
    body: SmuExtraShiftUpdateBody,
    user: AuthUser = Depends(require_hr),
) -> dict[str, Any]:
    try:
        return await update_smu_extra_shift(
            shift_id,
            shift_date=body.shift_date,
            shift_number=body.shift_number,
            note=body.note,
            clear_note=body.clear_note,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.delete("/smu-extra-shifts/{shift_id}")
async def hr_remove_extra_shift(
    shift_id: str,
    user: AuthUser = Depends(require_hr),
) -> dict[str, Any]:
    try:
        actor_id, actor_name = actor_from_user(user)
        return await remove_smu_extra_shift(
            shift_id=shift_id,
            actor_user_id=actor_id,
            actor_name=actor_name,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/conveyor-slots")
async def hr_list_conveyor_slots(active_only: bool = False, user: AuthUser = Depends(require_hr)) -> dict[str, Any]:
    return {"items": await list_conveyor_slots(active_only=active_only)}


@router.post("/conveyor-slots")
async def hr_create_conveyor_slot(body: ConveyorSlotBody, user: AuthUser = Depends(require_hr)) -> dict[str, Any]:
    return await create_conveyor_slot(
        code=body.code,
        name=body.name,
        starts_at_local=body.starts_at_local,
        duration_min=body.duration_min,
        timezone=body.timezone,
        sort_order=body.sort_order,
    )


@router.get("/lessons")
async def hr_list_lessons(
    track_id: str | None = None,
    user: AuthUser = Depends(require_hr),
) -> dict[str, Any]:
    return {"items": await list_hr_lessons(hr_user_id=_hr_scope(user), track_id=track_id)}


@router.post("/formation/preview")
async def hr_formation_preview(
    body: FormationPreviewBody,
    user: AuthUser = Depends(require_hr),
) -> dict[str, Any]:
    try:
        return await preview_formation_members(
            track_id=body.track_id,
            lesson_date=body.lesson_date,
            lesson_type=body.lesson_type,
            max_members=body.max_members,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/formation/plan")
async def hr_formation_plan(
    body: FormationPlanBody,
    user: AuthUser = Depends(require_hr),
) -> dict[str, Any]:
    try:
        return await preview_formation_plan(
            target_date=body.target_date,
            lesson_type=body.lesson_type,
            include_disabled=body.include_disabled,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/formation/plan/month")
async def hr_formation_plan_month(
    body: FormationPlanMonthBody,
    user: AuthUser = Depends(require_hr),
) -> dict[str, Any]:
    try:
        return await preview_formation_plan_month(
            month=body.month,
            lesson_type=body.lesson_type,
            include_disabled=body.include_disabled,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/formation/plan/create")
async def hr_formation_plan_create(
    body: FormationPlanCreateBody,
    user: AuthUser = Depends(require_hr),
) -> dict[str, Any]:
    try:
        return await create_formation_plan_lessons(
            target_date=body.target_date,
            items=body.items or None,
            lesson_type=body.lesson_type,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/formation/plan/month/create")
async def hr_formation_plan_month_create(
    body: FormationPlanMonthCreateBody,
    user: AuthUser = Depends(require_hr),
) -> dict[str, Any]:
    try:
        return await create_formation_plan_range(
            month=body.month,
            dates=body.dates,
            items=body.items or None,
            lesson_type=body.lesson_type,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/formation/log")
async def hr_formation_log(
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    user: AuthUser = Depends(require_hr),
) -> dict[str, Any]:
    return {"items": await list_formation_auto_log(from_date=from_date, to_date=to_date, limit=limit)}


@router.get("/tracks/{track_id}/formation-settings")
async def hr_get_track_formation_settings(
    track_id: str,
    user: AuthUser = Depends(require_hr),
) -> dict[str, Any]:
    track = await get_track(track_id)
    if not track:
        raise HTTPException(status_code=404, detail="Трек не найден")
    track["formation_slot_ids"] = await list_track_formation_slot_ids(track_id)
    return track


@router.patch("/tracks/{track_id}/formation-settings")
async def hr_update_track_formation_settings(
    track_id: str,
    body: TrackFormationSettingsBody,
    user: AuthUser = Depends(require_hr),
) -> dict[str, Any]:
    try:
        return await update_track_formation_settings(
            track_id,
            formation_auto_enabled=body.formation_auto_enabled,
            formation_max_members=body.formation_max_members,
            formation_min_members=body.formation_min_members,
            formation_lock_days=body.formation_lock_days,
            formation_weight_penalty=body.formation_weight_penalty,
            formation_lesson_type=body.formation_lesson_type,
            formation_default_place=body.formation_default_place,
            clear_default_place=body.clear_default_place,
            slot_ids=body.slot_ids,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/formation/auto-run")
async def hr_formation_auto_run(
    body: FormationAutoRunBody,
    user: AuthUser = Depends(require_hr),
) -> dict[str, Any]:
    try:
        return await run_auto_formation(
            target_date=body.target_date,
            lesson_type=body.lesson_type,
            max_members=body.max_members,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/lessons")
async def hr_create_lesson(body: HrCreateLessonBody, user: AuthUser = Depends(require_hr)) -> dict[str, Any]:
    try:
        teacher_id = body.teacher_id or await resolve_track_instructor(body.track_id)
        if not teacher_id:
            raise ValueError("Нет инструктора на треке — назначьте во вкладке «Инструкторы»")
        await verify_user_role(teacher_id, "teacher")
        ends_at = body.ends_at or (body.starts_at + timedelta(hours=1))
        if ends_at <= body.starts_at:
            raise ValueError("Время окончания должно быть позже начала")
        member_ids = body.member_ids
        if body.auto_form and member_ids is None:
            lesson_date = body.starts_at.date()
            member_ids = await select_formation_members(
                track_id=body.track_id,
                lesson_date=lesson_date,
                lesson_type=body.lesson_type,
                max_members=body.max_members,
            )
            if not member_ids:
                raise ValueError("Нет подходящих сотрудников для формирования группы")
        return await create_lesson(
            track_id=body.track_id,
            slot_id=body.slot_id,
            teacher_id=teacher_id,
            starts_at=body.starts_at,
            ends_at=ends_at,
            place=body.place,
            lesson_type=body.lesson_type,
            title=body.title,
            member_ids=member_ids,
        )
    except ValueError as error:
        detail = str(error)
        if "доступ" in detail.lower():
            raise HTTPException(status_code=403, detail=detail) from error
        raise HTTPException(status_code=400, detail=detail) from error
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.patch("/lessons/{lesson_id}")
async def hr_update_lesson(
    lesson_id: str,
    body: HrUpdateLessonBody,
    user: AuthUser = Depends(require_hr),
) -> dict[str, Any]:
    try:
        await verify_lesson_hr_access(lesson_id, _hr_scope(user))
        if body.ends_at is not None and body.starts_at is not None and body.ends_at <= body.starts_at:
            raise HTTPException(status_code=400, detail="Время окончания должно быть позже начала")
        lesson = await update_lesson(
            lesson_id,
            teacher_id=body.teacher_id,
            starts_at=body.starts_at,
            ends_at=body.ends_at,
            place=body.place,
            lesson_type=body.lesson_type,
            title=body.title,
        )
        return {"ok": True, "item": lesson}
    except ValueError as error:
        detail = str(error)
        if "доступ" in detail.lower():
            raise HTTPException(status_code=403, detail=detail) from error
        raise HTTPException(status_code=404, detail=detail) from error
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.delete("/lessons/{lesson_id}")
async def hr_delete_lesson(lesson_id: str, user: AuthUser = Depends(require_hr)) -> dict[str, Any]:
    try:
        await verify_lesson_hr_access(lesson_id, _hr_scope(user))
        actor_id, actor_name = actor_from_user(user)
        await delete_lesson(
            lesson_id,
            actor_user_id=actor_id,
            actor_name=actor_name,
        )
        return {"ok": True, "id": lesson_id}
    except ValueError as error:
        detail = str(error)
        if "доступ" in detail.lower():
            raise HTTPException(status_code=403, detail=detail) from error
        raise HTTPException(status_code=404, detail=detail) from error


@router.get("/notifications")
async def hr_notifications(user: AuthUser = Depends(require_hr)) -> dict[str, Any]:
    return {"items": await list_hr_notifications(hr_user_id=user.app_user_id or "")}


@router.get("/strikes")
async def hr_list_strikes(status: str | None = None, user: AuthUser = Depends(require_hr)) -> dict[str, Any]:
    return {"items": await list_strikes(status=status, hr_user_id=_hr_scope(user))}


@router.get("/lessons/{lesson_id}/attendance")
async def hr_get_lesson_attendance(lesson_id: str, user: AuthUser = Depends(require_hr)) -> dict[str, Any]:
    try:
        await verify_lesson_hr_access(lesson_id, _hr_scope(user))
        return {"items": await get_lesson_attendance(lesson_id)}
    except ValueError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error


@router.post("/lessons/{lesson_id}/attendance")
async def hr_save_lesson_attendance(
    lesson_id: str,
    body: SaveAttendanceBody,
    user: AuthUser = Depends(require_hr),
) -> dict[str, Any]:
    try:
        await verify_lesson_hr_access(lesson_id, _hr_scope(user))
        marks = [{"user_id": m.user_id, "status": m.status} for m in body.marks]
        return {"items": await save_lesson_attendance(lesson_id, marks, user.app_user_id or "")}
    except ValueError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error


@router.post("/strikes")
async def hr_create_strike(body: CreateStrikeBody, user: AuthUser = Depends(require_hr)) -> dict[str, Any]:
    try:
        return await create_strike(
            user_id=body.user_id,
            reason=body.reason,
            lesson_id=body.lesson_id,
            strike_number=body.strike_number,
        )
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/strikes/{strike_id}/appeal")
async def hr_simulate_appeal(
    strike_id: str,
    body: AppealBody,
    user: AuthUser = Depends(require_hr),
) -> dict[str, Any]:
    try:
        return await submit_strike_appeal(strike_id, body.appeal_reason)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/appeals")
async def hr_list_appeals(user: AuthUser = Depends(require_hr)) -> dict[str, Any]:
    return {"items": await list_strikes(status="appealed", hr_user_id=_hr_scope(user))}


@router.post("/appeals/{strike_id}/resolve")
async def hr_resolve_appeal(
    strike_id: str,
    body: ResolveAppealBody,
    user: AuthUser = Depends(require_hr),
) -> dict[str, Any]:
    try:
        return await resolve_strike_appeal(
            strike_id,
            approved=body.approved,
            resolved_by=user.app_user_id or "",
        )
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/reports/summary")
async def hr_report_summary(user: AuthUser = Depends(require_hr)) -> dict[str, Any]:
    return await hr_summary_report(hr_user_id=_hr_scope(user))


@router.get("/reports/attendance/tracks")
async def hr_report_attendance_tracks(
    track_id: str | None = None,
    user: AuthUser = Depends(require_hr),
) -> dict[str, Any]:
    return {"items": await attendance_report_by_tracks(track_id, hr_user_id=_hr_scope(user))}


@router.get("/reports/attendance/users")
async def hr_report_attendance_users(
    track_id: str | None = None,
    user: AuthUser = Depends(require_hr),
) -> dict[str, Any]:
    return {"items": await attendance_report_by_users(track_id, hr_user_id=_hr_scope(user))}


@router.get("/attendance/users/{user_id}/issues")
async def hr_user_attendance_issues(
    user_id: str,
    user: AuthUser = Depends(require_hr),
) -> dict[str, Any]:
    return {"items": await list_user_attendance_issues(user_id, hr_user_id=_hr_scope(user))}
