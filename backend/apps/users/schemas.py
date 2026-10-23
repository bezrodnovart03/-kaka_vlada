from ninja import ModelSchema, Schema

from .models import User


class LoginIn(Schema):
    username: str
    password: str


class RefreshIn(Schema):
    refresh: str


class TokenPairOut(Schema):
    access: str
    refresh: str


class UserOut(ModelSchema):
    is_admin: bool

    class Meta:
        model = User
        fields = ["id", "username", "first_name", "last_name", "email", "role"]
