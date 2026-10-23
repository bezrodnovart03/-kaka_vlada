from ninja import ModelSchema, Schema
from pydantic import Field

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
