"""
Напоминания о сроках оплаты в Telegram-чат.

Правила (кейс, стр. 7–8, 10):
- минимум за REMINDER_DAYS_BEFORE (3) дня до срока: название, сумма, валюта, дата;
- без дублей: период «захватывается» атомарным UPDATE ... WHERE reminder_sent_at IS NULL,
  поэтому повторная проверка или параллельный процесс второе сообщение не отправят;
- оплаченный период и удалённый платёж напоминаний не вызывают;
- платёж добавлен позже, чем за 3 дня до срока, — напоминание сразу.
"""

import html
import logging
import threading
from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.db import connection
from django.db.models import QuerySet
from django.utils import timezone

from apps.core.schemas import local_today
from apps.payments import services as payment_services
from apps.payments.models import OccurrenceStatus, PaymentOccurrence

from . import telegram

logger = logging.getLogger("apps.notifications")

PAY_CALLBACK_PREFIX = "paid:"

CURRENCY_SIGNS = {"RUB": "₽", "USD": "$", "EUR": "€"}


def format_money(amount: Decimal, currency: str) -> str:
    whole, _, cents = f"{amount:,.2f}".partition(".")
    return f"{whole.replace(',', ' ')},{cents} {CURRENCY_SIGNS.get(currency, '')} {currency}"


def format_due(due_date: date, today: date) -> str:
    days = (due_date - today).days
    when = {0: "сегодня", 1: "завтра"}.get(days)
    if when is None:
        when = f"через {days} дн." if days > 0 else f"просрочено на {-days} дн."
    return f"{due_date:%d.%m.%Y} ({when})"


def reminder_text(occurrence: PaymentOccurrence, today: date) -> str:
    payment = occurrence.recurring_payment
    lines = [
        "🔔 <b>Напоминание об оплате</b>",
        "",
        f"<b>{html.escape(payment.title)}</b>",
        f"Сумма: {format_money(occurrence.amount, occurrence.currency)}",
        f"Оплатить до: {format_due(occurrence.due_date, today)}",
    ]
    if payment.comment:
        lines.append(f"Комментарий: {html.escape(payment.comment)}")
    if settings.PANEL_URL:
        lines += ["", f'<a href="{html.escape(settings.PANEL_URL)}">Открыть панель</a>']
    return "\n".join(lines)


def pay_keyboard(occurrence: PaymentOccurrence) -> dict[str, Any] | None:
    if not settings.TELEGRAM_PAY_BUTTON:
        return None
    return {
        "inline_keyboard": [
            [{"text": "✅ Оплачено", "callback_data": f"{PAY_CALLBACK_PREFIX}{occurrence.id}"}]
        ]
    }


def due_for_reminder(today: date) -> QuerySet[PaymentOccurrence]:
    """Неоплаченные периоды активных платежей со сроком в окне [сегодня; сегодня + N]."""
    return PaymentOccurrence.objects.filter(
        status=OccurrenceStatus.UNPAID,
        reminder_sent_at__isnull=True,
        recurring_payment__deleted_at__isnull=True,
        due_date__gte=today,
        due_date__lte=today + timedelta(days=settings.REMINDER_DAYS_BEFORE),
    ).select_related("recurring_payment")


def _claim(occurrence: PaymentOccurrence) -> bool:
    """Атомарно помечает период «напоминание отправлено». False — уже кто-то отправил."""
    claimed = PaymentOccurrence.objects.filter(
        pk=occurrence.pk,
        status=OccurrenceStatus.UNPAID,
        reminder_sent_at__isnull=True,
        recurring_payment__deleted_at__isnull=True,
    ).update(reminder_sent_at=timezone.now())
    return claimed == 1


def _release(occurrence: PaymentOccurrence) -> None:
    PaymentOccurrence.objects.filter(pk=occurrence.pk).update(reminder_sent_at=None)


def send_due_reminders(
    today: date | None = None, *, recurring_payment_id: int | None = None
) -> int:
    """Отправляет все положенные напоминания. Возвращает число отправленных сообщений."""
    if not telegram.is_configured():
        logger.debug("Telegram не настроен — напоминания пропущены")
        return 0
    today = today or local_today()
    queryset = due_for_reminder(today)
    if recurring_payment_id is not None:
        queryset = queryset.filter(recurring_payment_id=recurring_payment_id)

    sent = 0
    for occurrence in queryset.order_by("due_date", "id"):
        if not _claim(occurrence):
            continue
        try:
            telegram.send_message(reminder_text(occurrence, today), pay_keyboard(occurrence))
        except telegram.TelegramError:
            # Сообщение не ушло — снимаем отметку, следующая проверка попробует снова.
            _release(occurrence)
            logger.exception("Не удалось отправить напоминание по периоду %s", occurrence.id)
            continue
        sent += 1
        logger.info(
            "Напоминание отправлено: период %s (%s, срок %s)",
            occurrence.id,
            occurrence.recurring_payment.title,
            occurrence.due_date,
        )
    return sent


