from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _
from simple_history.models import HistoricalRecords


class UserRole(models.TextChoices):
    # Значения совпадают с `Role` в API-контракте — без маппинга.
    ADMIN = "admin", _("Администратор")
    USER = "user", _("Пользователь")


class User(AbstractUser):
    # Неявное поле Django; объявлено для анализаторов без плагина (Pyright/Pylance).
    id: int

    role = models.CharField(
        _("роль"),
        max_length=16,
        choices=UserRole.choices,
        default=UserRole.USER,
    )

    created_at = models.DateTimeField(_("создан"), auto_now_add=True)
    updated_at = models.DateTimeField(_("изменён"), auto_now=True)

    history = HistoricalRecords()

    class Meta:  # pyright: ignore[reportIncompatibleVariableOverride]
        ordering = ["id"]
        verbose_name = _("пользователь")
        verbose_name_plural = _("пользователи")

    def __str__(self) -> str:
        return self.username

    @property
    def is_admin(self) -> bool:
        return self.role == UserRole.ADMIN

    @property
    def is_env_admin(self) -> bool:
        """Администратор из .env: через API его нельзя изменить или удалить."""
        return self.username == settings.ADMIN_USERNAME
