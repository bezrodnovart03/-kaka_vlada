from typing import Any

from django.contrib import admin
from django.http import HttpRequest
from simple_history.admin import SimpleHistoryAdmin

from .models import PaymentOccurrence, RecurringPayment


class OccurrenceInline(admin.TabularInline[PaymentOccurrence, RecurringPayment]):
    model = PaymentOccurrence
    extra = 0
    fields = (
        "due_date",
        "amount",
        "currency",
        "status",
        "paid_at",
        "marked_by",
        "reminder_sent_at",
    )
    readonly_fields = fields
    can_delete = False
    show_change_link = True


@admin.register(RecurringPayment)
class RecurringPaymentAdmin(SimpleHistoryAdmin):  # type: ignore[misc]  # simple_history без типов
    list_display = ("id", "title", "amount", "currency", "period", "first_due_date", "deleted_at")
    list_filter = ("currency", "period", ("deleted_at", admin.EmptyFieldListFilter))
    search_fields = ("title",)
    readonly_fields = ("anchor_day", "created_by", "created_at", "deleted_at")
    inlines = [OccurrenceInline]

    def save_model(
        self, request: HttpRequest, obj: RecurringPayment, form: Any, change: bool
    ) -> None:
        if not change:
            obj.created_by = request.user  # type: ignore[assignment]
        super().save_model(request, obj, form, change)


@admin.register(PaymentOccurrence)
class PaymentOccurrenceAdmin(SimpleHistoryAdmin):  # type: ignore[misc]
    list_display = (
        "id",
        "recurring_payment",
        "due_date",
        "amount",
        "currency",
        "status",
        "paid_at",
    )
    list_filter = ("status", "currency")
    search_fields = ("recurring_payment__title",)
    date_hierarchy = "due_date"
    readonly_fields = ("recurring_payment", "due_date", "amount", "currency", "created_at")
