from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from auth_deps import AuthUser, require_hr
from domain import (
    add_group_member,
    attendance_report_by_groups,
    attendance_report_by_users,
    bulk_add_group_members,
    bulk_create_users,
    create_group,
    create_lesson,
    create_strike,
    create_user,
    get_group_members,
    get_user_profile,
    hr_summary_report,
    list_groups,
    list_hr_lessons,
    list_hr_notifications,
    list_hr_teachers,
    list_strikes,
    list_user_attendance_issues,
    list_users,
    remove_group_member,
    resolve_strike_appeal,
    revoke_latest_strike,
    submit_strike_appeal,
    update_group,
    update_user_profile,
    verify_group_hr_access,
    verify_user_role,
)

router = APIRouter(prefix="/api/v1/hr", tags=["HR"])


def _hr_scope(user: AuthUser) -> str | None:
    if user.app_role_code == "admin":
        return None
    return user.app_user_id


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


class CreateGroupBody(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    id_hr: str | None = None
    id_parent: str | None = None
    status: str = "active"


class UpdateGroupBody(BaseModel):
    name: str | None = None
    status: str | None = None
    id_hr: str | None = None
    id_parent: str | None = None


class GroupMemberBody(BaseModel):
    user_id: str


class BulkGroupMembersBody(BaseModel):
    user_ids: list[str] = Field(min_length=1)


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
    group_id: str
    teacher_id: str
    starts_at: datetime
    ends_at: datetime | None = None
    place: str | None = None
    lesson_type: str = Field(default="lecture", pattern="^(lecture|practice)$")
    title: str | None = Field(default=None, max_length=255)


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
        return await update_user_profile(
            user_id,
            role_code=body.role_code,
            status=body.status,
            ban_reason=body.ban_reason,
            phone=body.phone,
            last_name=body.last_name,
            first_name=body.first_name,
            middle_name=body.middle_name,
            max_id=body.max_id,
            id_curator=body.id_curator,
            clear_id_curator=body.clear_id_curator,
        )
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


class RevokeStrikeBody(BaseModel):
    comment: str = Field(min_length=1)


class UserStrikeBody(BaseModel):
    reason: str = Field(min_length=1, default="manual")


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


@router.get("/groups")
async def hr_list_groups(user: AuthUser = Depends(require_hr)) -> dict[str, Any]:
    scope = _hr_scope(user)
    items = await list_groups(hr_user_id=scope)
    for group in items:
        group["members"] = await get_group_members(group["id"])
    return {"items": items}


@router.post("/groups")
async def hr_create_group(body: CreateGroupBody, user: AuthUser = Depends(require_hr)) -> dict[str, Any]:
    hr_id = body.id_hr or user.app_user_id
    if user.app_role_code != "admin" and body.id_hr and body.id_hr != user.app_user_id:
        raise HTTPException(status_code=403, detail="Нельзя создать группу для другого HR")
    group = await create_group(name=body.name, id_hr=hr_id or "", id_parent=body.id_parent)
    if body.status != "active":
        group = await update_group(group["id"], status=body.status)
    return group


@router.patch("/groups/{group_id}")
async def hr_update_group(
    group_id: str,
    body: UpdateGroupBody,
    user: AuthUser = Depends(require_hr),
) -> dict[str, Any]:
    try:
        await verify_group_hr_access(group_id, _hr_scope(user))
        if user.app_role_code != "admin" and body.id_hr and body.id_hr != user.app_user_id:
            raise HTTPException(status_code=403, detail="Нельзя назначить другого HR")
        return await update_group(
            group_id,
            name=body.name,
            status=body.status,
            id_hr=body.id_hr,
            id_parent=body.id_parent,
        )
    except ValueError as error:
        raise HTTPException(status_code=403 if "доступ" in str(error).lower() else 404, detail=str(error)) from error


@router.post("/groups/{group_id}/members")
async def hr_add_member(
    group_id: str,
    body: GroupMemberBody,
    user: AuthUser = Depends(require_hr),
) -> dict[str, str]:
    try:
        await verify_group_hr_access(group_id, _hr_scope(user))
        await add_group_member(group_id, body.user_id)
    except ValueError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    return {"status": "ok"}


@router.post("/groups/{group_id}/members/bulk")
async def hr_bulk_add_members(
    group_id: str,
    body: BulkGroupMembersBody,
    user: AuthUser = Depends(require_hr),
) -> dict[str, Any]:
    try:
        await verify_group_hr_access(group_id, _hr_scope(user))
        return await bulk_add_group_members(group_id, body.user_ids)
    except ValueError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error


@router.delete("/groups/{group_id}/members/{member_id}")
async def hr_remove_member(
    group_id: str,
    member_id: str,
    user: AuthUser = Depends(require_hr),
) -> dict[str, str]:
    try:
        await verify_group_hr_access(group_id, _hr_scope(user))
        await remove_group_member(group_id, member_id)
    except ValueError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    return {"status": "ok"}


@router.get("/teachers")
async def hr_list_teachers(user: AuthUser = Depends(require_hr)) -> dict[str, Any]:
    return {"items": await list_hr_teachers(hr_user_id=_hr_scope(user))}


@router.get("/lessons")
async def hr_list_lessons(
    group_id: str | None = None,
    user: AuthUser = Depends(require_hr),
) -> dict[str, Any]:
    return {"items": await list_hr_lessons(hr_user_id=_hr_scope(user), group_id=group_id)}


@router.post("/lessons")
async def hr_create_lesson(body: HrCreateLessonBody, user: AuthUser = Depends(require_hr)) -> dict[str, Any]:
    try:
        await verify_group_hr_access(body.group_id, _hr_scope(user))
        await verify_user_role(body.teacher_id, "teacher")
        ends_at = body.ends_at or (body.starts_at + timedelta(hours=1))
        if ends_at <= body.starts_at:
            raise ValueError("Время окончания должно быть позже начала")
        return await create_lesson(
            group_id=body.group_id,
            teacher_id=body.teacher_id,
            starts_at=body.starts_at,
            ends_at=ends_at,
            place=body.place,
            lesson_type=body.lesson_type,
            title=body.title,
        )
    except ValueError as error:
        detail = str(error)
        if "доступ" in detail.lower():
            raise HTTPException(status_code=403, detail=detail) from error
        raise HTTPException(status_code=400, detail=detail) from error
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/notifications")
async def hr_notifications(user: AuthUser = Depends(require_hr)) -> dict[str, Any]:
    return {"items": await list_hr_notifications(hr_user_id=user.app_user_id or "")}


@router.get("/lessons")
async def hr_list_lessons(
    group_id: str | None = None,
    user: AuthUser = Depends(require_hr),
) -> dict[str, Any]:
    return {"items": await list_hr_lessons(group_id=group_id, hr_user_id=_hr_scope(user))}


@router.get("/strikes")
async def hr_list_strikes(status: str | None = None, user: AuthUser = Depends(require_hr)) -> dict[str, Any]:
    return {"items": await list_strikes(status=status, hr_user_id=_hr_scope(user))}


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


@router.get("/reports/attendance/groups")
async def hr_report_attendance_groups(
    group_id: str | None = None,
    user: AuthUser = Depends(require_hr),
) -> dict[str, Any]:
    return {"items": await attendance_report_by_groups(group_id, hr_user_id=_hr_scope(user))}


@router.get("/reports/attendance/users")
async def hr_report_attendance_users(
    group_id: str | None = None,
    user: AuthUser = Depends(require_hr),
) -> dict[str, Any]:
    return {"items": await attendance_report_by_users(group_id, hr_user_id=_hr_scope(user))}


@router.get("/attendance/users/{user_id}/issues")
async def hr_user_attendance_issues(
    user_id: str,
    user: AuthUser = Depends(require_hr),
) -> dict[str, Any]:
    return {"items": await list_user_attendance_issues(user_id, hr_user_id=_hr_scope(user))}
