"""文档工作流 + 角色权限测试。"""

from __future__ import annotations

import shutil
import unittest
import uuid
from pathlib import Path

import app as app_module

DATASET_ID = "11111111-1111-4111-8111-111111111111"
DIFY_DOCUMENT_ID = "22222222-2222-4222-8222-222222222222"


class DocumentWorkflowTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = Path(__file__).resolve().parent.parent / ".test-tmp" / uuid.uuid4().hex
        self.tmpdir.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, self.tmpdir, ignore_errors=True)
        self.db_path = str(self.tmpdir / "test.sqlite3")
        self.app = app_module.create_app(
            {
                "TESTING": True,
                "DATABASE_PATH": self.db_path,
                "SECRET_KEY": "test-secret-key",
                "DIFY_API_KEY": "test-key",
                "DIFY_API_BASE_URL": "https://dify.example.test/v1",
                "DIFY_USER_ID": "test-user-001",
                "MAX_DOCUMENT_CONTENT": 200000,
                "INITIAL_ADMIN_USERNAME": "admin",
                "INITIAL_ADMIN_PASSWORD": "AdminPass123!",
                "INITIAL_ADMIN_DISPLAY_NAME": "系统管理员",
                "INITIAL_ADMIN_LEGACY": False,
            }
        )
        self.repo = self.app.extensions["document_repo"]
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
        self.users.create_user(
            username="admin2",
            display_name="第二管理员",
            password="Admin2Pass123!",
            role="admin",
        )
        self.admin = self.login("admin", "AdminPass123!")
        self.admin2 = self.login("admin2", "Admin2Pass123!")
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
        self.assertEqual(response.status_code, 302, f"{username} 登录失败：{response.get_data(as_text=True)[:300]}")
        return client

    @staticmethod
    def csrf(client) -> str:
        with client.session_transaction() as session:
            return session["csrf_token"]

    def post(self, client, path: str, data: dict | None = None):
        payload = dict(data or {})
        payload["csrf_token"] = self.csrf(client)
        return client.post(path, data=payload, follow_redirects=True)

    def create_document(self, client, *, with_dify: bool = True, title: str = "CBS 与 TDH 数据一致性排查手册"):
        response = self.post(
            client,
            "/admin/documents/new",
            {
                "title": title,
                "category": "数据同步",
                "owner": "运维一组",
                "description": "用于测试的模拟运维文档。",
                "dify_dataset_id": DATASET_ID if with_dify else "",
                "dify_document_id": DIFY_DOCUMENT_ID if with_dify else "",
                "update_reason": "初始版本：补充排查步骤",
                "content": "## 排查步骤\n\n1. 核对统计口径\n2. 检查同步任务\n3. 对比增量日志",
            },
        )
        self.assertEqual(response.status_code, 200)
        document = self.repo.list_documents(title)[0]
        version = self.repo.get_latest_version(int(document["id"]))
        return document, version

    def submit(self, client, version_id: int):
        return self.post(client, f"/admin/versions/{version_id}/submit")

    def review(self, client, version_id: int, decision: str = "approved", comment: str = "审核通过"):
        return self.post(
            client,
            f"/admin/versions/{version_id}/review",
            {"decision": decision, "review_comment": comment},
        )

    def sync(self, client, version_id: int, index_status: str = "success"):
        return self.post(
            client,
            f"/admin/versions/{version_id}/sync",
            {"dify_sync_note": "2026-11-06 在 Dify 替换并核对索引", "dify_index_status": index_status},
        )

    def rag(self, client, version_id: int, result: str = "passed"):
        return self.post(
            client,
            f"/admin/versions/{version_id}/rag",
            {
                "rag_test_query": "CBS 与 TDH 数量不一致时先查什么？",
                "rag_result": result,
                "rag_test_note": "回答引用了更新后的排查步骤",
            },
        )

    def publish(self, client, version_id: int):
        return self.post(client, f"/admin/versions/{version_id}/publish")

    # ---------- 权限边界 ----------

    def test_unauthenticated_admin_is_redirected(self) -> None:
        client = self.app.test_client()
        response = client.get("/admin/documents")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

    def test_employee_cannot_access_admin_or_publish(self) -> None:
        document, version = self.create_document(self.operator)
        self.assertEqual(self.employee.get("/admin/documents").status_code, 403)
        self.assertEqual(self.employee.get("/admin/users").status_code, 403)
        self.assertEqual(self.employee.get("/admin/feedback").status_code, 403)
        publish = self.employee.post(
            f"/admin/versions/{version['id']}/publish",
            data={"csrf_token": self.csrf(self.employee)},
        )
        self.assertEqual(publish.status_code, 403)
        self.assertEqual(self.repo.get_version(int(version["id"]))["publish_status"], "unpublished")

    def test_operator_can_create_and_submit_but_cannot_review_or_publish(self) -> None:
        document, version = self.create_document(self.operator)
        self.assertEqual(document["latest_review_status"], "draft")
        self.assertEqual(self.operator.get("/admin/documents").status_code, 200)
        self.submit(self.operator, int(version["id"]))
        self.assertEqual(self.repo.get_version(int(version["id"]))["review_status"], "pending")

        review = self.operator.post(
            f"/admin/versions/{version['id']}/review",
            data={"decision": "approved", "csrf_token": self.csrf(self.operator)},
        )
        self.assertEqual(review.status_code, 403)
        self.publish(self.operator, int(version["id"]))
        self.assertEqual(self.repo.get_version(int(version["id"]))["publish_status"], "unpublished")

    def test_admin_can_review_but_cannot_review_own_submission(self) -> None:
        document, version = self.create_document(self.admin, with_dify=False)
        self.submit(self.admin, int(version["id"]))
        self.review(self.admin, int(version["id"]))
        self.assertEqual(self.repo.get_version(int(version["id"]))["review_status"], "pending")
        self.review(self.admin2, int(version["id"]))
        self.assertEqual(self.repo.get_version(int(version["id"]))["review_status"], "approved")

    def test_publish_requires_sync_index_and_rag_for_dify_document(self) -> None:
        document, version = self.create_document(self.operator)
        version_id = int(version["id"])
        self.submit(self.operator, version_id)
        self.review(self.admin, version_id)

        # 只有审核通过，不能直接发布。
        self.publish(self.admin, version_id)
        self.assertEqual(self.repo.get_version(version_id)["publish_status"], "unpublished")

        self.sync(self.operator, version_id, "failed")
        self.publish(self.admin, version_id)
        self.assertEqual(self.repo.get_version(version_id)["publish_status"], "unpublished")

        self.sync(self.operator, version_id, "success")
        self.publish(self.admin, version_id)
        self.assertEqual(self.repo.get_version(version_id)["publish_status"], "unpublished")

        self.rag(self.operator, version_id)
        self.publish(self.admin, version_id)
        self.assertEqual(self.repo.get_version(version_id)["publish_status"], "published")

    def test_full_archive_flow(self) -> None:
        document, v1 = self.create_document(self.operator)
        doc_id = int(document["id"])
        v1_id = int(v1["id"])
        self.submit(self.operator, v1_id)
        self.review(self.admin, v1_id)
        self.sync(self.operator, v1_id)
        self.rag(self.operator, v1_id)
        self.publish(self.admin, v1_id)

        new_version = self.post(
            self.operator,
            f"/admin/documents/{doc_id}/versions/new",
            {
                "update_reason": "补充回滚步骤",
                "content": "## 排查步骤\n\n1. 核对统计口径\n2. 检查同步任务\n3. 回滚",
            },
        )
        self.assertEqual(new_version.status_code, 200)
        versions = self.repo.list_versions(doc_id)
        v2_id = int(versions[0]["id"])
        self.submit(self.operator, v2_id)
        self.review(self.admin, v2_id)
        self.sync(self.operator, v2_id)
        self.rag(self.operator, v2_id)
        self.publish(self.admin, v2_id)

        self.assertEqual(self.repo.get_version(v1_id)["publish_status"], "archived")
        self.assertEqual(self.repo.get_version(v2_id)["publish_status"], "published")
        self.assertEqual(int(self.repo.get_document(doc_id)["published_version_id"]), v2_id)

    def test_no_dify_document_can_publish_after_admin_review(self) -> None:
        _, version = self.create_document(self.operator, with_dify=False)
        version_id = int(version["id"])
        self.submit(self.operator, version_id)
        self.review(self.admin, version_id)
        self.publish(self.admin, version_id)
        result = self.repo.get_version(version_id)
        self.assertEqual(result["publish_status"], "published")
        self.assertEqual(result["rag_status"], "not_required")

    # ---------- 草稿、拒审、下载 ----------

    def test_reject_requires_comment_and_operator_can_edit_draft(self) -> None:
        _, version = self.create_document(self.operator, with_dify=False)
        version_id = int(version["id"])
        self.submit(self.operator, version_id)
        self.review(self.admin, version_id, decision="rejected", comment="")
        self.assertEqual(self.repo.get_version(version_id)["review_status"], "pending")

        self.review(self.admin, version_id, decision="rejected", comment="补充回滚步骤")
        self.assertEqual(self.repo.get_version(version_id)["review_status"], "rejected")

        edit_form = self.operator.get(f"/admin/versions/{version_id}/edit")
        self.assertEqual(edit_form.status_code, 200)
        self.assertIn("编辑草稿 v", edit_form.get_data(as_text=True))

        edit = self.post(
            self.operator,
            f"/admin/versions/{version_id}/edit",
            {
                "update_reason": "根据审核意见补充回滚",
                "content": "## 排查步骤\n\n1. 核对\n2. 回滚",
            },
        )
        self.assertEqual(edit.status_code, 200)
        updated = self.repo.get_version(version_id)
        self.assertIn("根据审核意见", updated["update_reason"])
        self.assertEqual(updated["review_status"], "rejected")

        self.submit(self.operator, version_id)
        self.review(self.admin, version_id)
        self.assertEqual(self.repo.get_version(version_id)["review_status"], "approved")

    def test_download_markdown(self) -> None:
        _, version = self.create_document(self.operator)
        response = self.operator.get(f"/admin/versions/{version['id']}/download")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "text/markdown")
        self.assertIn("核对统计口径", response.data.decode("utf-8"))

    def test_edit_metadata_and_search(self) -> None:
        document, _ = self.create_document(self.operator, title="原始标题")
        response = self.post(
            self.operator,
            f"/admin/documents/{document['id']}/edit",
            {
                "title": "更新后的标题",
                "category": "数据库",
                "owner": "运维二组",
                "description": "新的说明",
                "dify_dataset_id": DATASET_ID,
                "dify_document_id": DIFY_DOCUMENT_ID,
            },
        )
        self.assertEqual(response.status_code, 200)
        updated = self.repo.get_document(int(document["id"]))
        self.assertEqual(updated["title"], "更新后的标题")
        found = self.operator.get("/admin/documents?q=更新后")
        self.assertIn("更新后的标题", found.get_data(as_text=True))

    def test_csrf_required_for_admin_post(self) -> None:
        response = self.admin.post(
            "/admin/documents/new",
            data={"title": "无 CSRF"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.repo.stats()["documents"], 0)

    def test_invalid_version_document_pair(self) -> None:
        doc_a, _ = self.create_document(self.operator, title="文档 A")
        _, version_b = self.create_document(self.operator, title="文档 B")
        response = self.admin.get(
            f"/admin/documents/{doc_a['id']}?version={version_b['id']}"
        )
        self.assertEqual(response.status_code, 404)

    def test_password_not_rendered_in_admin(self) -> None:
        body = self.admin.get("/admin/users").get_data(as_text=True)
        self.assertNotIn("AdminPass123!", body)
        self.assertIn("用户管理", body)

    def test_permission_controls_are_hidden_in_frontend(self) -> None:
        document, version = self.create_document(self.operator)
        version_id = int(version["id"])
        self.submit(self.operator, version_id)
        self.review(self.admin, version_id)
        self.sync(self.operator, version_id)
        self.rag(self.operator, version_id)

        operator_body = self.operator.get(
            f"/admin/documents/{document['id']}?version={version_id}"
        ).get_data(as_text=True)
        admin_body = self.admin.get(
            f"/admin/documents/{document['id']}?version={version_id}"
        ).get_data(as_text=True)
        self.assertNotIn("发布此版本", operator_body)
        self.assertIn("等待管理员发布", operator_body)
        self.assertIn("发布此版本", admin_body)

        employee_chat = self.employee.get("/").get_data(as_text=True)
        admin_chat = self.admin.get("/").get_data(as_text=True)
        self.assertNotIn("管理后台", employee_chat)
        self.assertIn("管理后台", admin_chat)


if __name__ == "__main__":
    unittest.main()
