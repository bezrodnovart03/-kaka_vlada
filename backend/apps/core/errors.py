"""
Единый формат ошибок API (`ErrorOut`, см. docs/API.md §2).

Все 4xx — включая 422 от ninja и 401 от JWTAuth — приводятся к виду
`{"code": ..., "detail": ..., "fields": ...}`.
"""

from enum import StrEnum
from typing import Any

from django.http import Http404, HttpRequest, HttpResponse
from django.http.multipartparser import MultiPartParserError
from ninja import NinjaAPI, Schema
from ninja.errors import AuthenticationError, AuthorizationError, HttpError, ValidationError
from ninja_extra.exceptions import APIException


class ErrorCode(StrEnum):
    UNAUTHORIZED = "unauthorized"
    INVALID_CREDENTIALS = "invalid_credentials"
    TOKEN_INVALID = "token_invalid"
    FORBIDDEN = "forbidden"
    CSRF_FAILED = "csrf_failed"
    ENV_ADMIN_IMMUTABLE = "env_admin_immutable"
    CANNOT_DELETE_SELF = "cannot_delete_self"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    USERNAME_TAKEN = "username_taken"
    ALREADY_DELETED = "already_deleted"
    OCCURRENCE_NOT_PAID = "occurrence_not_paid"
    VALIDATION_ERROR = "validation_error"


class ErrorOut(Schema):
    code: ErrorCode
    detail: str
    fields: dict[str, list[str]] | None = None


class ApiError(Exception):
    """Бизнес-ошибка, которую обработчик превращает в `ErrorOut`."""

    def __init__(
        self,
        status: int,
        code: ErrorCode,
        detail: str,
        fields: dict[str, list[str]] | None = None,
    ) -> None:
        super().__init__(detail)
        self.status = status
        self.code = code
        self.detail = detail
        self.fields = fields

    def to_schema(self) -> ErrorOut:
        return ErrorOut(code=self.code, detail=self.detail, fields=self.fields)


def field_error(field: str, message: str, detail: str | None = None) -> ApiError:
    """422 с ошибкой одного поля — для проверок, которым нужна «сегодняшняя» дата или БД."""
    return ApiError(
        422, ErrorCode.VALIDATION_ERROR, detail or _VALIDATION_DETAIL, {field: [message]}
    )


# Код по умолчанию для ошибок, у которых его нет (HttpError, APIException).
_CODE_BY_STATUS = {
    401: ErrorCode.UNAUTHORIZED,
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    409: ErrorCode.CONFLICT,
}

_UNAUTHORIZED_DETAIL = "Требуется вход"
_FORBIDDEN_DETAIL = "Недостаточно прав"
_VALIDATION_DETAIL = "Проверьте поля формы"


def _field_key(loc: tuple[Any, ...]) -> str:
    # loc от ninja: ("body", "<имя параметра>", "field", ...) или ("query", "field", ...).
    parts = loc[2:] if loc and loc[0] == "body" else loc[1:]
    return ".".join(str(p) for p in parts) or str(loc[0] if loc else "body")


def _field_message(error: dict[str, Any]) -> str:
    ctx = error.get("ctx") or {}
    match error.get("type"):
        case "missing":
            return "Обязательное поле"
        case "string_too_short" if ctx.get("min_length") == 1:
            return "Обязательное поле"
        case "string_too_short":
            return f"Минимум {ctx.get('min_length')} символов"
        case "string_too_long":
            return f"Максимум {ctx.get('max_length')} символов"
        case "string_pattern_mismatch":
            return "Недопустимые символы"
        case "value_error" if ctx.get("error"):
            # ValueError из валидаторов схем: текст уже на русском, без префикса pydantic.
            return str(ctx["error"])
        case "decimal_parsing" | "decimal_type":
            return "Введите число"
        case "decimal_max_places":
            return f"Не более {ctx.get('decimal_places')} знаков после точки"
        case "decimal_max_digits" | "decimal_whole_digits":
            return "Слишком большая сумма"
        case "date_from_datetime_parsing" | "date_parsing" | "date_type":
            return "Некорректная дата"
        case "extra_forbidden":
            return "Неизвестное поле"
        case "enum" | "literal_error":
            return "Недопустимое значение"
        case "int_parsing" | "int_type":
            return "Введите целое число"
        case "greater_than_equal" | "less_than_equal" | "greater_than" | "less_than":
            return "Значение вне допустимого диапазона"
        case _:
            return str(error.get("msg", "Некорректное значение"))


