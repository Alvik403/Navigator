import asyncio
import logging
import os
import secrets
import time
import uuid
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlencode

import httpx
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, model_validator

from auth_deps import AuthUser, get_auth_user
from bot_events import MaxReplyTarget, extract_reply_target
from bot_handlers import (
    AUTH_APP_ROLES,
    MAX_USER_MAP,
    handle_bot_started_plain,
    handle_employee_callback,
    handle_message_created,
    lookup_keycloak_credentials,
    resolve_bot_account,
    route_welcome,
    send_unknown_user_message,
)
from db import (
    apply_schema,
    close_database,
    connect_database,
    database_health,
    get_schema_summary,
    list_tables,
    run_readonly_query,
    seed_demo_data,
    seed_formation_test_data,
)
from lesson_reminder_worker import LESSON_REMINDER_ENABLED, run_lesson_reminder_worker
from formation_worker import FORMATION_AUTO_ENABLED, run_formation_auto_worker
from max_client import (
    MAX_BOT_API_URL,
    answer_max_callback,
    auth_headers,
    extract_max_user_id,
    send_max_message,
)
from routers.admin import router as admin_router
from routers.hr import router as hr_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("max-auth")

KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "http://keycloak:8080")
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "max-education")
KEYCLOAK_CLIENT_ID = os.getenv("KEYCLOAK_CLIENT_ID", "max-auth-service")
KEYCLOAK_CLIENT_SECRET = os.getenv("KEYCLOAK_CLIENT_SECRET", "max-auth-service-secret")
SESSION_TTL_SECONDS = int(os.getenv("MAX_SESSION_TTL", "300"))
POLL_INTERVAL_MS = int(os.getenv("MAX_POLL_INTERVAL_MS", "2000"))
MAX_BOT_BASE_URL = os.getenv("MAX_BOT_BASE_URL", "https://max.ru/id482403059838_2_bot")
MAX_AUTH_PAYLOAD_PREFIX = os.getenv("MAX_AUTH_PAYLOAD_PREFIX", "login_")
MAX_RESET_PAYLOAD_PREFIX = os.getenv("MAX_RESET_PAYLOAD_PREFIX", "reset_")
WEB_RETURN_URL = os.getenv("WEB_RETURN_URL", "http://localhost:5173/max")
WEB_URL = os.getenv("WEB_URL", "http://localhost:5173")
KEYCLOAK_ADMIN = os.getenv("KEYCLOAK_ADMIN", "admin")
KEYCLOAK_ADMIN_PASSWORD = os.getenv("KEYCLOAK_ADMIN_PASSWORD", "admin")
MAX_BOT_TOKEN = os.getenv("MAX_BOT_TOKEN", "")

SessionMode = Literal["login", "reset"]
SessionStatus = Literal["pending", "confirmed", "rejected", "expired", "exchanged", "password_reset"]


@dataclass
class MaxSession:
    session_id: str
    auth_token: str
    status: SessionStatus
    mode: SessionMode
    created_at: float
    expires_at: float
    max_user_id: str | None = None
    keycloak_username: str | None = None
    temp_password: str | None = None
    exchange_used: bool = False


sessions: dict[str, MaxSession] = {}
updates_marker: int | None = None
_admin_token: str | None = None
_admin_token_expires_at: float = 0.0

