"""Keycloak Admin API helpers for Навигатор user management."""

from __future__ import annotations

import logging
import secrets
import time
from typing import Any

import httpx
from fastapi import HTTPException

logger = logging.getLogger("max-auth")

KEYCLOAK_URL = __import__("os").getenv("KEYCLOAK_URL", "http://keycloak:8080")
KEYCLOAK_REALM = __import__("os").getenv("KEYCLOAK_REALM", "max-education")
KEYCLOAK_ADMIN = __import__("os").getenv("KEYCLOAK_ADMIN", "admin")
KEYCLOAK_ADMIN_PASSWORD = __import__("os").getenv("KEYCLOAK_ADMIN_PASSWORD", "admin")

WEB_REALM_ROLES = frozenset({"admin", "hr_manager"})
APP_ROLE_TO_KC_ROLES: dict[str, list[str]] = {
    "admin": ["admin", "hr_manager"],
    "hr": ["hr_manager"],
}
WEB_APP_ROLES = frozenset(APP_ROLE_TO_KC_ROLES.keys())

_admin_token: str | None = None
_admin_token_expires_at: float = 0.0


async def get_admin_token() -> str:
    global _admin_token, _admin_token_expires_at

    if _admin_token and time.time() < _admin_token_expires_at - 30:
        return _admin_token

    token_url = f"{KEYCLOAK_URL}/realms/master/protocol/openid-connect/token"
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            token_url,
            data={
                "grant_type": "password",
                "client_id": "admin-cli",
                "username": KEYCLOAK_ADMIN,
                "password": KEYCLOAK_ADMIN_PASSWORD,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    if response.status_code != 200:
        raise HTTPException(status_code=502, detail="Не удалось получить admin-токен Keycloak")

    payload = response.json()
    _admin_token = payload["access_token"]
    _admin_token_expires_at = time.time() + int(payload.get("expires_in", 60))
    return _admin_token


def _admin_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _realm_url(path: str = "") -> str:
    base = f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}"
    return f"{base}/{path.lstrip('/')}" if path else base


async def find_user_by_username(username: str) -> dict[str, Any] | None:
    token = await get_admin_token()
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(
            _realm_url("users"),
            params={"username": username, "exact": "true"},
            headers=_admin_headers(token),
        )
    if response.status_code != 200:
        raise HTTPException(status_code=502, detail="Не удалось найти пользователя в Keycloak")
    users = response.json()
    return users[0] if users else None


async def get_user(keycloak_user_id: str) -> dict[str, Any]:
    token = await get_admin_token()
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(
            _realm_url(f"users/{keycloak_user_id}"),
            headers=_admin_headers(token),
        )
    if response.status_code != 200:
        raise HTTPException(status_code=502, detail="Не удалось прочитать пользователя Keycloak")
    return response.json()


async def create_user(
    *,
    username: str,
    email: str | None,
    first_name: str,
    last_name: str,
    enabled: bool = True,
    email_verified: bool = True,
    attributes: dict[str, str] | None = None,
) -> str:
    existing = await find_user_by_username(username)
    if existing:
        raise ValueError(f"Пользователь Keycloak «{username}» уже существует")

    payload: dict[str, Any] = {
        "username": username,
        "firstName": first_name,
        "lastName": last_name,
        "enabled": enabled,
        "emailVerified": email_verified,
        "requiredActions": [],
    }
    if email:
        payload["email"] = email
    if attributes:
        payload["attributes"] = {key: [value] for key, value in attributes.items() if value}

    token = await get_admin_token()
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            _realm_url("users"),
            headers=_admin_headers(token),
            json=payload,
        )

    if response.status_code not in (201, 204):
        raise HTTPException(
            status_code=502,
            detail=f"Не удалось создать пользователя Keycloak: {response.text}",
        )

    created = await find_user_by_username(username)
    if not created:
        raise HTTPException(status_code=502, detail="Пользователь Keycloak создан, но не найден")
    return str(created["id"])


async def update_user(
    keycloak_user_id: str,
    *,
    email: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    enabled: bool | None = None,
    email_verified: bool | None = None,
    attributes: dict[str, str] | None = None,
    clear_required_actions: bool = True,
) -> None:
    user_data = await get_user(keycloak_user_id)
    payload: dict[str, Any] = {
        "username": user_data.get("username"),
        "email": email if email is not None else user_data.get("email"),
        "firstName": first_name if first_name is not None else user_data.get("firstName"),
        "lastName": last_name if last_name is not None else user_data.get("lastName"),
        "enabled": enabled if enabled is not None else user_data.get("enabled", True),
        "emailVerified": email_verified if email_verified is not None else user_data.get("emailVerified", True),
    }
    if clear_required_actions:
        payload["requiredActions"] = []
    if attributes is not None:
        merged = dict(user_data.get("attributes") or {})
        for key, value in attributes.items():
            if value:
                merged[key] = [value]
            elif key in merged:
                del merged[key]
        payload["attributes"] = merged

    token = await get_admin_token()
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.put(
            _realm_url(f"users/{keycloak_user_id}"),
            headers=_admin_headers(token),
            json=payload,
        )
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Не удалось обновить пользователя Keycloak: {response.text}")


