"""企业智能运维知识助手 V1.4 —— Flask 后端。

职责：
1. 提供聊天页面；
2. 在服务端安全地调用 Dify Chatflow API；
3. 在服务端调用 Dify 消息反馈 API；
4. 提供文档版本管理后台（SQLite + 管理员认证）；
5. 做输入校验、异常处理和错误信息脱敏。

说明：Dify API Key 只从环境变量读取，绝不会返回给浏览器。
"""

from __future__ import annotations

import os
import secrets
import threading
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

import click
import requests
from dotenv import load_dotenv
from flask import Flask, g, jsonify, render_template, request, session

from admin import admin_bp
from auth import (
    ROLE_LABELS,
    ROLE_PERMISSIONS,
    AuditRepository,
    AuthError,
    UserRepository,
    auth_bp,
    ensure_initial_admin,
    has_permission,
    init_auth_db,
)
from documents import DocumentRepository, init_db
from feedback_store import FeedbackRecordRepository, init_feedback_db

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# 与前端反馈弹窗中的单选项保持一致，服务端再次校验，不能只依赖前端。
ALLOWED_FEEDBACK_REASONS = (
    "答案不准确",
    "回答内容不完整",
    "操作步骤已经过时",
    "没有解决我的问题",
    "知识库没有相关内容",
    "其他",
)

# 不在页面或日志中展示 Dify 的原始错误内容，只返回可理解的中文提示。
GENERIC_CHAT_ERROR = "知识助手暂时不可用，请稍后重试。"
GENERIC_FEEDBACK_ERROR = "反馈提交失败，请稍后重试。"


