"""文档版本管理的数据层。

V1.4 使用 SQLite 保存文档、版本、审核/发布/索引/RAG 状态与操作审计。
聊天与点赞/点踩仍由 Dify 原生记录，不进入这个数据库。

状态机：
- 审核：draft -> pending -> approved / rejected
- 发布：unpublished -> published -> archived
- Dify：pending -> synced；索引：pending -> success / failed
- RAG：pending -> passed / failed
"""

from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

REVIEW_LABELS = {
    "draft": "草稿",
    "pending": "待审核",
    "approved": "审核通过",
    "rejected": "已驳回",
}

PUBLISH_LABELS = {
    "unpublished": "未发布",
    "published": "已发布",
    "archived": "已归档",
}

SYNC_LABELS = {
    "pending": "待同步",
    "synced": "已登记同步",
    "not_required": "无需同步",
}

INDEX_LABELS = {
    "pending": "待确认索引",
    "success": "索引成功",
    "failed": "索引失败",
    "not_required": "无需索引",
}

RAG_LABELS = {
    "pending": "待 RAG 验证",
    "passed": "RAG 验证通过",
    "failed": "RAG 验证失败",
    "not_required": "无需验证",
}

EVENT_LABELS = {
    "created": "创建文档",
    "version_created": "新增版本",
    "version_edited": "编辑草稿",
    "submitted": "提交审核",
    "review_approved": "审核通过",
    "review_rejected": "审核驳回",
    "dify_synced": "登记 Dify 同步",
    "rag_verified": "登记 RAG 验证",
    "published": "发布版本",
    "archived": "自动归档",
}

REVIEW_STATUSES = tuple(REVIEW_LABELS)
PUBLISH_STATUSES = tuple(PUBLISH_LABELS)
SYNC_STATUSES = tuple(SYNC_LABELS)
INDEX_STATUSES = tuple(INDEX_LABELS)
RAG_STATUSES = tuple(RAG_LABELS)

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT '',
    owner TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    dify_dataset_id TEXT NOT NULL DEFAULT '',
    dify_document_id TEXT NOT NULL DEFAULT '',
    published_version_id INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS document_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    version_no INTEGER NOT NULL,
    update_reason TEXT NOT NULL,
    updated_by TEXT NOT NULL,
    content TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    review_status TEXT NOT NULL DEFAULT 'draft',
    reviewer TEXT NOT NULL DEFAULT '',
    review_comment TEXT NOT NULL DEFAULT '',
    reviewed_at TEXT,
    submitted_by_user_id INTEGER,
    submitted_by TEXT NOT NULL DEFAULT '',
    submitted_at TEXT,
    publish_status TEXT NOT NULL DEFAULT 'unpublished',
    published_at TEXT,
    dify_sync_status TEXT NOT NULL DEFAULT 'pending',
    dify_sync_note TEXT NOT NULL DEFAULT '',
    dify_synced_by TEXT NOT NULL DEFAULT '',
    dify_synced_at TEXT,
    dify_index_status TEXT NOT NULL DEFAULT 'pending',
    rag_status TEXT NOT NULL DEFAULT 'pending',
    rag_test_query TEXT NOT NULL DEFAULT '',
    rag_test_note TEXT NOT NULL DEFAULT '',
    rag_tested_by TEXT NOT NULL DEFAULT '',
    rag_tested_at TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(document_id, version_no)
);

CREATE TABLE IF NOT EXISTS version_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version_id INTEGER NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
    action TEXT NOT NULL,
    actor TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_versions_document
    ON document_versions(document_id, version_no DESC);
CREATE INDEX IF NOT EXISTS idx_versions_review
    ON document_versions(review_status);
CREATE INDEX IF NOT EXISTS idx_versions_publish
    ON document_versions(publish_status);
CREATE INDEX IF NOT EXISTS idx_events_version
    ON version_events(version_id, id);
