import logging

from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.models import update_last_login
from django.db import IntegrityError
from django.http import HttpRequest, HttpResponse
from ninja import Query, Router
from ninja_jwt.exceptions import TokenError
from ninja_jwt.settings import api_settings as jwt_settings
from ninja_jwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from ninja_jwt.tokens import RefreshToken

from apps.core.auth import admin_auth
from apps.core.errors import ApiError, ErrorCode, ErrorOut
from apps.core.schemas import PageQuery, paginate

from .models import User, UserRole
from .schemas import (
    AccessOut,
    LoginIn,
    MeOut,
    PaginatedUserOut,
    UserCreateIn,
    UserOut,
    UserPatchIn,
)
from .types import AuthedRequest

auth_router = Router(tags=["auth"])

audit = logging.getLogger("audit")

_TOKEN_INVALID_DETAIL = "Токен недействителен или просрочен"


def _require_xhr(request: HttpRequest) -> None:
    # Защита refresh-cookie от CSRF: кросс-сайтовая форма не может выставить этот заголовок,
    # а fetch с ним с чужого origin упрётся в CORS preflight.
    if request.headers.get("X-Requested-With") != "XMLHttpRequest":
        raise ApiError(403, ErrorCode.CSRF_FAILED, "Запрос отклонён")


def _set_refresh_cookie(response: HttpResponse, refresh: RefreshToken) -> None:
    response.set_cookie(
        settings.JWT_REFRESH_COOKIE_NAME,
        str(refresh),
        max_age=int(jwt_settings.REFRESH_TOKEN_LIFETIME.total_seconds()),
        path=settings.JWT_REFRESH_COOKIE_PATH,
        secure=settings.JWT_REFRESH_COOKIE_SECURE,
        httponly=True,
        samesite="Strict",
    )


def _delete_refresh_cookie(response: HttpResponse) -> None:
    response.delete_cookie(
        settings.JWT_REFRESH_COOKIE_NAME,
        path=settings.JWT_REFRESH_COOKIE_PATH,
        samesite="Strict",
    )


def _issue_tokens(response: HttpResponse, user: User) -> AccessOut:
    # В ninja_jwt for_user аннотирован как `cls: T -> T`, mypy принимает это за метод экземпляра.
    refresh: RefreshToken = RefreshToken.for_user(user)  # type: ignore[misc, assignment]
    _set_refresh_cookie(response, refresh)
    return AccessOut(access=str(refresh.access_token))


def _cookie_refresh_token(request: HttpRequest) -> RefreshToken | None:
    """Валидный (подпись, срок, не в blacklist) refresh из cookie или None."""
    raw = request.COOKIES.get(settings.JWT_REFRESH_COOKIE_NAME)
    if not raw:
        return None
    try:
        return RefreshToken(raw)
    except TokenError:
        return None


@auth_router.post(
    "/login",
    auth=None,
    response={200: AccessOut, 401: ErrorOut, 422: ErrorOut},
    summary="Вход по логину и паролю",
)
def login(request: HttpRequest, response: HttpResponse, payload: LoginIn) -> AccessOut:
    user = authenticate(request, username=payload.username, password=payload.password)
    if not isinstance(user, User):
        audit.warning("login failed username=%r", payload.username)
        raise ApiError(401, ErrorCode.INVALID_CREDENTIALS, "Неверный логин или пароль")
    update_last_login(User, user)
    audit.info("login ok username=%s", user.username)
    return _issue_tokens(response, user)


@auth_router.post(
    "/refresh",
    auth=None,
    response={200: AccessOut, 401: ErrorOut, 403: ErrorOut},
    summary="Новый access-токен по refresh-cookie",
)
def refresh(request: HttpRequest, response: HttpResponse) -> tuple[int, AccessOut | ErrorOut]:
    _require_xhr(request)

    # Ошибки возвращаем, а не бросаем: так ninja сохранит удаление cookie в ответе.
    def reject(detail: str) -> tuple[int, ErrorOut]:
        _delete_refresh_cookie(response)
        return 401, ErrorOut(code=ErrorCode.TOKEN_INVALID, detail=detail)

    token = _cookie_refresh_token(request)
    if token is None:
        return reject(_TOKEN_INVALID_DETAIL)

    user = User.objects.filter(
        **{jwt_settings.USER_ID_FIELD: token[jwt_settings.USER_ID_CLAIM]}, is_active=True
    ).first()
    if user is None:
        return reject("Пользователь не найден")

    # Ротация. BlacklistedToken.token уникален, поэтому из двух параллельных refresh
    # с одним токеном created=True получит только один — второй получит 401.
    # blacklist() возвращает результат get_or_create, хотя аннотирован как BlacklistedToken.
    blacklisted: tuple[BlacklistedToken, bool] = token.blacklist()  # type: ignore[assignment]
    if not blacklisted[1]:
        return reject(_TOKEN_INVALID_DETAIL)

    return 200, _issue_tokens(response, user)


