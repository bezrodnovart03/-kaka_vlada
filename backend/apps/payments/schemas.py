from datetime import date
from decimal import Decimal
from typing import Literal

from ninja import Schema
from pydantic import Field, field_validator

from apps.core.schemas import LocalDateTime, Money, PageQuery, UserBrief

from .models import (
    Currency,
    OccurrenceStatus,
    PaymentOccurrence,
    Period,
    RecurringPayment,
)

OccurrenceState = Literal["unpaid", "paid", "overdue", "upcoming"]


# ── регулярные платежи ───────────────────────────────────


class RecurringPaymentIn(Schema):
    title: str = Field(min_length=1, max_length=120)
    amount: Decimal = Field(max_digits=12, decimal_places=2, examples=["85000.00"])
    currency: Currency
    first_due_date: date
    period: Period = Period.MONTHLY
    comment: str | None = None

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Обязательное поле")
        return value

    @field_validator("amount")
    @classmethod
    def amount_positive(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("Сумма должна быть больше 0")
        return value

    @field_validator("comment")
    @classmethod
    def comment_strip(cls, value: str | None) -> str | None:
        return (value or "").strip() or None


class OccurrenceBrief(Schema):
    id: int
    due_date: date
    status: OccurrenceStatus
    paid_at: date | None
    is_overdue: bool


class RecurringPaymentOut(Schema):
    id: int
    title: str
    amount: Money
    currency: Currency
    period: Period
    anchor_day: int
    first_due_date: date
    comment: str | None
    is_active: bool
    deleted_at: LocalDateTime | None
    created_by: UserBrief
    created_at: LocalDateTime
    next_occurrence: OccurrenceBrief | None
    overdue_count: int

    @staticmethod
    def resolve_next_occurrence(obj: RecurringPayment) -> PaymentOccurrence | None:
        unpaid: list[PaymentOccurrence] = getattr(obj, "unpaid_occurrences", [])
        return unpaid[0] if unpaid else None

    @staticmethod
    def resolve_overdue_count(obj: RecurringPayment) -> int:
        return int(getattr(obj, "overdue_count", 0))


class RecurringPaymentFilter(PageQuery):
    currency: Currency | None = None
    search: str | None = Field(None, max_length=120)
    include_inactive: bool = False


# ── периоды оплаты ───────────────────────────────────────


class RecurringPaymentBrief(Schema):
    id: int
    title: str
    is_active: bool


class PaymentOccurrenceOut(Schema):
    id: int
    recurring_payment: RecurringPaymentBrief
    amount: Money
    currency: Currency
    due_date: date
    status: OccurrenceStatus
    paid_at: date | None
    is_overdue: bool
    overdue_days: int
    marked_by: UserBrief | None
    marked_at: LocalDateTime | None
    reminder_sent_at: LocalDateTime | None


class PaymentOccurrencePatchIn(Schema):
    """
    Один из вариантов: `{status: paid[, paid_at]}`, `{status: unpaid}`, `{paid_at}`.
    Сочетания проверяет эндпоинт: для них нужна «сегодняшняя» дата и состояние периода.
    """

    status: OccurrenceStatus | None = None
    paid_at: date | None = None


class OccurrenceFilter(PageQuery):
    recurring_payment_id: int | None = None
    currency: Currency | None = None
    state: OccurrenceState | None = None
    due_from: date | None = None
    due_to: date | None = None
    ordering: Literal["due_date", "-due_date"] = "due_date"


# ── итоги ────────────────────────────────────────────────


class SummaryQuery(Schema):
    date_from: date | None = None
    date_to: date | None = None


class CurrencyTotalsOut(Schema):
    currency: Currency
    planned: Money
    paid: Money
    unpaid: Money
    overdue: Money
    count_planned: int
    count_paid: int
    count_overdue: int


class SummaryOut(Schema):
    date_from: date
    date_to: date
    today: date
    totals: list[CurrencyTotalsOut]


# ── пагинация (`Paginated<T>`) ───────────────────────────


class PaginatedRecurringPaymentOut(Schema):
    items: list[RecurringPaymentOut]
    count: int


class PaginatedPaymentOccurrenceOut(Schema):
    items: list[PaymentOccurrenceOut]
    count: int
