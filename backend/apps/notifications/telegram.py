"""Минимальный клиент Telegram Bot API на stdlib (без лишних зависимостей)."""

import json
import urllib.error
import urllib.request
from typing import Any

from django.conf import settings

API_URL = "https://api.telegram.org/bot{token}/{method}"


class TelegramError(Exception):
    pass


def is_configured() -> bool:
    return bool(settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID)


def call(method: str, payload: dict[str, Any], timeout: float = 10) -> Any:
    request = urllib.request.Request(
        API_URL.format(token=settings.TELEGRAM_BOT_TOKEN, method=method),
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        # Telegram отдаёт описание ошибки в теле ответа.
        try:
            description = json.loads(exc.read()).get("description", str(exc))
        except ValueError:
            description = str(exc)
        raise TelegramError(f"{method}: {description}") from exc
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise TelegramError(f"{method}: {exc}") from exc
    if not body.get("ok"):
        raise TelegramError(f"{method}: {body.get('description', 'unknown error')}")
    return body.get("result")


def send_message(text: str, reply_markup: dict[str, Any] | None = None) -> Any:
    payload: dict[str, Any] = {
        "chat_id": settings.TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    return call("sendMessage", payload)