def _validation_fields(errors: list[dict[str, Any]]) -> dict[str, list[str]]:
    fields: dict[str, list[str]] = {}
    for error in errors:
        fields.setdefault(_field_key(tuple(error.get("loc", ()))), []).append(_field_message(error))
    return fields


def register_exception_handlers(api: NinjaAPI) -> None:
    def respond(request: HttpRequest, status: int, code: ErrorCode, detail: str) -> HttpResponse:
        return api.create_response(request, ErrorOut(code=code, detail=detail), status=status)

    def respond_by_status(request: HttpRequest, status: int, fallback: str) -> HttpResponse:
        code = _CODE_BY_STATUS.get(status, ErrorCode.VALIDATION_ERROR)
        detail = {401: _UNAUTHORIZED_DETAIL, 403: _FORBIDDEN_DETAIL}.get(status, fallback)
        return respond(request, status, code, detail)

    @api.exception_handler(ApiError)
    def on_api_error(request: HttpRequest, exc: ApiError) -> HttpResponse:
        return api.create_response(request, exc.to_schema(), status=exc.status)

    @api.exception_handler(ValidationError)
    def on_validation(request: HttpRequest, exc: ValidationError) -> HttpResponse:
        error = ErrorOut(
            code=ErrorCode.VALIDATION_ERROR,
            detail=_VALIDATION_DETAIL,
            fields=_validation_fields(list(exc.errors)),
        )
        return api.create_response(request, error, status=422)

    @api.exception_handler(AuthenticationError)
    def on_authentication(request: HttpRequest, exc: AuthenticationError) -> HttpResponse:
        return respond(request, 401, ErrorCode.UNAUTHORIZED, _UNAUTHORIZED_DETAIL)

    @api.exception_handler(AuthorizationError)
    def on_authorization(request: HttpRequest, exc: AuthorizationError) -> HttpResponse:
        return respond(request, 403, ErrorCode.FORBIDDEN, _FORBIDDEN_DETAIL)

    @api.exception_handler(HttpError)
    def on_http_error(request: HttpRequest, exc: HttpError) -> HttpResponse:
        if exc.status_code == 400:
            # ninja: «Cannot parse request body (...)» на невалидном JSON. По контракту
            # ошибки ввода — 422, и текст парсера (англ., с позицией) наружу не отдаём.
            error = ErrorOut(
                code=ErrorCode.VALIDATION_ERROR,
                detail="Некорректный JSON в теле запроса",
                fields={"body": ["Некорректный JSON"]},
            )
            return api.create_response(request, error, status=422)
        return respond_by_status(request, exc.status_code, str(exc))

    @api.exception_handler(Http404)
    def on_404(request: HttpRequest, exc: Http404) -> HttpResponse:
        return respond(request, 404, ErrorCode.NOT_FOUND, "Не найдено")

    @api.exception_handler(MultiPartParserError)
    def on_bad_multipart(request: HttpRequest, exc: MultiPartParserError) -> HttpResponse:
        # Битый multipart (нет boundary и т.п.) при загрузке файла — ошибка ввода, а не 500.
        error = ErrorOut(
            code=ErrorCode.VALIDATION_ERROR,
            detail="Некорректное тело multipart/form-data",
            fields={"body": ["Некорректное тело multipart/form-data"]},
        )
        return api.create_response(request, error, status=422)

    # Ошибки ninja_extra/ninja_jwt: AuthenticationFailed, InvalidToken из JWTAuth и т.п.
    # Их текст (на английском, иногда dict) наружу не отдаём.
    # Регистрация перекрывает обработчик, который NinjaExtraAPI ставит в __init__.
    @api.exception_handler(APIException)
    def on_extra_api_exception(request: HttpRequest, exc: APIException) -> HttpResponse:
        return respond_by_status(request, exc.status_code, str(exc.detail))
