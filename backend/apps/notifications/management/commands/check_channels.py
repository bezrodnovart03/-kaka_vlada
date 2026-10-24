from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.notifications import channels, telegram


class Command(BaseCommand):
    help = "Отправляет тестовое сообщение во все настроенные каналы напоминаний."

    def handle(self, *args: Any, **options: Any) -> None:
        results: list[tuple[str, str | None]] = []

        if telegram.is_configured():
            try:
                telegram.send_message("Invoice Keeper: тестовое сообщение, канал настроен.")
                results.append(("Telegram", None))
            except telegram.TelegramError as exc:
                results.append(("Telegram", str(exc)))

        for channel in channels.configured_channels():
            try:
                channel.send_test()
                results.append((str(channel.channel.label), None))
            except channels.ChannelError as exc:
                results.append((str(channel.channel.label), str(exc)))

        if not results:
            raise CommandError("Ни один канал не настроен: см. .env.example")
        for name, error in results:
            if error is None:
                self.stdout.write(self.style.SUCCESS(f"[OK] {name}"))
            else:
                self.stdout.write(self.style.ERROR(f"[FAIL] {name}: {error}"))
        if any(error for _, error in results):
            raise CommandError("Не все каналы работают")
