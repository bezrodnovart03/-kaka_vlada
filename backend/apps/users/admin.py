from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _
from simple_history.admin import SimpleHistoryAdmin

from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin[User], SimpleHistoryAdmin):  # type: ignore[misc]  # simple_history без типов
    # BaseUserAdmin даёт логику пароля/add-формы, SimpleHistoryAdmin — вкладку истории.
    list_display = (
        "id",
        "username",
        "first_name",
        "last_name",
        "email",
        "role",
        "is_active",
        "created_at",
    )
    list_filter = ("role", "is_staff", "is_superuser", "is_active")
    search_fields = ("username", "first_name", "last_name", "email")
    ordering = ("id",)
    readonly_fields = ("last_login", "date_joined", "created_at", "updated_at")

    # Берём стандартные секции UserAdmin и дописываем свои поля.
    fieldsets = (
        *(BaseUserAdmin.fieldsets or ()),
        (_("Роль"), {"fields": ("role",)}),
        (_("Даты"), {"fields": ("created_at", "updated_at")}),
    )
    add_fieldsets = (
        *(BaseUserAdmin.add_fieldsets or ()),
        (_("Роль"), {"fields": ("role",)}),
    )
