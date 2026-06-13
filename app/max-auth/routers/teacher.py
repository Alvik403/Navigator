from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from auth_deps import AuthUser, require_teacher
from domain import (
    attendance_report_by_groups,
    attendance_report_by_users,
    create_lesson,
    delete_lesson,
    get_group_members,
    get_lesson_attendance,
    get_lesson_member_ids,
    get_user_profile,
    list_attendance_mark_history,
    list_lessons,
    list_teacher_groups,
    save_lesson_attendance,
    update_lesson,
    verify_teacher_group_access,
    verify_teacher_lesson_access,
)

router = APIRouter(prefix="/api/v1/teacher", tags=["Teacher"])


def _is_admin(user: AuthUser) -> bool:
    return user.app_role_code == "admin"


class CreateLessonBody(BaseModel):
    group_id: str
    teacher_id: str | None = None
    starts_at: datetime
    ends_at: datetime
    place: str | None = None
    lesson_type: str = Field(default="practice", pattern="^(lecture|practice)$")
    title: str | None = None
    member_ids: list[str] | None = None


class UpdateLessonBody(BaseModel):
    teacher_id: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    place: str | None = None
    lesson_type: str | None = Field(default=None, pattern="^(lecture|practice)$")
    title: str | None = None


class AttendanceMarkBody(BaseModel):
    user_id: str
    status: str = Field(pattern="^(present|late|absent)$")


class SaveAttendanceBody(BaseModel):
    marks: list[AttendanceMarkBody]


@router.get("/me")
async def teacher_me(user: AuthUser = Depends(require_teacher)) -> dict[str, Any]:
    profile = await get_user_profile(user.app_user_id or "")
    return {"username": user.username, "roles": user.roles, "profile": profile}


@router.get("/groups")
async def teacher_list_groups(user: AuthUser = Depends(require_teacher)) -> dict[str, Any]:
    items = await list_teacher_groups(user.app_user_id or "")
    for group in items:
        group["members"] = await get_group_members(group["id"])
    return {"items": items}


@router.get("/lessons")
async def teacher_list_lessons(
    group_id: str | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    all_teachers: bool = False,
    user: AuthUser = Depends(require_teacher),
) -> dict[str, Any]:
    teacher_id = None if all_teachers else user.app_user_id
    items = await list_lessons(
        teacher_id=teacher_id,
        group_id=group_id,
        from_date=from_date,
        to_date=to_date,
    )
    for item in items:
        item["member_ids"] = await get_lesson_member_ids(item["id"])
    return {"items": items}


@router.post("/lessons")
async def teacher_create_lesson(body: CreateLessonBody, user: AuthUser = Depends(require_teacher)) -> dict[str, Any]:
    teacher_id = body.teacher_id or user.app_user_id or ""
    if not _is_admin(user):
        teacher_id = user.app_user_id or ""
        try:
            await verify_teacher_group_access(body.group_id, user.app_user_id or "")
        except ValueError as error:
            raise HTTPException(status_code=403, detail=str(error)) from error
    try:
        lesson = await create_lesson(
            group_id=body.group_id,
            teacher_id=teacher_id,
            starts_at=body.starts_at,
            ends_at=body.ends_at,
            place=body.place,
            lesson_type=body.lesson_type,
            title=body.title,
            member_ids=body.member_ids,
        )
        lesson["member_ids"] = await get_lesson_member_ids(lesson["id"])
        return lesson
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.patch("/lessons/{lesson_id}")
async def teacher_update_lesson(
    lesson_id: str,
    body: UpdateLessonBody,
    user: AuthUser = Depends(require_teacher),
) -> dict[str, Any]:
    try:
        await verify_teacher_lesson_access(
            lesson_id,
            user.app_user_id or "",
            require_owner=not _is_admin(user),
            is_admin=_is_admin(user),
        )
        lesson = await update_lesson(
            lesson_id,
            teacher_id=body.teacher_id if _is_admin(user) else None,
            starts_at=body.starts_at,
            ends_at=body.ends_at,
            place=body.place,
            lesson_type=body.lesson_type,
            title=body.title,
        )
        lesson["member_ids"] = await get_lesson_member_ids(lesson_id)
        return lesson
    except ValueError as error:
        status = 403 if "свои" in str(error) or "доступ" in str(error) else 404
        raise HTTPException(status_code=status, detail=str(error)) from error


@router.delete("/lessons/{lesson_id}")
async def teacher_delete_lesson(lesson_id: str, user: AuthUser = Depends(require_teacher)) -> dict[str, Any]:
    try:
        await verify_teacher_lesson_access(
            lesson_id,
            user.app_user_id or "",
            require_owner=not _is_admin(user),
            is_admin=_is_admin(user),
        )
        await delete_lesson(lesson_id)
        return {"ok": True, "id": lesson_id}
    except ValueError as error:
        status = 403 if "свои" in str(error) or "доступ" in str(error) else 404
        raise HTTPException(status_code=status, detail=str(error)) from error


@router.get("/lessons/{lesson_id}/attendance")
async def teacher_get_attendance(lesson_id: str, user: AuthUser = Depends(require_teacher)) -> dict[str, Any]:
    try:
        await verify_teacher_lesson_access(lesson_id, user.app_user_id or "", is_admin=_is_admin(user))
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return {"items": await get_lesson_attendance(lesson_id)}


@router.post("/lessons/{lesson_id}/attendance")
async def teacher_save_attendance(
    lesson_id: str,
    body: SaveAttendanceBody,
    user: AuthUser = Depends(require_teacher),
) -> dict[str, Any]:
    try:
        await verify_teacher_lesson_access(
            lesson_id,
            user.app_user_id or "",
            require_owner=not _is_admin(user),
            is_admin=_is_admin(user),
        )
        marks = [{"user_id": m.user_id, "status": m.status} for m in body.marks]
        items = await save_lesson_attendance(lesson_id, marks, user.app_user_id or "")
    except ValueError as error:
        status = 403 if "свои" in str(error) or "доступ" in str(error) else 400
        raise HTTPException(status_code=status, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"items": items}


@router.get("/attendance/history")
async def teacher_attendance_history(
    lesson_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    user: AuthUser = Depends(require_teacher),
) -> dict[str, Any]:
    if lesson_id:
        try:
            await verify_teacher_lesson_access(lesson_id, user.app_user_id or "", is_admin=_is_admin(user))
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
    items = await list_attendance_mark_history(
        teacher_id=user.app_user_id or "",
        lesson_id=lesson_id,
        limit=limit,
    )
    return {"items": items}


@router.get("/reports/attendance/groups")
async def teacher_report_groups(
    group_id: str | None = None,
    user: AuthUser = Depends(require_teacher),
) -> dict[str, Any]:
    teacher_scope = None if _is_admin(user) else user.app_user_id
    return {
        "items": await attendance_report_by_groups(
            group_id,
            teacher_user_id=teacher_scope,
        )
    }


@router.get("/reports/attendance/users")
async def teacher_report_users(
    group_id: str | None = None,
    user: AuthUser = Depends(require_teacher),
) -> dict[str, Any]:
    teacher_scope = None if _is_admin(user) else user.app_user_id
    return {
        "items": await attendance_report_by_users(
            group_id,
            teacher_user_id=teacher_scope,
        )
    }