app = FastAPI(title="MAX Auth Service", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(admin_router)
app.include_router(hr_router)


class StartResponse(BaseModel):
    session_id: str
    auth_token: str
    bot_url: str
    expires_at: int
    poll_interval_ms: int
    message: str


class StatusResponse(BaseModel):
    session_id: str
    status: SessionStatus
    expires_at: int
    keycloak_username: str | None = None
    temp_password: str | None = None


class RequiredActionsResponse(BaseModel):
    update_password: bool
    required_actions: list[str]


class ChangePasswordRequest(BaseModel):
    new_password: str = Field(min_length=8, max_length=128)
    confirmation: str = Field(min_length=8, max_length=128)

    @model_validator(mode="after")
    def validate_passwords(self) -> "ChangePasswordRequest":
        if self.new_password != self.confirmation:
            raise ValueError("Пароли не совпадают")
        return self


class ConfirmRequest(BaseModel):
    session_id: str | None = None
    auth_token: str | None = None
    max_user_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_reference(self) -> "ConfirmRequest":
        if not self.session_id and not self.auth_token:
            raise ValueError("Нужен session_id или auth_token")
        return self


class ExchangeRequest(BaseModel):
    session_id: str | None = None
    auth_token: str | None = None

    @model_validator(mode="after")
    def validate_reference(self) -> "ExchangeRequest":
        if not self.session_id and not self.auth_token:
            raise ValueError("Нужен session_id или auth_token")
        return self


class DbQueryRequest(BaseModel):
    sql: str = Field(min_length=1, max_length=10000)
    limit: int = Field(default=50, ge=1, le=200)


def build_auth_token(session_id: str, mode: SessionMode = "login") -> str:
    prefix = MAX_RESET_PAYLOAD_PREFIX if mode == "reset" else MAX_AUTH_PAYLOAD_PREFIX
    return f"{prefix}{session_id}"


def parse_payload(payload: str) -> tuple[SessionMode, str] | None:
    if payload.startswith(MAX_AUTH_PAYLOAD_PREFIX):
        return "login", payload
    if payload.startswith(MAX_RESET_PAYLOAD_PREFIX):
        return "reset", payload
    return None


def parse_auth_token(auth_token: str) -> str:
    if auth_token.startswith(MAX_AUTH_PAYLOAD_PREFIX):
        return auth_token[len(MAX_AUTH_PAYLOAD_PREFIX) :]
    if auth_token.startswith(MAX_RESET_PAYLOAD_PREFIX):
        return auth_token[len(MAX_RESET_PAYLOAD_PREFIX) :]
    return auth_token


def create_session(mode: SessionMode) -> MaxSession:
    session_id = uuid.uuid4().hex
    auth_token = build_auth_token(session_id, mode)
    now = time.time()
    session = MaxSession(
        session_id=session_id,
        auth_token=auth_token,
        status="pending",
        mode=mode,
        created_at=now,
        expires_at=now + SESSION_TTL_SECONDS,
    )
    sessions[session_id] = session
    return session


def build_bot_url(auth_token: str) -> str:
    query = urlencode({"start": auth_token})
    separator = "&" if "?" in MAX_BOT_BASE_URL else "?"
    return f"{MAX_BOT_BASE_URL}{separator}{query}"


def cleanup_sessions() -> None:
    now = time.time()
    expired_ids = [sid for sid, session in sessions.items() if session.expires_at <= now]
    for session_id in expired_ids:
        sessions.pop(session_id, None)


def resolve_session(session_id: str | None = None, auth_token: str | None = None) -> MaxSession:
    token = session_id or (parse_auth_token(auth_token) if auth_token else None)
    if not token:
        raise HTTPException(status_code=400, detail="Не указана сессия авторизации")
    return get_active_session(token)


def get_active_session(session_id: str) -> MaxSession:
    cleanup_sessions()
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Сессия не найдена")
    if session.expires_at <= time.time():
        session.status = "expired"
        raise HTTPException(status_code=410, detail="Время подтверждения истекло")
    return session


async def lookup_keycloak_user(max_user_id: str) -> dict[str, str]:
    try:
        return await lookup_keycloak_credentials(max_user_id)
    except ValueError as error:
        raise HTTPException(
            status_code=404,
            detail="MAX ID не привязан к учётной записи HR или преподавателя",
        ) from error


async def fetch_keycloak_tokens(username: str, password: str) -> dict:
    token_url = f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/token"
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            token_url,
            data={
                "grant_type": "password",
                "client_id": KEYCLOAK_CLIENT_ID,
                "client_secret": KEYCLOAK_CLIENT_SECRET,
                "username": username,
                "password": password,
                "scope": "openid profile email roles",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    if response.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Keycloak token error: {response.text}",
        )

    return response.json()


async def get_keycloak_admin_token() -> str:
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


async def find_keycloak_user_id(username: str) -> str:
    admin_token = await get_keycloak_admin_token()
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(
            f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}/users",
            params={"username": username, "exact": "true"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )

    if response.status_code != 200:
        raise HTTPException(status_code=502, detail="Не удалось найти пользователя в Keycloak")

    users = response.json()
    if not users:
        raise HTTPException(status_code=404, detail="Пользователь не найден в Keycloak")
    return users[0]["id"]


async def keycloak_set_password(user_id: str, password: str, *, temporary: bool) -> None:
    admin_token = await get_keycloak_admin_token()
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.put(
            f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}/users/{user_id}/reset-password",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"type": "password", "value": password, "temporary": temporary},
        )

    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail="Не удалось установить пароль в Keycloak")


