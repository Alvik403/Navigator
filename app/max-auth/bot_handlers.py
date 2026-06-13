"""MAX bot handlers: role detection by max_id and employee self-service menu."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from auth_deps import KC_USERNAME_TO_APP_USER
from domain import (
    get_employee_progress,
    get_profile_by_max_id,
    get_profile_by_phone,
    link_profile_max_id,
    list_employee_upcoming_lessons,
    list_user_groups,
    list_user_strikes,
    submit_user_strike_appeal,
)
from bot_contact import (
    extract_contact_payload,
    parse_phones_from_vcf,
    verify_contact_hash,
)
from bot_events import MaxReplyTarget, extract_reply_target
from max_client import MAX_BOT_TOKEN, answer_max_callback, extract_max_user_id, send_max_message

logger = logging.getLogger("max-auth")

WEB_URL = os.getenv("WEB_URL", "http://localhost:5173")
HR_CONTACT_NAME = os.getenv("HR_CONTACT_NAME", "").strip()
HR_CONTACT_URL = os.getenv("HR_CONTACT_URL", "").strip()
HR_MAX_PROFILE_URL = os.getenv("HR_MAX_PROFILE_URL", "").strip()

ROLE_LABELS = {
    "hr": "HR",
    "teacher": "Преподаватель",
    "admin": "Администратор",
    "employee": "Ученик",
    "curator": "Куратор",
}

AUTH_APP_ROLES = frozenset({"hr", "teacher", "admin"})
EMPLOYEE_ROLE = "employee"

KEYCLOAK_CREDENTIALS: dict[str, str] = {
    "hr.manager": "hr123456",
    "teacher.demo": "teacher123456",
    "admin": "admin123456",
}

_extra_credentials = os.getenv("KEYCLOAK_CREDENTIALS_JSON")
if _extra_credentials:
    KEYCLOAK_CREDENTIALS.update(json.loads(_extra_credentials))

APP_USER_TO_KC_USERNAME = {app_id: kc for kc, app_id in KC_USERNAME_TO_APP_USER.items()}

MAX_USER_MAP: dict[str, dict[str, str]] = {
    "1001": {
        "username": "hr.manager",
        "password": "hr123456",
        "label": "HR",
        "role": "hr_manager",
    },
    "1002": {
        "username": "teacher.demo",
        "password": "teacher123456",
        "label": "Преподаватель",
        "role": "teacher",
    },
}

_extra_users = os.getenv("MAX_USER_MAP_JSON")
if _extra_users:
    MAX_USER_MAP.update(json.loads(_extra_users))

CONTACT_INVALID_MESSAGE = (
    "Не удалось подтвердить контакт.\n\n"
    "Нажмите кнопку «Поделиться номером» ниже — так MAX подтверждает, "
    "что номер принадлежит вашему аккаунту."
)

INACTIVE_USER_MESSAGE = (
    "Ваш доступ в системе ограничен (статус: неактивен).\n\n"
    "Обратитесь к HR или куратору."
)

STRIKE_STATUS_LABELS = {
    "active": "активен",
    "appealed": "на рассмотрении",
}


@dataclass
class BotAccount:
    max_user_id: str
    app_user_id: str
    role_code: str
    role_name: str
    first_name: str
    last_name: str
    status: str
    strike_count: int
    keycloak_username: str | None = None
    keycloak_password: str | None = None

    @property
    def display_name(self) -> str:
        return f"{self.last_name} {self.first_name}".strip()

    @property
    def is_employee(self) -> bool:
        return self.role_code == EMPLOYEE_ROLE

    @property
    def can_web_auth(self) -> bool:
        return self.role_code in AUTH_APP_ROLES and bool(self.keycloak_username)


# max_user_id → strike_id awaiting appeal text
pending_appeals: dict[str, str] = {}


def _format_dt(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return str(value)
    return dt.strftime("%d.%m.%Y %H:%M")


async def resolve_bot_account(max_user_id: str) -> BotAccount | None:
    try:
        max_id_int = int(max_user_id)
    except ValueError:
        max_id_int = None

    if max_id_int is not None:
        profile = await get_profile_by_max_id(max_id_int)
        if profile:
            kc_username = APP_USER_TO_KC_USERNAME.get(str(profile["id"]))
            kc_password = KEYCLOAK_CREDENTIALS.get(kc_username) if kc_username else None
            return BotAccount(
                max_user_id=max_user_id,
                app_user_id=str(profile["id"]),
                role_code=str(profile.get("role_code") or ""),
                role_name=str(profile.get("role_name") or ""),
                first_name=str(profile.get("first_name") or ""),
                last_name=str(profile.get("last_name") or ""),
                status=str(profile.get("status") or "active"),
                strike_count=int(profile.get("strike_count") or 0),
                keycloak_username=kc_username,
                keycloak_password=kc_password,
            )

    # Legacy map only when profile is absent in DB (dev fallback for HR/teacher login).
    legacy = MAX_USER_MAP.get(max_user_id)
    if legacy and legacy.get("role") in {"hr_manager", "teacher", "admin"}:
        logger.debug("MAX legacy map used for max_user_id=%s role=%s", max_user_id, legacy.get("role"))
        return BotAccount(
            max_user_id=max_user_id,
            app_user_id=KC_USERNAME_TO_APP_USER.get(legacy["username"], ""),
            role_code={"hr_manager": "hr", "teacher": "teacher", "admin": "admin"}.get(
                legacy["role"], legacy["role"]
            ),
            role_name=legacy.get("label", legacy["role"]),
            first_name="",
            last_name=legacy.get("label", ""),
            status="active",
            strike_count=0,
            keycloak_username=legacy.get("username"),
            keycloak_password=legacy.get("password"),
        )
    return None


async def lookup_keycloak_credentials(max_user_id: str) -> dict[str, str]:
    account = await resolve_bot_account(max_user_id)
    if account and account.keycloak_username and account.keycloak_password:
        return {
            "username": account.keycloak_username,
            "password": account.keycloak_password,
            "label": ROLE_LABELS.get(account.role_code, account.role_name),
            "role": account.role_code,
        }
    legacy = MAX_USER_MAP.get(max_user_id)
    if legacy:
        return legacy
    raise ValueError("MAX ID не привязан к учётной записи")


def _button_link_url(raw_url: str) -> str | None:
    """MAX accepts only public http/https URLs in link buttons (not localhost)."""
    url = raw_url.strip()
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return None
    host = (parsed.hostname or "").lower()
    if not host or host in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}:
        return None
    return url


def _clipboard_max_id_button(max_user_id: str) -> dict[str, str]:
    return {"type": "clipboard", "text": "📋 Скопировать MAX ID", "payload": max_user_id}


def build_unknown_user_message(max_user_id: str) -> str:
    return (
        "Вы не найдены в системе MAX RASS.\n\n"
        f"Ваш MAX ID:\n{max_user_id}\n\n"
        "Скопируйте ID кнопкой ниже и передайте его HR при регистрации.\n\n"
        "Если HR уже добавил вас в систему, нажмите «Поделиться номером» — "
        "мы найдём профиль по номеру телефона из MAX."
    )


def build_phone_not_found_message(max_user_id: str) -> str:
    contact_label = HR_CONTACT_NAME or "HR"
    parts = [
        "Номер не найден в системе MAX RASS.",
        "",
        "Мы не нашли профиль с этим номером телефона.",
        f"Свяжитесь с {contact_label} — вас добавят в систему или проверят номер.",
        "",
        f"Ваш MAX ID:\n{max_user_id}",
    ]
    if HR_MAX_PROFILE_URL:
        parts.extend(["", f"Профиль HR: {HR_MAX_PROFILE_URL}"])
    if HR_CONTACT_URL:
        parts.append(f"Заявка на регистрацию: {HR_CONTACT_URL}")
    return "\n".join(parts)


def build_onboarding_hint_message(max_user_id: str) -> str:
    return (
        "Нажмите «Поделиться номером», чтобы найти профиль в системе.\n\n"
        f"Ваш MAX ID:\n{max_user_id}"
    )


def unknown_user_keyboard(max_user_id: str) -> list[list[dict[str, str]]]:
    return [
        [{"type": "request_contact", "text": "📱 Поделиться номером"}],
        [_clipboard_max_id_button(max_user_id)],
    ]


def phone_not_found_keyboard(max_user_id: str) -> list[list[dict[str, str]]]:
    rows: list[list[dict[str, str]]] = [
        [_clipboard_max_id_button(max_user_id)],
    ]
    link_buttons: list[dict[str, str]] = []
    profile_url = _button_link_url(HR_MAX_PROFILE_URL)
    if profile_url:
        link_buttons.append({"type": "link", "text": "👤 Профиль HR", "url": profile_url})
    form_url = _button_link_url(HR_CONTACT_URL)
    if form_url:
        link_buttons.append({"type": "link", "text": "📋 Заявка на регистрацию", "url": form_url})
    if link_buttons:
        rows.append(link_buttons)
    rows.append([{"type": "request_contact", "text": "📱 Поделиться номером снова"}])
    return rows


def request_contact_keyboard(max_user_id: str = "") -> list[list[dict[str, str]]]:
    if max_user_id:
        return unknown_user_keyboard(max_user_id)
    return [[{"type": "request_contact", "text": "📱 Поделиться номером"}]]


def employee_main_keyboard() -> list[list[dict[str, str]]]:
    return [
        [
            {"type": "callback", "text": "Мои группы", "payload": "emp:groups"},
            {"type": "callback", "text": "Прогресс", "payload": "emp:progress"},
        ],
        [
            {"type": "callback", "text": "Расписание", "payload": "emp:schedule"},
            {"type": "callback", "text": "Страйки", "payload": "emp:strikes"},
        ],
        [
            {"type": "callback", "text": "Главное меню", "payload": "emp:menu"},
        ],
    ]


async def bot_reply(
    target: MaxReplyTarget,
    text: str,
    buttons: list[list[dict[str, str]]] | None = None,
) -> None:
    await send_max_message(target.chat_id, text, buttons, user_id=target.user_id)


def reply_from_ids(
    chat_id: int | str | None,
    user_id: int | str | None = None,
) -> MaxReplyTarget:
    chat = int(chat_id) if chat_id is not None else None
    uid = int(user_id) if user_id is not None else None
    return MaxReplyTarget(chat_id=chat, user_id=uid)


async def send_unknown_user_message(
    target: MaxReplyTarget,
    max_user_id: str | None = None,
) -> None:
    uid = max_user_id or (str(target.user_id) if target.user_id is not None else "—")
    await bot_reply(target, build_unknown_user_message(uid), buttons=unknown_user_keyboard(uid))


async def handle_contact_link(
    target: MaxReplyTarget,
    max_user_id: str,
    contact_payload: dict[str, Any],
) -> dict[str, str]:
    vcf_info = str(contact_payload.get("vcf_info") or "")
    hash_value = str(contact_payload.get("hash") or "")

    if not vcf_info:
        await bot_reply(target, CONTACT_INVALID_MESSAGE, buttons=request_contact_keyboard(max_user_id))
        return {"status": "contact_invalid", "max_user_id": max_user_id}

    if not verify_contact_hash(vcf_info, hash_value, MAX_BOT_TOKEN):
        logger.warning("Contact hash verification failed for max_user_id=%s", max_user_id)
        await bot_reply(target, CONTACT_INVALID_MESSAGE, buttons=request_contact_keyboard(max_user_id))
        return {"status": "contact_hash_failed", "max_user_id": max_user_id}

    phones = parse_phones_from_vcf(vcf_info)
    if not phones:
        await bot_reply(target, CONTACT_INVALID_MESSAGE, buttons=request_contact_keyboard(max_user_id))
        return {"status": "contact_no_phone", "max_user_id": max_user_id}

    profile = None
    for phone in phones:
        profile = await get_profile_by_phone(phone)
        if profile:
            break

    if not profile:
        await bot_reply(
            target,
            build_phone_not_found_message(max_user_id),
            buttons=phone_not_found_keyboard(max_user_id),
        )
        return {"status": "phone_not_found", "max_user_id": max_user_id}

    user_id = str(profile["id"])
    try:
        max_id_int = int(max_user_id)
        await link_profile_max_id(user_id, max_id_int)
    except ValueError as error:
        await bot_reply(target, str(error), buttons=request_contact_keyboard(max_user_id))
        return {"status": "link_failed", "max_user_id": max_user_id}

    account = await resolve_bot_account(max_user_id)
    if not account:
        await send_unknown_user_message(target, max_user_id)
        return {"status": "link_resolve_failed", "max_user_id": max_user_id}

    await bot_reply(
        target,
        f"Аккаунт привязан: {account.display_name}.\n\nДобро пожаловать в MAX RASS!",
    )
    await route_welcome(target, account)
    return {"status": "linked_by_phone", "max_user_id": max_user_id, "role": account.role_code}


async def send_employee_menu(target: MaxReplyTarget, account: BotAccount) -> None:
    greeting = f"Здравствуйте, {account.display_name}!\n\nMAX RASS — ваш личный кабинет ученика."
    if account.strike_count:
        greeting += f"\n\n⚠ Активных страйков: {account.strike_count} из 3."
    await bot_reply(target, greeting, buttons=employee_main_keyboard())


async def send_staff_welcome(target: MaxReplyTarget, account: BotAccount) -> None:
    role_label = ROLE_LABELS.get(account.role_code, account.role_name)
    text = (
        f"Здравствуйте, {account.display_name or role_label}!\n\n"
        f"Роль: {role_label}\n\n"
    )
    if account.can_web_auth:
        text += (
            f"Для входа на сайт откройте {WEB_URL} и выберите «Войти через MAX».\n\n"
            "Бот подтвердит вход, когда вы перейдёте по ссылке с сайта."
        )
    else:
        text += "Для работы с системой используйте web-портал или обратитесь к администратору."
    await bot_reply(target, text)


async def send_curator_welcome(target: MaxReplyTarget, account: BotAccount) -> None:
    await bot_reply(
        target,
        f"Здравствуйте, {account.display_name}!\n\n"
        "Вы зарегистрированы как куратор. Уведомления о подопечных приходят в этот чат.\n\n"
        "Для управления учениками используйте HR-портал или обратитесь к HR.",
    )


async def route_welcome(target: MaxReplyTarget, account: BotAccount) -> None:
    if account.status != "active":
        await bot_reply(target, INACTIVE_USER_MESSAGE)
        return
    if account.is_employee:
        await send_employee_menu(target, account)
    elif account.role_code == "curator":
        await send_curator_welcome(target, account)
    elif account.role_code in AUTH_APP_ROLES:
        await send_staff_welcome(target, account)
    else:
        await send_unknown_user_message(target, account.max_user_id)


async def format_groups_message(user_id: str) -> str:
    groups = await list_user_groups(user_id)
    if not groups:
        return "Вы пока не состоите ни в одной группе.\n\nОбратитесь к HR для назначения."
    lines = [f"Ваши группы ({len(groups)}):"]
    for group in groups:
        status = group.get("status") or "active"
        hr = group.get("hr_name")
        line = f"• {group.get('name', '—')} — {status}"
        if hr:
            line += f" (HR: {hr})"
        lines.append(line)
    return "\n".join(lines)


async def format_progress_message(user_id: str) -> str:
    rows = await get_employee_progress(user_id)
    if not rows:
        return "Нет данных о прогрессе.\n\nВозможно, вы ещё не добавлены в группу."
    lines = ["Ваш прогресс:"]
    for row in rows:
        past = int(row.get("lessons_past") or 0)
        present = int(row.get("present_count") or 0)
        late = int(row.get("late_count") or 0)
        absent = int(row.get("absent_count") or 0)
        upcoming = int(row.get("lessons_upcoming") or 0)
        attended = present + late
        lines.append(
            f"\n📁 {row.get('group_name', '—')}\n"
            f"  ✓ Посещено: {attended} (из {past} прошедших)\n"
            f"  ✗ Пропуски: {absent}\n"
            f"  ○ Впереди: {upcoming} занятий"
        )
    return "\n".join(lines)


async def format_schedule_message(user_id: str) -> str:
    lessons = await list_employee_upcoming_lessons(user_id)
    if not lessons:
        return "Ближайших занятий нет."
    lines = ["Ближайшие занятия:"]
    for lesson in lessons:
        title = lesson.get("lesson_title") or lesson.get("title") or "Занятие"
        place = lesson.get("place") or "—"
        group = lesson.get("group_name") or "—"
        teacher = f"{lesson.get('teacher_last_name', '')} {lesson.get('teacher_first_name', '')}".strip()
        lines.append(
            f"\n• {_format_dt(lesson.get('starts_at'))}\n"
            f"  {title} · {group}\n"
            f"  {place}"
            + (f"\n  Преподаватель: {teacher}" if teacher else "")
        )
    return "\n".join(lines)



async def format_strikes_message(user_id: str) -> tuple[str, list[list[dict[str, str]]] | None]:
    strikes = await list_user_strikes(user_id)
    if not strikes:
        return "У вас нет страйков.", employee_main_keyboard()

    lines = ["Ваши страйки:"]
    appeal_buttons: list[list[dict[str, str]]] = []
    for strike in strikes:
        status = STRIKE_STATUS_LABELS.get(str(strike.get("status")), str(strike.get("status")))
        lesson_part = ""
        if strike.get("lesson_title"):
            lesson_part = f" · «{strike['lesson_title']}»"
        if strike.get("lesson_starts_at"):
            lesson_part += f" ({_format_dt(strike['lesson_starts_at'])})"
        lines.append(
            f"\n• №{strike.get('strike_number', '?')} — {strike.get('reason', '—')}{lesson_part}\n"
            f"  Статус: {status}"
        )
        if strike.get("status") == "active":
            appeal_buttons.append(
                [
                    {
                        "type": "callback",
                        "text": f"Апелляция №{strike.get('strike_number')}",
                        "payload": f"emp:appeal:{strike['id']}",
                    }
                ]
            )

    appeal_buttons.append([{"type": "callback", "text": "← Меню", "payload": "emp:menu"}])
    return "\n".join(lines), appeal_buttons


async def handle_employee_action(
    action: str,
    target: MaxReplyTarget,
    account: BotAccount,
    *,
    strike_id: str | None = None,
) -> None:
    if account.status != "active":
        await bot_reply(target, INACTIVE_USER_MESSAGE)
        return

    if action == "menu":
        await send_employee_menu(target, account)
        return

    if action == "groups":
        text = await format_groups_message(account.app_user_id)
        await bot_reply(target, text, buttons=employee_main_keyboard())
        return

    if action == "progress":
        text = await format_progress_message(account.app_user_id)
        await bot_reply(target, text, buttons=employee_main_keyboard())
        return

    if action == "schedule":
        text = await format_schedule_message(account.app_user_id)
        await bot_reply(target, text, buttons=employee_main_keyboard())
        return

    if action == "strikes":
        text, buttons = await format_strikes_message(account.app_user_id)
        await bot_reply(target, text, buttons=buttons)
        return

    if action == "appeal" and strike_id:
        pending_appeals[account.max_user_id] = strike_id
        await bot_reply(
            target,
            "Напишите текст апелляции одним сообщением (уважительная причина, справка и т.д.).\n\n"
            "Отмена: /menu",
        )
        return


async def handle_employee_text(
    target: MaxReplyTarget,
    max_user_id: str,
    text: str,
    account: BotAccount,
) -> None:
    normalized = text.strip().lower()
    command = normalized.split()[0] if normalized else ""

    if command in {"/cancel", "отмена"} and max_user_id in pending_appeals:
        pending_appeals.pop(max_user_id, None)
        await bot_reply(target, "Апелляция отменена.", buttons=employee_main_keyboard())
        return

    if max_user_id in pending_appeals:
        strike_id = pending_appeals.pop(max_user_id)
        reason = text.strip()
        if len(reason) < 5:
            pending_appeals[max_user_id] = strike_id
            await bot_reply(target, "Текст слишком короткий. Напишите подробнее (минимум 5 символов).")
            return
        try:
            await submit_user_strike_appeal(account.app_user_id, strike_id, reason)
        except ValueError as error:
            await bot_reply(target, str(error), buttons=employee_main_keyboard())
            return
        await bot_reply(
            target,
            "Апелляция отправлена HR на рассмотрение.\n\n"
            "Статус можно проверить в разделе «Страйки».",
            buttons=employee_main_keyboard(),
        )
        return

    if command in {"/start", "/menu", "меню", "start", "/help", "help", "помощь"}:
        await send_employee_menu(target, account)
        return
    if command in {"/groups", "группы"}:
        await handle_employee_action("groups", target, account)
        return
    if command in {"/progress", "прогресс"}:
        await handle_employee_action("progress", target, account)
        return
    if command in {"/schedule", "расписание"}:
        await handle_employee_action("schedule", target, account)
        return
    if command in {"/strikes", "страйки"}:
        await handle_employee_action("strikes", target, account)
        return

    await bot_reply(
        target,
        "Не понял команду. Используйте кнопки меню или:\n"
        "/groups · /progress · /schedule · /strikes · /menu",
        buttons=employee_main_keyboard(),
    )


def extract_message_text(event: dict[str, Any]) -> str | None:
    message = event.get("message")
    if isinstance(message, dict):
        body = message.get("body")
        if isinstance(body, dict):
            text = body.get("text")
            if isinstance(text, str) and text.strip():
                return text.strip()
    return None


def extract_event_user(event: dict[str, Any]) -> dict[str, Any] | None:
    message = event.get("message")
    if isinstance(message, dict):
        sender = message.get("sender")
        if isinstance(sender, dict):
            return sender
    user = event.get("user")
    if isinstance(user, dict):
        return user
    callback = event.get("callback")
    if isinstance(callback, dict):
        cb_user = callback.get("user")
        if isinstance(cb_user, dict):
            return cb_user
    return None


async def handle_message_created(event: dict[str, Any]) -> dict[str, str]:
    target = extract_reply_target(event)
    if not target.valid:
        logger.info("message_created ignored: no reply target, keys=%s", list(event.keys()))
        return {"status": "ignored", "reason": "no_reply_target"}

    user = extract_event_user(event)
    if not user:
        return {"status": "ignored", "reason": "no_user"}

    try:
        max_user_id = extract_max_user_id(user)
    except ValueError:
        return {"status": "ignored", "reason": "no_max_user_id"}

    account = await resolve_bot_account(max_user_id)

    contact_payload = extract_contact_payload(event)
    if contact_payload:
        return await handle_contact_link(target, max_user_id, contact_payload)

    if not account:
        text = extract_message_text(event)
        if text and text.strip().lower().split()[0] in {"/start", "start", "меню", "/menu"}:
            await send_unknown_user_message(target, max_user_id)
        else:
            await bot_reply(
                target,
                build_onboarding_hint_message(max_user_id),
                buttons=unknown_user_keyboard(max_user_id),
            )
        return {"status": "unknown_user", "max_user_id": max_user_id}

    if not account.is_employee:
        text = extract_message_text(event)
        if text and text.strip().lower().split()[0] in {"/start", "start", "меню", "/menu"}:
            await route_welcome(target, account)
            return {"status": "staff_welcome", "role": account.role_code}
        return {"status": "ignored_non_employee"}

    text = extract_message_text(event)
    if not text:
        return {"status": "ignored_empty"}

    await handle_employee_text(target, max_user_id, text, account)
    return {"status": "employee_message", "max_user_id": max_user_id}


async def handle_employee_callback(
    callback_id: str,
    payload_text: str,
    target: MaxReplyTarget,
    max_user_id: str,
) -> dict[str, str]:
    if not payload_text.startswith("emp:"):
        return {"status": "ignored"}

    account = await resolve_bot_account(max_user_id)
    if not account:
        await answer_max_callback(callback_id, "Не найден в системе")
        if target.valid:
            await send_unknown_user_message(target, max_user_id)
        return {"status": "unknown_user"}

    if not account.is_employee:
        await answer_max_callback(callback_id, "Доступно только ученикам")
        return {"status": "forbidden"}

    parts = payload_text.split(":", 2)
    action = parts[1] if len(parts) > 1 else "menu"
    strike_id = parts[2] if len(parts) > 2 and action == "appeal" else None

    if target.valid:
        await handle_employee_action(action, target, account, strike_id=strike_id)

    labels = {
        "menu": "Меню",
        "groups": "Группы",
        "progress": "Прогресс",
        "schedule": "Расписание",
        "strikes": "Страйки",
        "appeal": "Апелляция",
    }
    await answer_max_callback(callback_id, labels.get(action, "Готово"))
    return {"status": "employee_callback", "action": action}


async def handle_bot_started_plain(event: dict[str, Any]) -> dict[str, str]:
    """User opened bot without auth deep-link payload."""
    target = extract_reply_target(event)
    if not target.valid:
        logger.info("bot_started ignored: no reply target, keys=%s", list(event.keys()))
        return {"status": "ignored", "reason": "no_reply_target"}

    user = event.get("user")
    if not isinstance(user, dict):
        return {"status": "ignored", "reason": "no_user"}

    max_user_id = extract_max_user_id(user)
    account = await resolve_bot_account(max_user_id)
    if not account:
        await send_unknown_user_message(target, max_user_id)
        return {"status": "unknown_user", "max_user_id": max_user_id}

    await route_welcome(target, account)
    return {"status": "welcome", "role": account.role_code, "max_user_id": max_user_id}
