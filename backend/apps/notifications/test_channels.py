import io
import json
from datetime import date
from decimal import Decimal
from typing import Any
from unittest import mock

import httpx
from django.core import mail
from django.core.mail import EmailMultiAlternatives
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings

from apps.payments import services as payment_services
from apps.payments.models import OccurrenceStatus, PaymentOccurrence, RecurringPayment
from apps.users.models import User, UserRole

from . import channels, services, telegram
from .models import Channel, ReminderDelivery

TODAY = date(2026, 10, 23)
CHAT = "-100500"
WEBHOOK = "https://hooks.example.com/invoice-keeper"


@override_settings(
    TELEGRAM_BOT_TOKEN="",
    TELEGRAM_CHAT_ID="",
    REMINDER_DAYS_BEFORE=3,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class ChannelTests(TestCase):
    """Email, webhook и Apprise: без дублей в каждом канале, повтор после ошибки."""

    def setUp(self) -> None:
        patcher = mock.patch("django.utils.timezone.localdate", return_value=TODAY)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.admin = User.objects.create_user(username="boss", password="x", role=UserRole.ADMIN)
        self.requests: list[httpx.Request] = []
        self.webhook_status = 200

        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return httpx.Response(self.webhook_status)

        transport = mock.patch.object(channels, "webhook_transport", httpx.MockTransport(handler))
        transport.start()
        self.addCleanup(transport.stop)

    def payment(self, first_due_date: date, **extra: Any) -> RecurringPayment:
        payment = RecurringPayment.objects.create(
            title=extra.pop("title", "Аренда офиса"),
            amount=Decimal("85000.00"),
            currency="RUB",
            first_due_date=first_due_date,
            anchor_day=first_due_date.day,
            created_by=self.admin,
            **extra,
        )
        payment_services.sync_occurrences(payment, TODAY)
        return payment

    def auth_headers(self) -> dict[str, str]:
        login = self.client.post(
            "/api/v1/auth/login",
            {"username": "boss", "password": "x"},
            content_type="application/json",
        )
        return {"Authorization": f"Bearer {login.json()['access']}"}

    # ── email ──

    @override_settings(
        REMINDER_EMAIL_TO=["team@example.com", "TEAM@example.com", "cfo@example.com"]
    )
    def test_email_once_per_recipient_with_ics(self) -> None:
        self.payment(date(2026, 10, 26), comment="Договор №7")

        self.assertEqual(services.run_check(), 1)
        self.assertEqual(services.run_check(), 0)  # повторная проверка — без дубля

        # Адрес в разном регистре — один получатель; каждому — отдельное письмо.
        self.assertEqual(
            sorted(m.to[0] for m in mail.outbox), ["cfo@example.com", "team@example.com"]
        )
        message = mail.outbox[0]
        self.assertIn("Аренда офиса", message.subject)
        self.assertIn("85 000,00 ₽ RUB", message.body)
        self.assertIn("Договор №7", message.body)
        assert isinstance(message, EmailMultiAlternatives)
        self.assertEqual(message.alternatives[0][1], "text/html")
        _name, content, mimetype = message.attachments[0]
        self.assertEqual(mimetype, "text/calendar")
        self.assertIn("BEGIN:VCALENDAR", content)
        self.assertIn("DTSTART;VALUE=DATE:20261026", content)
        self.assertTrue(ReminderDelivery.objects.filter(channel=Channel.EMAIL).exists())

    @override_settings(REMINDER_EMAIL_TO_USERS=True)
    def test_email_to_active_users(self) -> None:
        # Админ из .env тоже активный пользователь: его email зависит от окружения.
        User.objects.update(email="")
        User.objects.create_user(username="anna", password="x", email="anna@example.com")
        User.objects.create_user(
            username="gone", password="x", email="gone@example.com", is_active=False
        )
        self.payment(date(2026, 10, 24))

        services.run_check()

        self.assertEqual([m.to[0] for m in mail.outbox], ["anna@example.com"])

    @override_settings(REMINDER_EMAIL_TO=["team@example.com"])
    def test_email_failure_is_retried(self) -> None:
        self.payment(date(2026, 10, 24))

        with mock.patch(
            "django.core.mail.backends.locmem.EmailBackend.send_messages",
            side_effect=OSError("smtp down"),
        ):
            self.assertEqual(services.run_check(), 0)
        self.assertFalse(ReminderDelivery.objects.exists())

        self.assertEqual(services.run_check(), 1)
        self.assertEqual(len(mail.outbox), 1)

    # ── webhook ──

    @override_settings(WEBHOOK_URL=WEBHOOK, WEBHOOK_SECRET="s3cret")
    def test_webhook_signed_payload_once(self) -> None:
        payment = self.payment(date(2026, 10, 25))

        self.assertEqual(services.run_check(), 1)
        self.assertEqual(services.run_check(), 0)

        self.assertEqual(len(self.requests), 1)
        request = self.requests[0]
        self.assertEqual(str(request.url), WEBHOOK)
        body = request.read()
        self.assertEqual(request.headers[channels.SIGNATURE_HEADER], channels.sign(body, "s3cret"))
        self.assertEqual(request.headers[channels.EVENT_HEADER], "payment.reminder")
        payload = json.loads(body)
        self.assertEqual(payload["event"], "payment.reminder")
        self.assertEqual(payload["recurring_payment"]["id"], payment.id)
        self.assertEqual(payload["occurrence"]["due_date"], "2026-10-25")
        self.assertEqual(payload["occurrence"]["days_left"], 2)
        self.assertEqual(payload["occurrence"]["amount"], "85000.00")
        self.assertEqual(payload["occurrence"]["currency"], "RUB")

    @override_settings(WEBHOOK_URL=WEBHOOK)
    def test_webhook_error_status_is_retried(self) -> None:
        self.payment(date(2026, 10, 24))
        self.webhook_status = 500

        self.assertEqual(services.run_check(), 0)
        self.assertFalse(ReminderDelivery.objects.exists())

        self.webhook_status = 204
        self.assertEqual(services.run_check(), 1)
        self.assertEqual(len(self.requests), 2)
        self.assertNotIn(channels.SIGNATURE_HEADER, self.requests[0].headers)  # секрет не задан

    @override_settings(WEBHOOK_URL=WEBHOOK)
    def test_paid_and_deleted_not_sent(self) -> None:
        self.payment(date(2026, 10, 24), title="Оплачен")
        PaymentOccurrence.objects.update(status=OccurrenceStatus.PAID, paid_at=TODAY)
        deleted = self.payment(date(2026, 10, 25), title="Удалён")
        payment_services.delete_payment(deleted, self.admin, TODAY)

        self.assertEqual(services.run_check(), 0)
        self.assertEqual(self.requests, [])

    # ── Apprise ──

    @override_settings(NOTIFY_URLS=["json://localhost:9/hook"])
    def test_apprise_markdown_once(self) -> None:
        self.payment(date(2026, 10, 24))

        with mock.patch("apprise.Apprise.notify", return_value=True) as notify:
            self.assertEqual(services.run_check(), 1)
            self.assertEqual(services.run_check(), 0)

        notify.assert_called_once()
        self.assertIn("**Аренда офиса**", notify.call_args.kwargs["body"])

    @override_settings(NOTIFY_URLS=["definitely-not-a-service"])
    def test_apprise_invalid_url_not_marked(self) -> None:
        self.payment(date(2026, 10, 24))

        self.assertEqual(services.run_check(), 0)
        self.assertFalse(ReminderDelivery.objects.exists())

    # ── вместе ──

    @override_settings(TELEGRAM_BOT_TOKEN="123:abc", TELEGRAM_CHAT_ID=CHAT, WEBHOOK_URL=WEBHOOK)
    def test_channels_independent(self) -> None:
        self.payment(date(2026, 10, 24))

        with mock.patch.object(telegram, "send_message", side_effect=telegram.TelegramError("x")):
            self.assertEqual(services.run_check(), 1)  # webhook ушёл, Telegram — нет
        self.assertIsNone(PaymentOccurrence.objects.get().reminder_sent_at)

        with mock.patch.object(telegram, "send_message") as send:
            self.assertEqual(services.run_check(), 1)  # дослали только в Telegram
        send.assert_called_once()
        self.assertEqual(len(self.requests), 1)

    @override_settings(WEBHOOK_URL=WEBHOOK)
    def test_api_lists_reminder_channels(self) -> None:
        self.payment(date(2026, 10, 24))
        services.run_check()

        response = self.client.get("/api/v1/payment-occurrences", headers=self.auth_headers())

        item = response.json()["items"][0]
        self.assertEqual([r["channel"] for r in item["reminders"]], ["webhook"])
        self.assertIsNone(item["reminder_sent_at"])
        self.assertEqual(item["attachments_count"], 0)

    @override_settings(WEBHOOK_URL=WEBHOOK)
    def test_created_close_to_due_date_reminds_immediately(self) -> None:
        headers = self.auth_headers()

        inline = mock.patch.object(services, "_run_in_background", side_effect=lambda f: f())
        with inline, self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                "/api/v1/recurring-payments",
                {
                    "title": "Сервер",
                    "amount": "49",
                    "currency": "USD",
                    "first_due_date": "2026-10-24",
                },
                content_type="application/json",
                headers=headers,
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(self.requests), 1)

    @override_settings(WEBHOOK_URL=WEBHOOK)
    def test_check_channels_command(self) -> None:
        out = io.StringIO()
        call_command("check_channels", stdout=out)

        self.assertIn("Webhook", out.getvalue())
        self.assertEqual(self.requests[0].headers[channels.EVENT_HEADER], "ping")

    def test_check_channels_without_config_fails(self) -> None:
        with self.assertRaises(CommandError):
            call_command("check_channels", stdout=io.StringIO())