class FeedbackRegistry:
    """进程内的轻量防重复提交登记表。

    聊天反馈仍由 Dify 原生记录，这里只防止短时间重复提交。服务重启后
    登记表会清空；多个 Flask 进程之间不共享，因此正式多进程部署时应
    替换为 Redis 或数据库。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[str, dict[str, str]] = {}

    def reserve(self, message_id: str, rating: str) -> tuple[bool, dict[str, str] | None]:
        """占位；返回 (是否成功占位, 已有记录)。"""
        with self._lock:
            existing = self._entries.get(message_id)
            if existing is not None:
                return False, dict(existing)
            self._entries[message_id] = {"status": "pending", "rating": rating}
            return True, None

    def commit(self, message_id: str, rating: str) -> None:
        with self._lock:
            self._entries[message_id] = {"status": "submitted", "rating": rating}

    def release(self, message_id: str) -> None:
        with self._lock:
            entry = self._entries.get(message_id)
            if entry and entry.get("status") == "pending":
                self._entries.pop(message_id, None)


def _env_float(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
        return value if value > 0 else default
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
        return value if value > 0 else default
    except (TypeError, ValueError):
        return default


def _is_uuid(value: str) -> bool:
    """Dify 的 conversation_id / message_id 均为 UUID。"""
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def _json_error(message: str, status: int, code: str) -> tuple[Any, int]:
    return jsonify({"ok": False, "code": code, "message": message}), status


def _dify_request(app: Flask, path: str, payload: dict[str, Any]) -> requests.Response:
    """统一发送 Dify 请求。API Key 只在这里使用，不记录、不返回。"""
    base_url = str(app.config["DIFY_API_BASE_URL"]).rstrip("/")
    headers = {
        "Authorization": f"Bearer {app.config['DIFY_API_KEY']}",
        "Content-Type": "application/json",
    }
    timeout = float(app.config["DIFY_TIMEOUT"])
    return requests.post(
        f"{base_url}{path}",
        headers=headers,
        json=payload,
        timeout=(5, timeout),
    )


def _safe_dify_json(response: requests.Response) -> dict[str, Any]:
    try:
        data = response.json()
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


def _log_dify_error(app: Flask, scene: str, response: requests.Response) -> None:
    """记录定位所需信息，但不记录 API Key、用户问题或回答正文。"""
    data = _safe_dify_json(response)
    request_id = ""
    details = data.get("details")
    if isinstance(details, dict):
        request_id = str(details.get("request_id", ""))[:80]
    app.logger.warning(
        "Dify %s failed: status=%s code=%s request_id=%s",
        scene,
        response.status_code,
        str(data.get("code", ""))[:80],
        request_id,
    )


def create_app(test_config: dict[str, Any] | None = None) -> Flask:
    app = Flask(__name__)
    default_api_base = "https://api.dify.ai/v1"
    default_db_path = str(Path(app.instance_path) / "ops_assistant.sqlite3")
    initial_username_env = os.getenv("INITIAL_ADMIN_USERNAME", "").strip()
    legacy_username_env = os.getenv("ADMIN_USERNAME", "").strip()
    initial_password_env = os.getenv("INITIAL_ADMIN_PASSWORD", "").strip()
    legacy_password_env = os.getenv("ADMIN_PASSWORD", "").strip()
    initial_username = initial_username_env or legacy_username_env or "admin"
    initial_password = initial_password_env or legacy_password_env
    legacy_initial = bool(legacy_password_env) and not bool(initial_password_env)
    app.config.from_mapping(
        DIFY_API_BASE_URL=os.getenv("DIFY_API_BASE_URL", default_api_base).strip() or default_api_base,
        DIFY_API_KEY=os.getenv("DIFY_API_KEY", "").strip(),
        DIFY_USER_ID=os.getenv("DIFY_USER_ID", "demo-user-001").strip(),
        DIFY_TIMEOUT=_env_float("DIFY_TIMEOUT", 60.0),
        MAX_QUERY_LENGTH=_env_int("MAX_QUERY_LENGTH", 2000),
        MAX_COMMENT_LENGTH=_env_int("MAX_COMMENT_LENGTH", 300),
        MAX_DOCUMENT_CONTENT=_env_int("MAX_DOCUMENT_CONTENT", 200000),
        DATABASE_PATH=os.getenv("DATABASE_PATH", "").strip() or default_db_path,
        INITIAL_ADMIN_USERNAME=initial_username,
        INITIAL_ADMIN_PASSWORD=initial_password,
        INITIAL_ADMIN_LEGACY=legacy_initial,
        INITIAL_ADMIN_DISPLAY_NAME=(
            os.getenv("INITIAL_ADMIN_DISPLAY_NAME", "").strip() or "系统管理员"
        ),
        SESSION_HOURS=_env_int("SESSION_HOURS", 8),
        SECRET_KEY=os.getenv("SECRET_KEY", "").strip() or secrets.token_hex(32),
        HOST=os.getenv("HOST", "127.0.0.1").strip(),
        PORT=_env_int("PORT", 5000),
        FLASK_DEBUG=os.getenv("FLASK_DEBUG", "0").strip().lower() in {"1", "true", "yes"},
    )
    if test_config:
        app.config.update(test_config)

    app.json.ensure_ascii = False
    app.secret_key = app.config["SECRET_KEY"]
    app.config.update(
        SESSION_COOKIE_NAME="ops_session",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=int(app.config["SESSION_HOURS"])),
    )
    app.extensions["feedback_registry"] = FeedbackRegistry()

    # 同一个 SQLite 文件：文档、用户/审计、反馈记录。
    database_path = str(app.config["DATABASE_PATH"])
    init_db(database_path)
    init_auth_db(database_path)
    init_feedback_db(database_path)
    app.extensions["document_repo"] = DocumentRepository(database_path)
    app.extensions["user_repo"] = UserRepository(database_path)
    app.extensions["audit_repo"] = AuditRepository(database_path)
    app.extensions["feedback_repo"] = FeedbackRecordRepository(database_path)

    try:
        created_admin = ensure_initial_admin(
            app.extensions["user_repo"],
            username=str(app.config["INITIAL_ADMIN_USERNAME"]),
            password=str(app.config["INITIAL_ADMIN_PASSWORD"]),
            display_name=str(app.config["INITIAL_ADMIN_DISPLAY_NAME"]),
            allow_legacy_short_password=bool(app.config["INITIAL_ADMIN_LEGACY"]),
        )
    except AuthError as exc:
        created_admin = False
        app.logger.error("初始管理员创建失败：%s", exc)
    if created_admin:
        if app.config["INITIAL_ADMIN_LEGACY"]:
            app.logger.warning(
                "已使用旧版 ADMIN_PASSWORD 迁移初始管理员。该密码可能较短，"
                "请登录后在用户管理中重置为至少 8 位密码。"
            )
        else:
            app.logger.warning("已根据环境变量创建初始管理员账号。请尽快登录并修改密码。")

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)

    if not app.config["DIFY_API_KEY"]:
        app.logger.warning("未配置 DIFY_API_KEY，聊天和反馈接口将返回服务未配置提示。")
    if app.extensions["user_repo"].count_users() == 0:
        app.logger.warning(
            "当前没有任何用户账号。请设置 INITIAL_ADMIN_PASSWORD 后重启，"
            "或运行 flask --app app create-admin 创建管理员。"
        )
    if not app.config["DIFY_USER_ID"]:
        app.config["DIFY_USER_ID"] = "demo-user-001"

    @app.before_request
    def load_current_user():
        g.user_repo = app.extensions["user_repo"]
        g.audit_repo = app.extensions["audit_repo"]
        g.feedback_repo = app.extensions["feedback_repo"]
        g.user = None
        user_id = session.get("user_id")
        if user_id is not None:
            user = g.user_repo.get_by_id(int(user_id))
            session_version = session.get("auth_version")
            if (
                user is not None
                and user.get("is_active")
                and session_version == user.get("session_version")
            ):
                g.user = user
            else:
                session.clear()

    @app.before_request
    def ensure_csrf_token():
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_urlsafe(32)

    @app.context_processor
    def inject_auth_context():
        user = g.get("user")
        return {
            "current_user": user,
            "csrf_token": session.get("csrf_token", ""),
            "role_labels": ROLE_LABELS,
            "role_permission_matrix": ROLE_PERMISSIONS,
            "can": lambda permission: has_permission(permission, user),
            "can_view_admin": has_permission("admin.access", user),
        }

    @app.cli.command("create-admin")
    @click.option("--username", prompt="管理员账号")
    @click.option("--display-name", prompt="显示名称", default="系统管理员")
    @click.password_option(confirmation_prompt=True)
    def create_admin(username: str, display_name: str, password: str):
        """交互式创建管理员；密码通过隐藏输入读取并只保存哈希。"""
        repo: UserRepository = app.extensions["user_repo"]
        try:
            repo.create_user(
                username=username,
                display_name=display_name,
                password=password,
                role="admin",
            )
        except AuthError as exc:
            raise click.ClickException(str(exc)) from exc
        click.echo(f"管理员 {username} 创建成功。")

    @app.after_request
    def add_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self'; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "font-src 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'",
        )
        if request.path.startswith("/api/") or request.path.startswith("/admin"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/health")
    def health():
        """只返回是否已配置，不校验 Key，也不泄露任何密钥内容。"""
        return jsonify(
            {
                "ok": True,
                "configured": bool(app.config["DIFY_API_KEY"]),
                "service": "企业智能运维知识助手",
                "version": "1.4",
                "document_management": True,
                "role_management": True,
            }
        )

    @app.post("/api/chat")
    def chat():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return _json_error("请求格式不正确，请刷新页面后重试。", 400, "invalid_request")

        query = data.get("query")
        if not isinstance(query, str):
            return _json_error("请输入有效的问题。", 400, "invalid_query")
        query = query.strip()
        if not query:
            return _json_error("问题不能为空。", 400, "empty_query")
        if len(query) > int(app.config["MAX_QUERY_LENGTH"]):
            return _json_error(
                f"问题不能超过 {app.config['MAX_QUERY_LENGTH']} 个字符。",
                400,
                "query_too_long",
            )

        conversation_id = data.get("conversation_id", "")
        if conversation_id is None:
            conversation_id = ""
        if not isinstance(conversation_id, str):
            return _json_error("会话标识无效，请点击「新对话」后重试。", 400, "invalid_conversation")
        conversation_id = conversation_id.strip()
        if conversation_id and not _is_uuid(conversation_id):
            return _json_error("会话标识无效，请点击「新对话」后重试。", 400, "invalid_conversation")

        if not app.config["DIFY_API_KEY"]:
            return _json_error(
                "知识助手尚未完成配置，请联系管理员设置服务端 API Key。",
                503,
                "service_not_configured",
            )

        payload: dict[str, Any] = {
            "inputs": {},
            "query": query,
            "response_mode": "blocking",
            "user": app.config["DIFY_USER_ID"],
        }
        if conversation_id:
            payload["conversation_id"] = conversation_id

        try:
            response = _dify_request(app, "/chat-messages", payload)
        except requests.Timeout:
            app.logger.warning("Dify chat request timed out")
            return _json_error("知识助手响应超时，请稍后重试。", 504, "upstream_timeout")
        except requests.ConnectionError:
            app.logger.warning("Dify chat connection failed")
            return _json_error("暂时无法连接知识助手服务，请检查网络后重试。", 502, "upstream_unreachable")
        except requests.RequestException as exc:
            app.logger.warning("Dify chat request error: %s", type(exc).__name__)
            return _json_error(GENERIC_CHAT_ERROR, 502, "upstream_error")

        if response.status_code != 200:
            _log_dify_error(app, "chat", response)
            if response.status_code == 401:
                return _json_error(
                    "知识助手鉴权失败，请联系管理员检查服务端 API 配置。",
                    503,
                    "upstream_auth_error",
                )
            if response.status_code == 404:
                return _json_error(
                    "当前会话已失效，请点击「新对话」后重试。",
                    409,
                    "conversation_not_found",
                )
            if response.status_code == 429:
                return _json_error("当前咨询人数较多，请稍后再试。", 429, "rate_limited")
            if response.status_code == 400:
                return _json_error(
                    "知识助手当前不可用，请联系管理员检查 Chatflow 发布状态。",
                    502,
                    "upstream_bad_request",
                )
            return _json_error(GENERIC_CHAT_ERROR, 502, "upstream_error")

        result = _safe_dify_json(response)
        answer = result.get("answer")
        message_id = result.get("message_id")
        new_conversation_id = result.get("conversation_id")

        if not isinstance(answer, str) or not answer.strip():
            app.logger.warning("Dify chat returned empty answer")
            return _json_error("知识助手没有返回有效回答，请稍后重试。", 502, "empty_answer")
        if not isinstance(message_id, str) or not _is_uuid(message_id):
            app.logger.warning("Dify chat returned invalid message_id")
            return _json_error("知识助手返回数据不完整，请稍后重试。", 502, "invalid_message_id")
        if not isinstance(new_conversation_id, str) or not _is_uuid(new_conversation_id):
            app.logger.warning("Dify chat returned invalid conversation_id")
            return _json_error("知识助手返回数据不完整，请稍后重试。", 502, "invalid_conversation_id")

        return jsonify(
            {
                "ok": True,
                "answer": answer.strip(),
                "message_id": message_id,
                "conversation_id": new_conversation_id,
            }
        )

    @app.post("/api/feedback")
    def feedback():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return _json_error("请求格式不正确，请刷新页面后重试。", 400, "invalid_request")

        message_id = data.get("message_id")
        if not isinstance(message_id, str) or not _is_uuid(message_id.strip()):
            return _json_error("消息标识无效，请刷新页面后重试。", 400, "invalid_message_id")
        message_id = message_id.strip()

        rating = data.get("rating")
        if rating not in {"like", "dislike"}:
            return _json_error("反馈类型无效。", 400, "invalid_rating")

        reason = data.get("reason", "")
        comment = data.get("comment", "")
        if reason is None:
            reason = ""
        if comment is None:
            comment = ""
        if not isinstance(reason, str) or not isinstance(comment, str):
            return _json_error("反馈内容格式不正确。", 400, "invalid_feedback_content")
        reason = reason.strip()
        comment = comment.strip()

        if rating == "dislike":
            if reason not in ALLOWED_FEEDBACK_REASONS:
                return _json_error("请选择有效的反馈原因。", 400, "invalid_reason")
            if len(comment) > int(app.config["MAX_COMMENT_LENGTH"]):
                return _json_error(
                    f"补充说明不能超过 {app.config['MAX_COMMENT_LENGTH']} 个字符。",
                    400,
                    "comment_too_long",
                )
            content = f"反馈原因：{reason}"
            if comment:
                content += f"；补充说明：{comment}"
        else:
            # 点赞不带文字内容；忽略误传的 reason/comment，避免脏数据。
            content = ""

        if not app.config["DIFY_API_KEY"]:
            return _json_error(
                "知识助手尚未完成配置，请联系管理员设置服务端 API Key。",
                503,
                "service_not_configured",
            )

        registry: FeedbackRegistry = app.extensions["feedback_registry"]
        reserved, existing = registry.reserve(message_id, rating)
        if not reserved:
            if existing and existing.get("status") == "submitted":
                return jsonify(
                    {
                        "ok": True,
                        "duplicate": True,
                        "message": "该消息已提交过反馈，无需重复提交。",
                    }
                )
            return _json_error("该消息的反馈正在提交，请稍候。", 409, "feedback_pending")

        payload: dict[str, Any] = {
            "rating": rating,
            "user": app.config["DIFY_USER_ID"],
        }
        if content:
            payload["content"] = content

        try:
            response = _dify_request(
                app,
                f"/messages/{quote(message_id, safe='')}/feedbacks",
                payload,
            )
        except requests.Timeout:
            registry.release(message_id)
            app.logger.warning("Dify feedback request timed out")
            return _json_error("反馈提交超时，请稍后重试。", 504, "upstream_timeout")
        except requests.ConnectionError:
            registry.release(message_id)
            app.logger.warning("Dify feedback connection failed")
            return _json_error("暂时无法连接反馈服务，请检查网络后重试。", 502, "upstream_unreachable")
        except requests.RequestException as exc:
            registry.release(message_id)
            app.logger.warning("Dify feedback request error: %s", type(exc).__name__)
            return _json_error(GENERIC_FEEDBACK_ERROR, 502, "upstream_error")

        if response.status_code != 200:
            registry.release(message_id)
            _log_dify_error(app, "feedback", response)
            if response.status_code == 401:
                return _json_error(
                    "反馈服务鉴权失败，请联系管理员检查服务端 API 配置。",
                    503,
                    "upstream_auth_error",
                )
            if response.status_code == 404:
                return _json_error("该回答的反馈记录已失效，请刷新页面后重试。", 404, "message_not_found")
            if response.status_code == 429:
                return _json_error("当前提交人数较多，请稍后再试。", 429, "rate_limited")
            return _json_error(GENERIC_FEEDBACK_ERROR, 502, "upstream_error")

        result = _safe_dify_json(response)
        if result.get("result") != "success":
            registry.release(message_id)
            app.logger.warning("Dify feedback returned unexpected body")
            return _json_error(GENERIC_FEEDBACK_ERROR, 502, "unexpected_response")

        registry.commit(message_id, rating)
        try:
            actor = g.get("user")
            app.extensions["feedback_repo"].record(
                message_id=message_id,
                dify_user=app.config["DIFY_USER_ID"],
                rating=rating,
                reason=reason,
                comment=comment,
                content=content,
                actor_user_id=int(actor["id"]) if actor else None,
                actor_username=actor["username"] if actor else "",
            )
        except Exception as exc:  # 本地镜像失败不能影响已成功的 Dify 反馈
            app.logger.warning("Failed to save local feedback mirror: %s", type(exc).__name__)
        success_message = (
            "感谢你的认可！" if rating == "like" else "感谢反馈，我们将持续优化知识助手。"
        )
        return jsonify({"ok": True, "rating": rating, "message": success_message})

    return app


app = create_app()


if __name__ == "__main__":
    print("=" * 62)
    print("企业智能运维知识助手 V1.4")
    print(f"聊天地址：http://{app.config['HOST']}:{app.config['PORT']}")
    print(f"登录地址：http://{app.config['HOST']}:{app.config['PORT']}/login")
    print(f"文档管理：http://{app.config['HOST']}:{app.config['PORT']}/admin/documents")
    print("按 Ctrl + C 停止服务")
    print("=" * 62)
    app.run(
        host=app.config["HOST"],
        port=int(app.config["PORT"]),
        debug=bool(app.config["FLASK_DEBUG"]),
    )
