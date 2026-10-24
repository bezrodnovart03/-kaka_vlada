import shutil
import tempfile
from pathlib import Path
from typing import Any

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from icalendar import Calendar

from .models import PaymentAttachment, PaymentOccurrence
from .tests import API, ApiTestCase

# Минимальные файлы с настоящими сигнатурами: тип проверяется по содержимому.
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


class AttachmentApiTests(ApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        media = tempfile.mkdtemp(prefix="ik-media-")
        self.addCleanup(shutil.rmtree, media, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=media, ATTACHMENT_MAX_BYTES=1024)
        override.enable()
        self.addCleanup(override.disable)
        self.media = Path(media)
        self.create_payment(first_due_date="2026-10-20")
        self.occurrence = PaymentOccurrence.objects.get(due_date="2026-10-20")
        self.base = f"{API}/payment-occurrences/{self.occurrence.id}/attachments"

    def upload(self, content: bytes, name: str, headers: dict[str, str] | None = None) -> Any:
        return self.client.post(
            f"{self.base}/file",
            {"file": SimpleUploadedFile(name, content, content_type="application/x-anything")},
            headers=headers or self.user_headers,
        )

    def test_user_uploads_downloads_and_deletes_receipt(self) -> None:
        response = self.upload(PDF, "C:\\Users\\anna\\чек №1.pdf")

        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual(body["kind"], "file")
        self.assertEqual(body["name"], "чек №1.pdf")  # путь клиента отброшен
        self.assertEqual(body["content_type"], "application/pdf")  # по содержимому
        self.assertEqual(body["size"], len(PDF))
        self.assertEqual(body["uploaded_by"]["username"], "anna")
        self.assertIsNone(body["url"])
        stored = Path(PaymentAttachment.objects.get().file.path)
        self.assertTrue(stored.is_file())
        self.assertNotIn("чек", stored.name)  # имя на диске случайное

        download = self.client.get(f"{self.base}/{body['id']}/download", headers=self.admin_headers)
        self.assertEqual(download.status_code, 200)
        self.assertEqual(b"".join(download.streaming_content), PDF)  # type: ignore[attr-defined]
        self.assertEqual(download["Content-Type"], "application/pdf")
        self.assertIn("attachment", download["Content-Disposition"])

        listed = self.get(f"/payment-occurrences/{self.occurrence.id}", self.user_headers)
        self.assertEqual(listed.json()["attachments_count"], 1)

        with self.captureOnCommitCallbacks(execute=True):
            deleted = self.client.delete(f"{self.base}/{body['id']}", headers=self.user_headers)
        self.assertEqual(deleted.status_code, 204)
        self.assertFalse(stored.exists())  # файл удалён с диска

    def test_rejects_wrong_type_by_content(self) -> None:
        response = self.upload(b"MZ\x90\x00 definitely not a receipt", "receipt.pdf")

        self.assertEqual(response.status_code, 422)
        self.assertIn("file", response.json()["fields"])
        self.assertFalse(PaymentAttachment.objects.exists())

    def test_rejects_too_large_and_empty(self) -> None:
        too_large = self.upload(PNG + b"\x00" * 2048, "big.png")
        empty = self.upload(b"", "empty.pdf")

        self.assertEqual(too_large.status_code, 422)
        self.assertEqual(empty.status_code, 422)
        self.assertEqual(list(self.media.rglob("*.*")), [])

    def test_link_attachment(self) -> None:
        response = self.post(
            f"/payment-occurrences/{self.occurrence.id}/attachments/link",
            {"url": "https://bank.example.com/receipt/42", "name": "Платёжка 12/10"},
            self.user_headers,
        )

        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual(body["kind"], "link")
        self.assertEqual(body["name"], "Платёжка 12/10")
        self.assertEqual(body["url"], "https://bank.example.com/receipt/42")

        download = self.client.get(f"{self.base}/{body['id']}/download", headers=self.user_headers)
        self.assertEqual(download.status_code, 409)

    def test_link_rejects_unsafe_schemes(self) -> None:
        for url in ("javascript:alert(1)", "ftp://example.com/a", "file:///etc/passwd", "просто"):
            response = self.post(
                f"/payment-occurrences/{self.occurrence.id}/attachments/link",
                {"url": url},
                self.user_headers,
            )
            self.assertEqual(response.status_code, 422, url)

    def test_only_author_or_admin_deletes(self) -> None:
        attachment_id = self.upload(PNG, "photo.png", self.admin_headers).json()["id"]

        forbidden = self.client.delete(f"{self.base}/{attachment_id}", headers=self.user_headers)
        self.assertEqual(forbidden.status_code, 403)

        user_link = self.post(
            f"/payment-occurrences/{self.occurrence.id}/attachments/link",
            {"url": "https://example.com/r"},
            self.user_headers,
        ).json()["id"]
        by_admin = self.client.delete(f"{self.base}/{user_link}", headers=self.admin_headers)
        self.assertEqual(by_admin.status_code, 204)

    def test_requires_auth_and_matching_occurrence(self) -> None:
        attachment_id = self.upload(PNG, "photo.png").json()["id"]
        other = PaymentOccurrence.objects.exclude(pk=self.occurrence.pk).first()
        assert other is not None

        self.assertEqual(self.client.get(self.base).status_code, 401)
        self.assertEqual(self.client.get(f"{self.base}/{attachment_id}/download").status_code, 401)
        foreign = f"{API}/payment-occurrences/{other.id}/attachments/{attachment_id}/download"
        self.assertEqual(self.client.get(foreign, headers=self.user_headers).status_code, 404)

    def test_list_attachments(self) -> None:
        self.upload(PDF, "a.pdf")
        self.post(
            f"/payment-occurrences/{self.occurrence.id}/attachments/link",
            {"url": "https://example.com/r"},
            self.user_headers,
        )

        response = self.client.get(self.base, headers=self.user_headers)

        self.assertEqual(response.status_code, 200)
        self.assertEqual([a["kind"] for a in response.json()], ["file", "link"])


class CalendarExportTests(ApiTestCase):
    def events(self, **params: Any) -> list[Any]:
        response = self.get("/payment-occurrences/calendar.ics", self.user_headers, **params)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response["Content-Type"].startswith("text/calendar"))
        return list(Calendar.from_ical(response.content).walk("VEVENT"))

    def test_occurrences_and_planned_dates(self) -> None:
        self.create_payment(first_due_date="2026-10-20")  # просрочен, далее ежемесячно
        occurrence = PaymentOccurrence.objects.get(due_date="2026-10-20")
        self.patch(
            f"/payment-occurrences/{occurrence.id}",
            {"status": "paid", "paid_at": "2026-10-21"},
            self.user_headers,
        )

        events = self.events(due_from="2026-10-01", due_to="2027-01-31")

        starts = [event.decoded("dtstart") for event in events]
        self.assertEqual(
            [d.isoformat() for d in starts],
            ["2026-10-20", "2026-11-20", "2026-12-20", "2027-01-20"],
        )
        self.assertTrue(str(events[0]["summary"]).startswith("✅"))
        self.assertEqual(events[0].walk("VALARM"), [])  # оплаченный — без оповещения
        self.assertEqual(len(events[1].walk("VALARM")), 1)
        self.assertEqual(len({str(event["uid"]) for event in events}), 4)

    def test_state_filter_and_range_validation(self) -> None:
        self.create_payment(first_due_date="2026-10-20")

        overdue = self.events(state="overdue", due_from="2026-10-01", due_to="2027-01-31")
        self.assertEqual([e.decoded("dtstart").isoformat() for e in overdue], ["2026-10-20"])

        bad = self.get(
            "/payment-occurrences/calendar.ics",
            self.user_headers,
            due_from="2026-10-10",
            due_to="2026-10-01",
        )
        self.assertEqual(bad.status_code, 422)
        self.assertEqual(
            self.client.get(f"{API}/payment-occurrences/calendar.ics").status_code, 401
        )


class AttachmentFuzzRegressionTests(ApiTestCase):
    """Случаи, найденные Schemathesis: раньше отвечали 500."""

    def test_huge_ids_are_404(self) -> None:
        huge = 10**24  # больше int64: фильтр по occurrence_id падал в SQLite с OverflowError
        for occurrence_id, attachment_id in ((huge, huge), (huge, 1), (1, huge)):
            path = f"{API}/payment-occurrences/{occurrence_id}/attachments/{attachment_id}/download"
            response = self.client.get(path, headers=self.user_headers)
            self.assertEqual(response.status_code, 404, path)

    def test_broken_multipart_is_422(self) -> None:
        self.create_payment(first_due_date="2026-10-20")
        occurrence = PaymentOccurrence.objects.get(due_date="2026-10-20")

        response = self.client.post(
            f"{API}/payment-occurrences/{occurrence.id}/attachments/file",
            data=b"--x\r\n",
            content_type="multipart/form-data",  # без boundary
            headers=self.user_headers,
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["code"], "validation_error")
