from typing import Any

from django.apps import AppConfig

from config.env import settings


def sync_env_admin(sender: AppConfig, **kwargs: Any) -> None:
    """
    Создаёт или обновляет администратора из .env после migrate.
    Через панель и API эту учётную запись изменить нельзя — источник правды .env.
    """
    from .models import User, UserRole

    admin, _ = User.objects.get_or_create(username=settings.admin.username)
    admin.email = settings.admin.email
    admin.role = UserRole.ADMIN
    admin.is_staff = True
    admin.is_superuser = True
    admin.is_active = True
    admin.set_password(settings.admin.password)
    admin.save()
