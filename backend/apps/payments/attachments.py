"""Чеки и ссылки к конкретной оплате (периоду)."""

import logging
import re
from pathlib import PurePath

import filetype  # type: ignore[import-untyped]  # без py.typed
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.core.validators import URLValidator

from apps.core.errors import ApiError, ErrorCode, field_error
from apps.users.models import User

from .models import AttachmentKind, PaymentAttachment, PaymentOccurrence

audit = logging.getLogger("audit")

# Тип определяется по содержимому файла, а не по расширению или заголовку клиента.
ALLOWED_TYPES = {
    "application/pdf": "PDF",
    "image/png": "PNG",
    "image/jpeg": "JPEG",
    "image/webp": "WebP",
    "image/heic": "HEIC",
}
MAX_ATTACHMENTS = 20
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_url_validator = URLValidator(schemes=["http", "https"])


def _clean_name(name: str, fallback: str) -> str:
    # Только имя без пути (Windows-клиенты присылают «C:\...\чек.pdf»), без управляющих символов.
    name = _CONTROL_CHARS.sub("", PurePath(name.replace("\\", "/")).name).strip()
    return (name or fallback)[:255]


def _check_limit(occurrence: PaymentOccurrence) -> None:
    if occurrence.attachments.count() >= MAX_ATTACHMENTS:
        raise ApiError(
            409, ErrorCode.CONFLICT, f"К периоду можно прикрепить не больше {MAX_ATTACHMENTS}"
        )


def detect_content_type(upload: UploadedFile[bytes]) -> str | None:
    upload.seek(0)
    head = upload.read(261)  # filetype читает сигнатуру из первых 261 байт
    upload.seek(0)
    kind = filetype.guess(head)
    if kind is None:
        return None
    mime = str(kind.mime)
    return mime if mime in ALLOWED_TYPES else None


def add_file(
    occurrence: PaymentOccurrence, upload: UploadedFile[bytes], user: User
) -> PaymentAttachment:
    size = upload.size or 0
    if size == 0:
        raise field_error("file", "Файл пустой")
    if size > settings.ATTACHMENT_MAX_BYTES:
        limit_mb = settings.ATTACHMENT_MAX_BYTES // (1024 * 1024)
        raise field_error("file", f"Файл больше {limit_mb} МБ")
    content_type = detect_content_type(upload)
    if content_type is None:
        allowed = ", ".join(ALLOWED_TYPES.values())
        raise field_error("file", f"Допустимые форматы: {allowed}")
    _check_limit(occurrence)

    name = _clean_name(upload.name or "", "чек")
    attachment = PaymentAttachment(
        occurrence=occurrence,
        kind=AttachmentKind.FILE,
        name=name,
        content_type=content_type,
        size=size,
        uploaded_by=user,
    )
    attachment.file.save(name, upload, save=False)
    attachment.save()
    audit.info(
        "attachment added id=%s occurrence=%s file=%r size=%s by=%s",
        attachment.id,
        occurrence.id,
        name,
        size,
        user.username,
    )
    return attachment


def add_link(
    occurrence: PaymentOccurrence, url: str, name: str | None, user: User
) -> PaymentAttachment:
    url = url.strip()
    try:
        _url_validator(url)
    except ValidationError:
        raise field_error("url", "Ссылка должна начинаться с http:// или https://") from None
    _check_limit(occurrence)

    attachment = PaymentAttachment.objects.create(
        occurrence=occurrence,
        kind=AttachmentKind.LINK,
        url=url,
        name=(_CONTROL_CHARS.sub("", name or "").strip() or url)[:255],
        uploaded_by=user,
    )
    audit.info(
        "attachment added id=%s occurrence=%s link by=%s",
        attachment.id,
        occurrence.id,
        user.username,
    )
    return attachment


def delete(attachment: PaymentAttachment, user: User) -> None:
    """Удалить может тот, кто добавил, или администратор."""
    if not (user.is_admin or attachment.uploaded_by_id == user.id):
        raise ApiError(403, ErrorCode.FORBIDDEN, "Удалить может автор или администратор")
    attachment_id = attachment.id
    attachment.delete()  # файл с диска — сигнал post_delete после коммита
    audit.info("attachment deleted id=%s by=%s", attachment_id, user.username)
