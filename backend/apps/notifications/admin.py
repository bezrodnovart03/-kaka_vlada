from typing import Any

from django.contrib import admin
from django.http import HttpRequest
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin
from unfold.contrib.filters.admin import ChoicesDropdownFilter, RangeDateTimeFilter
from unfold.decorators import display

from .models import ReminderDelivery


@admin.register(ReminderDelivery)
class ReminderDeliveryAdmin(ModelAdmin):  # type: ignore[misc]  # unfold без типов
    """Журнал доставки напоминаний в email, webhook и другие каналы (только просмотр)."""

    list_display = ("display_payment", "display_due", "channel", "sent_at")
    list_filter = (("channel", ChoicesDropdownFilter), ("sent_at", RangeDateTimeFilter))
    list_filter_submit = True
    search_fields = ("occurrence__recurring_payment__title",)
    list_select_related = ("occurrence__recurring_payment",)
    date_hierarchy = "sent_at"

    @display(description=_("Платёж"), ordering="occurrence__recurring_payment__title")
    def display_payment(self, obj: ReminderDelivery) -> str:
        return obj.occurrence.recurring_payment.title

    @display(description=_("Срок"), ordering="occurrence__due_date")
    def display_due(self, obj: ReminderDelivery) -> str:
        return f"{obj.occurrence.due_date:%d.%m.%Y}"

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False
