import base64
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from db import get_pool, serialize_record
from domain import (
    get_app_user_id_by_keycloak_id,
    link_keycloak_user_id,
    provision_keycloak_user,
    update_user_profile,
)

logger = logging.getLogger("max-auth")

KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "http://keycloak:8080")
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "max-education")
KEYCLOAK_CLIENT_ID = os.getenv("KEYCLOAK_CLIENT_ID", "")
KEYCLOAK_CLIENT_SECRET = os.getenv("KEYCLOAK_CLIENT_SECRET", "")

# Legacy demo mapping (Keycloak username → app.users.id). New users resolve via keycloak_user_id.
KC_USERNAME_TO_APP_USER: dict[str, str] = {
    "hr.manager": "11111111-1111-1111-1111-111111111111",
    "admin": "55555555-5555-5555-5555-555555555555",
}

KC_ROLE_TO_APP_ROLE: list[tuple[str, str]] = [
    ("admin", "admin"),
    ("hr_manager", "hr"),
]
HR_ROLES = {"hr_manager"}
APP_HR_ROLES = {"hr", "admin"}

security = HTTPBearer(auto_error=False)


@dataclass
class AuthUser:
    username: str
    roles: list[str]
    app_user_id: str | None
    app_role_code: str | None
    app_profile: dict[str, Any] | None
    profile: dict[str, Any]


def decode_jwt_payload(token: str) -> dict[str, Any]:
    try:
        segment = token.split(".")[1]
        padded = segment + "=" * ((4 - len(segment) % 4) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        return json.loads(raw)
    except (IndexError, ValueError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=401, detail="Некорректный токен") from error


def extract_roles(access_token: str, profile: dict[str, Any]) -> list[str]:
    payload = decode_jwt_payload(access_token)
    realm_roles = payload.get("realm_access", {}).get("roles", [])
    direct_roles = payload.get("roles", [])
    profile_roles = profile.get("realm_access", {}).get("roles", []) if isinstance(profile.get("realm_access"), dict) else []
    profile_direct = profile.get("roles", []) if isinstance(profile.get("roles"), list) else []
    return list({*realm_roles, *direct_roles, *profile_roles, *profile_direct})


async def fetch_userinfo(access_token: str) -> dict[str, Any]:
    url = f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/userinfo"
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(url, headers={"Authorization": f"Bearer {access_token}"})
    if response.status_code != 200:
        raise HTTPException(status_code=401, detail="Токен недействителен или истёк")
    return response.json()


def _profile_from_jwt_payload(payload: dict[str, Any]) -> dict[str, Any]:
    exp = payload.get("exp")
    if exp is not None and int(exp) < time.time():
        raise HTTPException(status_code=401, detail="Токен недействителен или истёк")
    iss = str(payload.get("iss", ""))
    if iss and KEYCLOAK_REALM not in iss:
        raise HTTPException(status_code=401, detail="Некорректный issuer токена")
    return {
        "preferred_username": payload.get("preferred_username") or payload.get("username"),
        "email": payload.get("email"),
        "given_name": payload.get("given_name"),
        "family_name": payload.get("family_name"),
        "name": payload.get("name"),
        "sub": payload.get("sub"),
        "realm_access": payload.get("realm_access") if isinstance(payload.get("realm_access"), dict) else {},
        "roles": payload.get("roles") if isinstance(payload.get("roles"), list) else [],
    }


async def _introspect_token(access_token: str) -> dict[str, Any]:
    if not KEYCLOAK_CLIENT_ID or not KEYCLOAK_CLIENT_SECRET:
        raise HTTPException(status_code=401, detail="Introspection недоступен")
    url = f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/token/introspect"
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            url,
            data={
                "client_id": KEYCLOAK_CLIENT_ID,
                "client_secret": KEYCLOAK_CLIENT_SECRET,
                "token": access_token,
            },
        )
    if response.status_code != 200:
        raise HTTPException(status_code=401, detail="Токен недействителен или истёк")
    data = response.json()
    if not data.get("active"):
        raise HTTPException(status_code=401, detail="Токен недействителен или истёк")
    return {
        "preferred_username": data.get("preferred_username") or data.get("username"),
        "email": data.get("email"),
        "given_name": data.get("given_name"),
        "family_name": data.get("family_name"),
        "name": data.get("name"),
        "sub": data.get("sub"),
        "realm_access": {"roles": data.get("realm_access", {}).get("roles", []) if isinstance(data.get("realm_access"), dict) else []},
    }


async def resolve_token_profile(access_token: str) -> dict[str, Any]:
    """Userinfo → introspection → JWT payload (dev/proxy hostname mismatch)."""
    try:
        return await fetch_userinfo(access_token)
    except HTTPException:
        pass
    try:
        return await _introspect_token(access_token)
    except HTTPException:
        pass
    return _profile_from_jwt_payload(decode_jwt_payload(access_token))


def resolve_app_role_from_keycloak_roles(roles: list[str]) -> str | None:
    role_set = set(roles)
    for kc_role, app_role in KC_ROLE_TO_APP_ROLE:
        if kc_role in role_set:
            return app_role
    return None


