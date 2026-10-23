from typing import Annotated

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email
from ninja import ModelSchema, Schema
from pydantic import Field, field_validator

from apps.core.schemas import LocalDateTime

from .models import User, UserRole


class LoginIn(Schema):
    username: str = Field(min_length=1, max_length=150)
    password: str = Field(min_length=1, max_length=128)


class AccessOut(Schema):
    """Refresh-токен в тело не попадает — он только в HttpOnly-cookie."""

    access: str


class MeOut(ModelSchema):
    role: UserRole
    is_env_admin: bool

    class Meta:
        model = User
        fields = ["id", "username", "first_name", "last_name", "email"]


# ── управление пользователями (только админ) ─────────────

# Как у Django UnicodeUsernameValidator: буквы, цифры и @.+-_
USERNAME_PATTERN = r"^[\w.@+-]+$"

Username = Annotated[str, Field(min_length=1, max_length=150, pattern=USERNAME_PATTERN)]
Password = Annotated[str, Field(min_length=8, max_length=128)]
Email = Annotated[str, Field(max_length=254)]
Name = Annotated[str, Field(max_length=150)]


class UserOut(Schema):
    id: int
    username: str
    first_name: str
    last_name: str
    email: str
    role: UserRole
    is_env_admin: bool
    is_active: bool
    last_login: LocalDateTime | None
    date_joined: LocalDateTime


class UserCreateIn(Schema):
    username: Username
    password: Password
    email: Email = ""
    first_name: Name = ""
    last_name: Name = ""

    @field_validator("email")
    @classmethod
    def email_format(cls, value: str) -> str:
        return _validate_email(value)


class UserPatchIn(Schema):
    username: Username | None = None
    password: Password | None = None
    email: Email | None = None
    first_name: Name | None = None
    last_name: Name | None = None
    is_active: bool | None = None

    @field_validator("email")
    @classmethod
    def email_format(cls, value: str | None) -> str | None:
        return None if value is None else _validate_email(value)


class PaginatedUserOut(Schema):
    items: list[UserOut]
    count: int


def _validate_email(value: str) -> str:
    value = value.strip()
    if value:
        try:
            validate_email(value)
        except DjangoValidationError:
            raise ValueError("Некорректный email") from None
    return value
