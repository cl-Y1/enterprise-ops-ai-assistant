"""文档版本管理后台测试。

覆盖：
- Basic Auth、后台禁用、CSRF；
- 文档与版本创建；
- 审核通过/驳回；
- Dify 同步前置条件；
- 发布与旧版本自动归档；
- 历史内容下载、搜索、编辑。
"""

from __future__ import annotations

import base64
import shutil
import unittest
import uuid
from pathlib import Path

import app as app_module

DATASET_ID = "11111111-1111-4111-8111-111111111111"
DIFY_DOCUMENT_ID = "22222222-2222-4222-8222-222222222222"


class DocumentAdminTestCase(unittest.TestCase):
    def setUp(self) -> None:
        # 不使用系统 tempfile：当前 Windows 受限环境会创建不可再次写入的 0700 目录。
        self.tmpdir = Path(__file__).resolve().parent.parent / ".test-tmp" / uuid.uuid4().hex
        self.tmpdir.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, self.tmpdir, ignore_errors=True)
        self.db_path = str(self.tmpdir / "test.sqlite3")
        self.app = app_module.create_app(
            {
                "TESTING": True,
                "DATABASE_PATH": self.db_path,
                "ADMIN_USERNAME": "admin",
                "ADMIN_PASSWORD": "test-password",
                "SECRET_KEY": "test-secret-key",
                "DIFY_API_KEY": "test-key",
                "DIFY_API_BASE_URL": "https://dify.example.test/v1",
                "DIFY_USER_ID": "test-user-001",
                "MAX_DOCUMENT_CONTENT": 200000,
            }
        )
        self.client = self.app.test_client()
        self.repo = self.app.extensions["document_repo"]
        credentials = base64.b64encode(b"admin:test-password").decode("ascii")
        self.auth = {"Authorization": f"Basic {credentials}"}

    def tearDown(self) -> None:
        # 实际清理由 addCleanup 完成；保留方法便于后续扩展断言。
        pass

    def csrf_token(self) -> str:
        response = self.client.get("/admin/documents", headers=self.auth)
        self.assertEqual(response.status_code, 200)
        with self.client.session_transaction() as session:
            return session["csrf_token"]

    def post(self, path: str, data: dict | None = None, *, follow_redirects: bool = False):
        payload = dict(data or {})
        payload["csrf_token"] = self.csrf_token()
        return self.client.post(
            path,
            data=payload,
            headers=self.auth,
            follow_redirects=follow_redirects,
        )

    def create_document(self, *, with_dify: bool = True, title: str = "CBS 与 TDH 数据一致性排查手册"):
        payload = {
            "title": title,
            "category": "数据同步",
            "owner": "运维一组",
            "description": "用于测试的模拟运维文档。",
            "dify_dataset_id": DATASET_ID if with_dify else "",
            "dify_document_id": DIFY_DOCUMENT_ID if with_dify else "",
            "update_reason": "初始版本：补充排查步骤",
            "content": "## 排查步骤\n\n1. 核对统计口径\n2. 检查同步任务\n3. 对比增量日志",
        }
        response = self.post("/admin/documents/new", payload)
        self.assertEqual(response.status_code, 302)
        document = self.repo.list_documents()[0]
        version = self.repo.get_latest_version(int(document["id"]))
        return document, version

    def submit(self, version_id: int):
        return self.post(f"/admin/versions/{version_id}/submit")

    def approve(self, version_id: int, comment: str = "内容确认"):
        return self.post(
            f"/admin/versions/{version_id}/review",
            {"decision": "approved", "review_comment": comment},
        )

    def sync(self, version_id: int, note: str = "2026-11-06 在 Dify 替换并完成索引"):
        return self.post(
            f"/admin/versions/{version_id}/sync",
            {"dify_sync_note": note},
        )

    def publish(self, version_id: int):
        return self.post(f"/admin/versions/{version_id}/publish")

    # ---------- 认证与安全 ----------

    def test_admin_requires_basic_auth(self) -> None:
        response = self.client.get("/admin/documents")
        self.assertEqual(response.status_code, 401)
        self.assertIn("WWW-Authenticate", response.headers)
        self.assertIn("需要管理员登录", response.get_data(as_text=True))

    def test_admin_rejects_wrong_password(self) -> None:
        credentials = base64.b64encode(b"admin:wrong").decode("ascii")
        response = self.client.get(
            "/admin/documents",
            headers={"Authorization": f"Basic {credentials}"},
        )
        self.assertEqual(response.status_code, 401)

    def test_admin_disabled_without_password(self) -> None:
        app = app_module.create_app(
            {
                "TESTING": True,
                "DATABASE_PATH": str(self.tmpdir / "disabled.sqlite3"),
                "ADMIN_PASSWORD": "",
                "SECRET_KEY": "test-secret",
            }
        )
        response = app.test_client().get("/admin/documents")
        self.assertEqual(response.status_code, 503)
        body = response.get_data(as_text=True)
        self.assertIn("管理后台尚未启用", body)
        self.assertNotIn("ADMIN_PASSWORD=", body)

    def test_post_without_csrf_is_rejected(self) -> None:
        response = self.client.post(
            "/admin/documents/new",
            data={"title": "无 CSRF"},
            headers=self.auth,
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.repo.stats()["documents"], 0)

    def test_password_not_rendered_in_admin_page(self) -> None:
        response = self.client.get("/admin/documents", headers=self.auth)
        body = response.get_data(as_text=True)
        self.assertNotIn("test-password", body)
        self.assertIn("文档版本管理", body)

    # ---------- 创建与详情 ----------

    def test_create_document_and_initial_version(self) -> None:
        new_form = self.client.get("/admin/documents/new", headers=self.auth)
        self.assertEqual(new_form.status_code, 200)
        self.assertIn("初始版本 v1", new_form.get_data(as_text=True))

        document, version = self.create_document()
        self.assertEqual(document["title"], "CBS 与 TDH 数据一致性排查手册")
        self.assertEqual(version["version_no"], 1)
        self.assertEqual(version["review_status"], "draft")
        self.assertEqual(version["publish_status"], "unpublished")
        self.assertEqual(version["updated_by"], "admin")
        self.assertEqual(len(version["content_sha256"]), 64)
        events = self.repo.get_events(int(version["id"]))
        self.assertEqual(events[0]["action"], "created")

        detail = self.client.get(
            f"/admin/documents/{document['id']}",
            headers=self.auth,
        )
        self.assertEqual(detail.status_code, 200)
        self.assertIn("排查步骤", detail.get_data(as_text=True))
        self.assertIn("草稿", detail.get_data(as_text=True))

    def test_dify_ids_must_be_paired(self) -> None:
        response = self.post(
            "/admin/documents/new",
            {
                "title": "不完整关联",
                "dify_dataset_id": DATASET_ID,
                "dify_document_id": "",
                "update_reason": "测试",
                "content": "内容",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("同时填写", response.get_data(as_text=True))
        self.assertEqual(self.repo.stats()["documents"], 0)

    def test_edit_document_metadata(self) -> None:
        document, _ = self.create_document()
        edit_form = self.client.get(
            f"/admin/documents/{document['id']}/edit",
            headers=self.auth,
        )
        self.assertEqual(edit_form.status_code, 200)
        self.assertIn("编辑文档信息", edit_form.get_data(as_text=True))

        response = self.post(
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
        self.assertEqual(response.status_code, 302)
        updated = self.repo.get_document(int(document["id"]))
        self.assertEqual(updated["title"], "更新后的标题")
        self.assertEqual(updated["owner"], "运维二组")

    def test_search_documents(self) -> None:
        self.create_document(title="CBS 数据同步手册")
        self.create_document(title="磁盘告警处理", with_dify=False)
        response = self.client.get("/admin/documents?q=磁盘", headers=self.auth)
        body = response.get_data(as_text=True)
        self.assertIn("磁盘告警处理", body)
        self.assertNotIn("CBS 数据同步手册", body)

    # ---------- 审核、同步、发布 ----------

    def test_full_review_sync_publish_and_archive_flow(self) -> None:
        document, v1 = self.create_document(with_dify=True)
        doc_id = int(document["id"])
        v1_id = int(v1["id"])

        self.submit(v1_id)
        self.assertEqual(self.repo.get_version(v1_id)["review_status"], "pending")

        self.approve(v1_id, "审核通过，可以更新 Dify")
        self.assertEqual(self.repo.get_version(v1_id)["review_status"], "approved")

        # 关联了 Dify 但尚未登记同步，不能发布。
        blocked = self.publish(v1_id)
        self.assertEqual(blocked.status_code, 302)
        self.assertEqual(self.repo.get_version(v1_id)["publish_status"], "unpublished")
        blocked_page = self.client.get(
            f"/admin/documents/{doc_id}?version={v1_id}",
            headers=self.auth,
        )
        self.assertIn("等待 Dify 同步", blocked_page.get_data(as_text=True))

        self.sync(v1_id)
        synced = self.repo.get_version(v1_id)
        self.assertEqual(synced["dify_sync_status"], "synced")
        self.assertEqual(synced["dify_synced_by"], "admin")

        self.publish(v1_id)
        published = self.repo.get_version(v1_id)
        self.assertEqual(published["publish_status"], "published")
        self.assertIsNotNone(published["published_at"])
        self.assertEqual(
            int(self.repo.get_document(doc_id)["published_version_id"]),
            v1_id,
        )

        # 创建 v2，走完整流程，v1 应自动归档。
        response = self.post(
            f"/admin/documents/{doc_id}/versions/new",
            {
                "update_reason": "补充回滚步骤",
                "content": "## 排查步骤\n\n1. 核对统计口径\n2. 检查同步任务\n3. 对比增量日志\n4. 回滚",
            },
        )
        self.assertEqual(response.status_code, 302)
        versions = self.repo.list_versions(doc_id)
        self.assertEqual(len(versions), 2)
        v2 = versions[0]
        v2_id = int(v2["id"])
        self.assertEqual(v2["version_no"], 2)

        self.submit(v2_id)
        self.approve(v2_id)
        self.sync(v2_id)
        self.publish(v2_id)

        old = self.repo.get_version(v1_id)
        new = self.repo.get_version(v2_id)
        self.assertEqual(old["publish_status"], "archived")
        self.assertEqual(new["publish_status"], "published")
        self.assertEqual(int(self.repo.get_document(doc_id)["published_version_id"]), v2_id)
        old_events = self.repo.get_events(v1_id)
        self.assertIn("archived", [event["action"] for event in old_events])

    def test_publish_without_dify_after_approval(self) -> None:
        _, version = self.create_document(with_dify=False)
        version_id = int(version["id"])
        self.submit(version_id)
        self.approve(version_id)
        self.publish(version_id)
        result = self.repo.get_version(version_id)
        self.assertEqual(result["publish_status"], "published")
        self.assertEqual(result["dify_sync_status"], "not_required")

    def test_reject_requires_comment_and_allows_resubmit(self) -> None:
        _, version = self.create_document(with_dify=False)
        version_id = int(version["id"])
        self.submit(version_id)

        rejected_without_comment = self.post(
            f"/admin/versions/{version_id}/review",
            {"decision": "rejected", "review_comment": ""},
        )
        self.assertEqual(rejected_without_comment.status_code, 302)
        self.assertEqual(self.repo.get_version(version_id)["review_status"], "pending")

        self.post(
            f"/admin/versions/{version_id}/review",
            {"decision": "rejected", "review_comment": "补充回滚步骤"},
        )
        rejected = self.repo.get_version(version_id)
        self.assertEqual(rejected["review_status"], "rejected")
        self.assertEqual(rejected["review_comment"], "补充回滚步骤")

        self.submit(version_id)
        self.assertEqual(self.repo.get_version(version_id)["review_status"], "pending")

    # ---------- 下载与边界 ----------

    def test_download_version_markdown(self) -> None:
        document, version = self.create_document()
        version_form = self.client.get(
            f"/admin/documents/{document['id']}/versions/new",
            headers=self.auth,
        )
        self.assertEqual(version_form.status_code, 200)
        self.assertIn("新增版本", version_form.get_data(as_text=True))
        self.assertIn("检查同步任务", version_form.get_data(as_text=True))

        response = self.client.get(
            f"/admin/versions/{version['id']}/download",
            headers=self.auth,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response.headers["Content-Disposition"])
        body = response.data.decode("utf-8")
        self.assertIn("核对统计口径", body)
        self.assertEqual(response.mimetype, "text/markdown")

    def test_invalid_version_for_document_returns_404(self) -> None:
        doc_a, _ = self.create_document(title="文档 A")
        _, version_b = self.create_document(title="文档 B")
        response = self.client.get(
            f"/admin/documents/{doc_a['id']}?version={version_b['id']}",
            headers=self.auth,
        )
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
