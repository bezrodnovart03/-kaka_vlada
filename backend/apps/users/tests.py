from typing import Any

from django.conf import settings
from django.test import TestCase

from .models import User, UserRole

URL = "/api/v1/auth"
XHR = {"X-Requested-With": "XMLHttpRequest"}
COOKIE = settings.JWT_REFRESH_COOKIE_NAME


class AuthApiTests(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username="anna", password="s3cret-pass", first_name="Анна"
        )

    def login(self, password: str = "s3cret-pass") -> Any:
        return self.client.post(
            f"{URL}/login",
            {"username": "anna", "password": password},
            content_type="application/json",
        )

    def bearer(self, access: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {access}"}

    def test_login_sets_http_only_cookie_and_returns_only_access(self) -> None:
        response = self.login()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.json()), {"access"})
        cookie = response.cookies[COOKIE]
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "Strict")
        self.assertEqual(cookie["path"], settings.JWT_REFRESH_COOKIE_PATH)

    def test_login_wrong_password(self) -> None:
        response = self.login(password="wrong")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.json(),
            {
                "code": "invalid_credentials",
                "detail": "Неверный логин или пароль",
                "fields": None,
            },
        )

    def test_login_validation_error_format(self) -> None:
        response = self.client.post(
            f"{URL}/login", {"username": ""}, content_type="application/json"
        )

        self.assertEqual(response.status_code, 422)
        body = response.json()
        self.assertEqual(body["code"], "validation_error")
        self.assertEqual(body["fields"]["username"], ["Обязательное поле"])
        self.assertEqual(body["fields"]["password"], ["Обязательное поле"])

    def test_me_returns_contract_fields(self) -> None:
        access = self.login().json()["access"]

        response = self.client.get(f"{URL}/me", headers=self.bearer(access))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "id": self.user.id,
                "username": "anna",
                "first_name": "Анна",
                "last_name": "",
                "email": "",
                "role": UserRole.USER.value,
                "is_env_admin": False,
            },
        )

    def test_env_admin_is_synced_with_admin_role(self) -> None:
        # Создаётся sync_env_admin на post_migrate тестовой БД.
        admin = User.objects.get(username=settings.ADMIN_USERNAME)

        self.assertTrue(admin.is_env_admin)
        self.assertEqual(admin.role, "admin")
        self.assertFalse(self.user.is_env_admin)

    def test_protected_without_token(self) -> None:
        response = self.client.get(f"{URL}/me")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "unauthorized")

    def test_protected_with_garbage_token(self) -> None:
        response = self.client.get(f"{URL}/me", headers=self.bearer("garbage"))

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.json(),
            {"code": "unauthorized", "detail": "Требуется вход", "fields": None},
        )

    def test_inactive_user_access_rejected(self) -> None:
        access = self.login().json()["access"]
        User.objects.filter(pk=self.user.pk).update(is_active=False)

        response = self.client.get(f"{URL}/me", headers=self.bearer(access))

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "unauthorized")

    def test_refresh_rotates_cookie(self) -> None:
        self.login()
        old_refresh = self.client.cookies[COOKIE].value

        response = self.client.post(f"{URL}/refresh", headers=XHR)

        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.json())
        self.assertNotEqual(response.cookies[COOKIE].value, old_refresh)

        # Старый refresh отозван.
        self.client.cookies[COOKIE] = old_refresh
        reused = self.client.post(f"{URL}/refresh", headers=XHR)
        self.assertEqual(reused.status_code, 401)
        self.assertEqual(reused.json()["code"], "token_invalid")
        self.assertEqual(reused.cookies[COOKIE].value, "")

    def test_refresh_requires_xhr_header(self) -> None:
        self.login()

        response = self.client.post(f"{URL}/refresh")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "csrf_failed")

    def test_refresh_without_cookie(self) -> None:
        response = self.client.post(f"{URL}/refresh", headers=XHR)

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "token_invalid")

    def test_refresh_inactive_user(self) -> None:
        self.login()
        User.objects.filter(pk=self.user.pk).update(is_active=False)

        response = self.client.post(f"{URL}/refresh", headers=XHR)

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "token_invalid")

    def test_logout_revokes_refresh_and_deletes_cookie(self) -> None:
        self.login()
        refresh = self.client.cookies[COOKIE].value

        response = self.client.post(f"{URL}/logout", headers=XHR)

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.cookies[COOKIE].value, "")
        self.client.cookies[COOKIE] = refresh
        self.assertEqual(self.client.post(f"{URL}/refresh", headers=XHR).status_code, 401)

    def test_logout_is_idempotent(self) -> None:
        self.assertEqual(self.client.post(f"{URL}/logout", headers=XHR).status_code, 204)

    def test_logout_requires_xhr_header(self) -> None:
        response = self.client.post(f"{URL}/logout")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "csrf_failed")


