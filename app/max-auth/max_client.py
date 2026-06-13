import logging
import os
from typing import Any

import httpx

logger = logging.getLogger("max-auth")

MAX_BOT_TOKEN = os.getenv("MAX_BOT_TOKEN", "")
MAX_BOT_API_URL = os.getenv("MAX_BOT_API_URL", "https://platform-api.max.ru")


def auth_headers() -> dict[str, str]:
    return {"Authorization": MAX_BOT_TOKEN}


def extract_max_user_id(user: dict[str, Any]) -> str:
    for key in ("user_id", "id", "userId"):
        value = user.get(key)
        if value is not None:
            return str(value)
    raise ValueError("В событии MAX отсутствует user id")


async def send_max_message(
    chat_id: int | str | None,
    text: str,
    buttons: list[list[dict[str, str]]] | None = None,
    *,
    user_id: int | str | None = None,
) -> None:
    if not MAX_BOT_TOKEN:
        logger.warning("MAX_BOT_TOKEN не задан, сообщение не отправлено")
        return

    params: dict[str, Any] = {}
    if chat_id is not None:
        params["chat_id"] = int(chat_id)
    elif user_id is not None:
        params["user_id"] = int(user_id)
    else:
        logger.warning("MAX send skipped: neither chat_id nor user_id")
        return

    payload: dict[str, Any] = {"text": text}
    if buttons:
        payload["attachments"] = [
            {
                "type": "inline_keyboard",
                "payload": {"buttons": buttons},
            }
        ]

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            f"{MAX_BOT_API_URL}/messages",
            params=params,
            headers=auth_headers(),
            json=payload,
        )
        if response.status_code >= 400:
            logger.error("MAX send message failed: %s", response.text)


async def answer_max_callback(
    callback_id: str,
    notification: str,
    message_text: str | None = None,
    *,
    remove_attachments: bool = False,
) -> None:
    if not MAX_BOT_TOKEN:
        return

    body: dict[str, Any] = {"notification": notification}
    if message_text:
        message: dict[str, Any] = {"text": message_text}
        if remove_attachments:
            message["attachments"] = []
        body["message"] = message

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            f"{MAX_BOT_API_URL}/answers",
            params={"callback_id": callback_id},
            headers=auth_headers(),
            json=body,
        )
        if response.status_code >= 400:
            logger.error("MAX answer callback failed: %s", response.text)
