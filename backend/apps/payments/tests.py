import json
from datetime import date
from typing import Any
from unittest import mock

from django.test import TestCase

from apps.users.models import User, UserRole

from .models import OccurrenceStatus, PaymentOccurrence, RecurringPayment
from .schedule import shift_months

API = "/api/v1"
TODAY = date(2026, 10, 23)


class ScheduleTests(TestCase):
    def test_missing_day_moves_to_month_end_and_back(self) -> None:
        start = date(2026, 1, 31)
        self.assertEqual(shift_months(start, 1, 31), date(2026, 2, 28))
        self.assertEqual(shift_months(start, 2, 31), date(2026, 3, 31))
        self.assertEqual(shift_months(start, 3, 31), date(2026, 4, 30))
        self.assertEqual(shift_months(date(2027, 12, 15), 2, 15), date(2028, 2, 15))
        self.assertEqual(shift_months(date(2028, 1, 30), 1, 30), date(2028, 2, 29))

    def test_negative_shift(self) -> None:
        self.assertEqual(shift_months(TODAY, -12, TODAY.day), date(2025, 10, 23))


class ApiTestCase(TestCase):
    def setUp(self) -> None:
        patcher = mock.patch("django.utils.timezone.localdate", return_value=TODAY)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.admin = User.objects.create_user(
            username="boss", password="boss-pass-123", role=UserRole.ADMIN
        )
        self.user = User.objects.create_user(username="anna", password="anna-pass-123")
        self.admin_headers = self.auth("boss", "boss-pass-123")
        self.user_headers = self.auth("anna", "anna-pass-123")

    def auth(self, username: str, password: str) -> dict[str, str]:
        response = self.client.post(
            f"{API}/auth/login",
            {"username": username, "password": password},
            content_type="application/json",
        )
        return {"Authorization": f"Bearer {response.json()['access']}"}

    def post(self, path: str, data: dict[str, Any], headers: dict[str, str]) -> Any:
        return self.client.post(
            f"{API}{path}", data, content_type="application/json", headers=headers
        )

    def patch(self, path: str, data: dict[str, Any], headers: dict[str, str]) -> Any:
        return self.client.patch(
            f"{API}{path}", data, content_type="application/json", headers=headers
        )

    def get(self, path: str, headers: dict[str, str], **params: Any) -> Any:
        return self.client.get(f"{API}{path}", params, headers=headers)

    def create_payment(self, **overrides: Any) -> Any:
        data = {
            "title": "Аренда офиса",
            "amount": "85000.00",
            "currency": "RUB",
            "first_due_date": "2026-10-26",
            "comment": "Договор №14/25",
        } | overrides
        return self.post("/recurring-payments", data, self.admin_headers)


