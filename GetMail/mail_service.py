from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(os.environ.get("GETMAIL_PROJECT_ROOT") or Path(__file__).resolve().parents[1]).resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import chatgpt_register


def _compact_text(value: str, limit: int = 220) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}..."


def _format_address(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()

    if isinstance(value, dict):
        email = str(value.get("email") or value.get("address") or "").strip()
        name = str(value.get("name") or "").strip()
        if name and email and name != email:
            return f"{name} <{email}>"
        return email or name

    if isinstance(value, list):
        items = [_format_address(item) for item in value]
        return ", ".join(item for item in items if item)

    return ""


def _build_message_summary(mailbox: dict[str, Any], message: dict[str, Any]) -> dict[str, Any]:
    message_id = str(message.get("id") or "").strip()
    detail = chatgpt_register._fetch_email_detail(mailbox, message_id) if message_id else None
    payload = detail if isinstance(detail, dict) else message
    content = chatgpt_register._extract_message_content(payload if isinstance(payload, dict) else {})
    code = chatgpt_register._extract_verification_code(content)
    preview = _compact_text(content or message.get("subject") or "", limit=260)

    return {
        "id": message_id or None,
        "subject": str(message.get("subject") or (payload or {}).get("subject") or "").strip(),
        "from": _format_address(message.get("from") or (payload or {}).get("from")),
        "to": _format_address(message.get("to") or (payload or {}).get("to")),
        "received_at": message.get("created_at") or (payload or {}).get("created_at"),
        "verification_code": code,
        "preview": preview,
    }


def lookup_mailbox(mail_token: str, timeout: int = 15, limit: int = 10) -> dict[str, Any]:
    mailbox = chatgpt_register.resolve_mailbox_query_token(mail_token)
    email = str(mailbox.get("email") or "").strip().lower()
    if not email:
        raise ValueError("mail_token 缺少邮箱地址")

    wait_seconds = max(0, min(int(timeout or 0), 120))
    limit = max(1, min(int(limit or 0), 20))
    started_at = time.time()
    deadline = started_at + wait_seconds
    latest_messages: list[dict[str, Any]] = []
    latest_total_count = 0
    ever_seen_message = False

    while True:
        raw_messages = chatgpt_register._fetch_received_emails(mailbox) or []
        latest_total_count = len(raw_messages)
        ever_seen_message = ever_seen_message or bool(raw_messages)
        latest_messages = [
            _build_message_summary(mailbox, message)
            for message in raw_messages[:limit]
            if isinstance(message, dict)
        ]

        latest_code = next((item.get("verification_code") for item in latest_messages if item.get("verification_code")), None)
        latest_subject = latest_messages[0]["subject"] if latest_messages else ""
        latest_received_at = latest_messages[0]["received_at"] if latest_messages else None
        latest_message_id = latest_messages[0]["id"] if latest_messages else None

        if latest_code:
            return {
                "status": "ok",
                "email": email,
                "verification_code": latest_code,
                "latest_subject": latest_subject,
                "latest_received_at": latest_received_at,
                "latest_message_id": latest_message_id,
                "message_count": latest_total_count,
                "messages": latest_messages,
                "message": "已提取到最新验证码",
                "hint": "",
                "polled_seconds": round(time.time() - started_at, 1),
            }

        if time.time() >= deadline:
            break

        sleep_seconds = min(3.0, max(0.5, deadline - time.time()))
        time.sleep(sleep_seconds)

    hint = chatgpt_register._mailbox_debug_hint(mailbox)
    message = "暂未收到任何邮件" if not ever_seen_message else "已收到邮件，但暂未提取到 6 位验证码"

    return {
        "status": "pending",
        "email": email,
        "verification_code": None,
        "latest_subject": latest_messages[0]["subject"] if latest_messages else "",
        "latest_received_at": latest_messages[0]["received_at"] if latest_messages else None,
        "latest_message_id": latest_messages[0]["id"] if latest_messages else None,
        "message_count": latest_total_count,
        "messages": latest_messages,
        "message": message,
        "hint": hint,
        "polled_seconds": round(time.time() - started_at, 1),
    }


def health_snapshot() -> dict[str, Any]:
    return {
        "status": "ok",
        "project_root": str(PROJECT_ROOT),
        "resend_api_base": chatgpt_register.RESEND_API_BASE,
        "resend_domain": chatgpt_register.RESEND_DOMAIN,
        "receiving_ready": bool(chatgpt_register.RESEND_API_KEY and chatgpt_register.RESEND_DOMAIN),
        "token_secret_source": "env" if os.environ.get("MAILBOX_QUERY_TOKEN_SECRET") else "file",
    }
