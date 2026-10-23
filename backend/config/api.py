from ninja_extra import NinjaExtraAPI
from ninja_jwt.authentication import JWTAuth

from apps.core.errors import register_exception_handlers
from apps.users.api import auth_router

# auth на уровне API: любой новый роутер закрыт по умолчанию,
# открытые эндпоинты явно помечаются `auth=None`.
api = NinjaExtraAPI(
    title="Invoice Keeper API",
    version="1.0.0",
    description="Напоминания о регулярных платежах",
    urls_namespace="api-v1",
    auth=JWTAuth(),
)

register_exception_handlers(api)

api.add_router("/auth", auth_router)
