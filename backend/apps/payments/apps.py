from django.apps import AppConfig
from django.db.models.signals import post_delete


class PaymentsConfig(AppConfig):
    name = "apps.payments"
    verbose_name = "Платежи"

    def ready(self) -> None:
        from .models import PaymentAttachment
        from .signals import delete_attachment_file

        post_delete.connect(delete_attachment_file, sender=PaymentAttachment)
