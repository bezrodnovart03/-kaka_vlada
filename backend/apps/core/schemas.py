"""Общие типы и схемы API (docs/API.md §1)."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any

from django.db.models import Model, QuerySet
from django.utils import timezone
from ninja import Schema
from pydantic import Field, PlainSerializer, WithJsonSchema

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


def local_today() -> date:
    """«Сегодня» в TIME_ZONE из .env — единая точка для сроков и просрочек."""
    return timezone.localdate()


class UserBrief(Schema):
    id: int
    username: str


class PageQuery(Schema):
    page: int = Field(1, ge=1)
    page_size: int = Field(50, ge=1, le=200)


def paginate[M: Model](queryset: QuerySet[M], query: PageQuery) -> dict[str, Any]:
    """Ответ `Paginated<T>`: `{"items": [...], "count": N}`."""
    offset = (query.page - 1) * query.page_size
    return {
        "items": list(queryset[offset : offset + query.page_size]),
        "count": queryset.count(),
    }
