from datetime import date, timedelta
from typing import Any

from django.db import transaction
from django.db.models import Count, QuerySet
from django.http import FileResponse, HttpResponse
from ninja import File, Query, Router, UploadedFile

from apps.core.auth import admin_auth
from apps.core.errors import ApiError, ErrorCode, ErrorOut, field_error
from apps.core.schemas import local_today, paginate
from apps.notifications.services import send_due_reminders_in_background
from apps.users.types import AuthedRequest

from . import attachments, ics, services
from .models import (
    AttachmentKind,
    OccurrenceStatus,
    PaymentAttachment,
    PaymentOccurrence,
    RecurringPayment,
)
from .schedule import shift_months
from .schemas import (
    AttachmentLinkIn,
    AttachmentOut,
    CalendarQuery,
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
# Сроки дальше этого горизонта — почти наверняка опечатка в годе (9999-12-31 принимался).
MAX_FIRST_DUE_YEARS = 10


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
    description=(
        "first_due_date — не раньше чем 12 месяцев назад и не позже чем через "
        f"{MAX_FIRST_DUE_YEARS} лет от сегодня, иначе 422."
    ),
)
def create_recurring_payment(
    request: AuthedRequest, payload: RecurringPaymentIn
) -> tuple[int, RecurringPayment]:
    today = local_today()
    if payload.first_due_date < shift_months(today, -12, today.day):
        raise field_error("first_due_date", "Дата не может быть раньше чем 12 месяцев назад")
    if payload.first_due_date > shift_months(today, 12 * MAX_FIRST_DUE_YEARS, today.day):
        raise field_error(
            "first_due_date", f"Дата не может быть позже чем через {MAX_FIRST_DUE_YEARS} лет"
        )

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
    transaction.on_commit(
        lambda: send_due_reminders_in_background(today, recurring_payment_id=payment.id)
    )
    return 201, services.payments_queryset(today).get(pk=payment.pk)


