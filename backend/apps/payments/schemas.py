from datetime import date
from decimal import Decimal
from typing import Any, Literal

from ninja import Schema
from pydantic import ConfigDict, Field, field_validator, model_validator

from apps.core.schemas import (
    InputSchema,
    ISODate,
    LocalDateTime,
    Money,
    MultilineText,
    PageQuery,
    PlainText,
    UserBrief,
)

from .models import (
    AttachmentKind,
    Currency,
    OccurrenceStatus,
    PaymentOccurrence,
    Period,
    RecurringPayment,
)

OccurrenceState = Literal["unpaid", "paid", "overdue", "upcoming"]


# ── регулярные платежи ───────────────────────────────────


class RecurringPaymentIn(InputSchema):
    title: PlainText = Field(min_length=1, max_length=120)
    amount: Decimal = Field(max_digits=12, decimal_places=2, examples=["85000.00"])
    currency: Currency
    first_due_date: ISODate = Field(
        description="Не раньше чем 12 месяцев назад и не позже чем через 10 лет от сегодня."
    )
    period: Period = Period.MONTHLY
    comment: MultilineText | None = None

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
    search: PlainText | None = Field(None, max_length=120)
    include_inactive: bool = False


# ── периоды оплаты ───────────────────────────────────────


class RecurringPaymentBrief(Schema):
    id: int
    title: str
    is_active: bool


ReminderChannelName = Literal["telegram", "email", "webhook", "apprise"]


class ReminderOut(Schema):
    channel: ReminderChannelName
    sent_at: LocalDateTime


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
    reminder_sent_at: LocalDateTime | None = Field(description="Напоминание в Telegram")
    reminders: list[ReminderOut] = Field(description="Напоминания по всем каналам")
    attachments_count: int = Field(description="Число прикреплённых чеков и ссылок")

    @staticmethod
    def resolve_reminders(obj: PaymentOccurrence) -> list[dict[str, Any]]:
        reminders: list[dict[str, Any]] = []
        if obj.reminder_sent_at is not None:
            reminders.append({"channel": "telegram", "sent_at": obj.reminder_sent_at})
        # related_name модели apps.notifications.ReminderDelivery; в запросах — prefetch.
        reminders += [
            {"channel": delivery.channel, "sent_at": delivery.sent_at}
            for delivery in obj.reminder_deliveries.all()
        ]
        return reminders

    @staticmethod
    def resolve_attachments_count(obj: PaymentOccurrence) -> int:
        count = getattr(obj, "attachments_total", None)
        return int(count) if count is not None else obj.attachments.count()


_DATE_JSON_SCHEMA = {"type": "string", "format": "date", "example": "2026-10-23"}


def _patch_variants_schema(schema: dict[str, Any]) -> None:
    """OpenAPI: ровно три варианта тела, как `PaymentOccurrencePatchIn` в docs/API.md §9."""

    def variant(title: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
        return {
            "title": title,
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        }

    variants = [
        variant(
            "Отметить оплаченным (без paid_at — сегодня)",
            {"status": {"const": "paid"}, "paid_at": _DATE_JSON_SCHEMA},
            ["status"],
        ),
        variant("Отменить оплату", {"status": {"const": "unpaid"}}, ["status"]),
        variant("Исправить дату оплаты", {"paid_at": _DATE_JSON_SCHEMA}, ["paid_at"]),
    ]
    title = schema.get("title")
    schema.clear()
    schema.update({"title": title, "oneOf": variants})


class PaymentOccurrencePatchIn(InputSchema):
    """
    Один из вариантов: `{status: paid[, paid_at]}`, `{status: unpaid}`, `{paid_at}`.
    Сочетания проверяет эндпоинт: для них нужна «сегодняшняя» дата и состояние периода.
    """

    model_config = ConfigDict(extra="forbid", json_schema_extra=_patch_variants_schema)

    # None — «поле не прислано»; явный null отклоняется (в контракте null не предусмотрен).
    status: OccurrenceStatus | None = None
    paid_at: ISODate | None = None

    @model_validator(mode="before")
    @classmethod
    def reject_nulls(cls, values: Any) -> Any:
        if isinstance(values, dict):
            nulls = [
                name for name in ("status", "paid_at") if name in values and values[name] is None
            ]
            if nulls:
                raise ValueError(f"Поле не может быть null: {', '.join(nulls)}")
        return values


class OccurrenceFilter(PageQuery):
    recurring_payment_id: int | None = None
    currency: Currency | None = None
    state: OccurrenceState | None = None
    due_from: ISODate | None = None
    due_to: ISODate | None = None
    ordering: Literal["due_date", "-due_date"] = "due_date"


# ── чеки и ссылки ────────────────────────────────────────


class AttachmentOut(Schema):
    id: int
    kind: AttachmentKind
    name: str
    url: str | None = Field(description="Для ссылки — адрес; для файла — null")
    content_type: str = Field(description="Для файла — тип по содержимому; для ссылки — пусто")
    size: int | None
    uploaded_by: UserBrief | None
    created_at: LocalDateTime


class AttachmentLinkIn(InputSchema):
    url: PlainText = Field(min_length=1, max_length=2000, examples=["https://example.com/receipt"])
    name: PlainText | None = Field(None, max_length=255, description="По умолчанию — сама ссылка")


class CalendarQuery(Schema):
    currency: Currency | None = None
    state: OccurrenceState | None = None
    due_from: ISODate | None = Field(None, description="По умолчанию — 3 месяца назад")
    due_to: ISODate | None = Field(None, description="По умолчанию — через 12 месяцев")


# ── итоги ────────────────────────────────────────────────


class SummaryQuery(Schema):
    date_from: ISODate | None = None
    date_to: ISODate | None = None


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
