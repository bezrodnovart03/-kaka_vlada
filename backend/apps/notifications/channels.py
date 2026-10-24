"""
Дополнительные каналы напоминаний: email (SMTP), webhook и другие сервисы через Apprise.

У каждого канала одна задача — доставить напоминание по периоду или поднять ChannelError.
Дедупликацию и повтор после ошибки делает services.send_due_reminders через ReminderDelivery.
"""

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol

import apprise
import httpx
from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection
from django.utils import timezone
from django.utils.html import escape, linebreaks

from apps.payments.ics import occurrences_calendar
from apps.payments.models import PaymentOccurrence
from apps.users.models import User

from .formatting import format_due, format_money
from .models import Channel

SIGNATURE_HEADER = "X-Invoice-Keeper-Signature"
EVENT_HEADER = "X-Invoice-Keeper-Event"
DELIVERY_HEADER = "X-Invoice-Keeper-Delivery"
REMINDER_EVENT = "payment.reminder"
TEST_EVENT = "ping"

# Подменяется в тестах (httpx.MockTransport), в работе — обычный сетевой транспорт.
webhook_transport: httpx.BaseTransport | None = None


class ChannelError(Exception):
    pass


@dataclass(frozen=True)
class Reminder:
    """Содержимое напоминания, общее для всех каналов."""

    occurrence: PaymentOccurrence
    today: date

    @property
    def title(self) -> str:
        return self.occurrence.recurring_payment.title

    @property
    def money(self) -> str:
        return format_money(self.occurrence.amount, self.occurrence.currency)

    @property
    def due(self) -> str:
        return format_due(self.occurrence.due_date, self.today)

    @property
    def subject(self) -> str:
        return f"Напоминание об оплате: {self.title} — {self.occurrence.due_date:%d.%m.%Y}"

    def lines(self) -> list[str]:
        lines = [f"Сумма: {self.money}", f"Оплатить до: {self.due}"]
        comment = self.occurrence.recurring_payment.comment
        if comment:
            lines.append(f"Комментарий: {comment}")
        return lines


class ReminderChannel(Protocol):
    channel: Channel

    def is_configured(self) -> bool: ...

    def send(self, reminder: Reminder) -> None: ...

    def send_test(self) -> None: ...


# ── email ────────────────────────────────────────────────


def email_recipients() -> list[str]:
    """REMINDER_EMAIL_TO и (если включено) email активных пользователей, без повторов."""
    seen: dict[str, str] = {}
    addresses = list(settings.REMINDER_EMAIL_TO)
    if settings.REMINDER_EMAIL_TO_USERS:
        addresses += (
            User.objects.filter(is_active=True).exclude(email="").values_list("email", flat=True)
        )
    for address in addresses:
        address = address.strip()
        if address:
            seen.setdefault(address.casefold(), address)
    return list(seen.values())


class EmailChannel:
    channel = Channel.EMAIL

    def is_configured(self) -> bool:
        return bool(settings.REMINDER_EMAIL_TO or settings.REMINDER_EMAIL_TO_USERS)

    def _send(self, messages: list[EmailMultiAlternatives]) -> None:
        if not messages:
            raise ChannelError("email: нет получателей")
        try:
            with get_connection(fail_silently=False) as connection:
                connection.send_messages(messages)
        except Exception as exc:  # smtplib, socket, ssl — у всех свои исключения
            raise ChannelError(f"email: {exc}") from exc

    def message(self, reminder: Reminder, to: str) -> EmailMultiAlternatives:
        text_lines = ["Напоминание об оплате", "", reminder.title, *reminder.lines()]
        if settings.PANEL_URL:
            text_lines += ["", f"Панель: {settings.PANEL_URL}"]
        html_rows = "".join(
            f"<tr><td style='padding:2px 12px 2px 0;color:#666'>{escape(label)}</td>"
            f"<td><b>{escape(value)}</b></td></tr>"
            for label, _, value in (line.partition(": ") for line in reminder.lines())
        )
        panel_link = (
            f"<p><a href='{escape(settings.PANEL_URL)}'>Открыть панель</a></p>"
            if settings.PANEL_URL
            else ""
        )
        html = (
            "<div style='font-family:Arial,sans-serif;font-size:14px'>"
            "<p>🔔 Напоминание об оплате</p>"
            f"<h2 style='margin:8px 0'>{escape(reminder.title)}</h2>"
            f"<table>{html_rows}</table>{panel_link}"
            "<p style='color:#888;font-size:12px'>Событие для календаря — во вложении.</p>"
            "</div>"
        )
        message = EmailMultiAlternatives(
            subject=reminder.subject, body="\n".join(text_lines), to=[to]
        )
        message.attach_alternative(html, "text/html")
        message.attach(
            f"payment-{reminder.occurrence.id}.ics",
            occurrences_calendar([reminder.occurrence]),
            "text/calendar",
        )
        return message

    def send(self, reminder: Reminder) -> None:
        # Отдельное письмо каждому: адреса команды не раскрываются друг другу.
        self._send([self.message(reminder, to) for to in email_recipients()])

    def send_test(self) -> None:
        body = "Тестовое сообщение Invoice Keeper: email-напоминания настроены."
        messages = [
            EmailMultiAlternatives(subject="Invoice Keeper: проверка канала", body=body, to=[to])
            for to in email_recipients()
        ]
        for message in messages:
            message.attach_alternative(linebreaks(escape(body)), "text/html")
        self._send(messages)


