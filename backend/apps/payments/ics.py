"""Периоды оплаты в формате iCalendar (RFC 5545): импорт в Google, Apple, Outlook-календарь."""

from collections.abc import Iterable
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.utils import timezone
from icalendar import Alarm, Calendar, Event

from apps.notifications.formatting import format_money

from .models import PaymentOccurrence, RecurringPayment

UID_DOMAIN = "invoice-keeper"


def _event(
    payment: RecurringPayment,
    due_date: date,
    amount: Decimal,
    currency: str,
    paid_at: date | None,
) -> Event:
    """Событие на весь день срока; у неоплаченного — оповещение за REMINDER_DAYS_BEFORE дней."""
    money = format_money(amount, currency)
    event = Event()
    # UID по (платёж, срок) — та же пара уникальна у периодов. Плановый срок и созданный
    # позже период дают одно событие: повторный импорт обновляет его, а не дублирует.
    event.add("uid", f"payment-{payment.id}-{due_date:%Y%m%d}@{UID_DOMAIN}")
    event.add("dtstamp", timezone.now())
    event.add("dtstart", due_date)
    event.add("dtend", due_date + timedelta(days=1))
    event.add("transp", "TRANSPARENT")
    mark = "✅ " if paid_at is not None else ""
    event.add("summary", f"{mark}Оплата: {payment.title} — {money}")

    lines = [f"Сумма: {money}", f"Срок: {due_date:%d.%m.%Y}"]
    if paid_at is not None:
        lines.append(f"Оплачено: {paid_at:%d.%m.%Y}")
    if payment.comment:
        lines.append(f"Комментарий: {payment.comment}")
    if settings.PANEL_URL:
        lines.append(settings.PANEL_URL)
        event.add("url", settings.PANEL_URL)
    event.add("description", "\n".join(lines))

    if paid_at is None:
        alarm = Alarm()
        alarm.add("action", "DISPLAY")
        alarm.add("description", f"Оплатить: {payment.title} — {money}")
        alarm.add("trigger", -timedelta(days=settings.REMINDER_DAYS_BEFORE))
        event.add_component(alarm)
    return event


def occurrence_event(occurrence: PaymentOccurrence) -> Event:
    return _event(
        occurrence.recurring_payment,
        occurrence.due_date,
        occurrence.amount,
        occurrence.currency,
        occurrence.paid_at,
    )


def planned_event(payment: RecurringPayment, due_date: date) -> Event:
    """Будущий срок по расписанию, период для которого ещё не создан."""
    return _event(payment, due_date, payment.amount, payment.currency, None)


def build_calendar(events: Iterable[Event]) -> bytes:
    calendar = Calendar()
    calendar.add("prodid", "-//Invoice Keeper//Payments//RU")
    calendar.add("version", "2.0")
    calendar.add("calscale", "GREGORIAN")
    calendar.add("method", "PUBLISH")
    calendar.add("x-wr-calname", "Invoice Keeper — оплаты")
    calendar.add("x-wr-timezone", settings.TIME_ZONE)
    for event in events:
        calendar.add_component(event)
    ical: bytes = calendar.to_ical()
    return ical


def occurrences_calendar(occurrences: Iterable[PaymentOccurrence]) -> bytes:
    return build_calendar(occurrence_event(occurrence) for occurrence in occurrences)