async def keycloak_get_user(user_id: str) -> dict[str, Any]:
    admin_token = await get_keycloak_admin_token()
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(
            f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}/users/{user_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    if response.status_code != 200:
        raise HTTPException(status_code=502, detail="Не удалось прочитать пользователя Keycloak")
    return response.json()


async def keycloak_update_required_actions(user_id: str, required_actions: list[str]) -> None:
    admin_token = await get_keycloak_admin_token()
    async with httpx.AsyncClient(timeout=15.0) as client:
        update_response = await client.put(
            f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}/users/{user_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"requiredActions": required_actions},
        )
    if update_response.status_code >= 400:
        raise HTTPException(status_code=502, detail="Не удалось обновить обязательные действия Keycloak")


async def keycloak_add_required_action(user_id: str, action: str) -> None:
    user_data = await keycloak_get_user(user_id)
    required_actions = list(user_data.get("requiredActions") or [])
    if action not in required_actions:
        required_actions.append(action)
    await keycloak_update_required_actions(user_id, required_actions)


async def keycloak_remove_required_action(user_id: str, action: str) -> None:
    user_data = await keycloak_get_user(user_id)
    required_actions = [item for item in (user_data.get("requiredActions") or []) if item != action]
    await keycloak_update_required_actions(user_id, required_actions)


def sync_max_user_password(max_user_id: str, password: str) -> None:
    user = MAX_USER_MAP.get(max_user_id)
    if user:
        user["password"] = password


async def complete_password_reset(
    session: MaxSession,
    max_user_id: str,
    target: MaxReplyTarget,
) -> dict[str, str]:
    mapping = await lookup_keycloak_user(max_user_id)
    username = mapping["username"]
    temp_password = secrets.token_urlsafe(9)
    user_id = await find_keycloak_user_id(username)
    await keycloak_set_password(user_id, temp_password, temporary=True)
    await keycloak_add_required_action(user_id, "UPDATE_PASSWORD")
    sync_max_user_password(max_user_id, temp_password)

    session.status = "password_reset"
    session.max_user_id = max_user_id
    session.keycloak_username = username
    session.temp_password = temp_password

    await send_max_message(
        target.chat_id,
        "Восстановление пароля Навигатор\n\n"
        f"Временный пароль: {temp_password}\n\n"
        f"Войдите на сайт {WEB_URL} и установите новый пароль.",
        user_id=target.user_id,
    )

    return {
        "status": "password_reset",
        "session_id": session.session_id,
        "keycloak_username": username,
    }


async def confirm_session(session: MaxSession, max_user_id: str) -> dict:
    mapping = await lookup_keycloak_user(max_user_id)
    session.status = "confirmed"
    session.max_user_id = max_user_id
    session.keycloak_username = mapping["username"]
    return {
        "status": "confirmed",
        "session_id": session.session_id,
        "auth_token": session.auth_token,
        "max_user_id": max_user_id,
        "keycloak_username": session.keycloak_username,
    }


def reject_session(session: MaxSession) -> None:
    session.status = "rejected"


def build_confirm_keyboard(auth_token: str) -> list[list[dict[str, str]]]:
    return [
        [
            {
                "type": "callback",
                "text": "Подтвердить",
                "payload": f"ok:{auth_token}",
            },
            {
                "type": "callback",
                "text": "Отклонить",
                "payload": f"no:{auth_token}",
            },
        ]
    ]


