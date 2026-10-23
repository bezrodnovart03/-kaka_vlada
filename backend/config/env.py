from datetime import timedelta
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class BaseAppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


class DatabaseSettings(BaseAppSettings):
    """
    Настройки подключения к базе данных.
    Поддерживает SQLite и сетевые БД.
    """

    engine: str = Field(default="django.db.backends.sqlite3", alias="DB_ENGINE")
    name: str = Field(default="db.sqlite3", alias="DB_NAME")

    host: str | None = Field(default=None, alias="DB_HOST")
    port: int | None = Field(default=None, alias="DB_PORT")
    user: str | None = Field(default=None, alias="DB_USER")
    password: str | None = Field(default=None, alias="DB_PASSWORD")

    @property
    def django_config(self) -> dict[str, Any]:
        if self.engine == "django.db.backends.sqlite3":
            return {
                "ENGINE": self.engine,
                "NAME": str(BASE_DIR / self.name),
            }

        return {
            "ENGINE": self.engine,
            "NAME": self.name,
            "USER": self.user,
            "PASSWORD": self.password,
            "HOST": self.host,
            "PORT": self.port,
        }


class DjangoSettings(BaseAppSettings):
    secret_key: Annotated[str, Field(alias="SECRET_KEY")]
    debug: bool = Field(default=False, alias="DEBUG")
    allowed_hosts: list[str] = Field(default_factory=list, alias="ALLOWED_HOSTS")
    # Единый часовой пояс для сроков оплаты и напоминаний.
    time_zone: str = Field(default="Europe/Moscow", alias="TIME_ZONE")


class JWTSettings(BaseAppSettings):
    access_token_lifetime_minutes: int = Field(
        default=30, alias="JWT_ACCESS_TOKEN_LIFETIME_MINUTES"
    )
    refresh_token_lifetime_days: int = Field(default=7, alias="JWT_REFRESH_TOKEN_LIFETIME_DAYS")
    # None — по DEBUG: в dev без Secure (http://localhost), в проде с Secure.
    refresh_cookie_secure: bool | None = Field(default=None, alias="JWT_REFRESH_COOKIE_SECURE")

    @property
    def access_token_lifetime(self) -> timedelta:
        return timedelta(minutes=self.access_token_lifetime_minutes)

    @property
    def refresh_token_lifetime(self) -> timedelta:
        return timedelta(days=self.refresh_token_lifetime_days)


class AdminSettings(BaseAppSettings):
    """
    Учётная запись администратора. Задаётся только через .env
    и синхронизируется в БД после миграций.
    """

    username: Annotated[str, Field(alias="ADMIN_USERNAME")]
    password: Annotated[str, Field(alias="ADMIN_PASSWORD")]
    email: str = Field(default="", alias="ADMIN_EMAIL")


class ReminderSettings(BaseAppSettings):
    """Telegram-напоминания. Без токена и чата бот молчит, остальное работает."""

    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: str = Field(default="", alias="TELEGRAM_CHAT_ID")
    days_before: int = Field(default=3, ge=0, le=30, alias="REMINDER_DAYS_BEFORE")
    # Как часто фоновый процесс проверяет сроки (он же long-polling кнопки «Оплачено»).
    check_interval_seconds: int = Field(
        default=60, ge=5, le=3600, alias="REMINDER_CHECK_INTERVAL_SECONDS"
    )
    # Кнопка «Оплачено» прямо в сообщении бота.
    pay_button: bool = Field(default=True, alias="TELEGRAM_PAY_BUTTON")
    # Базовый URL панели для ссылки в сообщении (необязательно).
    panel_url: str = Field(default="", alias="PANEL_URL")

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)


# Обязательные поля DjangoSettings/AdminSettings приходят из .env, а не из аргументов __init__.
# mypy понимает это через плагин pydantic, Pyright — нет, поэтому игнор только для него.
class Settings(BaseAppSettings):
    django: DjangoSettings = Field(default_factory=DjangoSettings)  # pyright: ignore[reportArgumentType]
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    jwt: JWTSettings = Field(default_factory=JWTSettings)
    admin: AdminSettings = Field(default_factory=AdminSettings)  # pyright: ignore[reportArgumentType]
    reminders: ReminderSettings = Field(default_factory=ReminderSettings)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
