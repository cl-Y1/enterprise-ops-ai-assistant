"""认证、角色与审计测试。"""

from __future__ import annotations

import shutil
import unittest
import uuid
from pathlib import Path
from unittest.mock import Mock, patch

import requests

import app as app_module

MESSAGE_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


class RBACTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = Path(__file__).resolve().parent.parent / ".test-tmp" / uuid.uuid4().hex
        self.tmpdir.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, self.tmpdir, ignore_errors=True)
        self.app = app_module.create_app(
            {
                "TESTING": True,
                "DATABASE_PATH": str(self.tmpdir / "rbac.sqlite3"),
                "SECRET_KEY": "test-secret-key",
                "DIFY_API_KEY": "test-key",
                "DIFY_API_BASE_URL": "https://dify.example.test/v1",
                "DIFY_USER_ID": "test-user-001",
                "INITIAL_ADMIN_USERNAME": "admin",
                "INITIAL_ADMIN_PASSWORD": "AdminPass123!",
                "INITIAL_ADMIN_DISPLAY_NAME": "系统管理员",
                "INITIAL_ADMIN_LEGACY": False,
            }
        )
        self.users = self.app.extensions["user_repo"]
        self.users.create_user(
            username="operator1",
            display_name="运维一组",
            password="OperatorPass123!",
            role="operator",
        )
        self.users.create_user(
            username="employee1",
            display_name="普通员工",
            password="EmployeePass123!",
            role="employee",
        )
        self.admin = self.login("admin", "AdminPass123!")
        self.operator = self.login("operator1", "OperatorPass123!")
        self.employee = self.login("employee1", "EmployeePass123!")

    def login(self, username: str, password: str):
        client = self.app.test_client()
        page = client.get("/login")
        self.assertEqual(page.status_code, 200)
        with client.session_transaction() as session:
            token = session["csrf_token"]
        response = client.post(
            "/login",
            data={"username": username, "password": password, "csrf_token": token},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        return client

    @staticmethod
    def csrf(client) -> str:
        with client.session_transaction() as session:
            return session["csrf_token"]

    def test_role_specific_redirect_after_login(self) -> None:
        employee_login = self.app.test_client()
        employee_login.get("/login")
        with employee_login.session_transaction() as session:
            token = session["csrf_token"]
        response = employee_login.post(
            "/login",
            data={"username": "employee1", "password": "EmployeePass123!", "csrf_token": token},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/")

    def test_login_page_and_failed_login(self) -> None:
        client = self.app.test_client()
        page = client.get("/login")
        self.assertIn("登录工作台", page.get_data(as_text=True))
        with client.session_transaction() as session:
            token = session["csrf_token"]
        response = client.post(
            "/login",
            data={"username": "admin", "password": "wrong-password", "csrf_token": token},
            follow_redirects=True,
        )
        self.assertIn("账号或密码错误", response.get_data(as_text=True))
        self.assertEqual(client.get("/admin/documents").status_code, 302)

    def test_employee_cannot_manage_users_or_roles(self) -> None:
        self.assertEqual(self.employee.get("/admin/users").status_code, 403)
        self.assertEqual(self.employee.get("/admin/roles").status_code, 403)
        self.assertEqual(self.employee.get("/admin/audit").status_code, 403)

    def test_operator_can_view_feedback_but_not_users_or_audit(self) -> None:
        self.assertEqual(self.operator.get("/admin/feedback").status_code, 200)
        self.assertEqual(self.operator.get("/admin/users").status_code, 403)
        self.assertEqual(self.operator.get("/admin/roles").status_code, 403)
        self.assertEqual(self.operator.get("/admin/audit").status_code, 403)

    def test_admin_can_view_users_roles_and_audit(self) -> None:
        self.assertEqual(self.admin.get("/admin/users").status_code, 200)
        roles = self.admin.get("/admin/roles")
        self.assertEqual(roles.status_code, 200)
        self.assertIn("权限矩阵", roles.get_data(as_text=True))
        audit = self.admin.get("/admin/audit")
        self.assertEqual(audit.status_code, 200)
        self.assertIn("登录成功", audit.get_data(as_text=True))

    def test_password_is_hashed_and_user_can_be_created(self) -> None:
        user = self.users.get_by_username("operator1")
        self.assertNotEqual(user["password_hash"], "OperatorPass123!")
        self.assertTrue(
            user["password_hash"].startswith(("scrypt:", "pbkdf2:"))
        )

        response = self.admin.post(
            "/admin/users/new",
            data={
                "username": "newemployee",
                "display_name": "新员工",
                "role": "employee",
                "password": "NewEmployeePass123!",
                "is_active": "1",
                "csrf_token": self.csrf(self.admin),
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        created = self.users.get_by_username("newemployee")
        self.assertIsNotNone(created)
        self.assertEqual(created["role"], "employee")

    def test_role_change_invalidates_old_session(self) -> None:
        target = self.users.get_by_username("operator1")
        response = self.admin.post(
            f"/admin/users/{target['id']}/edit",
            data={
                "display_name": "运维一组",
                "role": "employee",
                "is_active": "1",
                "csrf_token": self.csrf(self.admin),
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        # 角色改变后 session_version 递增，旧运维会话不能再进入后台。
        after = self.operator.get("/admin/documents")
        self.assertEqual(after.status_code, 302)
        self.assertIn("/login", after.headers["Location"])

    def test_logout_invalidates_old_session_cookie(self) -> None:
        with self.operator.session_transaction() as session:
            old_session = dict(session)
        response = self.operator.post(
            "/logout",
            data={"csrf_token": self.csrf(self.operator)},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

        replay = self.app.test_client()
        with replay.session_transaction() as session:
            session.update(old_session)
        response = replay.get("/admin/documents")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

    def test_feedback_page_reads_local_mirror(self) -> None:
        response = Mock(spec=requests.Response)
        response.status_code = 200
        response.json.return_value = {"result": "success"}
        with patch("app.requests.post", return_value=response):
            result = self.employee.post(
                "/api/feedback",
                json={
                    "message_id": MESSAGE_ID,
                    "rating": "dislike",
                    "reason": "答案不准确",
                    "comment": "缺少 Service 日志检查步骤",
                },
            )
        self.assertEqual(result.status_code, 200)

        page = self.operator.get("/admin/feedback")
        self.assertEqual(page.status_code, 200)
        body = page.get_data(as_text=True)
        self.assertIn("答案不准确", body)
        self.assertIn("缺少 Service 日志检查步骤", body)
        self.assertEqual(self.employee.get("/admin/feedback").status_code, 403)

    def test_unauthenticated_admin_post_is_rejected(self) -> None:
        client = self.app.test_client()
        response = client.post(
            "/admin/versions/1/publish",
            data={"csrf_token": "forged"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])


if __name__ == "__main__":
    unittest.main()
