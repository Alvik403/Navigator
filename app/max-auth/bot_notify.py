"""Push notifications to employees via MAX bot."""

from __future__ import annotations

import logging
from typing import Any

from domain import get_user_profile
from max_client import send_max_message

logger = logging.getLogger("max-auth")


async def notify_max_user(
    app_user_id: str,
    text: str,
    buttons: list[list[dict[str, str]]] | None = None,
) -> bool:
    profile = await get_user_profile(app_user_id)
    if not profile:
        logger.info("MAX notify skipped: profile not found for user %s", app_user_id)
        return False
    max_id = profile.get("max_id")
    if max_id is None:
        logger.info("MAX notify skipped: user %s has no max_id", app_user_id)
        return False
    await send_max_message(None, text, buttons, user_id=int(max_id))
    return True


async def notify_strike_issued(strike: dict[str, Any]) -> bool:
    user_id = str(strike.get("user_id", ""))
    strike_number = strike.get("strike_number", "?")
    active_count = int(strike.get("active_strike_count") or strike_number)
    reason = strike.get("reason") or "нарушение"
    strike_id = strike.get("id", "")

    text = (
        f"Вам выдан страйк №{strike_number} ({reason}).\n\n"
        f"У вас {active_count} из 3 активных страйков."
    )
    if strike.get("auto_banned") or active_count >= 3:
        text += "\n\nДоступ к занятиям заблокирован. Обратитесь к HR или куратору."
    else:
        text += "\n\nПри 3 страйках доступ будет заблокирован."

    buttons: list[list[dict[str, str]]] | None = None
    if strike_id and strike.get("status") == "active":
        buttons = [
            [
                {
                    "type": "callback",
                    "text": "Подать апелляцию",
                    "payload": f"emp:appeal:{strike_id}",
                }
            ]
        ]
    return await notify_max_user(user_id, text, buttons)


async def notify_appeal_resolved(
    *,
    user_id: str,
    strike_number: int,
    approved: bool,
) -> bool:
    if approved:
        text = (
            f"Апелляция по страйку №{strike_number} принята.\n\n"
            "Страйк снят."
        )
    else:
        text = (
            f"Апелляция по страйку №{strike_number} отклонена.\n\n"
            "Страйк остаётся активным."
        )
    return await notify_max_user(user_id, text)


async def notify_lesson_reminder(user_id: str, text: str) -> bool:
    return await notify_max_user(user_id, text)
