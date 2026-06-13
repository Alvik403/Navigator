"""Helpers to extract reply targets from MAX Update payloads."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MaxReplyTarget:
    chat_id: int | None = None
    user_id: int | None = None

    @property
    def valid(self) -> bool:
        return self.chat_id is not None or self.user_id is not None


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _user_id_from_user(user: dict[str, Any] | None) -> int | None:
    if not isinstance(user, dict):
        return None
    for key in ("user_id", "id", "userId"):
        parsed = _as_int(user.get(key))
        if parsed is not None:
            return parsed
    return None


def extract_reply_target(event: dict[str, Any]) -> MaxReplyTarget:
    chat_id = _as_int(event.get("chat_id"))
    user_id: int | None = None

    message = event.get("message")
    if isinstance(message, dict):
        recipient = message.get("recipient")
        if isinstance(recipient, dict):
            if chat_id is None:
                chat_id = _as_int(recipient.get("chat_id"))
            user_id = _as_int(recipient.get("user_id"))
        sender = message.get("sender")
        if user_id is None:
            user_id = _user_id_from_user(sender)

    callback = event.get("callback")
    if isinstance(callback, dict):
        if user_id is None:
            user_id = _user_id_from_user(callback.get("user"))

    user = event.get("user")
    if user_id is None:
        user_id = _user_id_from_user(user)

    return MaxReplyTarget(chat_id=chat_id, user_id=user_id)
