"""Бизнес-логика регулярных платежей и периодов."""

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Prefetch, Q, QuerySet
from django.utils import timezone

from apps.core.errors import ApiError, ErrorCode
from apps.users.models import User

from .models import (
    Currency,
    OccurrenceStatus,
    PaymentOccurrence,
    RecurringPayment,
)

audit = logging.getLogger("audit")


# ── периоды ──────────────────────────────────────────────


def generation_horizon(today: date) -> date:
    """Периоды заводятся заранее на срок напоминания, чтобы бот успел о них написать."""
    return today + timedelta(days=settings.REMINDER_DAYS_BEFORE)


def sync_occurrences(payment: RecurringPayment, today: date) -> None:
    """
    Создаёт недостающие периоды: все сроки до горизонта напоминаний и ещё
    хотя бы один будущий — «следующий период с отдельным статусом».
    Существующие периоды не трогает: прошлые оплаты и просрочки сохраняются.
    """
    if not payment.is_active:
        return
    existing = set(payment.occurrences.values_list("due_date", flat=True))
    horizon = generation_horizon(today)
    has_upcoming = False
    for due_date in payment.schedule():
        if due_date > horizon and has_upcoming:
            break
        if due_date not in existing:
            PaymentOccurrence.objects.get_or_create(
                recurring_payment=payment,
                due_date=due_date,
                defaults={"amount": payment.amount, "currency": payment.currency},
            )
        has_upcoming = has_upcoming or due_date >= today
        if due_date > horizon:
            break


def sync_all_occurrences(today: date) -> None:
    for payment in RecurringPayment.objects.filter(deleted_at__isnull=True):
        sync_occurrences(payment, today)


# ── регулярные платежи ───────────────────────────────────


def payments_queryset(today: date) -> QuerySet[RecurringPayment]:
    unpaid = PaymentOccurrence.objects.filter(status=OccurrenceStatus.UNPAID).order_by("due_date")
    return (
        RecurringPayment.objects.select_related("created_by")
        .annotate(
            overdue_count=Count(
                "occurrences",
                filter=Q(
                    occurrences__status=OccurrenceStatus.UNPAID,
                    occurrences__due_date__lt=today,
                ),
            )
        )
        .prefetch_related(Prefetch("occurrences", queryset=unpaid, to_attr="unpaid_occurrences"))
    )


@transaction.atomic
def create_payment(
    *,
    user: User,
    title: str,
    amount: Decimal,
    currency: str,
    first_due_date: date,
    period: str,
    comment: str | None,
    today: date,
) -> RecurringPayment:
    payment = RecurringPayment.objects.create(
        title=title,
        amount=amount,
        currency=currency,
        first_due_date=first_due_date,
        anchor_day=first_due_date.day,
        period=period,
        comment=comment,
        created_by=user,
    )
    sync_occurrences(payment, today)
    audit.info("payment created id=%s title=%r by=%s", payment.id, title, user.username)
    return payment


@transaction.atomic
def delete_payment(payment: RecurringPayment, user: User, today: date) -> None:
    """
    Мягкое удаление: платёж прекращается, неоплаченные будущие периоды удаляются
    (вместе с ними — и напоминания), прошлые и оплаченные остаются в истории.
    """
    if not payment.is_active:
        raise ApiError(409, ErrorCode.ALREADY_DELETED, "Платёж уже удалён")
    payment.deleted_at = timezone.now()
    payment.save(update_fields=["deleted_at"])
    for occurrence in payment.occurrences.filter(
        status=OccurrenceStatus.UNPAID, due_date__gt=today
    ):
        occurrence.delete()
    audit.info("payment deleted id=%s by=%s", payment.id, user.username)


# ── оплата периода ───────────────────────────────────────


def mark_paid(
    occurrence: PaymentOccurrence, paid_at: date, user: User | None, source: str = "api"
) -> PaymentOccurrence:
    occurrence.status = OccurrenceStatus.PAID
    occurrence.paid_at = paid_at
    return _save_mark(occurrence, user, f"paid at={paid_at}", source)


def mark_unpaid(
    occurrence: PaymentOccurrence, user: User | None, source: str = "api"
) -> PaymentOccurrence:
    occurrence.status = OccurrenceStatus.UNPAID
    occurrence.paid_at = None
    return _save_mark(occurrence, user, "unpaid", source)


def correct_paid_at(
    occurrence: PaymentOccurrence, paid_at: date, user: User | None
) -> PaymentOccurrence:
    if not occurrence.is_paid:
        raise ApiError(409, ErrorCode.OCCURRENCE_NOT_PAID, "Период не оплачен — нечего исправлять")
    occurrence.paid_at = paid_at
    return _save_mark(occurrence, user, f"paid_at corrected={paid_at}", "api")


def _save_mark(
    occurrence: PaymentOccurrence, user: User | None, action: str, source: str
) -> PaymentOccurrence:
    occurrence.marked_by = user
    occurrence.marked_at = timezone.now()
    occurrence.save(update_fields=["status", "paid_at", "marked_by", "marked_at"])
    audit.info(
        "occurrence id=%s %s by=%s via=%s",
        occurrence.id,
        action,
        user.username if user else "-",
        source,
    )
    return occurrence


# ── итоги по валютам ─────────────────────────────────────


@dataclass
class CurrencyTotals:
    currency: str
    planned: Decimal = Decimal("0.00")
    paid: Decimal = Decimal("0.00")
    unpaid: Decimal = Decimal("0.00")
    overdue: Decimal = Decimal("0.00")
    count_planned: int = 0
    count_paid: int = 0
    count_overdue: int = 0

    def add(self, amount: Decimal, *, paid: bool, overdue: bool) -> None:
        self.planned += amount
        self.count_planned += 1
        if paid:
            self.paid += amount
            self.count_paid += 1
            return
        self.unpaid += amount
        if overdue:
            self.overdue += amount
            self.count_overdue += 1


@dataclass
class Summary:
    date_from: date
    date_to: date
    today: date
    totals: list[CurrencyTotals] = field(default_factory=list)


def summarize(date_from: date, date_to: date, today: date) -> Summary:
    """
    Итоги по каждой валюте отдельно, без конвертации. Считаются периоды со сроком
    в диапазоне; для будущих сроков, периоды которых ещё не созданы, активные платежи
    дают плановую сумму по расписанию — так работает «бюджет на месяц / год».
    """
    totals = {currency: CurrencyTotals(currency) for currency in Currency.values}

    occurrences = PaymentOccurrence.objects.filter(due_date__gte=date_from, due_date__lte=date_to)
    for occurrence in occurrences.only("amount", "currency", "due_date", "status"):
        totals[occurrence.currency].add(
            occurrence.amount,
            paid=occurrence.is_paid,
            overdue=occurrence.due_date < today,
        )

    for payment in RecurringPayment.objects.filter(deleted_at__isnull=True):
        last = payment.occurrences.order_by("-due_date").values_list("due_date", flat=True).first()
        for due_date in payment.schedule():
            if due_date > date_to:
                break
            # Прошлые сроки уже представлены реальными периодами (или удалены осознанно).
            if due_date < date_from or (last is not None and due_date <= last):
                continue
            totals[payment.currency].add(payment.amount, paid=False, overdue=due_date < today)

    return Summary(
        date_from=date_from,
        date_to=date_to,
        today=today,
        totals=[totals[currency] for currency in Currency.values],
    )
