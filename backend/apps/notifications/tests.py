from datetime import date
from decimal import Decimal
from typing import Any
from unittest import mock

from django.test import TestCase, override_settings

from apps.payments import services as payment_services
from apps.payments.models import OccurrenceStatus, PaymentOccurrence, RecurringPayment
from apps.users.models import User, UserRole

from . import services, telegram

TODAY = date(2026, 10, 23)
CHAT = "-100500"


@override_settings(TELEGRAM_BOT_TOKEN="123:abc", TELEGRAM_CHAT_ID=CHAT, REMINDER_DAYS_BEFORE=3)
class ReminderTests(TestCase):
    def setUp(self) -> None:
        patcher = mock.patch("django.utils.timezone.localdate", return_value=TODAY)
        patcher.start()
        self.addCleanup(patcher.stop)
        send = mock.patch.object(telegram, "send_message")
        self.send = send.start()
        self.addCleanup(send.stop)
        self.admin = User.objects.create_user(username="boss", password="x", role=UserRole.ADMIN)

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

    def test_reminds_three_days_before_once(self) -> None:
        self.payment(date(2026, 10, 26))

        self.assertEqual(services.run_check(), 1)
        self.assertEqual(services.run_check(), 0)  # повторная проверка — без дубля

        self.send.assert_called_once()
        text = self.send.call_args.args[0]
        self.assertIn("Аренда офиса", text)
        self.assertIn("85 000,00 ₽ RUB", text)
        self.assertIn("26.10.2026", text)
        occurrence = PaymentOccurrence.objects.get(due_date=date(2026, 10, 26))
        self.assertIsNotNone(occurrence.reminder_sent_at)

    def test_too_early_no_reminder(self) -> None:
        self.payment(date(2026, 10, 27))

        self.assertEqual(services.run_check(), 0)
        self.send.assert_not_called()

    def test_paid_period_not_reminded(self) -> None:
        self.payment(date(2026, 10, 25))
        PaymentOccurrence.objects.update(status=OccurrenceStatus.PAID, paid_at=TODAY)

        self.assertEqual(services.run_check(), 0)

    def test_deleted_payment_not_reminded(self) -> None:
        payment = self.payment(date(2026, 10, 24))
        payment_services.delete_payment(payment, self.admin, TODAY)

        self.assertEqual(services.run_check(), 0)
        self.send.assert_not_called()

    def test_failed_send_is_retried(self) -> None:
        self.payment(date(2026, 10, 24))
        self.send.side_effect = telegram.TelegramError("down")

        self.assertEqual(services.run_check(), 0)
        self.assertIsNone(PaymentOccurrence.objects.get().reminder_sent_at)

        self.send.side_effect = None
        self.assertEqual(services.run_check(), 1)

    def test_created_close_to_due_date_reminds_immediately(self) -> None:
        login = self.client.post(
            "/api/v1/auth/login",
            {"username": "boss", "password": "x"},
            content_type="application/json",
        )
        headers = {"Authorization": f"Bearer {login.json()['access']}"}

        # Фоновый поток в тесте запускаем синхронно: иначе он не увидит данные транзакции теста.
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
        self.send.assert_called_once()
        self.assertIn("Сервер", self.send.call_args.args[0])

    @override_settings(TELEGRAM_BOT_TOKEN="", TELEGRAM_CHAT_ID="")
    def test_not_configured_does_nothing(self) -> None:
        self.payment(date(2026, 10, 24))

        self.assertEqual(services.run_check(), 0)
        self.assertIsNone(PaymentOccurrence.objects.get().reminder_sent_at)

    def test_pay_button_marks_paid_once(self) -> None:
        self.payment(date(2026, 10, 24))
        occurrence = PaymentOccurrence.objects.get()
        callback = {
            "id": "1",
            "data": f"paid:{occurrence.id}",
            "from": {"username": "anna"},
            "message": {"chat": {"id": int(CHAT)}},
        }

        self.assertEqual(services.handle_pay_callback(callback), "Отмечено как оплачено")
        occurrence.refresh_from_db()
        self.assertEqual(occurrence.status, OccurrenceStatus.PAID)
        self.assertEqual(occurrence.paid_at, TODAY)
        self.assertTrue(services.handle_pay_callback(callback).startswith("Уже оплачено"))

    def test_pay_button_from_other_chat_ignored(self) -> None:
        self.payment(date(2026, 10, 24))
        occurrence = PaymentOccurrence.objects.get()
        callback = {"id": "1", "data": f"paid:{occurrence.id}", "message": {"chat": {"id": 1}}}

        self.assertEqual(services.handle_pay_callback(callback), "Недоступно в этом чате")
        occurrence.refresh_from_db()
        self.assertEqual(occurrence.status, OccurrenceStatus.UNPAID)

    def test_create_does_not_wait_for_telegram(self) -> None:
        login = self.client.post(
            "/api/v1/auth/login",
            {"username": "boss", "password": "x"},
            content_type="application/json",
        )
        headers = {"Authorization": f"Bearer {login.json()['access']}"}

        with (
            mock.patch.object(services, "_run_in_background") as background,
            self.captureOnCommitCallbacks(execute=True),
        ):
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
        background.assert_called_once()
        self.send.assert_not_called()  # отправка ушла в поток, запрос её не ждал

    def test_failing_callback_does_not_block_next_updates(self) -> None:
        self.payment(date(2026, 10, 24))
        occurrence = PaymentOccurrence.objects.get()

        def callback(update_id: int, data: str) -> dict[str, Any]:
            return {
                "update_id": update_id,
                "callback_query": {
                    "id": str(update_id),
                    "data": data,
                    "message": {"chat": {"id": int(CHAT)}},
                },
            }

        updates = [callback(10, f"paid:{occurrence.id}"), callback(11, f"paid:{occurrence.id}")]
        calls: list[tuple[str, dict[str, Any]]] = []

        def fake_call(method: str, payload: dict[str, Any], timeout: float = 10) -> Any:
            calls.append((method, payload))
            return updates if method == "getUpdates" else True

        real_handle = services.handle_pay_callback
        failures = iter([RuntimeError("db down")])

        def flaky_handle(cb: dict[str, Any], today: date | None = None) -> str:
            error = next(failures, None)
            if error is not None:
                raise error
            return real_handle(cb, today)

        with (
            mock.patch.object(telegram, "call", side_effect=fake_call),
            mock.patch.object(services, "handle_pay_callback", side_effect=flaky_handle),
        ):
            offset = services.poll_updates(None, timeout=0)

        self.assertEqual(offset, 12)
        answers = [p["text"] for m, p in calls if m == "answerCallbackQuery"]
        self.assertEqual(
            answers, ["Не удалось отметить оплату, попробуйте в панели", "Отмечено как оплачено"]
        )
        occurrence.refresh_from_db()
        self.assertEqual(occurrence.status, OccurrenceStatus.PAID)