async def handle_bot_started(event: dict[str, Any]) -> dict[str, str]:
    payload_raw = event.get("payload")
    if not payload_raw:
        return await handle_bot_started_plain(event)

    parsed = parse_payload(str(payload_raw))
    if not parsed:
        return await handle_bot_started_plain(event)

    mode, auth_token = parsed
    user = event.get("user")
    if not isinstance(user, dict):
        raise HTTPException(status_code=400, detail="В событии MAX отсутствует user")

    target = extract_reply_target(event)
    if not target.valid:
        return {"status": "ignored", "reason": "no_reply_target"}

    try:
        max_user_id = extract_max_user_id(user)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    session = resolve_session(auth_token=auth_token)
    if session.mode != mode:
        return {"status": "ignored", "reason": "session_mode_mismatch"}

    session.max_user_id = max_user_id

    account = await resolve_bot_account(max_user_id)
    if not account:
        logger.info(
            "MAX access denied: max_user_id=%s session_id=%s",
            max_user_id,
            session.session_id,
        )
        await send_unknown_user_message(target)
        return {
            "status": "access_denied",
            "session_id": session.session_id,
            "max_user_id": max_user_id,
        }

    if account.role_code not in AUTH_APP_ROLES or not account.can_web_auth:
        logger.info(
            "MAX web auth denied for role=%s max_user_id=%s",
            account.role_code,
            max_user_id,
        )
        await send_max_message(
            target.chat_id,
            "Вход на сайт доступен только HR и преподавателям.\n\n"
            "Если вы ученик — используйте меню бота ниже.",
            user_id=target.user_id,
        )
        await route_welcome(target, account)
        return {
            "status": "web_auth_denied",
            "session_id": session.session_id,
            "max_user_id": max_user_id,
            "role": account.role_code,
        }

    mapping = await lookup_keycloak_user(max_user_id)
    if mode == "reset":
        prompt = (
            f"Запрос на восстановление пароля Навигатор\n\n"
            f"Роль: {mapping['label']}\n"
            f"Аккаунт: {mapping['username']}\n\n"
            "Подтвердите восстановление пароля?"
        )
    else:
        prompt = (
            f"Запрос на вход в Навигатор\n\n"
            f"Роль: {mapping['label']}\n"
            f"Аккаунт: {mapping['username']}\n\n"
            "Подтвердите вход в систему?"
        )

    await send_max_message(
        target.chat_id,
        prompt,
        buttons=build_confirm_keyboard(session.auth_token),
        user_id=target.user_id,
    )
    return {"status": "prompt_sent", "session_id": session.session_id, "mode": mode}


async def handle_message_callback(event: dict[str, Any]) -> dict[str, str]:
    callback = event.get("callback")
    if not isinstance(callback, dict):
        return {"status": "ignored"}

    callback_id = callback.get("callback_id")
    button_payload = callback.get("payload")
    if not callback_id or not button_payload:
        return {"status": "ignored"}

    user = event.get("user") or callback.get("user")
    if not isinstance(user, dict):
        raise HTTPException(status_code=400, detail="В callback отсутствует user")

    try:
        max_user_id = extract_max_user_id(user)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    payload_text = str(button_payload)
    target = extract_reply_target(event)

    if payload_text.startswith("emp:"):
        return await handle_employee_callback(callback_id, payload_text, target, max_user_id)

    if payload_text.startswith("ok:"):
        auth_token = payload_text[3:]
        session = resolve_session(auth_token=auth_token)
        if session.max_user_id and session.max_user_id != max_user_id:
            await answer_max_callback(callback_id, "Ошибка: другой пользователь")
            return {"status": "forbidden"}

        if session.mode == "reset":
            if not target.valid:
                return {"status": "ignored", "reason": "no_reply_target"}
            await complete_password_reset(session, max_user_id, target)
            await answer_max_callback(
                callback_id,
                "Пароль восстановлен",
                "Временный пароль отправлен в чат.\n\nВойдите на сайт и установите новый пароль.",
                remove_attachments=True,
            )
            return {"status": "password_reset", "session_id": session.session_id}

        await confirm_session(session, max_user_id)
        await answer_max_callback(
            callback_id,
            "Вход подтверждён",
            f"Вход подтверждён.\n\nВернитесь на сайт, чтобы завершить авторизацию:\n{WEB_RETURN_URL}",
            remove_attachments=True,
        )
        return {"status": "confirmed", "session_id": session.session_id}

    if payload_text.startswith("no:"):
        auth_token = payload_text[3:]
        session = resolve_session(auth_token=auth_token)
        reject_session(session)
        await answer_max_callback(
            callback_id,
            "Вход отклонён",
            "Вход в систему отклонён.",
            remove_attachments=True,
        )
        return {"status": "rejected", "session_id": session.session_id}

    return {"status": "ignored", "reason": "unknown_callback_payload"}


