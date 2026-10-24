import tempfile
from pathlib import Path

from django.test import TestCase, override_settings

from apps.users.models import User

from .logs import parse_records, read_tail

LOG_TEXT = """\
2026-10-24 21:48:47,845 INFO audit: login ok username=admin
2026-10-24 21:49:01,100 ERROR apps.notifications: Ошибка getUpdates
Traceback (most recent call last):
TelegramError: Conflict
2026-10-24 21:50:00,000 WARNING audit: login failed username=bob
"""


class LogsViewTests(TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = Path(self.dir.name) / "app.log"
        self.path.write_text(LOG_TEXT, encoding="utf-8")
        self.root = User.objects.create_superuser(username="root", password="x")

    def test_parse_joins_traceback_to_record(self) -> None:
        records = parse_records(read_tail(self.path))
        self.assertEqual([r["level"] for r in records], ["INFO", "ERROR", "WARNING"])
        self.assertIn("TelegramError: Conflict", records[1]["message"])

    def test_tail_drops_cut_first_line(self) -> None:
        last = "2026-10-24 21:50:00,000 WARNING audit: login failed username=bob"
        # Хвост захватывает конец предпоследней строки — она отбрасывается.
        lines = read_tail(self.path, size=len(last) + 10)
        self.assertEqual(lines, [last])

    def test_superuser_sees_filtered_records_newest_first(self) -> None:
        self.client.force_login(self.root)
        with override_settings(LOG_FILE=self.path):
            response = self.client.get("/admin/logs/", {"level": "WARNING"})
        self.assertEqual(response.status_code, 200)
        records = response.context["records"]
        self.assertEqual([r["level"] for r in records], ["WARNING", "ERROR"])

    def test_search(self) -> None:
        self.client.force_login(self.root)
        with override_settings(LOG_FILE=self.path):
            response = self.client.get("/admin/logs/", {"q": "BOB"})
        self.assertEqual(len(response.context["records"]), 1)

    def test_without_log_file(self) -> None:
        self.client.force_login(self.root)
        with override_settings(LOG_FILE=None):
            response = self.client.get("/admin/logs/")
        self.assertContains(response, "задайте LOG_FILE")

    def test_staff_without_superuser_forbidden(self) -> None:
        staff = User.objects.create_user(username="staff", password="x", is_staff=True)
        self.client.force_login(staff)
        with override_settings(LOG_FILE=self.path):
            response = self.client.get("/admin/logs/")
        self.assertEqual(response.status_code, 403)

    def test_anonymous_redirected_to_login(self) -> None:
        response = self.client.get("/admin/logs/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response["Location"])