def profile_names_from_keycloak(profile: dict[str, Any], username: str) -> tuple[str, str]:
    last_name = str(profile.get("family_name") or "").strip()
    first_name = str(profile.get("given_name") or "").strip()
    if not last_name and not first_name:
        full_name = str(profile.get("name") or "").strip()
        if full_name:
            parts = full_name.split()
            if len(parts) == 1:
                return parts[0], "-"
            return parts[-1], " ".join(parts[:-1])
        fallback = username.strip() or "User"
        return fallback, "-"
    if not last_name:
        return first_name, "-"
    if not first_name:
        return last_name, "-"
    return last_name, first_name


async def _sync_max_id_from_keycloak(
    app_user_id: str | None,
    app_profile: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not app_user_id or not app_profile:
        return app_profile
    if app_profile.get("max_id") is not None:
        return app_profile
    kc_id = app_profile.get("keycloak_user_id")
    if not kc_id:
        return app_profile
    try:
        from keycloak_admin import keycloak_user_summary

        keycloak = await keycloak_user_summary(str(kc_id))
        if keycloak and keycloak.get("max_id") is not None:
            return await update_user_profile(
                app_user_id,
                max_id=int(keycloak["max_id"]),
                update_max_id=True,
            )
    except (ValueError, RuntimeError, HTTPException) as error:
        logger.warning("Failed to sync max_id from Keycloak for %s: %s", app_user_id, error)
    return app_profile


async def resolve_app_user_id(
    *,
    username: str,
    keycloak_user_id: str | None,
    roles: list[str],
    profile: dict[str, Any],
) -> str | None:
    app_user_id = KC_USERNAME_TO_APP_USER.get(username)

    if keycloak_user_id:
        if app_user_id:
            try:
                await link_keycloak_user_id(app_user_id, keycloak_user_id)
            except (ValueError, RuntimeError) as error:
                logger.warning("Failed to link Keycloak user %s to %s: %s", keycloak_user_id, app_user_id, error)
        else:
            try:
                app_user_id = await get_app_user_id_by_keycloak_id(keycloak_user_id)
            except (ValueError, RuntimeError):
                app_user_id = None

    if app_user_id or not keycloak_user_id:
        return app_user_id

    app_role = resolve_app_role_from_keycloak_roles(roles)
    if not app_role:
        return None

    last_name, first_name = profile_names_from_keycloak(profile, username)
    try:
        provisioned = await provision_keycloak_user(
            keycloak_user_id=keycloak_user_id,
            role_code=app_role,
            last_name=last_name,
            first_name=first_name,
        )
    except (ValueError, RuntimeError) as error:
        logger.warning("Auto-provision failed for Keycloak user %s: %s", keycloak_user_id, error)
        try:
            return await get_app_user_id_by_keycloak_id(keycloak_user_id)
        except (ValueError, RuntimeError):
            return None

    return str(provisioned.get("id")) if provisioned.get("id") else None


async def fetch_app_profile(app_user_id: str | None) -> dict[str, Any] | None:
    if not app_user_id:
        return None
    sql = """
        SELECT u.id, u.keycloak_user_id, u.is_active,
               p.last_name, p.first_name, p.middle_name, p.phone, p.max_id, p.status,
               r.code AS role_code, r.name AS role_name
        FROM app.users u
        JOIN app.profiles p ON p.user_id = u.id
        JOIN app.roles r ON r.id = p.role_id
        WHERE u.id = $1::uuid
    """
    try:
        async with get_pool().acquire() as conn:
            row = await conn.fetchrow(sql, uuid.UUID(app_user_id))
    except RuntimeError:
        return None
    return serialize_record(row) if row else None


async def get_auth_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> AuthUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Требуется Bearer-токен")

    profile = await resolve_token_profile(credentials.credentials)
    username = profile.get("preferred_username") or profile.get("email") or ""
    roles = extract_roles(credentials.credentials, profile)
    keycloak_user_id = profile.get("sub")
    app_user_id = await resolve_app_user_id(
        username=str(username),
        keycloak_user_id=str(keycloak_user_id) if keycloak_user_id else None,
        roles=roles,
        profile=profile,
    )
    app_profile = await fetch_app_profile(app_user_id)
    app_profile = await _sync_max_id_from_keycloak(app_user_id, app_profile)

    return AuthUser(
        username=str(username),
        roles=roles,
        app_user_id=app_user_id,
        app_role_code=app_profile.get("role_code") if app_profile else None,
        app_profile=app_profile,
        profile=profile,
    )


async def require_hr(user: AuthUser = Depends(get_auth_user)) -> AuthUser:
    if user.app_role_code not in APP_HR_ROLES and not HR_ROLES.intersection(user.roles):
        raise HTTPException(status_code=403, detail="Доступ только для HR")
    if not user.app_user_id:
        raise HTTPException(status_code=403, detail="Пользователь не привязан к записи в БД")
    return user


async def require_admin(user: AuthUser = Depends(get_auth_user)) -> AuthUser:
    if user.app_role_code != "admin":
        raise HTTPException(status_code=403, detail="Доступ только для системного администратора")
    if not user.app_user_id:
        raise HTTPException(status_code=403, detail="Пользователь не привязан к записи в БД")
    return user
