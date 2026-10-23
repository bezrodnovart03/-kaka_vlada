from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.models import update_last_login
from django.http import HttpRequest, HttpResponse
from ninja import Router
from ninja_jwt.exceptions import TokenError
from ninja_jwt.settings import api_settings as jwt_settings
from ninja_jwt.token_blacklist.models import BlacklistedToken
from ninja_jwt.tokens import RefreshToken

from apps.core.errors import ApiError, ErrorCode, ErrorOut

from .models import User
from .schemas import AccessOut, LoginIn, MeOut
from .types import AuthedRequest

auth_router = Router(tags=["auth"])

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
        raise ApiError(401, ErrorCode.INVALID_CREDENTIALS, "Неверный логин или пароль")
    update_last_login(User, user)
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
