from typing import Any

from django.db import transaction

from .models import PaymentAttachment


def delete_attachment_file(
    sender: type[PaymentAttachment], instance: PaymentAttachment, **kwargs: Any
) -> None:
    """
    Файл удаляется с диска после коммита: и при удалении вложения, и при каскадном
    удалении периода (удалённый платёж убирает будущие неоплаченные периоды).
    Если транзакция откатится, файл останется на месте.
    """
    if not instance.file:
        return
    storage, name = instance.file.storage, str(instance.file.name)
    transaction.on_commit(lambda: storage.delete(name))
