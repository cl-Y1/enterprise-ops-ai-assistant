"""本地反馈记录镜像。

Dify 仍然是反馈的权威来源；这里额外保存一份轻量记录，供运维人员和管理员在
角色权限后台上查看。写入失败不会影响已经成功的 Dify 反馈提交。
"""

from __future__ import annotations

import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def init_feedback_db(db_path: str) -> None:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as connection:
        connection.executescript(
            """
            PRAGMA foreign_keys = ON;

            CREATE TABLE IF NOT EXISTS feedback_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id TEXT NOT NULL UNIQUE,
                dify_user TEXT NOT NULL,
                rating TEXT NOT NULL CHECK (rating IN ('like', 'dislike')),
                reason TEXT NOT NULL DEFAULT '',
                comment TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL DEFAULT '',
                actor_user_id INTEGER,
                actor_username TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_feedback_created
                ON feedback_records(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_feedback_rating
                ON feedback_records(rating);
            """
        )
        connection.commit()


class FeedbackRecordRepository:
    def __init__(self, db_path: str) -> None:
        self.db_path = str(db_path)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
        finally:
            connection.close()

    def record(
        self,
        *,
        message_id: str,
        dify_user: str,
        rating: str,
        reason: str = "",
        comment: str = "",
        content: str = "",
        actor_user_id: int | None = None,
        actor_username: str = "",
    ) -> None:
        with self._connect() as connection:
            with connection:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO feedback_records
                        (message_id, dify_user, rating, reason, comment, content,
                         actor_user_id, actor_username, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        message_id,
                        dify_user,
                        rating,
                        reason,
                        comment,
                        content,
                        actor_user_id,
                        actor_username,
                        now_text(),
                    ),
                )

    def list_records(self, *, search: str = "", rating: str = "", limit: int = 200) -> list[dict[str, Any]]:
        conditions = []
        params: list[Any] = []
        if search:
            pattern = f"%{search}%"
            conditions.append(
                "(message_id LIKE ? OR reason LIKE ? OR comment LIKE ? OR actor_username LIKE ?)"
            )
            params.extend([pattern, pattern, pattern, pattern])
        if rating in {"like", "dislike"}:
            conditions.append("rating = ?")
            params.append(rating)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(max(1, min(limit, 500)))
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM feedback_records {where} ORDER BY id DESC LIMIT ?",
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def stats(self) -> dict[str, int]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT rating, COUNT(*) AS count FROM feedback_records GROUP BY rating"
            ).fetchall()
        counts = {"like": 0, "dislike": 0}
        for row in rows:
            counts[row["rating"]] = int(row["count"])
        counts["total"] = counts["like"] + counts["dislike"]
        return counts