async def set_password(keycloak_user_id: str, password: str, *, temporary: bool = False) -> None:
    token = await get_admin_token()
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.put(
            _realm_url(f"users/{keycloak_user_id}/reset-password"),
            headers=_admin_headers(token),
            json={"type": "password", "value": password, "temporary": temporary},
        )
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail="Не удалось установить пароль в Keycloak")


def generate_password() -> str:
    return secrets.token_urlsafe(10)


async def _get_role_representation(role_name: str) -> dict[str, Any]:
    token = await get_admin_token()
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(
            _realm_url(f"roles/{role_name}"),
            headers=_admin_headers(token),
        )
    if response.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Роль Keycloak «{role_name}» не найдена")
    return response.json()


async def get_user_realm_roles(keycloak_user_id: str) -> list[str]:
    token = await get_admin_token()
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(
            _realm_url(f"users/{keycloak_user_id}/role-mappings/realm"),
            headers=_admin_headers(token),
        )
    if response.status_code != 200:
        raise HTTPException(status_code=502, detail="Не удалось прочитать роли Keycloak")
    return [str(item.get("name")) for item in response.json() if item.get("name")]


async def sync_realm_roles_for_app_role(keycloak_user_id: str, app_role_code: str) -> None:
    desired = set(APP_ROLE_TO_KC_ROLES.get(app_role_code, []))
    current = set(await get_user_realm_roles(keycloak_user_id))
    current_web = current & WEB_REALM_ROLES

    to_remove = current_web - desired
    to_add = desired - current

    token = await get_admin_token()
    async with httpx.AsyncClient(timeout=15.0) as client:
        if to_remove:
            roles = [await _get_role_representation(name) for name in to_remove]
            response = await client.request(
                "DELETE",
                _realm_url(f"users/{keycloak_user_id}/role-mappings/realm"),
                headers=_admin_headers(token),
                json=roles,
            )
            if response.status_code >= 400:
                raise HTTPException(status_code=502, detail="Не удалось снять роли Keycloak")

        if to_add:
            roles = [await _get_role_representation(name) for name in to_add]
            response = await client.post(
                _realm_url(f"users/{keycloak_user_id}/role-mappings/realm"),
                headers=_admin_headers(token),
                json=roles,
            )
            if response.status_code >= 400:
                raise HTTPException(status_code=502, detail="Не удалось назначить роли Keycloak")


def read_max_id_attribute(user_data: dict[str, Any]) -> int | None:
    attrs = user_data.get("attributes") or {}
    raw = attrs.get("max_id")
    if not raw:
        return None
    value = raw[0] if isinstance(raw, list) else raw
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


async def keycloak_user_summary(keycloak_user_id: str | None) -> dict[str, Any] | None:
    if not keycloak_user_id:
        return None
    try:
        user_data = await get_user(keycloak_user_id)
    except HTTPException:
        return None
    roles = await get_user_realm_roles(keycloak_user_id)
    return {
        "id": keycloak_user_id,
        "username": user_data.get("username"),
        "email": user_data.get("email"),
        "enabled": user_data.get("enabled", True),
        "email_verified": user_data.get("emailVerified", False),
        "realm_roles": roles,
        "max_id": read_max_id_attribute(user_data),
    }


async def provision_keycloak_account(
    *,
    username: str,
    email: str | None,
    first_name: str,
    last_name: str,
    app_role_code: str,
    max_id: int | None,
    password: str | None = None,
) -> tuple[str, str | None]:
    """Create Keycloak user, set password and roles. Returns (keycloak_user_id, password)."""
    attrs: dict[str, str] = {}
    if max_id is not None:
        attrs["max_id"] = str(max_id)

    kc_id = await create_user(
        username=username,
        email=email,
        first_name=first_name,
        last_name=last_name,
        attributes=attrs or None,
    )

    temp_password = password or generate_password()
    await set_password(kc_id, temp_password, temporary=False)

    if app_role_code in WEB_APP_ROLES:
        await sync_realm_roles_for_app_role(kc_id, app_role_code)

    return kc_id, None if password else temp_password


async def sync_keycloak_account(
    keycloak_user_id: str,
    *,
    email: str | None,
    first_name: str,
    last_name: str,
    app_role_code: str,
    max_id: int | None,
) -> None:
    attrs: dict[str, str] = {}
    if max_id is not None:
        attrs["max_id"] = str(max_id)
    elif max_id is None:
        attrs["max_id"] = ""

    await update_user(
        keycloak_user_id,
        email=email,
        first_name=first_name,
        last_name=last_name,
        attributes=attrs,
    )
    if app_role_code in WEB_APP_ROLES:
        await sync_realm_roles_for_app_role(keycloak_user_id, app_role_code)