@recurring_router.delete(
    "/{payment_id}",
    auth=admin_auth,
    response={204: None, 401: ErrorOut, 403: ErrorOut, 404: ErrorOut, 409: ErrorOut, 422: ErrorOut},
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
    return (
        PaymentOccurrence.objects.select_related("recurring_payment", "marked_by")
        .prefetch_related("reminder_deliveries")
        .annotate(attachments_total=Count("attachments"))
    )


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
    queryset = _filter_state(queryset, filters.state, today).order_by(filters.ordering, "id")
    return paginate(queryset, filters)


def _filter_state(
    queryset: QuerySet[PaymentOccurrence], state: str | None, today: date
) -> QuerySet[PaymentOccurrence]:
    match state:
        case "paid":
            return queryset.filter(status=OccurrenceStatus.PAID)
        case "unpaid":
            return queryset.filter(status=OccurrenceStatus.UNPAID)
        case "overdue":
            return queryset.filter(status=OccurrenceStatus.UNPAID, due_date__lt=today)
        case "upcoming":
            return queryset.filter(status=OccurrenceStatus.UNPAID, due_date__gte=today)
    return queryset


def _binary_response(media_types: list[str], description: str) -> dict[str, Any]:
    """openapi_extra для эндпоинтов, которые отдают файл, а не JSON."""
    binary = {"schema": {"type": "string", "format": "binary"}}
    return {
        "responses": {
            200: {"description": description, "content": dict.fromkeys(media_types, binary)}
        }
    }


MAX_CALENDAR_DAYS = 3 * 366


@occurrences_router.get(
    "/calendar.ics",
    response={401: ErrorOut, 422: ErrorOut},
    summary="Экспорт периодов в календарь (iCalendar .ics)",
    description=(
        "События на весь день срока с оповещением за REMINDER_DAYS_BEFORE дней. Кроме созданных "
        "периодов — будущие сроки активных платежей по расписанию. По умолчанию — от 3 месяцев "
        f"назад до 12 месяцев вперёд; диапазон длиннее {MAX_CALENDAR_DAYS} дней — 422."
    ),
    openapi_extra=_binary_response(["text/calendar"], "Файл .ics"),
)
def export_calendar(request: AuthedRequest, query: Query[CalendarQuery]) -> HttpResponse:
    today = local_today()
    due_from = query.due_from or shift_months(today, -3, today.day)
    due_to = query.due_to or shift_months(today, 12, today.day)
    if due_from > due_to:
        raise field_error("due_to", "Дата начала позже даты окончания")
    if (due_to - due_from).days + 1 > MAX_CALENDAR_DAYS:
        raise field_error("due_to", f"Диапазон не должен превышать {MAX_CALENDAR_DAYS} дней")

    services.sync_all_occurrences(today)
    occurrences = PaymentOccurrence.objects.select_related("recurring_payment").filter(
        due_date__gte=due_from, due_date__lte=due_to
    )
    payments = RecurringPayment.objects.filter(deleted_at__isnull=True)
    if query.currency:
        occurrences = occurrences.filter(currency=query.currency)
        payments = payments.filter(currency=query.currency)
    occurrences = _filter_state(occurrences, query.state, today).order_by("due_date", "id")
    events = [ics.occurrence_event(occurrence) for occurrence in occurrences]

    # Плановые сроки — только неоплаченные будущие: они подходят под фильтры без статуса,
    # «неоплаченные» и «предстоящие».
    if query.state in (None, "unpaid", "upcoming"):
        for payment in payments:
            last = (
                payment.occurrences.order_by("-due_date").values_list("due_date", flat=True).first()
            )
            for due_date in payment.schedule():
                if due_date > due_to:
                    break
                if due_date < max(due_from, today) or (last is not None and due_date <= last):
                    continue
                events.append(ics.planned_event(payment, due_date))

    response = HttpResponse(ics.build_calendar(events), content_type="text/calendar; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="invoice-keeper.ics"'
    return response


@occurrences_router.get(
    "/{occurrence_id}",
    response={200: PaymentOccurrenceOut, 401: ErrorOut, 404: ErrorOut, 422: ErrorOut},
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
    description=(
        "Тело — один из трёх вариантов (oneOf). paid_at не может быть в будущем (422); "
        "исправление даты у неоплаченного периода — 409 occurrence_not_paid."
    ),
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


# ── чеки и ссылки ────────────────────────────────────────


def _get_attachment(occurrence_id: int, attachment_id: int) -> PaymentAttachment:
    # Период сверяется в Python: у поиска по pk Django отсекает числа вне диапазона БД,
    # а фильтр по occurrence_id с id > int64 падал в SQLite с OverflowError (500).
    attachment = (
        PaymentAttachment.objects.select_related("uploaded_by").filter(pk=attachment_id).first()
    )
    if attachment is None or attachment.occurrence_id != occurrence_id:
        raise ApiError(404, ErrorCode.NOT_FOUND, "Вложение не найдено")
    return attachment


@occurrences_router.get(
    "/{occurrence_id}/attachments",
    response={200: list[AttachmentOut], 401: ErrorOut, 404: ErrorOut, 422: ErrorOut},
    summary="Чеки и ссылки периода",
)
def list_attachments(request: AuthedRequest, occurrence_id: int) -> QuerySet[PaymentAttachment]:
    occurrence = _get_occurrence(occurrence_id)
    return occurrence.attachments.select_related("uploaded_by")


@occurrences_router.post(
    "/{occurrence_id}/attachments/file",
    response={201: AttachmentOut, 401: ErrorOut, 404: ErrorOut, 409: ErrorOut, 422: ErrorOut},
    summary="Прикрепить чек (файл)",
    description=(
        "multipart/form-data, поле `file`. Форматы: PDF, PNG, JPEG, WebP, HEIC — тип "
        "определяется по содержимому файла. Размер — до ATTACHMENT_MAX_MB (по умолчанию 10 МБ). "
        f"Не больше {attachments.MAX_ATTACHMENTS} вложений на период (409)."
    ),
)
def upload_attachment(
    request: AuthedRequest, occurrence_id: int, file: File[UploadedFile]
) -> tuple[int, PaymentAttachment]:
    occurrence = _get_occurrence(occurrence_id)
    return 201, attachments.add_file(occurrence, file, request.auth)


@occurrences_router.post(
    "/{occurrence_id}/attachments/link",
    response={201: AttachmentOut, 401: ErrorOut, 404: ErrorOut, 409: ErrorOut, 422: ErrorOut},
    summary="Прикрепить ссылку (на чек, платёжку, счёт)",
    description=(
        "Только http:// и https:// (иначе 422). "
        f"Не больше {attachments.MAX_ATTACHMENTS} вложений на период (409)."
    ),
)
def add_link_attachment(
    request: AuthedRequest, occurrence_id: int, payload: AttachmentLinkIn
) -> tuple[int, PaymentAttachment]:
    occurrence = _get_occurrence(occurrence_id)
    return 201, attachments.add_link(occurrence, payload.url, payload.name, request.auth)


@occurrences_router.get(
    "/{occurrence_id}/attachments/{attachment_id}/download",
    response={401: ErrorOut, 404: ErrorOut, 409: ErrorOut, 422: ErrorOut},
    summary="Скачать прикреплённый файл",
    description="У вложения-ссылки файла нет — 409.",
    openapi_extra=_binary_response(
        [*attachments.ALLOWED_TYPES, "application/octet-stream"], "Файл чека"
    ),
)
def download_attachment(
    request: AuthedRequest, occurrence_id: int, attachment_id: int
) -> FileResponse:
    attachment = _get_attachment(occurrence_id, attachment_id)
    if attachment.kind != AttachmentKind.FILE:
        raise ApiError(409, ErrorCode.CONFLICT, "Это ссылка, а не файл")
    try:
        handle = attachment.file.open("rb")
    except FileNotFoundError:
        raise ApiError(404, ErrorCode.NOT_FOUND, "Файл не найден в хранилище") from None
    return FileResponse(
        handle,
        as_attachment=True,
        filename=attachment.name,
        content_type=attachment.content_type or "application/octet-stream",
    )


@occurrences_router.delete(
    "/{occurrence_id}/attachments/{attachment_id}",
    response={204: None, 401: ErrorOut, 403: ErrorOut, 404: ErrorOut, 422: ErrorOut},
    summary="Удалить чек или ссылку (автор или админ)",
)
def delete_attachment(
    request: AuthedRequest, occurrence_id: int, attachment_id: int
) -> tuple[int, None]:
    attachments.delete(_get_attachment(occurrence_id, attachment_id), request.auth)
    return 204, None


# ── итоги по валютам ─────────────────────────────────────


@summary_router.get(
    "/summary",
    response={200: SummaryOut, 401: ErrorOut, 422: ErrorOut},
    summary="Итоговые суммы по валютам за период",
    description=(
        "По умолчанию — текущий месяц. date_from позже date_to или диапазон длиннее "
        f"{MAX_SUMMARY_DAYS} дней — 422."
    ),
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