class RecurringPaymentApiTests(ApiTestCase):
    def test_create_returns_contract_shape(self) -> None:
        response = self.create_payment()

        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual(body["amount"], "85000.00")
        self.assertEqual(body["period"], "monthly")
        self.assertEqual(body["anchor_day"], 26)
        self.assertTrue(body["is_active"])
        self.assertEqual(body["created_by"], {"id": self.admin.id, "username": "boss"})
        self.assertEqual(body["next_occurrence"]["due_date"], "2026-10-26")
        self.assertEqual(body["next_occurrence"]["status"], "unpaid")
        self.assertFalse(body["next_occurrence"]["is_overdue"])
        self.assertEqual(body["overdue_count"], 0)
        self.assertRegex(body["created_at"], r"\+03:00$")

    def test_user_cannot_create_or_delete(self) -> None:
        response = self.post(
            "/recurring-payments",
            {"title": "x", "amount": "1", "currency": "RUB", "first_due_date": "2026-10-26"},
            self.user_headers,
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "forbidden")

        payment_id = self.create_payment().json()["id"]
        response = self.client.delete(
            f"{API}/recurring-payments/{payment_id}", headers=self.user_headers
        )
        self.assertEqual(response.status_code, 403)

    def test_requires_auth(self) -> None:
        self.assertEqual(self.client.get(f"{API}/recurring-payments").status_code, 401)
        self.assertEqual(self.client.get(f"{API}/payment-occurrences").status_code, 401)
        self.assertEqual(self.client.get(f"{API}/payments/summary").status_code, 401)

    def test_validation(self) -> None:
        response = self.create_payment(amount="0", currency="GBP", first_due_date="2025-01-01")

        self.assertEqual(response.status_code, 422)
        fields = response.json()["fields"]
        self.assertEqual(fields["amount"], ["Сумма должна быть больше 0"])
        self.assertIn("currency", fields)

        response = self.create_payment(first_due_date="2025-01-01")
        self.assertEqual(response.status_code, 422)
        self.assertIn("first_due_date", response.json()["fields"])

    def test_past_start_creates_history_with_overdue_and_next_period(self) -> None:
        body = self.create_payment(first_due_date="2026-08-26").json()

        due_dates = list(
            PaymentOccurrence.objects.filter(recurring_payment_id=body["id"]).values_list(
                "due_date", flat=True
            )
        )
        self.assertEqual(due_dates, [date(2026, 8, 26), date(2026, 9, 26), date(2026, 10, 26)])
        self.assertEqual(body["overdue_count"], 2)
        self.assertEqual(body["next_occurrence"]["due_date"], "2026-08-26")

    def test_next_period_generated_when_horizon_passes(self) -> None:
        self.create_payment(first_due_date="2026-10-15")
        # Срок 15.10 прошёл — следующий период (15.11) создаётся сразу, со своим статусом.
        response = self.get("/payment-occurrences", self.user_headers)

        dates = [item["due_date"] for item in response.json()["items"]]
        self.assertEqual(dates, ["2026-10-15", "2026-11-15"])

    def test_list_filters(self) -> None:
        self.create_payment()
        self.create_payment(title="Сервер", amount="49.00", currency="USD")

        response = self.get("/recurring-payments", self.user_headers, currency="USD")
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["items"][0]["title"], "Сервер")

        response = self.get("/recurring-payments", self.user_headers, search="аренда")
        self.assertEqual([i["title"] for i in response.json()["items"]], ["Аренда офиса"])

    def test_soft_delete_keeps_history(self) -> None:
        payment_id = self.create_payment(first_due_date="2026-09-26").json()["id"]
        past = PaymentOccurrence.objects.get(due_date=date(2026, 9, 26))

        response = self.client.delete(
            f"{API}/recurring-payments/{payment_id}", headers=self.admin_headers
        )

        self.assertEqual(response.status_code, 204)
        payment = RecurringPayment.objects.get(pk=payment_id)
        self.assertIsNotNone(payment.deleted_at)
        # Прошлый период остался, будущий (26.10) удалён.
        self.assertEqual(
            list(payment.occurrences.values_list("id", flat=True)),
            [past.id],
        )
        listed = self.get("/recurring-payments", self.user_headers).json()
        self.assertEqual(listed["count"], 0)
        listed = self.get("/recurring-payments", self.user_headers, include_inactive=True).json()
        self.assertFalse(listed["items"][0]["is_active"])

        again = self.client.delete(
            f"{API}/recurring-payments/{payment_id}", headers=self.admin_headers
        )
        self.assertEqual(again.status_code, 409)
        self.assertEqual(again.json()["code"], "already_deleted")

    def test_delete_not_found(self) -> None:
        response = self.client.delete(f"{API}/recurring-payments/999", headers=self.admin_headers)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Платёж не найден")


