"""Общие типы и схемы API (docs/API.md §1)."""

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any

from django.db.models import Model, QuerySet
from django.utils import timezone
from ninja import Schema
from pydantic import (
    BeforeValidator,
    Field,
    ModelWrapValidatorHandler,
    PlainSerializer,
    ValidationInfo,
    WithJsonSchema,
    model_validator,
)

# Деньги — строка-decimal с 2 знаками: "85000.00". Float нигде не используется.
Money = Annotated[
    Decimal,
    PlainSerializer(lambda value: f"{value:.2f}", return_type=str),
    WithJsonSchema({"type": "string", "format": "decimal", "example": "85000.00"}),
]

# datetime в часовом поясе TIME_ZONE со смещением: "2026-10-23T20:18:00+03:00".
LocalDateTime = Annotated[
    datetime,
    PlainSerializer(
        lambda value: timezone.localtime(value).isoformat(timespec="seconds"), return_type=str
    ),
    WithJsonSchema({"type": "string", "format": "date-time"}),
]


_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _parse_iso_date(value: Any) -> date:
    # Только "ГГГГ-ММ-ДД". Без этого pydantic в lax-режиме превращает число в unix-время:
    # {"paid_at": 0} становилось 1970-01-01.
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, str) and _ISO_DATE.fullmatch(value):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    raise ValueError("Дата в формате ГГГГ-ММ-ДД")


# date из API: строго ISO-строка (docs/API.md §1).
ISODate = Annotated[
    date,
    BeforeValidator(_parse_iso_date),
    WithJsonSchema({"type": "string", "format": "date", "example": "2026-10-23"}),
]

# Управляющие символы (NUL и прочие C0) в тексте не принимаем: PostgreSQL не хранит NUL,
# а остальные ломают вывод в Telegram и панели. Переводы строк и табы — только в многострочном.
# Правило — `pattern`: одно и то же ограничение и проверяется, и попадает в OpenAPI.
PlainText = Annotated[str, Field(pattern=r"^[^\x00-\x1f\x7f]*$")]
MultilineText = Annotated[str, Field(pattern=r"^[^\x00-\x08\x0b\x0c\x0e-\x1f\x7f]*$")]


class InputSchema(Schema):
    """
    Тело запроса: только JSON-объект.

    ninja.Schema валидирует с from_attributes=True через DjangoGetter, и тогда список,
    строка или число в теле проходят как «объект без полей» — PATCH с `[]` отвечал 200.
    Переопределяем корневой валидатор ninja (то же имя) без этой обёртки.
    """

    @model_validator(mode="wrap")
    @classmethod
    def _run_root_validator(
        cls, values: Any, handler: ModelWrapValidatorHandler[Any], info: ValidationInfo
    ) -> Any:
        if not isinstance(values, dict):
            raise ValueError("Ожидается JSON-объект")
        return handler(values)


def local_today() -> date:
    """«Сегодня» в TIME_ZONE из .env — единая точка для сроков и просрочек."""
    return timezone.localdate()


class UserBrief(Schema):
    id: int
    username: str


# Верхняя граница page: без неё offset переполнял int64 в SQLite (500 на ?page=10**20).
MAX_PAGE = 100_000


class PageQuery(Schema):
    page: int = Field(1, ge=1, le=MAX_PAGE)
    page_size: int = Field(50, ge=1, le=200)


def paginate[M: Model](queryset: QuerySet[M], query: PageQuery) -> dict[str, Any]:
    """Ответ `Paginated<T>`: `{"items": [...], "count": N}`."""
    offset = (query.page - 1) * query.page_size
    return {
        "items": list(queryset[offset : offset + query.page_size]),
        "count": queryset.count(),
    }
