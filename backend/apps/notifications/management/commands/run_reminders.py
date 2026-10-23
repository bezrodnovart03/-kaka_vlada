import logging
import time
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandParser

from apps.notifications import services, telegram

logger = logging.getLogger("apps.notifications")


class Command(BaseCommand):
    help = (
        "Фоновый процесс напоминаний: каждые REMINDER_CHECK_INTERVAL_SECONDS проверяет сроки "
        "и пишет в Telegram-чат; между проверками обрабатывает кнопку «Оплачено»."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--once", action="store_true", help="Одна проверка без цикла (для cron)."
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if not telegram.is_configured():
            self.stderr.write(
                "TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID не заданы в .env — сообщения не уйдут."
            )
        if options["once"]:
            sent = services.run_check()
            self.stdout.write(f"Отправлено напоминаний: {sent}")
            return

        interval = settings.REMINDER_CHECK_INTERVAL_SECONDS
        self.stdout.write(
            f"Напоминания запущены: проверка каждые {interval} с, "
            f"за {settings.REMINDER_DAYS_BEFORE} дн. до срока. Ctrl+C — выход."
        )
        offset: int | None = None
        try:
            while True:
                started = time.monotonic()
                try:
                    services.run_check()
                except Exception:
                    logger.exception("Ошибка проверки напоминаний")
                remaining = max(1, int(interval - (time.monotonic() - started)))
                offset = self._wait(offset, remaining)
        except KeyboardInterrupt:
            self.stdout.write("Остановлено.")

    def _wait(self, offset: int | None, seconds: int) -> int | None:
        """Ждёт до следующей проверки; если бот настроен — слушает нажатия кнопок."""
        if not (telegram.is_configured() and settings.TELEGRAM_PAY_BUTTON):
            time.sleep(seconds)
            return offset
        deadline = time.monotonic() + seconds
        while (left := int(deadline - time.monotonic())) > 0:
            try:
                offset = services.poll_updates(offset, timeout=min(left, 30))
            except telegram.TelegramError:
                logger.exception("Ошибка getUpdates")
                time.sleep(min(left, 5))
            except Exception:
                logger.exception("Ошибка обработки кнопки «Оплачено»")
                time.sleep(min(left, 5))
        return offset
