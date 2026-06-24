from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from auth_deps import AuthUser, require_admin
from audit import (
    ACTION_LABELS,
    ENTITY_LABELS,
    actor_from_user,
    list_audit_logs,
    restore_audit_entry,
    write_audit_log,
)
from domain import create_user, get_user_profile, link_keycloak_user_id, list_users, update_user_profile
from keycloak_admin import (
    WEB_APP_ROLES,
    find_user_by_username,
    generate_password,
    keycloak_user_summary,
    provision_keycloak_account,
    set_password,
    sync_keycloak_account,
)

router = APIRouter(prefix="/api/v1/admin", tags=["Admin"])


class AdminCreateUserBody(BaseModel):
    last_name: str = Field(min_length=1, max_length=255)
    first_name: str = Field(min_length=1, max_length=255)
    middle_name: str | None = None
    role_code: str = Field(min_length=1, max_length=50)
    phone: str | None = None
    max_id: int | None = None
    status: str = "active"
    id_curator: str | None = None
    keycloak_username: str | None = Field(default=None, max_length=255)
    keycloak_email: str | None = None
    keycloak_password: str | None = Field(default=None, min_length=6, max_length=128)
    create_keycloak: bool = True

    @field_validator("keycloak_username")
    @classmethod
    def normalize_username(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class AdminUpdateUserBody(BaseModel):
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
    keycloak_username: str | None = None
    keycloak_email: str | None = None
    sync_keycloak: bool = True


class AdminKeycloakCreateBody(BaseModel):
    keycloak_username: str = Field(min_length=1, max_length=255)
    keycloak_email: str | None = None
    keycloak_password: str | None = Field(default=None, min_length=6, max_length=128)


class ResetPasswordBody(BaseModel):
    password: str | None = Field(default=None, min_length=6, max_length=128)
    temporary: bool = False


class LinkKeycloakBody(BaseModel):
    username: str = Field(min_length=1, max_length=255)


def _serialize_user(row: dict[str, Any], keycloak: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = dict(row)
    payload["keycloak"] = keycloak
    return payload


def _profile_label(row: dict[str, Any]) -> str:
    parts = [row.get("last_name"), row.get("first_name"), row.get("middle_name")]
    return " ".join(p for p in parts if p) or str(row.get("id") or "—")


async def _load_user_bundle(user_id: str) -> dict[str, Any]:
    profile = await get_user_profile(user_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    kc_id = profile.get("keycloak_user_id")
    keycloak = await keycloak_user_summary(str(kc_id) if kc_id else None)
    return _serialize_user(profile, keycloak)


async def _ensure_keycloak_for_new_user(
    profile: dict[str, Any],
    *,
    role_code: str,
    keycloak_username: str | None,
    keycloak_email: str | None,
    keycloak_password: str | None,
    create_keycloak: bool,
) -> tuple[dict[str, Any], str | None]:
    if role_code not in WEB_APP_ROLES or not create_keycloak:
        return profile, None

    username = keycloak_username
    if not username:
        raise HTTPException(
            status_code=400,
            detail="Для ролей admin/hr укажите логин Keycloak (keycloak_username)",
        )

    user_id = str(profile["id"])
    generated_password: str | None = None

    existing_kc = await find_user_by_username(username)
    if existing_kc:
        kc_id = str(existing_kc["id"])
        await link_keycloak_user_id(user_id, kc_id)
        await sync_keycloak_account(
            kc_id,
            email=keycloak_email or existing_kc.get("email"),
            first_name=str(profile.get("first_name") or ""),
            last_name=str(profile.get("last_name") or ""),
            app_role_code=role_code,
            max_id=profile.get("max_id"),
        )
    else:
        kc_id, generated_password = await provision_keycloak_account(
            username=username,
            email=keycloak_email,
            first_name=str(profile.get("first_name") or ""),
            last_name=str(profile.get("last_name") or ""),
            app_role_code=role_code,
            max_id=profile.get("max_id"),
            password=keycloak_password,
        )
        await link_keycloak_user_id(user_id, kc_id)

    refreshed = await get_user_profile(user_id)
    return refreshed or profile, generated_password


@router.get("/roles")
async def admin_list_roles(_user: AuthUser = Depends(require_admin)) -> dict[str, Any]:
    return {
        "items": [
            {"code": "admin", "name": "Администратор", "web_access": True},
            {"code": "hr", "name": "HR", "web_access": True},
            {"code": "teacher", "name": "Инструктор (MAX)", "web_access": False},
            {"code": "curator", "name": "Куратор", "web_access": False},
            {"code": "employee", "name": "Ученик", "web_access": False},
        ]
    }


@router.get("/users")
async def admin_list_users(
    role: str | None = None,
    _user: AuthUser = Depends(require_admin),
) -> dict[str, Any]:
    rows = await list_users(role, hr_user_id=None)
    items: list[dict[str, Any]] = []
    for row in rows:
        kc_id = row.get("keycloak_user_id")
        keycloak = await keycloak_user_summary(str(kc_id) if kc_id else None)
        items.append(_serialize_user(row, keycloak))
    return {"items": items}


@router.get("/users/{user_id}")
async def admin_get_user(user_id: str, _user: AuthUser = Depends(require_admin)) -> dict[str, Any]:
    return await _load_user_bundle(user_id)


@router.post("/users")
async def admin_create_user(
    body: AdminCreateUserBody,
    user: AuthUser = Depends(require_admin),
) -> dict[str, Any]:
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

    try:
        profile, generated_password = await _ensure_keycloak_for_new_user(
            profile,
            role_code=body.role_code,
            keycloak_username=body.keycloak_username,
            keycloak_email=body.keycloak_email,
            keycloak_password=body.keycloak_password,
            create_keycloak=body.create_keycloak,
        )
    except HTTPException:
        raise
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    bundle = await _load_user_bundle(str(profile["id"]))
    if generated_password:
        bundle["generated_keycloak_password"] = generated_password
    actor_id, actor_name = actor_from_user(user)
    await write_audit_log(
        actor_user_id=actor_id,
        actor_name=actor_name,
        action="create",
        entity_type="user",
        entity_id=str(bundle["id"]),
        entity_label=_profile_label(bundle),
        payload={k: v for k, v in bundle.items() if k not in ("keycloak", "generated_keycloak_password")},
    )
    return bundle


@router.patch("/users/{user_id}")
async def admin_update_user(
    user_id: str,
    body: AdminUpdateUserBody,
    user: AuthUser = Depends(require_admin),
) -> dict[str, Any]:
    existing = await get_user_profile(user_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

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
        raise HTTPException(status_code=400, detail=str(error)) from error

    role_code = str(profile.get("role_code") or "")
    kc_id = profile.get("keycloak_user_id")

    if body.keycloak_username and not kc_id:
        existing_kc = await find_user_by_username(body.keycloak_username.strip())
        if not existing_kc:
            raise HTTPException(status_code=404, detail="Пользователь Keycloak не найден")
        kc_id = str(existing_kc["id"])
        await link_keycloak_user_id(user_id, kc_id)
        profile = await get_user_profile(user_id) or profile

    if body.sync_keycloak and kc_id and role_code in WEB_APP_ROLES:
        try:
            await sync_keycloak_account(
                str(kc_id),
                email=body.keycloak_email,
                first_name=str(profile.get("first_name") or ""),
                last_name=str(profile.get("last_name") or ""),
                app_role_code=role_code,
                max_id=profile.get("max_id"),
            )
        except HTTPException as error:
            raise HTTPException(status_code=error.status_code, detail=error.detail) from error

    bundle = await _load_user_bundle(user_id)
    actor_id, actor_name = actor_from_user(user)
    await write_audit_log(
        actor_user_id=actor_id,
        actor_name=actor_name,
        action="update",
        entity_type="user",
        entity_id=user_id,
        entity_label=_profile_label(bundle),
        payload={
            "before": existing,
            "after": {k: v for k, v in bundle.items() if k != "keycloak"},
            "fields": sorted(body.model_fields_set),
        },
    )
    return bundle


@router.post("/users/{user_id}/keycloak/link")
async def admin_link_keycloak(
    user_id: str,
    body: LinkKeycloakBody,
    _user: AuthUser = Depends(require_admin),
) -> dict[str, Any]:
    profile = await get_user_profile(user_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    kc_user = await find_user_by_username(body.username.strip())
    if not kc_user:
        raise HTTPException(status_code=404, detail="Пользователь Keycloak не найден")

    await link_keycloak_user_id(user_id, str(kc_user["id"]))
    role_code = str(profile.get("role_code") or "")
    if role_code in WEB_APP_ROLES:
        await sync_keycloak_account(
            str(kc_user["id"]),
            email=kc_user.get("email"),
            first_name=str(profile.get("first_name") or ""),
            last_name=str(profile.get("last_name") or ""),
            app_role_code=role_code,
            max_id=profile.get("max_id"),
        )
    return await _load_user_bundle(user_id)


@router.post("/users/{user_id}/keycloak/create")
async def admin_create_keycloak(
    user_id: str,
    body: AdminKeycloakCreateBody,
    _user: AuthUser = Depends(require_admin),
) -> dict[str, Any]:
    profile = await get_user_profile(user_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    if profile.get("keycloak_user_id"):
        raise HTTPException(status_code=400, detail="Keycloak уже привязан")

    role_code = str(profile.get("role_code") or "")
    if role_code not in WEB_APP_ROLES:
        raise HTTPException(status_code=400, detail="Keycloak создаётся только для admin/hr")

    profile, generated_password = await _ensure_keycloak_for_new_user(
        profile,
        role_code=role_code,
        keycloak_username=body.keycloak_username,
        keycloak_email=body.keycloak_email,
        keycloak_password=body.keycloak_password,
        create_keycloak=True,
    )
    bundle = await _load_user_bundle(str(profile["id"]))
    if generated_password:
        bundle["generated_keycloak_password"] = generated_password
    return bundle


@router.post("/users/{user_id}/keycloak/reset-password")
async def admin_reset_keycloak_password(
    user_id: str,
    body: ResetPasswordBody,
    _user: AuthUser = Depends(require_admin),
) -> dict[str, Any]:
    profile = await get_user_profile(user_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    kc_id = profile.get("keycloak_user_id")
    if not kc_id:
        raise HTTPException(status_code=400, detail="Keycloak не привязан")

    password = body.password or generate_password()
    await set_password(str(kc_id), password, temporary=body.temporary)
    return {
        "status": "ok",
        "password": password,
        "temporary": body.temporary,
    }


@router.get("/audit-log/meta")
async def admin_audit_log_meta(_user: AuthUser = Depends(require_admin)) -> dict[str, Any]:
    return {
        "actions": [{"code": k, "label": v} for k, v in ACTION_LABELS.items()],
        "entity_types": [{"code": k, "label": v} for k, v in ENTITY_LABELS.items()],
    }


@router.get("/audit-log")
async def admin_list_audit_log(
    actor_user_id: str | None = None,
    action: str | None = None,
    entity_type: str | None = None,
    restorable_only: bool = False,
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _user: AuthUser = Depends(require_admin),
) -> dict[str, Any]:
    items = await list_audit_logs(
        actor_user_id=actor_user_id,
        action=action,
        entity_type=entity_type,
        restorable_only=restorable_only,
        limit=limit,
        offset=offset,
    )
    return {"items": items}


@router.post("/audit-log/{entry_id}/restore")
async def admin_restore_audit_log_entry(
    entry_id: str,
    user: AuthUser = Depends(require_admin),
) -> dict[str, Any]:
    actor_id, actor_name = actor_from_user(user)
    try:
        item = await restore_audit_entry(
            entry_id,
            actor_user_id=actor_id,
            actor_name=actor_name,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return item
