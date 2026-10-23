from datetime import timedelta

from django.db import transaction
from django.db.models import QuerySet
from ninja import Query, Router

from apps.core.auth import admin_auth
from apps.core.errors import ApiError, ErrorCode, ErrorOut, field_error
from apps.core.schemas import local_today, paginate
from apps.notifications.services import send_due_reminders
from apps.users.types import AuthedRequest

from . import services
from .models import OccurrenceStatus, PaymentOccurrence, RecurringPayment
from .schedule import shift_months
from .schemas import (
    OccurrenceFilter,
    PaginatedPaymentOccurrenceOut,
    PaginatedRecurringPaymentOut,
    PaymentOccurrenceOut,
    PaymentOccurrencePatchIn,
    RecurringPaymentFilter,
    RecurringPaymentIn,
    RecurringPaymentOut,
    SummaryOut,
    SummaryQuery,
)

recurring_router = Router(tags=["recurring-payments"])
occurrences_router = Router(tags=["payment-occurrences"])
summary_router = Router(tags=["summary"])

MAX_SUMMARY_DAYS = 366


# ── регулярные платежи ───────────────────────────────────


@recurring_router.get(
    "",
    response={200: PaginatedRecurringPaymentOut, 401: ErrorOut, 422: ErrorOut},
    summary="Список регулярных платежей",
)
def list_recurring_payments(
    request: AuthedRequest, filters: Query[RecurringPaymentFilter]
) -> dict[str, object]:
    today = local_today()
    services.sync_all_occurrences(today)
    queryset = services.payments_queryset(today)
    if not filters.include_inactive:
        queryset = queryset.filter(deleted_at__isnull=True)
    if filters.currency:
        queryset = queryset.filter(currency=filters.currency)
    if filters.search:
        queryset = queryset.filter(search_title__contains=filters.search.strip().casefold())
    return paginate(queryset, filters)


@recurring_router.post(
    "",
    auth=admin_auth,
    response={201: RecurringPaymentOut, 401: ErrorOut, 403: ErrorOut, 422: ErrorOut},
    summary="Создание регулярного платежа (админ)",
)
def create_recurring_payment(
    request: AuthedRequest, payload: RecurringPaymentIn
) -> tuple[int, RecurringPayment]:
    today = local_today()
    if payload.first_due_date < shift_months(today, -12, today.day):
        raise field_error("first_due_date", "Дата не может быть раньше чем 12 месяцев назад")

    payment = services.create_payment(
        user=request.auth,
        title=payload.title,
        amount=payload.amount,
        currency=payload.currency,
        first_due_date=payload.first_due_date,
        period=payload.period,
        comment=payload.comment,
        today=today,
    )
    # Срок ближе, чем за REMINDER_DAYS_BEFORE дней — напоминание уходит сразу.
    transaction.on_commit(lambda: send_due_reminders(today, recurring_payment_id=payment.id))
    return 201, services.payments_queryset(today).get(pk=payment.pk)


@recurring_router.delete(
    "/{payment_id}",
    auth=admin_auth,
    response={204: None, 401: ErrorOut, 403: ErrorOut, 404: ErrorOut, 409: ErrorOut},
    summary="Прекращение платежа и напоминаний с сохранением истории (админ)",
)
def delete_recurring_payment(request: AuthedRequest, payment_id: int) -> tuple[int, None]:
    payment = RecurringPayment.objects.filter(pk=payment_id).first()
    if payment is None:
        raise ApiError(404, ErrorCode.NOT_FOUND, "Платёж не найден")
    services.delete_payment(payment, request.auth, local_today())
    return 204, None


# ── периоды оплаты ───────────────────────────────────────


def _occurrences() -> QuerySet[PaymentOccurrence]:
    return PaymentOccurrence.objects.select_related("recurring_payment", "marked_by")


def _get_occurrence(occurrence_id: int) -> PaymentOccurrence:
    occurrence = _occurrences().filter(pk=occurrence_id).first()
    if occurrence is None:
        raise ApiError(404, ErrorCode.NOT_FOUND, "Период не найден")
    return occurrence