def _run_in_background(target: Callable[[], None]) -> None:
    threading.Thread(target=target, name="telegram-reminder", daemon=True).start()


def send_due_reminders_in_background(today: date, *, recurring_payment_id: int) -> None:
    """
    Напоминание сразу после создания платежа — без ожидания Telegram в HTTP-запросе.
    Если поток не отправит (сеть, остановка процесса), run_reminders дошлёт
    на следующей проверке: отметка reminder_sent_at снимается при ошибке отправки.
    """
    if not telegram.is_configured():
        return

    def send() -> None:
        try:
            send_due_reminders(today, recurring_payment_id=recurring_payment_id)
        except Exception:
            logger.exception("Фоновая отправка напоминания по платежу %s", recurring_payment_id)
        finally:
            # У потока своё подключение к БД — закрываем, чтобы не копились.
            connection.close()

    _run_in_background(send)


def run_check(today: date | None = None) -> int:
    """Один цикл проверки: дозаводит периоды и рассылает напоминания."""
    today = today or local_today()
    payment_services.sync_all_occurrences(today)
    return send_due_reminders(today)


# ── кнопка «Оплачено» в сообщении бота ───────────────────


def handle_pay_callback(callback: dict[str, Any], today: date | None = None) -> str:
    """
    Обрабатывает нажатие «Оплачено». Принимаются только нажатия из чата напоминаний.
    Возвращает текст всплывающего ответа для answerCallbackQuery.
    """
    today = today or local_today()
    message = callback.get("message") or {}
    chat_id = str((message.get("chat") or {}).get("id", ""))
    if chat_id != str(settings.TELEGRAM_CHAT_ID):
        return "Недоступно в этом чате"

    data = str(callback.get("data", ""))
    try:
        occurrence_id = int(data.removeprefix(PAY_CALLBACK_PREFIX))
    except ValueError:
        return "Неизвестная команда"

    occurrence = (
        PaymentOccurrence.objects.select_related("recurring_payment")
        .filter(pk=occurrence_id)
        .first()
    )
    if occurrence is None:
        return "Период не найден"
    if occurrence.is_paid:
        return f"Уже оплачено {occurrence.paid_at:%d.%m.%Y}"

    payment_services.mark_paid(occurrence, today, user=None, source="telegram")
    who = (callback.get("from") or {}).get("username") or (callback.get("from") or {}).get(
        "first_name", ""
    )
    logger.info("Период %s отмечен оплаченным из Telegram (%s)", occurrence.id, who)

    if message.get("message_id"):
        suffix = f"\n\n✅ <b>Оплачено</b> {today:%d.%m.%Y}" + (
            f" — {html.escape(str(who))}" if who else ""
        )
        try:
            telegram.call(
                "editMessageText",
                {
                    "chat_id": message["chat"]["id"],
                    "message_id": message["message_id"],
                    "text": reminder_text(occurrence, today) + suffix,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
            )
        except telegram.TelegramError:
            logger.exception("Не удалось обновить сообщение %s", message["message_id"])
    return "Отмечено как оплачено"


def poll_updates(offset: int | None, timeout: int) -> int | None:
    """Long-polling getUpdates: обрабатывает нажатия кнопок. Возвращает новый offset."""
    payload: dict[str, Any] = {"timeout": timeout, "allowed_updates": ["callback_query"]}
    if offset is not None:
        payload["offset"] = offset
    updates = telegram.call("getUpdates", payload, timeout=timeout + 10) or []
    for update in updates:
        # offset сдвигаем до обработки: упавшее обновление не должно приходить снова
        # и блокировать все следующие нажатия.
        offset = int(update["update_id"]) + 1
        callback = update.get("callback_query")
        if not callback:
            continue
        if not str(callback.get("data", "")).startswith(PAY_CALLBACK_PREFIX):
            continue
        try:
            answer = handle_pay_callback(callback)
        except Exception:
            logger.exception("Ошибка обработки кнопки «Оплачено»: update %s", update["update_id"])
            answer = "Не удалось отметить оплату, попробуйте в панели"
        # Отвечаем всегда — иначе кнопка в Telegram бесконечно «крутится».
        try:
            telegram.call(
                "answerCallbackQuery", {"callback_query_id": callback["id"], "text": answer}
            )
        except telegram.TelegramError:
            logger.exception("answerCallbackQuery failed")
    return offset
