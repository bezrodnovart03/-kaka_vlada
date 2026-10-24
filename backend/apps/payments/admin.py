from decimal import Decimal
from typing import Any

from django.contrib import admin
from django.http import HttpRequest
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from simple_history.admin import SimpleHistoryAdmin
from unfold.admin import ModelAdmin, TabularInline
from unfold.contrib.filters.admin import ChoicesDropdownFilter, RangeDateFilter
from unfold.decorators import display

from apps.core.schemas import local_today

from . import services
from .models import PaymentOccurrence, RecurringPayment

CURRENCY_SIGNS = {"RUB": "₽", "USD": "$", "EUR": "€"}


def money(amount: Decimal, currency: str) -> str:
    whole, _sep, cents = f"{amount:,.2f}".partition(".")
    # Неразрывные пробелы: сумма в таблице не переносится на несколько строк.
    nbsp = "\u00a0"
    return f"{whole.replace(',', nbsp)},{cents}{nbsp}{CURRENCY_SIGNS.get(currency, currency)}"


def _occurrence_state(occurrence: PaymentOccurrence) -> tuple[str, str]:
    """(ключ цвета, текст) для метки статуса периода."""
    if occurrence.is_paid:
        if occurrence.overdue_days:
            return "late", f"Оплачено с опозданием ({occurrence.overdue_days} дн.)"
        return "paid", "Оплачено"
    if occurrence.due_date < local_today():
        return "overdue", f"Просрочено {occurrence.overdue_days} дн."
    return "upcoming", "Ожидает оплаты"


OCCURRENCE_STATE_COLORS = {
    "paid": "success",
    "late": "warning",
    "overdue": "danger",
    "upcoming": "info",
}


class OccurrenceInline(TabularInline):  # type: ignore[misc]  # unfold без типов
    model = PaymentOccurrence
    extra = 0
    fields = (
        "due_date",
        "display_amount",
        "display_state",
        "paid_at",
        "marked_by",
        "reminder_sent_at",
    )
    readonly_fields = fields
    can_delete = False
    show_change_link = True
    ordering = ("-due_date",)

    @display(description=_("Сумма"))
    def display_amount(self, obj: PaymentOccurrence) -> str:
        return money(obj.amount, obj.currency)

    # В readonly-полях инлайна Unfold не рисует цветные метки (label=) — только текст.
    @display(description=_("Статус"))
    def display_state(self, obj: PaymentOccurrence) -> str:
        return _occurrence_state(obj)[1]

    def has_add_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False


@admin.register(RecurringPayment)
class RecurringPaymentAdmin(SimpleHistoryAdmin, ModelAdmin):  # type: ignore[misc]
    list_display = (
        "display_title",
        "display_amount",
        "period",
        "first_due_date",
        "display_active",
        "created_by",
    )
    list_filter = (
        ("currency", ChoicesDropdownFilter),
        ("period", ChoicesDropdownFilter),
        ("deleted_at", admin.EmptyFieldListFilter),
        ("first_due_date", RangeDateFilter),
    )
    list_filter_submit = True
    search_fields = ("title",)
    list_select_related = ("created_by",)
    readonly_fields = ("anchor_day", "created_by", "created_at", "deleted_at")
    fieldsets = (
        (None, {"fields": ("title", ("amount", "currency"), "comment")}),
        (_("Расписание"), {"fields": (("first_due_date", "period"), "anchor_day")}),
        (_("Служебное"), {"fields": ("created_by", "created_at", "deleted_at")}),
    )
    inlines = [OccurrenceInline]

    @display(description=_("Платёж"), header=True, ordering="title")
    def display_title(self, obj: RecurringPayment) -> list[str]:
        return [obj.title, obj.comment or ""]

    @display(description=_("Сумма"), ordering="amount")
    def display_amount(self, obj: RecurringPayment) -> str:
        return money(obj.amount, obj.currency)

    @display(
        description=_("Состояние"),
        ordering="deleted_at",
        label={"active": "success", "deleted": "danger"},
    )
    def display_active(self, obj: RecurringPayment) -> tuple[str, str]:
        return ("active", "Активен") if obj.is_active else ("deleted", "Удалён")

    def save_model(
        self, request: HttpRequest, obj: RecurringPayment, form: Any, change: bool
    ) -> None:
        if not change:
            obj.created_by = request.user  # type: ignore[assignment]
        super().save_model(request, obj, form, change)
        if not change:
            # Как при создании через API: сразу заводим периоды по расписанию.
            services.sync_occurrences(obj, local_today())

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        # Жёсткое удаление стёрло бы историю периодов; удалять — через API (мягко).
        return False


@admin.register(PaymentOccurrence)
class PaymentOccurrenceAdmin(SimpleHistoryAdmin, ModelAdmin):  # type: ignore[misc]
    list_display = (
        "display_payment",
        "due_date",
        "display_amount",
        "display_state",
        "paid_at",
        "marked_by",
        "reminder_sent_at",
    )
    list_filter = (
        ("status", ChoicesDropdownFilter),
        ("currency", ChoicesDropdownFilter),
        ("due_date", RangeDateFilter),
    )
    list_filter_submit = True
    search_fields = ("recurring_payment__title",)
    list_select_related = ("recurring_payment", "marked_by")
    date_hierarchy = "due_date"
    readonly_fields = (
        "recurring_payment",
        "due_date",
        "amount",
        "currency",
        "marked_by",
        "marked_at",
        "reminder_sent_at",
        "created_at",
    )
    fieldsets = (
        (None, {"fields": ("recurring_payment", "due_date", ("amount", "currency"))}),
        (_("Оплата"), {"fields": ("status", "paid_at", "marked_by", "marked_at")}),
        (_("Служебное"), {"fields": ("reminder_sent_at", "created_at")}),
    )

    @display(description=_("Платёж"), header=True, ordering="recurring_payment__title")
    def display_payment(self, obj: PaymentOccurrence) -> list[str]:
        payment = obj.recurring_payment
        return [payment.title, "" if payment.is_active else "платёж удалён"]

    @display(description=_("Сумма"), ordering="amount")
    def display_amount(self, obj: PaymentOccurrence) -> str:
        return money(obj.amount, obj.currency)

    @display(description=_("Статус"), ordering="status", label=OCCURRENCE_STATE_COLORS)
    def display_state(self, obj: PaymentOccurrence) -> tuple[str, str]:
        return _occurrence_state(obj)

    def save_model(
        self, request: HttpRequest, obj: PaymentOccurrence, form: Any, change: bool
    ) -> None:
        # Отметка из админки — тоже «кто и когда отметил», как через API.
        if change and {"status", "paid_at"} & set(form.changed_data):
            obj.marked_by = request.user  # type: ignore[assignment]
            obj.marked_at = timezone.now()
        super().save_model(request, obj, form, change)

    # Периоды создаёт только расписание (services.sync_occurrences): срок, сумма и валюта
    # берутся из платежа и через админку не задаются — форма добавления сохраняла бы NULL.
    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False
