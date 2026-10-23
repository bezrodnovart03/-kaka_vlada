from django.apps import AppConfig
from django.db.models.signals import post_migrate


class UsersConfig(AppConfig):
    name = "apps.users"
    verbose_name = "Пользователи"

    def ready(self) -> None:
        from .signals import sync_env_admin

        post_migrate.connect(sync_env_admin, sender=self)
