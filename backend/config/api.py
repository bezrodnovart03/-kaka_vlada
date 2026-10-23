from ninja_extra import NinjaExtraAPI

from apps.users.api import auth_router

api = NinjaExtraAPI(
    title="Invoice Keeper API",
    version="1.0.0",
    description="Напоминания о регулярных платежах",
    urls_namespace="api-v1",
)

api.add_router("/auth", auth_router)
