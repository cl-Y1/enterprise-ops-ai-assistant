"""用户认证、角色权限、CSRF 与操作审计。

角色：
- employee：问答与反馈
- operator：普通员工 + 文档运维工作流
- admin：全部权限
"""

from __future__ import annotations

import hmac
import re
import secrets
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Iterator

from flask import (
    Blueprint,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
MIN_PASSWORD_LENGTH = 8

ROLE_LABELS = {
    "employee": "普通员工",
    "operator": "运维人员",
    "admin": "管理员",
}

ROLE_DESCRIPTIONS = {
    "employee": "使用知识问答，提交点赞、点踩和文字反馈。",
    "operator": "维护文档版本、Dify 同步与 RAG 验证，不能审核或发布。",
    "admin": "管理用户与角色，审核、发布文档并查看全部日志。",
}

ROLE_PERMISSIONS: dict[str, set[str]] = {
    "employee": {
        "chat.use",
        "feedback.submit",
    },
    "operator": {
        "chat.use",
        "feedback.submit",
        "feedback.view",
        "admin.access",
        "documents.view",
        "documents.create",
        "documents.edit",
        "documents.submit",
        "documents.download",
        "documents.sync",
        "documents.dify",
        "documents.rag",
    },
    "admin": {
        "chat.use",
        "feedback.submit",
        "feedback.view",
        "admin.access",
        "documents.view",
        "documents.create",
        "documents.edit",
        "documents.submit",
        "documents.download",
        "documents.sync",
        "documents.dify",
        "documents.rag",
        "documents.review",
        "documents.publish",
        "documents.history",
        "users.manage",
        "roles.view",
        "audit.view",
    },
}

PERMISSION_CATALOG = [
    ("chat.use", "使用 AI 知识问答", "问答与反馈"),
    ("feedback.submit", "点赞、点踩并提交文字反馈", "问答与反馈"),
    ("feedback.view", "查看反馈记录", "问答与反馈"),
    ("admin.access", "进入运维管理后台", "后台"),
    ("documents.view", "查看文档与历史版本", "文档管理"),
    ("documents.create", "创建文档和版本", "文档管理"),
    ("documents.edit", "编辑文档信息/草稿", "文档管理"),
    ("documents.submit", "提交文档审核", "文档管理"),
    ("documents.download", "下载/复制 Markdown", "文档管理"),
    ("documents.sync", "登记 Dify 同步与索引状态", "文档管理"),
    ("documents.dify", "维护 Dify 数据集/文档 ID", "文档管理"),
    ("documents.rag", "执行并登记 RAG 验证", "文档管理"),
    ("documents.review", "审核或驳回文档", "文档管理"),
    ("documents.publish", "发布版本并归档旧版本", "文档管理"),
    ("documents.history", "管理全部历史版本", "文档管理"),
    ("users.manage", "新建用户、分配角色、重置密码", "系统管理"),
    ("roles.view", "查看角色权限矩阵", "系统管理"),
    ("audit.view", "查看操作日志", "系统管理"),
]

AUDIT_ACTION_LABELS = {
    "login_success": "登录成功",
    "login_failed": "登录失败",
    "logout": "退出登录",
    "user_created": "创建用户",
    "user_updated": "更新用户",
    "password_reset": "重置密码",
    "document_created": "创建文档",
    "document_updated": "更新文档信息",
    "version_created": "新增版本",
    "version_edited": "编辑草稿",
    "version_submitted": "提交审核",
    "version_reviewed": "审核版本",
    "dify_synced": "登记 Dify 同步",
    "rag_verified": "登记 RAG 验证",
    "version_published": "发布版本",
}


class AuthError(Exception):
    """认证或用户管理业务异常。"""


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def init_auth_db(db_path: str) -> None:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as connection:
        connection.executescript(
            """
            PRAGMA foreign_keys = ON;

            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                display_name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('employee', 'operator', 'admin')),
                is_active INTEGER NOT NULL DEFAULT 1,
                session_version INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_login_at TEXT
            );

            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                actor_id INTEGER,
                actor_username TEXT NOT NULL DEFAULT '',
                action TEXT NOT NULL,
                target_type TEXT NOT NULL DEFAULT '',
                target_id TEXT NOT NULL DEFAULT '',
                result TEXT NOT NULL DEFAULT 'success',
                detail TEXT NOT NULL DEFAULT '',
                ip TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_logs(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_logs(action);
            """
        )
        connection.commit()


class UserRepository:
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
    def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row is not None else None

    def count_users(self) -> int:
        with self._connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0])

    def count_active_admins(self) -> int:
        with self._connect() as connection:
            return int(
                connection.execute(
                    "SELECT COUNT(*) FROM users WHERE role = 'admin' AND is_active = 1"
                ).fetchone()[0]
            )

    def get_by_id(self, user_id: int) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return self._row_to_dict(row)

    def get_by_username(self, username: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE username = ? COLLATE NOCASE",
                (username,),
            ).fetchone()
        return self._row_to_dict(row)

    def list_users(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM users ORDER BY role ASC, username ASC"
            ).fetchall()
        return [dict(row) for row in rows]

    def create_user(
        self,
        *,
        username: str,
        display_name: str,
        password: str,
        role: str,
        is_active: bool = True,
        enforce_password_policy: bool = True,
    ) -> int:
        username = username.strip()
        display_name = display_name.strip()
        if not USERNAME_PATTERN.fullmatch(username):
            raise AuthError("账号需为 3–32 位，只允许字母、数字、点、下划线和短横线。")
        if not display_name:
            raise AuthError("请填写显示名称。")
        if len(display_name) > 50:
            raise AuthError("显示名称不能超过 50 个字符。")
        if role not in ROLE_LABELS:
            raise AuthError("角色无效。")
        if enforce_password_policy and len(password) < MIN_PASSWORD_LENGTH:
            raise AuthError(f"密码至少需要 {MIN_PASSWORD_LENGTH} 个字符。")
        if not password:
            raise AuthError("密码不能为空。")
        now = now_text()
        password_hash = generate_password_hash(password, method="scrypt")
        try:
            with self._connect() as connection:
                with connection:
                    cursor = connection.execute(
                        """
                        INSERT INTO users
                            (username, display_name, password_hash, role, is_active,
                             session_version, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                        """,
                        (username, display_name, password_hash, role, int(is_active), now, now),
                    )
                    return int(cursor.lastrowid)
        except sqlite3.IntegrityError as exc:
            raise AuthError("该账号已存在。") from exc

    def verify_password(self, user: dict[str, Any], password: str) -> bool:
        return check_password_hash(user["password_hash"], password)

    def record_login(self, user_id: int) -> None:
        with self._connect() as connection:
            with connection:
                connection.execute(
                    "UPDATE users SET last_login_at = ?, updated_at = ? WHERE id = ?",
                    (now_text(), now_text(), user_id),
                )

    def update_user(
        self,
        user_id: int,
        *,
        display_name: str,
        role: str,
        is_active: bool,
    ) -> None:
        user = self.get_by_id(user_id)
        if user is None:
            raise AuthError("用户不存在。")
        display_name = display_name.strip()
        if not display_name:
            raise AuthError("请填写显示名称。")
        if len(display_name) > 50:
            raise AuthError("显示名称不能超过 50 个字符。")
        if role not in ROLE_LABELS:
            raise AuthError("角色无效。")

        removing_admin = user["role"] == "admin" and user["is_active"] == 1 and (
            role != "admin" or not is_active
        )
        if removing_admin and self.count_active_admins() <= 1:
            raise AuthError("必须保留至少一个启用状态的管理员。")

        now = now_text()
        invalidate = role != user["role"] or int(is_active) != int(user["is_active"])
        with self._connect() as connection:
            with connection:
                connection.execute(
                    """
                    UPDATE users
                    SET display_name = ?, role = ?, is_active = ?, updated_at = ?,
                        session_version = session_version + ?
                    WHERE id = ?
                    """,
                    (display_name, role, int(is_active), now, 1 if invalidate else 0, user_id),
                )

    def reset_password(self, user_id: int, new_password: str) -> None:
        if len(new_password) < MIN_PASSWORD_LENGTH:
            raise AuthError(f"密码至少需要 {MIN_PASSWORD_LENGTH} 个字符。")
        password_hash = generate_password_hash(new_password, method="scrypt")
        with self._connect() as connection:
            with connection:
                changed = connection.execute(
                    """
                    UPDATE users
                    SET password_hash = ?, session_version = session_version + 1, updated_at = ?
                    WHERE id = ?
                    """,
                    (password_hash, now_text(), user_id),
                ).rowcount
        if not changed:
            raise AuthError("用户不存在。")

    def increment_session_version(self, user_id: int) -> None:
        with self._connect() as connection:
            with connection:
                connection.execute(
                    "UPDATE users SET session_version = session_version + 1 WHERE id = ?",
                    (user_id,),
                )