"""


class DocumentError(Exception):
    """文档模块的业务异常。"""


class DocumentNotFound(DocumentError):
    """文档或版本不存在。"""


class InvalidTransition(DocumentError):
    """当前状态不允许执行该操作。"""


def now_text() -> str:
    """本地时间，精确到秒，便于在管理页直接展示。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def init_db(db_path: str) -> None:
    """创建数据库和表，并对旧版数据库做增量迁移。可重复执行。"""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as connection:
        connection.row_factory = sqlite3.Row
        connection.executescript(SCHEMA)
        _migrate_schema(connection)
        connection.commit()


def _migrate_schema(connection: sqlite3.Connection) -> None:
    """为已有 V1.3 数据库补充 V1.4 字段，不破坏历史版本。"""
    columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(document_versions)").fetchall()
    }
    additions = {
        "submitted_by_user_id": "INTEGER",
        "submitted_by": "TEXT NOT NULL DEFAULT ''",
        "submitted_at": "TEXT",
        "dify_index_status": "TEXT NOT NULL DEFAULT 'pending'",
        "rag_status": "TEXT NOT NULL DEFAULT 'pending'",
        "rag_test_query": "TEXT NOT NULL DEFAULT ''",
        "rag_test_note": "TEXT NOT NULL DEFAULT ''",
        "rag_tested_by": "TEXT NOT NULL DEFAULT ''",
        "rag_tested_at": "TEXT",
    }
    for column, definition in additions.items():
        if column not in columns:
            connection.execute(
                f"ALTER TABLE document_versions ADD COLUMN {column} {definition}"
            )
    # 未关联 Dify 的旧版本不需要同步/索引/RAG 验证。
    connection.execute(
        """
        UPDATE document_versions
        SET dify_index_status = 'not_required', rag_status = 'not_required'
        WHERE document_id IN (
            SELECT id FROM documents WHERE dify_document_id = ''
        )
          AND dify_index_status = 'pending'
          AND rag_status = 'pending'
        """
    )


