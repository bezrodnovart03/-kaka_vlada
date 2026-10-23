from ninja_extra import NinjaExtraAPI

from apps.core.auth import UserJWTAuth
from apps.core.errors import register_exception_handlers
from apps.payments.api import occurrences_router, recurring_router, summary_router
from apps.users.api import auth_router, users_router

# auth на уровне API: любой новый роутер закрыт по умолчанию,
# открытые эндпоинты явно помечаются `auth=None`.
api = NinjaExtraAPI(
    title="Invoice Keeper API",
    version="1.0.0",
    description="Напоминания о регулярных платежах",
    urls_namespace="api-v1",
    auth=UserJWTAuth(),
)

register_exception_handlers(api)

api.add_router("/auth", auth_router)
api.add_router("/recurring-payments", recurring_router)
api.add_router("/payment-occurrences", occurrences_router)
api.add_router("/payments", summary_router)
api.add_router("/users", users_router)
