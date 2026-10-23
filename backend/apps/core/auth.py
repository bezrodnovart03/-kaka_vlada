from typing import Any

from django.http import HttpRequest
from ninja_jwt.authentication import JWTAuth

from apps.core.errors import ApiError, ErrorCode


class UserJWTAuth(JWTAuth):
    """
    JWTAuth, который дополнительно кладёт пользователя в `request.user`:
    так django-simple-history записывает автора изменения в журнал.
    """

    def authenticate(self, request: HttpRequest, token: str) -> Any:
        user = super().authenticate(request, token)
        request.user = user
        return user


class AdminJWTAuth(UserJWTAuth):
    """
    Только администратор. Проверка идёт до разбора тела запроса, поэтому
    пользователь получает 403, а не 422 на кривые данные. Права проверяются
    на бэкенде — фронт только скрывает кнопки.
    """

    def authenticate(self, request: HttpRequest, token: str) -> Any:
        user = super().authenticate(request, token)
        if not getattr(user, "is_admin", False):
            raise ApiError(403, ErrorCode.FORBIDDEN, "Недостаточно прав")
        return user


admin_auth = AdminJWTAuth()