async def process_update(event: dict[str, Any]) -> dict[str, str]:
    update_type = event.get("update_type") or event.get("type")
    if update_type == "bot_started":
        return await handle_bot_started(event)
    if update_type == "message_callback":
        return await handle_message_callback(event)
    if update_type == "message_created":
        return await handle_message_created(event)
    logger.info("MAX update ignored: unknown type=%s", update_type)
    return {"status": "ignored", "reason": f"unknown_type:{update_type}"}


async def poll_max_updates() -> None:
    global updates_marker

    while True:
        if not MAX_BOT_TOKEN:
            await asyncio.sleep(5)
            continue

        try:
            params: dict[str, Any] = {
                "timeout": 30,
                "limit": 100,
                "types": "bot_started,message_callback,message_created",
            }
            if updates_marker is not None:
                params["marker"] = updates_marker

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.get(
                    f"{MAX_BOT_API_URL}/updates",
                    headers=auth_headers(),
                    params=params,
                )

            if response.status_code >= 400:
                logger.error("MAX updates poll failed: %s", response.text)
                await asyncio.sleep(5)
                continue

            data = response.json()
            if data.get("marker") is not None:
                updates_marker = data["marker"]

            for update in data.get("updates", []):
                try:
                    result = await process_update(update)
                    logger.info("Processed MAX update: %s", result)
                except Exception:
                    logger.exception("Failed to process MAX update")

        except httpx.HTTPError as error:
            logger.warning("MAX long polling error: %s", error)
            await asyncio.sleep(5)
        except Exception:
            logger.exception("Unexpected MAX long polling error")
            await asyncio.sleep(5)


@app.on_event("startup")
async def startup() -> None:
    await connect_database()
    await apply_schema()
    logger.info("Application database schema is ready")

    if MAX_BOT_TOKEN:
        asyncio.create_task(poll_max_updates())
        logger.info("MAX bot long polling started")
    else:
        logger.warning("MAX_BOT_TOKEN is empty — bot messages disabled")

    if LESSON_REMINDER_ENABLED:
        asyncio.create_task(run_lesson_reminder_worker())
    else:
        logger.info("Lesson reminder worker disabled (LESSON_REMINDER_ENABLED=false)")

    if FORMATION_AUTO_ENABLED:
        asyncio.create_task(run_formation_auto_worker())
    else:
        logger.info("Formation auto worker disabled (FORMATION_AUTO_ENABLED=false)")


@app.on_event("shutdown")
async def shutdown() -> None:
    await close_database()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "bot_enabled": str(bool(MAX_BOT_TOKEN)).lower()}


@app.get("/api/v1/db/health")
async def get_db_health() -> dict[str, str]:
    return await database_health()


@app.get("/api/v1/db/tables")
async def get_db_tables() -> dict[str, list[dict[str, Any]]]:
    return {"tables": await list_tables()}


@app.get("/api/v1/db/schema")
async def get_db_schema() -> dict[str, Any]:
    return await get_schema_summary()


@app.post("/api/v1/db/query")
async def query_db(body: DbQueryRequest) -> dict[str, Any]:
    try:
        return await run_readonly_query(body.sql, body.limit)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/v1/db/seed-demo")
async def seed_db_demo() -> dict[str, Any]:
    return {"status": "ok", "result": await seed_demo_data()}


@app.post("/api/v1/db/seed-formation-test")
async def seed_db_formation_test() -> dict[str, Any]:
    return {"status": "ok", "result": await seed_formation_test_data()}


@app.post("/api/v1/db/lesson-reminders/run")
async def run_lesson_reminders_now() -> dict[str, Any]:
    from lesson_reminder_worker import process_lesson_reminders

    return {"status": "ok", "result": await process_lesson_reminders()}