class OccurrenceApiTests(ApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.create_payment(first_due_date="2026-09-26")
        self.overdue = PaymentOccurrence.objects.get(due_date=date(2026, 9, 26))
        self.upcoming = PaymentOccurrence.objects.get(due_date=date(2026, 10, 26))

    def url(self, occurrence: PaymentOccurrence) -> str:
        return f"/payment-occurrences/{occurrence.id}"

    def test_overdue_shape(self) -> None:
        body = self.get(self.url(self.overdue), self.user_headers).json()

        self.assertEqual(body["status"], "unpaid")
        self.assertTrue(body["is_overdue"])
        self.assertEqual(body["overdue_days"], 27)
        self.assertEqual(body["recurring_payment"]["title"], "Аренда офиса")
        self.assertIsNone(body["marked_by"])

    def test_user_marks_paid_today_then_cancels(self) -> None:
        response = self.patch(self.url(self.upcoming), {"status": "paid"}, self.user_headers)

        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body["status"], "paid")
        self.assertEqual(body["paid_at"], "2026-10-23")
        self.assertFalse(body["is_overdue"])
        self.assertEqual(body["marked_by"], {"id": self.user.id, "username": "anna"})

        body = self.patch(self.url(self.upcoming), {"status": "unpaid"}, self.user_headers).json()
        self.assertEqual(body["status"], "unpaid")
        self.assertIsNone(body["paid_at"])

    def test_correct_paid_date_removes_overdue(self) -> None:
        body = self.patch(self.url(self.overdue), {"status": "paid"}, self.user_headers).json()
        self.assertTrue(body["is_overdue"])
        self.assertEqual(body["overdue_days"], 27)

        # Оплатили в день срока — вовремя.
        body = self.patch(self.url(self.overdue), {"paid_at": "2026-09-26"}, self.user_headers)
        body = body.json()
        self.assertFalse(body["is_overdue"])
        self.assertEqual(body["overdue_days"], 0)
        self.assertEqual(body["due_date"], "2026-09-26")

        body = self.patch(self.url(self.overdue), {"paid_at": "2026-09-27"}, self.user_headers)
        self.assertEqual(body.json()["overdue_days"], 1)

    def test_pay_with_explicit_date_and_history(self) -> None:
        self.patch(
            self.url(self.overdue), {"status": "paid", "paid_at": "2026-09-20"}, self.user_headers
        )
        self.overdue.refresh_from_db()

        self.assertEqual(self.overdue.paid_at, date(2026, 9, 20))
        self.assertEqual(self.overdue.history.count(), 2)
        self.assertEqual(self.overdue.history.first().history_user, self.user)

    def test_patch_validation(self) -> None:
        cases: list[tuple[dict[str, Any], int, str]] = [
            ({}, 422, "validation_error"),
            ({"status": "unpaid", "paid_at": "2026-10-01"}, 422, "validation_error"),
            ({"status": "paid", "paid_at": "2026-10-24"}, 422, "validation_error"),
            ({"paid_at": "2026-10-01"}, 409, "occurrence_not_paid"),
        ]
        for data, status, code in cases:
            with self.subTest(data=data):
                response = self.patch(self.url(self.upcoming), data, self.user_headers)
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.json()["code"], code)

    def test_not_found(self) -> None:
        response = self.get("/payment-occurrences/999", self.user_headers)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Период не найден")

    def test_state_filters(self) -> None:
        self.patch(self.url(self.upcoming), {"status": "paid"}, self.user_headers)

        def ids(state: str) -> list[int]:
            body = self.get("/payment-occurrences", self.user_headers, state=state).json()
            return [item["id"] for item in body["items"]]

        self.assertEqual(ids("overdue"), [self.overdue.id])
        self.assertEqual(ids("paid"), [self.upcoming.id])
        self.assertEqual(ids("unpaid"), [self.overdue.id])
        self.assertEqual(ids("upcoming"), [])

        body = self.get("/payment-occurrences", self.user_headers, ordering="-due_date").json()
        self.assertEqual(body["items"][0]["id"], self.upcoming.id)

    def test_pagination(self) -> None:
        body = self.get("/payment-occurrences", self.user_headers, page_size=1, page=2).json()

        self.assertEqual(body["count"], 2)
        self.assertEqual([item["id"] for item in body["items"]], [self.upcoming.id])
        response = self.get("/payment-occurrences", self.user_headers, page_size=500)
        self.assertEqual(response.status_code, 422)


