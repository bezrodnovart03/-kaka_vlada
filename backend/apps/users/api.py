from django.contrib.auth import authenticate
from django.contrib.auth.models import update_last_login
from django.http import HttpRequest
from ninja import Router
from ninja_jwt.authentication import JWTAuth
from ninja_jwt.exceptions import AuthenticationFailed, InvalidToken, TokenError
from ninja_jwt.tokens import RefreshToken

from .models import User
from .schemas import LoginIn, RefreshIn, TokenPairOut, UserOut
from .types import AuthedRequest

auth_router = Router(tags=["auth"])


def _token_pair(user: User) -> TokenPairOut:
    # В ninja_jwt for_user аннотирован как `cls: T -> T`, mypy принимает это за метод экземпляра.
    refresh: RefreshToken = RefreshToken.for_user(user)  # type: ignore[misc, assignment]
    return TokenPairOut(access=str(refresh.access_token), refresh=str(refresh))


def _validated_refresh(raw: str) -> RefreshToken:
    try:
        return RefreshToken(raw)
    except TokenError as e:
        raise InvalidToken(e.args[0]) from e


@auth_router.post("/login", response=TokenPairOut, summary="Вход по логину и паролю")
def login(request: HttpRequest, payload: LoginIn) -> TokenPairOut:
    user = authenticate(request, username=payload.username, password=payload.password)
    if not isinstance(user, User):
        raise AuthenticationFailed("Неверный логин или пароль")
    update_last_login(User, user)
    return _token_pair(user)


@auth_router.post("/refresh", response=TokenPairOut, summary="Обновление пары токенов")
def refresh(request: HttpRequest, payload: RefreshIn) -> TokenPairOut:
    token = _validated_refresh(payload.refresh)
    user = User.objects.filter(id=token["user_id"], is_active=True).first()
    if user is None:
        raise AuthenticationFailed("Пользователь не найден")
    # Ротация: старый refresh больше не принимается.
    token.blacklist()
    return _token_pair(user)


@auth_router.get("/me", response=UserOut, auth=JWTAuth(), summary="Текущий пользователь")
def me(request: AuthedRequest) -> User:
    return request.auth


@auth_router.post(
    "/logout", response={204: None}, auth=JWTAuth(), summary="Завершение текущей сессии"
)
def logout(request: AuthedRequest, payload: RefreshIn) -> tuple[int, None]:
    token = _validated_refresh(payload.refresh)
    if token["user_id"] != request.auth.id:
        raise InvalidToken("Токен принадлежит другому пользователю")
    token.blacklist()
    return 204, None
