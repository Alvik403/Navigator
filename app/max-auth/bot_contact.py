"""Parse MAX contact attachments and verify request_contact hash."""

from __future__ import annotations

import hashlib
import hmac
import re
from typing import Any


def normalize_phone_digits(raw: str) -> str | None:
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    elif len(digits) == 10:
        digits = "7" + digits
    if len(digits) != 11 or not digits.startswith("7"):
        return None
    return digits


def normalize_phone_display(raw: str) -> str | None:
    digits = normalize_phone_digits(raw)
    return f"+{digits}" if digits else None


def parse_phones_from_vcf(vcf_info: str) -> list[str]:
    if not vcf_info:
        return []
    phones: list[str] = []
    for line in vcf_info.replace("\r\n", "\n").split("\n"):
        stripped = line.strip()
        if not stripped.upper().startswith("TEL"):
            continue
        if ":" not in stripped:
            continue
        phones.append(stripped.split(":", 1)[1].strip())
    return phones


def verify_contact_hash(vcf_info: str, hash_value: str, bot_token: str) -> bool:
    if not vcf_info or not hash_value or not bot_token:
        return False
    normalized = vcf_info.replace("\\r\\n", "\r\n").replace("\\n", "\n")
    digest = hmac.new(
        bot_token.encode("utf-8"),
        normalized.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(digest, hash_value)


def extract_contact_payload(event: dict[str, Any]) -> dict[str, Any] | None:
    message = event.get("message")
    if not isinstance(message, dict):
        return None
    body = message.get("body")
    if not isinstance(body, dict):
        return None
    attachments = body.get("attachments")
    if not isinstance(attachments, list):
        return None
    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        if attachment.get("type") != "contact":
            continue
        payload = attachment.get("payload")
        if isinstance(payload, dict):
            return payload
    return None