class SummaryApiTests(ApiTestCase):
    def test_totals_per_currency(self) -> None:
        self.create_payment(first_due_date="2026-10-05", amount="57500.00")
        self.create_payment(first_due_date="2026-10-26")
        self.create_payment(
            title="Сервер", amount="49.00", currency="USD", first_due_date="2026-10-10"
        )
        PaymentOccurrence.objects.filter(due_date=date(2026, 10, 5)).update(
            status=OccurrenceStatus.PAID, paid_at=date(2026, 10, 5)
        )

        body = self.get("/payments/summary", self.user_headers).json()

        self.assertEqual(body["date_from"], "2026-10-01")
        self.assertEqual(body["date_to"], "2026-10-31")
        self.assertEqual(body["today"], "2026-10-23")
        self.assertEqual([t["currency"] for t in body["totals"]], ["RUB", "USD", "EUR"])
        rub, usd, eur = body["totals"]
        self.assertEqual(
            rub,
            {
                "currency": "RUB",
                "planned": "142500.00",
                "paid": "57500.00",
                "unpaid": "85000.00",
                "overdue": "0.00",
                "count_planned": 2,
                "count_paid": 1,
                "count_overdue": 0,
            },
        )
        self.assertEqual((usd["overdue"], usd["count_overdue"]), ("49.00", 1))
        self.assertEqual(eur["planned"], "0.00")

    def test_year_budget_includes_future_periods(self) -> None:
        self.create_payment(first_due_date="2026-10-26", amount="100.00")

        body = self.get(
            "/payments/summary", self.user_headers, date_from="2026-10-01", date_to="2027-09-30"
        ).json()

        self.assertEqual(body["totals"][0]["planned"], "1200.00")
        self.assertEqual(body["totals"][0]["count_planned"], 12)

    def test_range_validation(self) -> None:
        response = self.get(
            "/payments/summary", self.user_headers, date_from="2026-01-01", date_to="2027-06-01"
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"], "Диапазон не должен превышать 366 дней")

        response = self.get(
            "/payments/summary", self.user_headers, date_from="2026-02-01", date_to="2026-01-01"
        )
        self.assertEqual(response.status_code, 422)


class PaymentAdminTests(TestCase):
    def setUp(self) -> None:
        self.admin = User.objects.create_superuser(
            username="root", password="x", role=UserRole.ADMIN
        )
        self.client.force_login(self.admin)

    def test_occurrence_cannot_be_added_manually(self) -> None:
        response = self.client.get("/admin/payments/paymentoccurrence/add/")

        self.assertEqual(response.status_code, 403)
        response = self.client.post("/admin/payments/paymentoccurrence/add/", {"status": "unpaid"})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(PaymentOccurrence.objects.exists())

    def test_payment_created_in_admin_gets_occurrences(self) -> None:
        response = self.client.post(
            "/admin/payments/recurringpayment/add/",
            {
                "title": "Хостинг",
                "amount": "1500.00",
                "currency": "RUB",
                "period": "monthly",
                "first_due_date": date.today().isoformat(),
                "comment": "",
                # пустой inline-формсет периодов
                "occurrences-TOTAL_FORMS": "0",
                "occurrences-INITIAL_FORMS": "0",
            },
        )

        self.assertEqual(response.status_code, 302, response.content[:2000])
        payment = RecurringPayment.objects.get(title="Хостинг")
        self.assertTrue(payment.occurrences.exists())
        self.assertEqual(payment.created_by, self.admin)

    def test_paid_without_date_is_form_error_not_500(self) -> None:
        payment = RecurringPayment.objects.create(
            title="Аренда",
            amount="100.00",
            currency="RUB",
            first_due_date=date(2026, 10, 26),
            anchor_day=26,
            created_by=self.admin,
        )
        occurrence = PaymentOccurrence.objects.create(
            recurring_payment=payment, amount="100.00", currency="RUB", due_date=date(2026, 10, 26)
        )

        response = self.client.post(
            f"/admin/payments/paymentoccurrence/{occurrence.pk}/change/",
            {"status": "paid", "paid_at": ""},
        )

        self.assertEqual(response.status_code, 200)  # форма с ошибкой, без 500
        occurrence.refresh_from_db()
        self.assertEqual(occurrence.status, OccurrenceStatus.UNPAID)


class AdminDashboardTests(TestCase):
    def setUp(self) -> None:
        self.admin = User.objects.create_superuser(
            username="root", password="x", role=UserRole.ADMIN
        )
        self.client.force_login(self.admin)
        today_patch = mock.patch("django.utils.timezone.localdate", return_value=date(2026, 10, 23))
        today_patch.start()
        self.addCleanup(today_patch.stop)

    def occurrence(self, title: str, due_date: date, **extra: Any) -> PaymentOccurrence:
        payment = RecurringPayment.objects.create(
            title=title,
            amount="100.00",
            currency="USD",
            first_due_date=due_date,
            anchor_day=due_date.day,
            created_by=self.admin,
        )
        return PaymentOccurrence.objects.create(
            recurring_payment=payment, amount="100.00", currency="USD", due_date=due_date, **extra
        )

    def test_dashboard_shows_totals_overdue_and_upcoming(self) -> None:
        self.occurrence("Просроченный хостинг", date(2026, 10, 20))
        self.occurrence("Скорый домен", date(2026, 10, 25))
        self.occurrence(
            "Оплаченная аренда", date(2026, 10, 5), status="paid", paid_at=date(2026, 10, 5)
        )

        response = self.client.get("/admin/")

        self.assertEqual(response.status_code, 200)
        kpi = {item["title"]: item["value"] for item in response.context["kpi"]}
        self.assertEqual(kpi["Просрочено периодов"], 1)
        self.assertEqual(kpi["К оплате в ближайшие 14 дней"], 1)
        self.assertEqual(kpi["Оплачено в этом месяце"], "1 из 3")
        usd = next(r for r in response.context["totals_table"]["rows"] if "USD" in r[0])
        self.assertEqual(usd[1], "300,00 $")
        self.assertContains(response, "Просроченный хостинг")
        self.assertContains(response, "Скорый домен")
        self.assertContains(response, "через 2 дня")
        self.assertContains(response, "3 дня")  # просрочка

        status = json.loads(response.context["status_chart"])
        october = status["labels"].index("Окт 26")
        by_label = {d["label"]: d["data"][october] for d in status["datasets"]}
        self.assertEqual(
            by_label,
            {
                "Оплачено вовремя": 1,
                "Оплачено с опозданием": 0,
                "Просрочено": 1,
                "Ожидает оплаты": 1,
            },
        )
        charts = {c["currency"]: json.loads(c["data"]) for c in response.context["currency_charts"]}
        self.assertEqual(list(charts), ["USD"])  # пустые валюты не рисуем
        usd = {d["label"]: d["data"][october] for d in charts["USD"]["datasets"]}
        self.assertEqual(usd, {"План": 300.0, "Оплачено": 100.0})


class SchemathesisRegressionTests(ApiTestCase):
    """Находки Schemathesis: 500, мусор во входных данных, расхождения с OpenAPI."""

    def raw(self, method: str, path: str, body: str, headers: dict[str, str]) -> Any:
        return getattr(self.client, method)(
            f"{API}{path}", body, content_type="application/json", headers=headers
        )

    def occurrence_id(self) -> int:
        self.create_payment(first_due_date="2026-10-20")
        return PaymentOccurrence.objects.get(due_date=date(2026, 10, 20)).pk

    def test_huge_page_is_422_not_500(self) -> None:
        for path, headers in (
            ("/recurring-payments", self.user_headers),
            ("/payment-occurrences", self.user_headers),
            ("/users", self.admin_headers),
        ):
            with self.subTest(path=path):
                response = self.get(path, headers, page=232759599943861239808)
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json()["code"], "validation_error")
                self.assertIn("page", response.json()["fields"])

    def test_summary_at_end_of_calendar_is_not_500(self) -> None:
        self.create_payment(first_due_date="2026-10-26")

        response = self.get(
            "/payments/summary", self.user_headers, date_from="9999-12-01", date_to="9999-12-31"
        )

        self.assertEqual(response.status_code, 200)

    def test_dates_must_be_iso_strings(self) -> None:
        occurrence_id = self.occurrence_id()
        path = f"/payment-occurrences/{occurrence_id}"

        for body in ({"paid_at": 0}, {"status": "paid", "paid_at": 1700000000}):
            with self.subTest(body=body):
                response = self.patch(path, body, self.user_headers)
                self.assertEqual(response.status_code, 422)
                self.assertEqual(
                    response.json()["fields"]["paid_at"], ["Дата в формате ГГГГ-ММ-ДД"]
                )
        self.assertEqual(
            PaymentOccurrence.objects.get(pk=occurrence_id).status, OccurrenceStatus.UNPAID
        )

        response = self.get("/payment-occurrences", self.user_headers, due_to="0")
        self.assertEqual(response.status_code, 422)
        self.assertIn("due_to", response.json()["fields"])
        self.assertEqual(self.create_payment(first_due_date="20261026").status_code, 422)

    def test_first_due_date_upper_bound(self) -> None:
        self.assertEqual(self.create_payment(first_due_date="9999-12-31").status_code, 422)
        self.assertEqual(self.create_payment(first_due_date="2036-10-23").status_code, 201)
        response = self.create_payment(first_due_date="2036-10-24")
        self.assertEqual(response.status_code, 422)
        self.assertIn("first_due_date", response.json()["fields"])

    def test_control_characters_rejected(self) -> None:
        nul, newline = chr(0), chr(10)
        for field, value in (
            ("title", f"x{nul}y"),
            ("title", f"x{newline}y"),
            ("comment", f"x{nul}y"),
        ):
            with self.subTest(field=field, value=repr(value)):
                response = self.create_payment(**{field: value})
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json()["fields"][field], ["Недопустимые символы"])
        # Перевод строки в комментарии допустим.
        response = self.create_payment(comment=f"строка 1{newline}строка 2")
        self.assertEqual(response.status_code, 201)
        response = self.get("/recurring-payments", self.user_headers, search=f"a{nul}")
        self.assertEqual(response.status_code, 422)

    def test_invalid_json_is_422(self) -> None:
        nul = chr(0)
        for path, method, headers in (
            ("/auth/login", "post", {}),
            ("/recurring-payments", "post", self.admin_headers),
            (f"/payment-occurrences/{self.occurrence_id()}", "patch", self.user_headers),
        ):
            with self.subTest(path=path):
                response = self.raw(method, path, nul, headers)
                self.assertEqual(response.status_code, 422)
                self.assertEqual(
                    response.json(),
                    {
                        "code": "validation_error",
                        "detail": "Некорректный JSON в теле запроса",
                        "fields": {"body": ["Некорректный JSON"]},
                    },
                )

    def test_non_object_body_rejected(self) -> None:
        path = f"/payment-occurrences/{self.occurrence_id()}"
        for body in ("[]", "[null, null]", '"str"', "5", "null"):
            with self.subTest(body=body):
                response = self.raw("patch", path, body, self.user_headers)
                self.assertEqual(response.status_code, 422)

    def test_patch_occurrence_variants(self) -> None:
        path = f"/payment-occurrences/{self.occurrence_id()}"

        rejected: tuple[dict[str, Any], ...] = (
            {},
            {"status": None},
            {"status": "paid", "paid_at": None},
            {"status": "unpaid", "paid_at": None},
            {"status": "paid", "extra": 1},
        )
        for body in rejected:
            with self.subTest(body=body):
                self.assertEqual(self.patch(path, body, self.user_headers).status_code, 422)

        self.assertEqual(self.patch(path, {"status": "paid"}, self.user_headers).status_code, 200)
        fixed = self.patch(path, {"paid_at": "2026-10-21"}, self.user_headers)
        self.assertEqual(fixed.json()["paid_at"], "2026-10-21")
        self.assertEqual(self.patch(path, {"status": "unpaid"}, self.user_headers).status_code, 200)

    def test_path_param_errors_are_documented_422(self) -> None:
        response = self.get("/payment-occurrences/null,null", self.user_headers)
        self.assertEqual(response.status_code, 422)
        schema = self.client.get(f"{API}/openapi.json").json()
        for path, method in (
            ("/api/v1/payment-occurrences/{occurrence_id}", "get"),
            ("/api/v1/payment-occurrences/{occurrence_id}", "patch"),
            ("/api/v1/recurring-payments/{payment_id}", "delete"),
            ("/api/v1/users/{user_id}", "delete"),
            ("/api/v1/users/{user_id}", "patch"),
        ):
            with self.subTest(path=path, method=method):
                self.assertIn("422", schema["paths"][path][method]["responses"])

    def test_openapi_describes_rules(self) -> None:
        schema = self.client.get(f"{API}/openapi.json").json()
        components = schema["components"]["schemas"]

        patch_in = components["PaymentOccurrencePatchIn"]
        self.assertEqual(len(patch_in["oneOf"]), 3)
        self.assertTrue(all(v["additionalProperties"] is False for v in patch_in["oneOf"]))

        email = components["UserCreateIn"]["properties"]["email"]
        self.assertIn({"format": "email"}, email["anyOf"])

        for path in ("/api/v1/auth/refresh", "/api/v1/auth/logout"):
            params = {p["name"]: p for p in schema["paths"][path]["post"]["parameters"]}
            self.assertEqual(params["X-Requested-With"]["schema"]["enum"], ["XMLHttpRequest"])
            self.assertTrue(params["X-Requested-With"]["required"])
            self.assertEqual(params["refresh_token"]["in"], "cookie")

        page = next(
            p
            for p in schema["paths"]["/api/v1/recurring-payments"]["get"]["parameters"]
            if p["name"] == "page"
        )
        self.assertEqual(page["schema"]["maximum"], 100_000)