class UsersApiTests(TestCase):
    def setUp(self) -> None:
        self.env_admin = User.objects.get(username=settings.ADMIN_USERNAME)
        self.env_admin.set_password("admin-pass-1")
        self.env_admin.save()
        self.user = User.objects.create_user(username="anna", password="s3cret-pass")
        self.admin_headers = self.bearer(settings.ADMIN_USERNAME, "admin-pass-1")
        self.user_headers = self.bearer("anna", "s3cret-pass")

    def bearer(self, username: str, password: str) -> dict[str, str]:
        response = self.client.post(
            f"{URL}/login",
            {"username": username, "password": password},
            content_type="application/json",
        )
        return {"Authorization": f"Bearer {response.json()['access']}"}

    def send(self, method: str, path: str, data: Any = None, user: bool = False) -> Any:
        headers = self.user_headers if user else self.admin_headers
        return getattr(self.client, method)(
            f"/api/v1/users{path}", data, content_type="application/json", headers=headers
        )

    def test_user_has_no_access(self) -> None:
        for method, path in [("get", ""), ("post", ""), ("patch", "/1"), ("delete", "/1")]:
            with self.subTest(method=method):
                response = self.send(method, path, {}, user=True)
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.json()["code"], "forbidden")

    def test_list_hides_secrets(self) -> None:
        body = self.send("get", "").json()

        self.assertEqual(body["count"], 2)
        admin = body["items"][0]
        self.assertTrue(admin["is_env_admin"])
        self.assertEqual(admin["role"], "admin")
        self.assertNotIn("password", admin)

    def test_create_regular_user(self) -> None:
        response = self.send(
            "post",
            "",
            {"username": "petr", "password": "min8chars", "role": "admin", "first_name": "Пётр"},
        )

        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual(body["role"], "user")
        self.assertIsNone(body["last_login"])
        self.assertTrue(User.objects.get(username="petr").check_password("min8chars"))

    def test_create_validation_and_conflict(self) -> None:
        response = self.send("post", "", {"username": "anna", "password": "min8chars"})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["fields"], {"username": ["Логин уже занят"]})

        response = self.send("post", "", {"username": "bad name", "password": "short"})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["fields"]["password"], ["Минимум 8 символов"])
        self.assertIn("username", response.json()["fields"])

    def test_patch_block_and_password_revokes_refresh(self) -> None:
        self.client.post(
            f"{URL}/login",
            {"username": "anna", "password": "s3cret-pass"},
            content_type="application/json",
        )
        response = self.send(
            "patch", f"/{self.user.id}", {"first_name": "Аня", "password": "new-pass-123"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["first_name"], "Аня")
        refreshed = self.client.post(f"{URL}/refresh", headers=XHR)
        self.assertEqual(refreshed.status_code, 401)

        response = self.send("patch", f"/{self.user.id}", {"is_active": False})
        self.assertFalse(response.json()["is_active"])
        self.assertEqual(self.client.get(f"{URL}/me", headers=self.user_headers).status_code, 401)

    def test_env_admin_immutable(self) -> None:
        response = self.send("patch", f"/{self.env_admin.id}", {"first_name": "X"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "env_admin_immutable")

        response = self.send("delete", f"/{self.env_admin.id}")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "env_admin_immutable")

    def test_delete_user(self) -> None:
        response = self.send("delete", f"/{self.user.id}")

        self.assertEqual(response.status_code, 204)
        self.assertFalse(User.objects.filter(pk=self.user.pk).exists())
        self.assertEqual(self.client.get(f"{URL}/me", headers=self.user_headers).status_code, 401)
        self.assertEqual(self.send("delete", f"/{self.user.id}").status_code, 404)
