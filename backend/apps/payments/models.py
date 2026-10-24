from collections.abc import Iterator
from datetime import date
from typing import Any

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _
from simple_history.models import HistoricalRecords

from apps.core.schemas import local_today

from .schedule import due_dates


class Currency(models.TextChoices):
    RUB = "RUB", "RUB"
    USD = "USD", "USD"
    EUR = "EUR", "EUR"


class Period(models.TextChoices):
    MONTHLY = "monthly", _("Ежемесячно")
    QUARTERLY = "quarterly", _("Ежеквартально")
    YEARLY = "yearly", _("Ежегодно")


PERIOD_MONTHS: dict[str, int] = {
    Period.MONTHLY: 1,
    Period.QUARTERLY: 3,
    Period.YEARLY: 12,
}


class OccurrenceStatus(models.TextChoices):
    UNPAID = "unpaid", _("Не оплачено")
    PAID = "paid", _("Оплачено")


class RecurringPayment(models.Model):
    """Шаблон регулярного платежа. Статусы и даты оплаты живут на периодах."""

    id: int

    title = models.CharField(_("название"), max_length=120)
    amount = models.DecimalField(_("сумма"), max_digits=12, decimal_places=2)
    currency = models.CharField(_("валюта"), max_length=3, choices=Currency.choices)
    period = models.CharField(
        _("периодичность"), max_length=16, choices=Period.choices, default=Period.MONTHLY
    )
    first_due_date = models.DateField(_("первый срок"))
    # День месяца из first_due_date: от него считаются следующие сроки (30 → 28 фев → 30 мар).
    anchor_day = models.PositiveSmallIntegerField(_("день месяца"))
    # null, а не "": в контракте comment — `string | null`.
    comment = models.TextField(_("комментарий"), null=True, blank=True)  # noqa: DJ001
    # title.casefold(): в SQLite icontains/LOWER не работают с кириллицей.
    search_title = models.CharField(max_length=120, editable=False, default="")

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("создал"),
    )
    created_at = models.DateTimeField(_("создан"), auto_now_add=True)
    # Мягкое удаление: платёж прекращён, история периодов сохраняется.
    deleted_at = models.DateTimeField(_("удалён"), null=True, blank=True)

    history = HistoricalRecords()

    class Meta:
        ordering = ["title", "id"]
        verbose_name = _("регулярный платёж")
        verbose_name_plural = _("регулярные платежи")

    def __str__(self) -> str:
        return self.title

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.anchor_day = self.first_due_date.day
        self.search_title = self.title.casefold()
        super().save(*args, **kwargs)

    @property
    def is_active(self) -> bool:
        return self.deleted_at is None

    def schedule(self) -> Iterator[date]:
        return due_dates(self.first_due_date, PERIOD_MONTHS[self.period], self.anchor_day)


class PaymentOccurrence(models.Model):
    """Период регулярного платежа: свой срок, свой статус и фактическая дата оплаты."""

    id: int
    recurring_payment_id: int

    recurring_payment = models.ForeignKey(
        RecurringPayment,
        on_delete=models.CASCADE,
        related_name="occurrences",
        verbose_name=_("регулярный платёж"),
    )
    # Снимок суммы и валюты на момент создания периода.
    amount = models.DecimalField(_("сумма"), max_digits=12, decimal_places=2)
    currency = models.CharField(_("валюта"), max_length=3, choices=Currency.choices)
    due_date = models.DateField(_("срок оплаты"))
    status = models.CharField(
        _("статус"),
        max_length=8,
        choices=OccurrenceStatus.choices,
        default=OccurrenceStatus.UNPAID,
    )
    paid_at = models.DateField(_("фактическая дата оплаты"), null=True, blank=True)

    marked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("кто отметил"),
    )
    marked_at = models.DateTimeField(_("когда отмечено"), null=True, blank=True)
    reminder_sent_at = models.DateTimeField(_("напоминание отправлено"), null=True, blank=True)
    created_at = models.DateTimeField(_("создан"), auto_now_add=True)

    history = HistoricalRecords()

    class Meta:
        ordering = ["due_date", "id"]
        verbose_name = _("период оплаты")
        verbose_name_plural = _("периоды оплаты")
        constraints = [
            models.UniqueConstraint(
                fields=["recurring_payment", "due_date"], name="uniq_occurrence_due_date"
            ),
            models.CheckConstraint(
                condition=models.Q(status=OccurrenceStatus.UNPAID, paid_at__isnull=True)
                | models.Q(status=OccurrenceStatus.PAID, paid_at__isnull=False),
                name="occurrence_paid_at_matches_status",
            ),
        ]
        indexes = [models.Index(fields=["status", "due_date"])]

    def __str__(self) -> str:
        # Без обращения к платежу (лишний запрос на строку в списках и инлайне).
        return f"Срок {self.due_date:%d.%m.%Y}"

    @property
    def is_paid(self) -> bool:
        return self.status == OccurrenceStatus.PAID

    @property
    def overdue_days(self) -> int:
        """Просрочка со следующего дня после срока; оплата в день срока — вовремя."""
        reference = self.paid_at if self.paid_at is not None else local_today()
        return max(0, (reference - self.due_date).days)

    @property
    def is_overdue(self) -> bool:
        return self.overdue_days > 0
