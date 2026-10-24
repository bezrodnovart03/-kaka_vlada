from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group
from django.utils.translation import gettext_lazy as _
from ninja_jwt.token_blacklist.admin import BlacklistedTokenAdmin as BaseBlacklistedTokenAdmin
from ninja_jwt.token_blacklist.admin import OutstandingTokenAdmin as BaseOutstandingTokenAdmin
from ninja_jwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from simple_history.admin import SimpleHistoryAdmin
from unfold.admin import ModelAdmin
from unfold.contrib.filters.admin import ChoicesDropdownFilter
from unfold.decorators import display
from unfold.forms import AdminPasswordChangeForm, UserChangeForm, UserCreationForm

from .models import User, UserRole

# Стандартные регистрации Django и ninja_jwt заменяем на версии с оформлением Unfold.
# https://unfoldadmin.com/docs/installation/auth/
admin.site.unregister(Group)
admin.site.unregister(OutstandingToken)
admin.site.unregister(BlacklistedToken)


@admin.register(User)
class UserAdmin(SimpleHistoryAdmin, BaseUserAdmin[User], ModelAdmin):  # type: ignore[misc]
    # SimpleHistoryAdmin — вкладка истории, BaseUserAdmin — логика пароля и add-формы,
    # ModelAdmin Unfold — оформление. Порядок — по докам Unfold для simple_history.
    form = UserChangeForm
    add_form = UserCreationForm
    change_password_form = AdminPasswordChangeForm

    list_display = (
        "display_user",
        "email",
        "display_role",
        "is_active",
        "last_login",
        "created_at",
    )
    list_filter = (
        ("role", ChoicesDropdownFilter),
        "is_active",
        "is_staff",
        "is_superuser",
    )
    list_filter_submit = True
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

    @display(description=_("Пользователь"), header=True, ordering="username")
    def display_user(self, obj: User) -> list[str]:
        full_name = obj.get_full_name()
        initials = "".join(part[0] for part in full_name.split()[:2]) or obj.username[:2]
        return [obj.username, full_name or "—", initials.upper()]

    @display(
        description=_("Роль"),
        ordering="role",
        label={UserRole.ADMIN: "danger", UserRole.USER: "info"},
    )
    def display_role(self, obj: User) -> tuple[str, str]:
        label = "Администратор (.env)" if obj.is_env_admin else obj.get_role_display()
        return obj.role, label


@admin.register(Group)
class GroupAdmin(BaseGroupAdmin, ModelAdmin):  # type: ignore[misc]
    pass


@admin.register(OutstandingToken)
class OutstandingTokenAdmin(BaseOutstandingTokenAdmin, ModelAdmin):  # type: ignore[misc]
    pass


@admin.register(BlacklistedToken)
class BlacklistedTokenAdmin(BaseBlacklistedTokenAdmin, ModelAdmin):  # type: ignore[misc]
    pass