# ── webhook ──────────────────────────────────────────────


def sign(body: bytes, secret: str) -> str:
    """Подпись тела: `sha256=<hex>` — как у GitHub. Получатель сверяет hmac.compare_digest."""
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def reminder_payload(reminder: Reminder) -> dict[str, Any]:
    occurrence = reminder.occurrence
    payment = occurrence.recurring_payment
    return {
        "event": REMINDER_EVENT,
        "sent_at": timezone.localtime().isoformat(timespec="seconds"),
        "occurrence": {
            "id": occurrence.id,
            "due_date": occurrence.due_date.isoformat(),
            "days_left": (occurrence.due_date - reminder.today).days,
            "amount": f"{occurrence.amount:.2f}",
            "currency": occurrence.currency,
            "status": occurrence.status,
        },
        "recurring_payment": {
            "id": payment.id,
            "title": payment.title,
            "period": payment.period,
            "comment": payment.comment,
        },
        "text": "\n".join([f"Напоминание об оплате: {reminder.title}", *reminder.lines()]),
        "panel_url": settings.PANEL_URL or None,
    }


class WebhookChannel:
    channel = Channel.WEBHOOK

    def is_configured(self) -> bool:
        return bool(settings.WEBHOOK_URL)

    def post(self, event: str, payload: dict[str, Any], delivery_id: str) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "InvoiceKeeper-Webhook/1.0",
            EVENT_HEADER: event,
            # Ключ идемпотентности: при повторе после сетевой ошибки получатель отбросит дубль.
            DELIVERY_HEADER: delivery_id,
        }
        if settings.WEBHOOK_SECRET:
            headers[SIGNATURE_HEADER] = sign(body, settings.WEBHOOK_SECRET)
        try:
            with httpx.Client(
                transport=webhook_transport, timeout=settings.WEBHOOK_TIMEOUT
            ) as client:
                response = client.post(settings.WEBHOOK_URL, content=body, headers=headers)
        except httpx.HTTPError as exc:
            raise ChannelError(f"webhook: {exc}") from exc
        if not response.is_success:
            raise ChannelError(f"webhook: HTTP {response.status_code}")

    def send(self, reminder: Reminder) -> None:
        self.post(
            REMINDER_EVENT,
            reminder_payload(reminder),
            f"{REMINDER_EVENT}:{reminder.occurrence.id}",
        )

    def send_test(self) -> None:
        now = timezone.localtime().isoformat(timespec="seconds")
        self.post(TEST_EVENT, {"event": TEST_EVENT, "sent_at": now}, f"{TEST_EVENT}:{now}")


# ── другие каналы (Apprise) ──────────────────────────────


class AppriseChannel:
    """Discord, Slack, ntfy, Matrix, MS Teams, Pushover и др. — по URL из NOTIFY_URLS."""

    channel = Channel.APPRISE

    def is_configured(self) -> bool:
        return bool(settings.NOTIFY_URLS)

    def notify(self, title: str, body: str) -> None:
        targets = apprise.Apprise()
        for url in settings.NOTIFY_URLS:
            if not targets.add(url):
                # Сам URL не выводим: в нём обычно токен сервиса.
                scheme = url.split("://", 1)[0]
                raise ChannelError(f"apprise: неверный URL сервиса ({scheme}://...)")
        if not targets.notify(title=title, body=body, body_format=apprise.NotifyFormat.MARKDOWN):
            raise ChannelError("apprise: не все сервисы приняли сообщение")

    def send(self, reminder: Reminder) -> None:
        lines = [f"**{reminder.title}**", *reminder.lines()]
        if settings.PANEL_URL:
            lines.append(f"[Открыть панель]({settings.PANEL_URL})")
        self.notify("🔔 Напоминание об оплате", "\n\n".join(lines))

    def send_test(self) -> None:
        self.notify("Invoice Keeper", "Тестовое сообщение: канал настроен.")


CHANNELS: tuple[ReminderChannel, ...] = (EmailChannel(), WebhookChannel(), AppriseChannel())


def configured_channels() -> list[ReminderChannel]:
    return [channel for channel in CHANNELS if channel.is_configured()]