@auth_router.get("/me", response={200: MeOut, 401: ErrorOut}, summary="Текущий пользователь")
def me(request: AuthedRequest) -> User:
    return request.auth


@auth_router.post(
    "/logout",
    auth=None,
    response={204: None, 403: ErrorOut},
    summary="Выход: отзыв refresh-токена и удаление cookie",
)
def logout(request: HttpRequest, response: HttpResponse) -> tuple[int, None]:
    # Без auth: выйти можно и с истёкшим access. Идемпотентно — всегда 204.
    _require_xhr(request)
    token = _cookie_refresh_token(request)
    if token is not None:
        token.blacklist()
    _delete_refresh_cookie(response)
    return 204, None


# ── управление пользователями (только админ) ─────────────

users_router = Router(tags=["users"], auth=admin_auth)

_USERNAME_TAKEN = "Логин уже занят"


def _get_user(user_id: int) -> User:
    user = User.objects.filter(pk=user_id).first()
    if user is None:
        raise ApiError(404, ErrorCode.NOT_FOUND, "Пользователь не найден")
    return user


def _ensure_mutable(user: User, verb: str) -> None:
    # Учётные записи администраторов через панель и API не управляются.
    if user.is_env_admin or user.is_admin:
        raise ApiError(403, ErrorCode.ENV_ADMIN_IMMUTABLE, f"Администратора из .env нельзя {verb}")


def _ensure_username_free(username: str, exclude_id: int | None = None) -> None:
    taken = User.objects.filter(username=username)
    if exclude_id is not None:
        taken = taken.exclude(pk=exclude_id)
    if taken.exists():
        raise ApiError(
            409, ErrorCode.USERNAME_TAKEN, _USERNAME_TAKEN, {"username": [_USERNAME_TAKEN]}
        )


def _revoke_refresh_tokens(user: User) -> None:
    for token in OutstandingToken.objects.filter(user=user):
        BlacklistedToken.objects.get_or_create(token=token)


@users_router.get(
    "",
    response={200: PaginatedUserOut, 401: ErrorOut, 403: ErrorOut, 422: ErrorOut},
    summary="Список пользователей (админ)",
)
def list_users(request: AuthedRequest, query: Query[PageQuery]) -> dict[str, object]:
    return paginate(User.objects.order_by("id"), query)


@users_router.post(
    "",
    response={201: UserOut, 401: ErrorOut, 403: ErrorOut, 409: ErrorOut, 422: ErrorOut},
    summary="Создание обычного пользователя (админ)",
)
def create_user(request: AuthedRequest, payload: UserCreateIn) -> tuple[int, User]:
    _ensure_username_free(payload.username)
    try:
        user = User.objects.create_user(
            username=payload.username,
            password=payload.password,
            email=payload.email,
            first_name=payload.first_name,
            last_name=payload.last_name,
            role=UserRole.USER,
        )
    except IntegrityError:
        _ensure_username_free(payload.username)
        raise
    audit.info("user created id=%s username=%s by=%s", user.id, user.username, request.auth)
    return 201, user


@users_router.patch(
    "/{user_id}",
    response={
        200: UserOut,
        401: ErrorOut,
        403: ErrorOut,
        404: ErrorOut,
        409: ErrorOut,
        422: ErrorOut,
    },
    summary="Изменение пользователя (админ)",
)
def patch_user(request: AuthedRequest, user_id: int, payload: UserPatchIn) -> User:
    user = _get_user(user_id)
    _ensure_mutable(user, "изменить")

    changes = payload.model_dump(exclude_unset=True, exclude_none=True)
    password = changes.pop("password", None)
    if "username" in changes:
        _ensure_username_free(changes["username"], exclude_id=user.pk)
    for name, value in changes.items():
        setattr(user, name, value)
    if password is not None:
        user.set_password(password)
    user.save()
    if password is not None:
        _revoke_refresh_tokens(user)

    audit.info(
        "user updated id=%s fields=%s by=%s",
        user.id,
        sorted([*changes, *(["password"] if password else [])]),
        request.auth,
    )
    return user


@users_router.delete(
    "/{user_id}",
    response={204: None, 401: ErrorOut, 403: ErrorOut, 404: ErrorOut},
    summary="Удаление пользователя (админ)",
)
def delete_user(request: AuthedRequest, user_id: int) -> tuple[int, None]:
    user = _get_user(user_id)
    _ensure_mutable(user, "удалить")
    if user.pk == request.auth.pk:
        raise ApiError(403, ErrorCode.CANNOT_DELETE_SELF, "Нельзя удалить самого себя")
    username = user.username
    # Отметки об оплате остаются: marked_by станет NULL (on_delete=SET_NULL).
    user.delete()
    audit.info("user deleted id=%s username=%s by=%s", user_id, username, request.auth)
    return 204, None
