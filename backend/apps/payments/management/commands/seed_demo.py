from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandParser
from django.db import transaction

from apps.core.schemas import local_today
from apps.payments import attachments, services
from apps.payments.models import OccurrenceStatus, Period, RecurringPayment
from apps.payments.schedule import shift_months
from apps.users.models import User, UserRole

DEMO_USERNAME = "user"
DEMO_PASSWORD = "user-pass-123"


class Command(BaseCommand):
    help = (
        "Тестовые данные относительно сегодняшней даты: аренда в рублях (просрочка "
        "и оплаченная история), сервер в долларах (срок через 2 дня), подписка в евро "
        f"и пользователь {DEMO_USERNAME} / {DEMO_PASSWORD}."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--reset", action="store_true", help="Удалить все платежи перед загрузкой."
        )

    @transaction.atomic
    def handle(self, *args: Any, **options: Any) -> None:
        today = local_today()
        admin = User.objects.get(username=settings.ADMIN_USERNAME)

        if options["reset"]:
            RecurringPayment.objects.all().delete()
        elif RecurringPayment.objects.exists():
            self.stdout.write("Платежи уже есть — пропускаю (используйте --reset).")
            self._ensure_user()
            return

        def create(
            title: str,
            amount: str,
            currency: str,
            first: date,
            period: str = Period.MONTHLY,
            comment: str | None = None,
        ) -> RecurringPayment:
            return services.create_payment(
                user=admin,
                title=title,
                amount=Decimal(amount),
                currency=currency,
                first_due_date=first,
                period=period,
                comment=comment,
                today=today,
            )

        # Аренда: срок был 2 дня назад и не оплачен (просрочка). Три предыдущих месяца —
        # история: вовремя, на 2 дня позже, вовремя. Следующий период — через месяц.
        overdue_due = today - timedelta(days=2)
        rent = create(
            "Аренда офиса",
            "85000.00",
            "RUB",
            shift_months(overdue_due, -3, overdue_due.day),
            comment="Договор аренды №14/25",
        )
        history = list(rent.occurrences.filter(due_date__lt=overdue_due).order_by("due_date"))
        for index, occurrence in enumerate(history):
            delay = timedelta(days=2 if index == 1 else 0)
            services.mark_paid(occurrence, occurrence.due_date + delay, admin, source="seed")
        if history:
            # Чек к последней оплате — ссылка; файлы прикрепляются в панели.
            attachments.add_link(
                history[-1],
                "https://example.com/receipts/rent",
                "Платёжное поручение",
                admin,
            )

        create(
            "Сервер Hetzner",
            "49.00",
            "USD",
            today + timedelta(days=2),
            comment="VPS для продакшена",
        )
        create("Подписка JetBrains", "29.90", "EUR", today + timedelta(days=12))
        create(
            "Домен invoice-keeper.ru",
            "1200.00",
            "RUB",
            today + timedelta(days=40),
            period=Period.YEARLY,
        )

        self._ensure_user()
        unpaid = rent.occurrences.filter(status=OccurrenceStatus.UNPAID).count()
        self.stdout.write(
            self.style.SUCCESS(
                f"Готово: 4 платежа (аренда — {unpaid} неоплаченных периода), "
                f"пользователь {DEMO_USERNAME} / {DEMO_PASSWORD}."
            )
        )

    def _ensure_user(self) -> None:
        user, created = User.objects.get_or_create(
            username=DEMO_USERNAME,
            defaults={"first_name": "Анна", "last_name": "Петрова", "role": UserRole.USER},
        )
        if created:
            user.set_password(DEMO_PASSWORD)
            user.save()