@occurrences_router.get(
    "",
    response={200: PaginatedPaymentOccurrenceOut, 401: ErrorOut, 422: ErrorOut},
    summary="Список периодов: оплаченные, неоплаченные, просроченные",
)
def list_occurrences(request: AuthedRequest, filters: Query[OccurrenceFilter]) -> dict[str, object]:
    today = local_today()
    services.sync_all_occurrences(today)
    queryset = _occurrences()
    if filters.recurring_payment_id is not None:
        queryset = queryset.filter(recurring_payment_id=filters.recurring_payment_id)
    if filters.currency:
        queryset = queryset.filter(currency=filters.currency)
    if filters.due_from:
        queryset = queryset.filter(due_date__gte=filters.due_from)
    if filters.due_to:
        queryset = queryset.filter(due_date__lte=filters.due_to)
    match filters.state:
        case "paid":
            queryset = queryset.filter(status=OccurrenceStatus.PAID)
        case "unpaid":
            queryset = queryset.filter(status=OccurrenceStatus.UNPAID)
        case "overdue":
            queryset = queryset.filter(status=OccurrenceStatus.UNPAID, due_date__lt=today)
        case "upcoming":
            queryset = queryset.filter(status=OccurrenceStatus.UNPAID, due_date__gte=today)
    queryset = queryset.order_by(filters.ordering, "id")
    return paginate(queryset, filters)


@occurrences_router.get(
    "/{occurrence_id}",
    response={200: PaymentOccurrenceOut, 401: ErrorOut, 404: ErrorOut},
    summary="Конкретный период",
)
def get_occurrence(request: AuthedRequest, occurrence_id: int) -> PaymentOccurrence:
    return _get_occurrence(occurrence_id)


@occurrences_router.patch(
    "/{occurrence_id}",
    response={
        200: PaymentOccurrenceOut,
        401: ErrorOut,
        404: ErrorOut,
        409: ErrorOut,
        422: ErrorOut,
    },
    summary="Отметить или отменить оплату, исправить фактическую дату",
)
def patch_occurrence(
    request: AuthedRequest, occurrence_id: int, payload: PaymentOccurrencePatchIn
) -> PaymentOccurrence:
    today = local_today()
    status, paid_at = payload.status, payload.paid_at
    if status is None and paid_at is None:
        raise field_error("status", "Укажите статус или дату оплаты")
    if status == OccurrenceStatus.UNPAID and paid_at is not None:
        raise field_error("paid_at", "При отмене оплаты дата не указывается")
    if paid_at is not None and paid_at > today:
        raise field_error("paid_at", "Дата оплаты не может быть в будущем")

    occurrence = _get_occurrence(occurrence_id)
    user = request.auth
    with transaction.atomic():
        match status:
            case OccurrenceStatus.PAID:
                services.mark_paid(occurrence, paid_at or today, user)
            case OccurrenceStatus.UNPAID:
                services.mark_unpaid(occurrence, user)
            case None if paid_at is not None:
                services.correct_paid_at(occurrence, paid_at, user)
    return occurrence


# ── итоги по валютам ─────────────────────────────────────


@summary_router.get(
    "/summary",
    response={200: SummaryOut, 401: ErrorOut, 422: ErrorOut},
    summary="Итоговые суммы по валютам за период",
)
def payments_summary(request: AuthedRequest, query: Query[SummaryQuery]) -> services.Summary:
    today = local_today()
    month_start = today.replace(day=1)
    date_from = query.date_from or month_start
    date_to = query.date_to or shift_months(month_start, 1, 1) - timedelta(days=1)
    if date_from > date_to:
        message = "Дата начала позже даты окончания"
        raise field_error("date_to", message, detail=message)
    if (date_to - date_from).days + 1 > MAX_SUMMARY_DAYS:
        message = f"Диапазон не должен превышать {MAX_SUMMARY_DAYS} дней"
        raise field_error("date_to", message, detail=message)

    services.sync_all_occurrences(today)
    return services.summarize(date_from, date_to, today)