@app.get("/api/v1/auth/me")
async def get_auth_me(user: AuthUser = Depends(get_auth_user)) -> dict[str, Any]:
    return {
        "username": user.username,
        "keycloak_roles": user.roles,
        "app_user_id": user.app_user_id,
        "app_role_code": user.app_role_code,
        "profile": user.app_profile,
    }


@app.post("/api/v1/auth/max/start", response_model=StartResponse)
async def start_max_login() -> StartResponse:
    cleanup_sessions()
    session = create_session("login")
    return StartResponse(
        session_id=session.session_id,
        auth_token=session.auth_token,
        bot_url=build_bot_url(session.auth_token),
        expires_at=int(session.expires_at),
        poll_interval_ms=POLL_INTERVAL_MS,
        message="Откройте бота в MAX и подтвердите вход.",
    )


@app.post("/api/v1/auth/max/reset/start", response_model=StartResponse)
async def start_max_password_reset() -> StartResponse:
    cleanup_sessions()
    session = create_session("reset")
    return StartResponse(
        session_id=session.session_id,
        auth_token=session.auth_token,
        bot_url=build_bot_url(session.auth_token),
        expires_at=int(session.expires_at),
        poll_interval_ms=POLL_INTERVAL_MS,
        message="Откройте бота в MAX и подтвердите восстановление пароля.",
    )


@app.get("/api/v1/auth/max/status/{session_id}", response_model=StatusResponse)
async def get_max_status(session_id: str) -> StatusResponse:
    session = get_active_session(session_id)
    return StatusResponse(
        session_id=session.session_id,
        status=session.status,
        expires_at=int(session.expires_at),
        keycloak_username=session.keycloak_username,
        temp_password=session.temp_password if session.status == "password_reset" else None,
    )


@app.get("/api/v1/auth/required-actions", response_model=RequiredActionsResponse)
async def get_required_actions(user: AuthUser = Depends(get_auth_user)) -> RequiredActionsResponse:
    user_id = await find_keycloak_user_id(user.username)
    user_data = await keycloak_get_user(user_id)
    required_actions = list(user_data.get("requiredActions") or [])
    return RequiredActionsResponse(
        update_password="UPDATE_PASSWORD" in required_actions,
        required_actions=required_actions,
    )


@app.post("/api/v1/auth/change-password")
async def change_password(body: ChangePasswordRequest, user: AuthUser = Depends(get_auth_user)) -> dict[str, str]:
    user_id = await find_keycloak_user_id(user.username)
    user_data = await keycloak_get_user(user_id)
    required_actions = list(user_data.get("requiredActions") or [])
    if "UPDATE_PASSWORD" not in required_actions:
        raise HTTPException(status_code=400, detail="Смена пароля сейчас не требуется")

    await keycloak_set_password(user_id, body.new_password, temporary=False)
    await keycloak_remove_required_action(user_id, "UPDATE_PASSWORD")
    return {"status": "ok", "message": "Пароль успешно изменён"}


@app.post("/api/v1/auth/max/confirm")
async def confirm_max_login(body: ConfirmRequest) -> dict:
    session = resolve_session(body.session_id, body.auth_token)
    return await confirm_session(session, body.max_user_id)


@app.post("/api/v1/auth/max/exchange")
async def exchange_max_session(body: ExchangeRequest) -> dict:
    session = resolve_session(body.session_id, body.auth_token)
    if session.mode != "login":
        raise HTTPException(status_code=400, detail="Сессия не предназначена для входа")
    if session.status != "confirmed":
        raise HTTPException(status_code=400, detail="Сессия ещё не подтверждена")
    if session.exchange_used:
        raise HTTPException(status_code=400, detail="Сессия уже использована")

    mapping = await lookup_keycloak_user(session.max_user_id or "")
    tokens = await fetch_keycloak_tokens(mapping["username"], mapping["password"])
    session.exchange_used = True
    session.status = "exchanged"
    return tokens


@app.post("/api/v1/bot/events")
async def bot_events(event: dict[str, Any]) -> dict[str, str]:
    """Webhook MAX Bot API (production)."""
    return await process_update(event)