class AuditRepository:
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

    def log(
        self,
        *,
        actor_id: int | None,
        actor_username: str,
        action: str,
        target_type: str = "",
        target_id: str = "",
        result: str = "success",
        detail: str = "",
        ip: str = "",
    ) -> None:
        with self._connect() as connection:
            with connection:
                connection.execute(
                    """
                    INSERT INTO audit_logs
                        (actor_id, actor_username, action, target_type, target_id,
                         result, detail, ip, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        actor_id,
                        actor_username,
                        action,
                        target_type,
                        str(target_id),
                        result,
                        detail[:1000],
                        ip[:80],
                        now_text(),
                    ),
                )

    def list_logs(
        self,
        *,
        search: str = "",
        action: str = "",
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        conditions = []
        params: list[Any] = []
        if search:
            conditions.append(
                "(actor_username LIKE ? OR target_type LIKE ? OR target_id LIKE ? OR detail LIKE ?)"
            )
            pattern = f"%{search}%"
            params.extend([pattern, pattern, pattern, pattern])
        if action:
            conditions.append("action = ?")
            params.append(action)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(max(1, min(limit, 500)))
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM audit_logs {where} ORDER BY id DESC LIMIT ?",
                params,
            ).fetchall()
        return [dict(row) for row in rows]


def ensure_initial_admin(
    repo: UserRepository,
    *,
    username: str,
    password: str,
    display_name: str,
    allow_legacy_short_password: bool = False,
) -> bool:
    """仅在数据库没有任何用户时创建初始管理员。

    allow_legacy_short_password 只用于从 V1.3 的 ADMIN_PASSWORD 迁移，
    新用户创建仍必须满足最小长度策略。
    """
    if repo.count_users() > 0:
        return False
    if not username or not password:
        return False
    repo.create_user(
        username=username,
        display_name=display_name or "系统管理员",
        password=password,
        role="admin",
        is_active=True,
        enforce_password_policy=not allow_legacy_short_password,
    )
    return True


def has_permission(permission: str, user: dict[str, Any] | None = None) -> bool:
    user = user or g.get("user")
    if not user:
        return False
    return permission in ROLE_PERMISSIONS.get(user.get("role", ""), set())


def role_home(user: dict[str, Any] | None = None) -> str:
    user = user or g.get("user")
    if user and user.get("role") in {"operator", "admin"}:
        return url_for("admin.documents")
    return url_for("index")


def _safe_next(target: str | None) -> str:
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return ""


def validate_csrf() -> bool:
    submitted = request.form.get("csrf_token", "") or request.headers.get("X-CSRF-Token", "")
    expected = session.get("csrf_token", "")
    return bool(expected and submitted and hmac.compare_digest(str(submitted), str(expected)))


def login_required(view: Callable):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not g.get("user"):
            return redirect(url_for("auth.login", next=request.full_path))
        return view(*args, **kwargs)

    return wrapped


def permission_required(permission: str):
    def decorator(view: Callable):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = g.get("user")
            if not user:
                return redirect(url_for("auth.login", next=request.full_path))
            if not has_permission(permission, user):
                return (
                    render_template(
                        "admin/error.html",
                        status=403,
                        title="没有访问权限",
                        message="当前角色不能执行这个操作。",
                    ),
                    403,
                )
            return view(*args, **kwargs)

        return wrapped

    return decorator


auth_bp = Blueprint("auth", __name__)


@auth_bp.get("/login")
def login():
    if g.get("user"):
        return redirect(role_home(g.user))
    return render_template(
        "auth/login.html",
        next_url=_safe_next(request.args.get("next")),
        username="",
        has_users=g.user_repo.count_users() > 0,
    )


@auth_bp.post("/login")
def login_post():
    if g.get("user"):
        return redirect(role_home(g.user))
    if not validate_csrf():
        abort(400, description="表单已过期，请刷新后重试。")

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    next_url = _safe_next(request.form.get("next"))
    users: UserRepository = g.user_repo
    audit: AuditRepository = g.audit_repo

    user = users.get_by_username(username) if username else None
    if user is None or not user["is_active"] or not users.verify_password(user, password):
        audit.log(
            actor_id=None,
            actor_username=username[:64],
            action="login_failed",
            target_type="session",
            result="failed",
            detail="账号或密码错误",
            ip=request.remote_addr or "",
        )
        flash("账号或密码错误，请重试。", "danger")
        return render_template(
            "auth/login.html",
            next_url=next_url,
            username=username,
            has_users=True,
        )

    session.clear()
    session["user_id"] = user["id"]
    session["auth_version"] = user["session_version"]
    session["csrf_token"] = secrets.token_urlsafe(32)
    session.permanent = True
    users.record_login(int(user["id"]))
    audit.log(
        actor_id=int(user["id"]),
        actor_username=user["username"],
        action="login_success",
        target_type="session",
        result="success",
        detail=f"角色：{user['role']}",
        ip=request.remote_addr or "",
    )

    if user["role"] in {"operator", "admin"} and next_url.startswith("/admin"):
        return redirect(next_url)
    return redirect(role_home(user))


@auth_bp.post("/logout")
def logout():
    if not validate_csrf():
        abort(400, description="表单已过期，请刷新后重试。")
    user = g.get("user")
    if user:
        users: UserRepository = g.user_repo
        audit: AuditRepository = g.audit_repo
        users.increment_session_version(int(user["id"]))
        audit.log(
            actor_id=int(user["id"]),
            actor_username=user["username"],
            action="logout",
            target_type="session",
            result="success",
            ip=request.remote_addr or "",
        )
    session.clear()
    flash("已安全退出。", "success")
    return redirect(url_for("auth.login"))
