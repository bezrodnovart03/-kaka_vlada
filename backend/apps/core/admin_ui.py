"""Колбэки для настроек Unfold (settings.UNFOLD): бейджи, окружение, права пунктов меню."""

from django.conf import settings
from django.http import HttpRequest

from apps.core.schemas import local_today


def environment_callback(request: HttpRequest) -> list[str]:
    # Метка в шапке, чтобы не перепутать локальную админку с боевой.
    if settings.DEBUG:
        return ["Разработка", "warning"]
    return ["Продакшен", "danger"]


def overdue_badge(request: HttpRequest) -> str:
    """Число просроченных периодов у активных платежей — бейдж в меню."""
    from apps.payments.dashboard import overdue_occurrences

    count = overdue_occurrences(local_today()).count()
    return str(count) if count else ""


def superuser_only(request: HttpRequest) -> bool:
    return bool(request.user.is_superuser)