class DocumentRepository:
    def __init__(self, db_path: str) -> None:
        self.db_path = str(db_path)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
        finally:
            connection.close()

    @staticmethod
    def _event(connection: sqlite3.Connection, version_id: int, action: str, actor: str, note: str = "") -> None:
        connection.execute(
            "INSERT INTO version_events (version_id, action, actor, note, created_at) VALUES (?, ?, ?, ?, ?)",
            (version_id, action, actor, note, now_text()),
        )

    def stats(self) -> dict[str, int]:
        with self._connect() as connection:
            return {
                "documents": int(connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0]),
                "pending": int(
                    connection.execute(
                        "SELECT COUNT(*) FROM document_versions WHERE review_status = 'pending'"
                    ).fetchone()[0]
                ),
                "published": int(
                    connection.execute(
                        "SELECT COUNT(*) FROM documents WHERE published_version_id IS NOT NULL"
                    ).fetchone()[0]
                ),
                "archived_versions": int(
                    connection.execute(
                        "SELECT COUNT(*) FROM document_versions WHERE publish_status = 'archived'"
                    ).fetchone()[0]
                ),
            }

    def list_documents(self, search: str = "") -> list[sqlite3.Row]:
        search = search.strip()
        pattern = f"%{search}%"
        with self._connect() as connection:
            return connection.execute(
                """
                SELECT
                    d.*,
                    pv.version_no AS published_version_no,
                    lv.id AS latest_version_id,
                    lv.version_no AS latest_version_no,
                    lv.review_status AS latest_review_status,
                    lv.publish_status AS latest_publish_status,
                    lv.updated_by AS latest_updated_by,
                    lv.created_at AS latest_version_created_at,
                    (SELECT COUNT(*) FROM document_versions v WHERE v.document_id = d.id) AS version_count
                FROM documents d
                LEFT JOIN document_versions pv ON pv.id = d.published_version_id
                LEFT JOIN document_versions lv ON lv.id = (
                    SELECT id FROM document_versions
                    WHERE document_id = d.id
                    ORDER BY version_no DESC
                    LIMIT 1
                )
                WHERE d.title LIKE ? OR d.category LIKE ? OR d.owner LIKE ?
                ORDER BY d.updated_at DESC, d.id DESC
                """,
                (pattern, pattern, pattern),
            ).fetchall()

    def get_document(self, document_id: int) -> sqlite3.Row:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    d.*,
                    pv.version_no AS published_version_no,
                    lv.id AS latest_version_id,
                    lv.version_no AS latest_version_no,
                    lv.review_status AS latest_review_status,
                    lv.publish_status AS latest_publish_status,
                    (SELECT COUNT(*) FROM document_versions v WHERE v.document_id = d.id) AS version_count
                FROM documents d
                LEFT JOIN document_versions pv ON pv.id = d.published_version_id
                LEFT JOIN document_versions lv ON lv.id = (
                    SELECT id FROM document_versions
                    WHERE document_id = d.id
                    ORDER BY version_no DESC
                    LIMIT 1
                )
                WHERE d.id = ?
                """,
                (document_id,),
            ).fetchone()
        if row is None:
            raise DocumentNotFound("文档不存在。")
        return row

    def create_document(
        self,
        *,
        title: str,
        category: str,
        owner: str,
        description: str,
        dify_dataset_id: str,
        dify_document_id: str,
        update_reason: str,
        updated_by: str,
        content: str,
    ) -> tuple[int, int]:
        now = now_text()
        sync_status = "pending" if dify_document_id else "not_required"
        verify_status = "pending" if dify_document_id else "not_required"
        with self._connect() as connection:
            with connection:
                cursor = connection.execute(
                    """
                    INSERT INTO documents
                        (title, category, owner, description, dify_dataset_id, dify_document_id, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (title, category, owner, description, dify_dataset_id, dify_document_id, now, now),
                )
                document_id = int(cursor.lastrowid)
                version_cursor = connection.execute(
                    """
                    INSERT INTO document_versions
                        (document_id, version_no, update_reason, updated_by, content, content_sha256,
                         review_status, publish_status, dify_sync_status, dify_index_status,
                         rag_status, created_at)
                    VALUES (?, 1, ?, ?, ?, ?, 'draft', 'unpublished', ?, ?, ?, ?)
                    """,
                    (
                        document_id,
                        update_reason,
                        updated_by,
                        content,
                        content_hash(content),
                        sync_status,
                        verify_status,
                        verify_status,
                        now,
                    ),
                )
                version_id = int(version_cursor.lastrowid)
                self._event(connection, version_id, "created", updated_by, "创建文档及初始版本")
        return document_id, version_id

    def update_document(
        self,
        document_id: int,
        *,
        title: str,
        category: str,
        owner: str,
        description: str,
        dify_dataset_id: str,
        dify_document_id: str,
    ) -> None:
        with self._connect() as connection:
            with connection:
                changed = connection.execute(
                    """
                    UPDATE documents
                    SET title = ?, category = ?, owner = ?, description = ?,
                        dify_dataset_id = ?, dify_document_id = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        title,
                        category,
                        owner,
                        description,
                        dify_dataset_id,
                        dify_document_id,
                        now_text(),
                        document_id,
                    ),
                ).rowcount
        if not changed:
            raise DocumentNotFound("文档不存在。")

    def list_versions(self, document_id: int) -> list[sqlite3.Row]:
        with self._connect() as connection:
            return connection.execute(
                "SELECT * FROM document_versions WHERE document_id = ? ORDER BY version_no DESC",
                (document_id,),
            ).fetchall()

    def get_latest_version(self, document_id: int) -> sqlite3.Row | None:
        with self._connect() as connection:
            return connection.execute(
                "SELECT * FROM document_versions WHERE document_id = ? ORDER BY version_no DESC LIMIT 1",
                (document_id,),
            ).fetchone()

    def get_published_version(self, document_id: int) -> sqlite3.Row | None:
        with self._connect() as connection:
            return connection.execute(
                """
                SELECT v.*
                FROM document_versions v
                JOIN documents d ON d.published_version_id = v.id
                WHERE d.id = ?
                """,
                (document_id,),
            ).fetchone()

    def get_version(self, version_id: int) -> sqlite3.Row:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    v.*,
                    d.title AS document_title,
                    d.category AS document_category,
                    d.owner AS document_owner,
                    d.dify_dataset_id AS document_dify_dataset_id,
                    d.dify_document_id AS document_dify_document_id,
                    d.published_version_id AS document_published_version_id
                FROM document_versions v
                JOIN documents d ON d.id = v.document_id
                WHERE v.id = ?
                """,
                (version_id,),
            ).fetchone()
        if row is None:
            raise DocumentNotFound("版本不存在。")
        return row

    def get_events(self, version_id: int) -> list[sqlite3.Row]:
        with self._connect() as connection:
            return connection.execute(
                "SELECT * FROM version_events WHERE version_id = ? ORDER BY id DESC",
                (version_id,),
            ).fetchall()

    def add_version(
        self,
        document_id: int,
        *,
        update_reason: str,
        updated_by: str,
        content: str,
    ) -> int:
        document = self.get_document(document_id)
        sync_status = "pending" if document["dify_document_id"] else "not_required"
        verify_status = "pending" if document["dify_document_id"] else "not_required"
        now = now_text()
        with self._connect() as connection:
            with connection:
                next_version = int(
                    connection.execute(
                        "SELECT COALESCE(MAX(version_no), 0) + 1 FROM document_versions WHERE document_id = ?",
                        (document_id,),
                    ).fetchone()[0]
                )
                cursor = connection.execute(
                    """
                    INSERT INTO document_versions
                        (document_id, version_no, update_reason, updated_by, content, content_sha256,
                         review_status, publish_status, dify_sync_status, dify_index_status,
                         rag_status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, 'draft', 'unpublished', ?, ?, ?, ?)
                    """,
                    (
                        document_id,
                        next_version,
                        update_reason,
                        updated_by,
                        content,
                        content_hash(content),
                        sync_status,
                        verify_status,
                        verify_status,
                        now,
                    ),
                )
                version_id = int(cursor.lastrowid)
                connection.execute("UPDATE documents SET updated_at = ? WHERE id = ?", (now, document_id))
                self._event(
                    connection,
                    version_id,
                    "version_created",
                    updated_by,
                    f"新增 v{next_version}：{update_reason}",
                )
        return version_id

    def update_draft_version(
        self,
        version_id: int,
        *,
        update_reason: str,
        updated_by: str,
        content: str,
    ) -> int:
        version = self.get_version(version_id)
        if version["review_status"] not in {"draft", "rejected"}:
            raise InvalidTransition("只有草稿或已驳回的版本可以编辑内容。")
        if version["publish_status"] != "unpublished":
            raise InvalidTransition("已发布或已归档的版本不能编辑。")
        now = now_text()
        with self._connect() as connection:
            with connection:
                connection.execute(
                    """
                    UPDATE document_versions
                    SET update_reason = ?, updated_by = ?, content = ?, content_sha256 = ?
                    WHERE id = ?
                    """,
                    (update_reason, updated_by, content, content_hash(content), version_id),
                )
                connection.execute(
                    "UPDATE documents SET updated_at = ? WHERE id = ?",
                    (now, version["document_id"]),
                )
                self._event(connection, version_id, "version_edited", updated_by, update_reason)
        return int(version["document_id"])

    def submit_version(self, version_id: int, actor_id: int | None, actor_name: str) -> int:
        version = self.get_version(version_id)
        if version["review_status"] not in {"draft", "rejected"}:
            raise InvalidTransition("只有草稿或已驳回的版本可以提交审核。")
        if version["publish_status"] != "unpublished":
            raise InvalidTransition("已发布或已归档的版本不能再次提交审核。")
        now = now_text()
        with self._connect() as connection:
            with connection:
                connection.execute(
                    """
                    UPDATE document_versions
                    SET review_status = 'pending', reviewer = '', review_comment = '',
                        reviewed_at = NULL, submitted_by_user_id = ?, submitted_by = ?,
                        submitted_at = ?
                    WHERE id = ?
                    """,
                    (actor_id, actor_name, now, version_id),
                )
                connection.execute(
                    "UPDATE documents SET updated_at = ? WHERE id = ?",
                    (now, version["document_id"]),
                )
                self._event(connection, version_id, "submitted", actor_name, "提交审核")
        return int(version["document_id"])

    def review_version(
        self,
        version_id: int,
        reviewer_id: int | None,
        reviewer_name: str,
        decision: str,
        comment: str,
    ) -> int:
        if decision not in {"approved", "rejected"}:
            raise InvalidTransition("审核结论无效。")
        version = self.get_version(version_id)
        if version["review_status"] != "pending":
            raise InvalidTransition("只有待审核版本可以执行审核。")
        if (
            reviewer_id is not None
            and version["submitted_by_user_id"] is not None
            and int(version["submitted_by_user_id"]) == reviewer_id
        ):
            raise InvalidTransition("不能审核自己提交的版本，请由另一位管理员审核。")
        now = now_text()
        action = "review_approved" if decision == "approved" else "review_rejected"
        with self._connect() as connection:
            with connection:
                connection.execute(
                    """
                    UPDATE document_versions
                    SET review_status = ?, reviewer = ?, review_comment = ?, reviewed_at = ?
                    WHERE id = ?
                    """,
                    (decision, reviewer_name, comment, now, version_id),
                )
                connection.execute(
                    "UPDATE documents SET updated_at = ? WHERE id = ?",
                    (now, version["document_id"]),
                )
                self._event(connection, version_id, action, reviewer_name, comment or "审核完成")
        return int(version["document_id"])

    def record_dify_sync(
        self,
        version_id: int,
        actor: str,
        note: str,
        index_status: str,
    ) -> int:
        version = self.get_version(version_id)
        if not version["document_dify_dataset_id"] or not version["document_dify_document_id"]:
            raise InvalidTransition("该文档尚未关联 Dify 数据集和文档。")
        if version["review_status"] != "approved":
            raise InvalidTransition("只有审核通过的版本可以登记 Dify 同步。")
        if version["publish_status"] != "unpublished":
            raise InvalidTransition("已发布或已归档的版本不能修改同步状态。")
        if not note.strip():
            raise DocumentError("请填写 Dify 同步说明，例如操作时间或批次号。")
        if index_status not in {"success", "failed"}:
            raise DocumentError("请选择 Dify 索引结果。")
        now = now_text()
        with self._connect() as connection:
            with connection:
                connection.execute(
                    """
                    UPDATE document_versions
                    SET dify_sync_status = 'synced', dify_sync_note = ?,
                        dify_synced_by = ?, dify_synced_at = ?,
                        dify_index_status = ?
                    WHERE id = ?
                    """,
                    (note.strip(), actor, now, index_status, version_id),
                )
                connection.execute(
                    "UPDATE documents SET updated_at = ? WHERE id = ?",
                    (now, version["document_id"]),
                )
                self._event(
                    connection,
                    version_id,
                    "dify_synced",
                    actor,
                    f"{note.strip()}；索引：{INDEX_LABELS[index_status]}",
                )
        return int(version["document_id"])

    def record_rag_verification(
        self,
        version_id: int,
        actor: str,
        query: str,
        result: str,
        note: str,
    ) -> int:
        version = self.get_version(version_id)
        if not version["document_dify_document_id"]:
            raise InvalidTransition("只有关联 Dify 的版本需要登记 RAG 验证。")
        if version["review_status"] != "approved":
            raise InvalidTransition("只有审核通过的版本可以登记 RAG 验证。")
        if version["publish_status"] != "unpublished":
            raise InvalidTransition("已发布或已归档的版本不能修改验证结果。")
        if version["dify_sync_status"] != "synced" or version["dify_index_status"] != "success":
            raise InvalidTransition("请先完成 Dify 同步并确认索引成功，再进行 RAG 验证。")
        if not query.strip():
            raise DocumentError("请填写 RAG 验证问题。")
        if result not in {"passed", "failed"}:
            raise DocumentError("请选择 RAG 验证结果。")
        now = now_text()
        with self._connect() as connection:
            with connection:
                connection.execute(
                    """
                    UPDATE document_versions
                    SET rag_status = ?, rag_test_query = ?, rag_test_note = ?,
                        rag_tested_by = ?, rag_tested_at = ?
                    WHERE id = ?
                    """,
                    (result, query.strip(), note.strip(), actor, now, version_id),
                )
                connection.execute(
                    "UPDATE documents SET updated_at = ? WHERE id = ?",
                    (now, version["document_id"]),
                )
                self._event(
                    connection,
                    version_id,
                    "rag_verified",
                    actor,
                    f"{RAG_LABELS[result]}：{query.strip()}",
                )
        return int(version["document_id"])

    def publish_version(self, version_id: int, actor: str) -> int:
        version = self.get_version(version_id)
        if version["review_status"] != "approved":
            raise InvalidTransition("只有审核通过的版本可以发布。")
        if version["publish_status"] == "published":
            raise InvalidTransition("该版本已经发布。")
        if version["publish_status"] == "archived":
            raise InvalidTransition("已归档的历史版本不能重新发布。")

        linked_to_dify = bool(version["document_dify_document_id"])
        if linked_to_dify:
            if version["dify_sync_status"] != "synced":
                raise InvalidTransition("请先在 Dify 更新知识库文档，并登记同步后再发布。")
            if version["dify_index_status"] != "success":
                raise InvalidTransition("Dify 索引尚未成功，不能发布。")
            if version["rag_status"] != "passed":
                raise InvalidTransition("RAG 验证尚未通过，不能发布。")

        now = now_text()
        with self._connect() as connection:
            with connection:
                previous = connection.execute(
                    """
                    SELECT id, version_no FROM document_versions
                    WHERE document_id = ? AND publish_status = 'published' AND id != ?
                    """,
                    (version["document_id"], version_id),
                ).fetchall()
                for old in previous:
                    connection.execute(
                        "UPDATE document_versions SET publish_status = 'archived' WHERE id = ?",
                        (old["id"],),
                    )
                    self._event(
                        connection,
                        int(old["id"]),
                        "archived",
                        actor,
                        f"v{version['version_no']} 发布后自动归档",
                    )
                connection.execute(
                    """
                    UPDATE document_versions
                    SET publish_status = 'published', published_at = ?,
                        dify_sync_status = CASE WHEN ? = 1 THEN dify_sync_status ELSE 'not_required' END,
                        dify_index_status = CASE WHEN ? = 1 THEN dify_index_status ELSE 'not_required' END,
                        rag_status = CASE WHEN ? = 1 THEN rag_status ELSE 'not_required' END
                    WHERE id = ?
                    """,
                    (now, 1 if linked_to_dify else 0, 1 if linked_to_dify else 0, 1 if linked_to_dify else 0, version_id),
                )
                connection.execute(
                    "UPDATE documents SET published_version_id = ?, updated_at = ? WHERE id = ?",
                    (version_id, now, version["document_id"]),
                )
                self._event(connection, version_id, "published", actor, f"发布 v{version['version_no']}")
        return int(version["document_id"])
