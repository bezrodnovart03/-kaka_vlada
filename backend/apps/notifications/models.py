from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.payments.models import PaymentOccurrence


class Channel(models.TextChoices):
    EMAIL = "email", "Email"
    WEBHOOK = "webhook", "Webhook"
    APPRISE = "apprise", _("Другие каналы")


class ReminderDelivery(models.Model):
    """
    Напоминание по периоду, отправленное в канал. Уникальность (период, канал) — защита
    от дублей: запись создаётся до отправки («захват») и удаляется, если отправка не удалась.
    Telegram, как и раньше, отмечается в PaymentOccurrence.reminder_sent_at.
    """

    occurrence = models.ForeignKey(
        PaymentOccurrence,
        on_delete=models.CASCADE,
        related_name="reminder_deliveries",
        verbose_name=_("период"),
    )
    channel = models.CharField(_("канал"), max_length=16, choices=Channel.choices)
    sent_at = models.DateTimeField(_("отправлено"), auto_now_add=True)

    class Meta:
        ordering = ["sent_at", "id"]
        verbose_name = _("доставка напоминания")
        verbose_name_plural = _("доставки напоминаний")
        constraints = [
            models.UniqueConstraint(
                fields=["occurrence", "channel"], name="uniq_reminder_delivery_channel"
            )
        ]

    def __str__(self) -> str:
        return f"{self.get_channel_display()} — {self.sent_at:%d.%m.%Y %H:%M}"
