from django.http import HttpRequest

from .models import User


class AuthedRequest(HttpRequest):
    """Запрос после JWTAuth: ninja кладёт пользователя в request.auth."""

    auth: User
