"""角色权限管理后台。

认证：Flask 签名 Session + 用户表 + session_version 失效机制。
权限：登录后在每个路由做真实权限校验，前端隐藏按钮只作为体验优化。
"""

from __future__ import annotations

import re
from io import BytesIO
from typing import Any

from flask import (
    Blueprint,
    current_app,
    flash,
    g,
    make_response,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)

from auth import (
    AUDIT_ACTION_LABELS,
    MIN_PASSWORD_LENGTH,
    PERMISSION_CATALOG,
    ROLE_DESCRIPTIONS,
    ROLE_LABELS,
    ROLE_PERMISSIONS,
    AuditRepository,
    AuthError,
    UserRepository,
    has_permission,
    permission_required,
    validate_csrf,
)
from documents import (
    EVENT_LABELS,
    INDEX_LABELS,
    PUBLISH_LABELS,
    RAG_LABELS,
    REVIEW_LABELS,
    SYNC_LABELS,
    DocumentError,
    DocumentNotFound,
    DocumentRepository,
    InvalidTransition,
)

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

DIFY_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,120}$")


def _repo() -> DocumentRepository:
    return current_app.extensions["document_repo"]


def _users() -> UserRepository:
    return current_app.extensions["user_repo"]


def _audit_repo() -> AuditRepository:
    return current_app.extensions["audit_repo"]


def _audit(
    action: str,
    *,
    target_type: str = "",
    target_id: str | int = "",
    result: str = "success",
    detail: str = "",
) -> None:
    user = g.get("user")
    if not user:
        return
    _audit_repo().log(
        actor_id=int(user["id"]),
        actor_username=user["username"],
        action=action,
        target_type=target_type,
        target_id=str(target_id),
        result=result,
        detail=detail,
        ip=request.remote_addr or "",
    )


def _access_error(status: int, title: str, message: str):
    response = make_response(
        render_template("admin/error.html", status=status, title=title, message=message),
        status,
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@admin_bp.before_request
def protect_admin():
    user = g.get("user")
    if not user:
        return redirect(url_for("auth.login", next=request.full_path))
    if not has_permission("admin.access", user):
        return _access_error(403, "没有访问权限", "普通员工不能访问管理后台。")
    if request.method == "POST" and not validate_csrf():
        return _access_error(400, "表单已过期", "安全校验失败，请刷新页面后重新提交。")
    return None


@admin_bp.context_processor
def inject_admin_context() -> dict[str, Any]:
    permission_rows = []
    for code, label, group in PERMISSION_CATALOG:
        permission_rows.append(
            {
                "code": code,
                "label": label,
                "group": group,
                "roles": {
                    role: code in ROLE_PERMISSIONS.get(role, set())
                    for role in ROLE_LABELS
                },
            }
        )
    return {
        "review_labels": REVIEW_LABELS,
        "publish_labels": PUBLISH_LABELS,
        "sync_labels": SYNC_LABELS,
        "index_labels": INDEX_LABELS,
        "rag_labels": RAG_LABELS,
        "event_labels": EVENT_LABELS,
        "audit_action_labels": AUDIT_ACTION_LABELS,
        "role_descriptions": ROLE_DESCRIPTIONS,
        "permission_rows": permission_rows,
        "min_password_length": MIN_PASSWORD_LENGTH,
    }


def _current_username() -> str:
    return g.user["username"]


def _current_user_id() -> int:
    return int(g.user["id"])


def _version_url(version_id: int) -> str:
    try:
        version = _repo().get_version(version_id)
    except DocumentNotFound:
        return url_for("admin.documents")
    return url_for(
        "admin.document_detail",
        document_id=int(version["document_id"]),
        version=version_id,
    )


# ---------------------------------------------------------------------------
# 文档管理
# ---------------------------------------------------------------------------


@admin_bp.get("/")
def index():
    return redirect(url_for("admin.documents"))


@admin_bp.get("/documents")
@permission_required("documents.view")
def documents():
    search = request.args.get("q", "").strip()
    return render_template(
        "admin/documents.html",
        documents=_repo().list_documents(search),
        stats=_repo().stats(),
        search=search,
    )


def _document_defaults() -> dict[str, str]:
    return {
        "title": "",
        "category": "",
        "owner": g.user["display_name"],
        "description": "",
        "dify_dataset_id": "",
        "dify_document_id": "",
        "update_reason": "",
        "content": "",
    }


def _validate_document_form() -> tuple[dict[str, str], list[str]]:
    data = {
        "title": request.form.get("title", "").strip(),
        "category": request.form.get("category", "").strip(),
        "owner": request.form.get("owner", "").strip(),
        "description": request.form.get("description", "").strip(),
        "dify_dataset_id": request.form.get("dify_dataset_id", "").strip(),
        "dify_document_id": request.form.get("dify_document_id", "").strip(),
    }
    errors: list[str] = []
    if not data["title"]:
        errors.append("请填写文档标题。")
    elif len(data["title"]) > 120:
        errors.append("文档标题不能超过 120 个字符。")
    if len(data["category"]) > 50:
        errors.append("分类不能超过 50 个字符。")
    if len(data["owner"]) > 50:
        errors.append("负责人不能超过 50 个字符。")
    if len(data["description"]) > 500:
        errors.append("文档说明不能超过 500 个字符。")

    has_dataset = bool(data["dify_dataset_id"])
    has_document = bool(data["dify_document_id"])
    if has_dataset != has_document:
        errors.append("Dify 数据集 ID 和文档 ID 需要同时填写，或同时留空。")
    for field, label in (
        ("dify_dataset_id", "Dify 数据集 ID"),
        ("dify_document_id", "Dify 文档 ID"),
    ):
        value = data[field]
        if value and not DIFY_ID_PATTERN.fullmatch(value):
            errors.append(f"{label}格式不正确，只允许字母、数字、下划线和短横线。")
    if not has_permission("documents.dify") and (
        data["dify_dataset_id"] or data["dify_document_id"]
    ):
        errors.append("当前角色不能维护 Dify 数据集/文档 ID。")
    return data, errors


def _validate_version_form() -> tuple[dict[str, str], list[str]]:
    data = {
        "update_reason": request.form.get("update_reason", "").strip(),
        "updated_by": _current_username(),
        "content": request.form.get("content", "").strip(),
    }
    errors: list[str] = []
    if not data["update_reason"]:
        errors.append("请填写本次更新原因。")
    elif len(data["update_reason"]) > 500:
        errors.append("更新原因不能超过 500 个字符。")
    if not data["content"]:
        errors.append("文档内容不能为空。")
    elif len(data["content"]) > int(current_app.config["MAX_DOCUMENT_CONTENT"]):
        errors.append(f"文档内容不能超过 {current_app.config['MAX_DOCUMENT_CONTENT']} 个字符。")
    return data, errors


def _render_document_form(
    mode: str,
    *,
    form: dict[str, str] | None = None,
    errors: list[str] | None = None,
    document: Any = None,
    status: int = 200,
):
    return (
        render_template(
            "admin/document_form.html",
            mode=mode,
            form=form or _document_defaults(),
            errors=errors or [],
            document=document,
        ),
        status,
    )


def _render_version_form(
    mode: str,
    document: Any,
    *,
    version: Any = None,
    form: dict[str, str] | None = None,
    errors: list[str] | None = None,
    status: int = 200,
):
    latest = _repo().get_latest_version(int(document["id"]))
    if form is None:
        if version is not None:
            form = {
                "update_reason": version["update_reason"],
                "updated_by": version["updated_by"],
                "content": version["content"],
            }
        else:
            form = {
                "update_reason": "",
                "updated_by": _current_username(),
                "content": latest["content"] if latest is not None else "",
            }
    return (
        render_template(
            "admin/version_form.html",
            mode=mode,
            document=document,
            version=version,
            latest=latest,
            form=form,
            errors=errors or [],
        ),
        status,
    )


@admin_bp.route("/documents/new", methods=["GET", "POST"])
@permission_required("documents.create")
def new_document():
    if request.method == "GET":
        return _render_document_form("new")

    data, errors = _validate_document_form()
    version_data, version_errors = _validate_version_form()
    errors.extend(version_errors)
    form = {**data, **version_data}
    if errors:
        return _render_document_form("new", form=form, errors=errors, status=400)

    document_id, version_id = _repo().create_document(
        **data,
        update_reason=version_data["update_reason"],
        updated_by=version_data["updated_by"],
        content=version_data["content"],
    )
    _audit("document_created", target_type="document", target_id=document_id, detail=data["title"])
    flash("文档创建成功，初始版本已保存为草稿。", "success")
    return redirect(url_for("admin.document_detail", document_id=document_id, version=version_id))


@admin_bp.route("/documents/<int:document_id>/edit", methods=["GET", "POST"])
@permission_required("documents.edit")
def edit_document(document_id: int):
    try:
        document = _repo().get_document(document_id)
    except DocumentNotFound:
        return _access_error(404, "文档不存在", "该文档可能已被删除。")

    if request.method == "GET":
        form = {
            key: document[key]
            for key in ("title", "category", "owner", "description", "dify_dataset_id", "dify_document_id")
        }
        form.update({"update_reason": "", "content": ""})
        return _render_document_form("edit", form=form, document=document)

    data, errors = _validate_document_form()
    if errors:
        return _render_document_form(
            "edit",
            form=request.form.to_dict(),
            errors=errors,
            document=document,
            status=400,
        )

    try:
        _repo().update_document(document_id, **data)
    except DocumentNotFound:
        return _access_error(404, "文档不存在", "该文档可能已被删除。")
    _audit("document_updated", target_type="document", target_id=document_id, detail=data["title"])
    flash("文档信息已更新。", "success")
    return redirect(url_for("admin.document_detail", document_id=document_id))


@admin_bp.get("/documents/<int:document_id>")
@permission_required("documents.view")
def document_detail(document_id: int):
    try:
        document = _repo().get_document(document_id)
    except DocumentNotFound:
        return _access_error(404, "文档不存在", "该文档可能已被删除。")

    versions = _repo().list_versions(document_id)
    latest = _repo().get_latest_version(document_id)
    published = _repo().get_published_version(document_id)

    selected = None
    selected_id = request.args.get("version", type=int)
    if selected_id is not None:
        try:
            selected = _repo().get_version(selected_id)
        except DocumentNotFound:
            return _access_error(404, "版本不存在", "该版本可能已被删除。")
        if int(selected["document_id"]) != document_id:
            return _access_error(404, "版本不存在", "该版本不属于当前文档。")
    elif latest is not None:
        selected = latest

    events = _repo().get_events(int(selected["id"])) if selected is not None else []
    self_submitted = bool(
        selected
        and selected["submitted_by_user_id"] is not None
        and int(selected["submitted_by_user_id"]) == _current_user_id()
    )
    return render_template(
        "admin/document_detail.html",
        document=document,
        versions=versions,
        latest=latest,
        published=published,
        selected=selected,
        events=events,
        dify_linked=bool(document["dify_dataset_id"] and document["dify_document_id"]),
        self_submitted=self_submitted,
    )


@admin_bp.route("/documents/<int:document_id>/versions/new", methods=["GET", "POST"])
@permission_required("documents.create")
def add_version(document_id: int):
    try:
        document = _repo().get_document(document_id)
    except DocumentNotFound:
        return _access_error(404, "文档不存在", "该文档可能已被删除。")

    if request.method == "GET":
        return _render_version_form("new", document)

    data, errors = _validate_version_form()
    if errors:
        return _render_version_form("new", document, form=data, errors=errors, status=400)

    try:
        version_id = _repo().add_version(
            document_id,
            update_reason=data["update_reason"],
            updated_by=data["updated_by"],
            content=data["content"],
        )
    except DocumentNotFound:
        return _access_error(404, "文档不存在", "该文档可能已被删除。")
    _audit("version_created", target_type="version", target_id=version_id, detail=data["update_reason"])
    flash("新版本已保存为草稿。", "success")
    return redirect(url_for("admin.document_detail", document_id=document_id, version=version_id))


@admin_bp.route("/versions/<int:version_id>/edit", methods=["GET", "POST"])
@permission_required("documents.edit")
def edit_version(version_id: int):
    try:
        version = _repo().get_version(version_id)
    except DocumentNotFound:
        return _access_error(404, "版本不存在", "该版本可能已被删除。")
    if version["review_status"] not in {"draft", "rejected"} or version["publish_status"] != "unpublished":
        flash("只有未发布的草稿或已驳回版本可以编辑内容。", "danger")
        return redirect(_version_url(version_id))

    document = _repo().get_document(int(version["document_id"]))
    if request.method == "GET":
        return _render_version_form("edit", document, version=version)

    data, errors = _validate_version_form()
    if errors:
        return _render_version_form("edit", document, version=version, form=data, errors=errors, status=400)

    try:
        _repo().update_draft_version(
            version_id,
            update_reason=data["update_reason"],
            updated_by=data["updated_by"],
            content=data["content"],
        )
    except (DocumentNotFound, InvalidTransition) as exc:
        flash(str(exc), "danger")
        return redirect(_version_url(version_id))
    _audit("version_edited", target_type="version", target_id=version_id, detail=data["update_reason"])
    flash("草稿内容已更新。", "success")
    return redirect(_version_url(version_id))


@admin_bp.post("/versions/<int:version_id>/submit")
@permission_required("documents.submit")
def submit_version(version_id: int):
    try:
        _repo().submit_version(version_id, _current_user_id(), _current_username())
    except (InvalidTransition, DocumentNotFound) as exc:
        _audit("version_submitted", target_type="version", target_id=version_id, result="failed", detail=str(exc))
        flash(str(exc), "danger")
    else:
        _audit("version_submitted", target_type="version", target_id=version_id)
        flash("版本已提交审核。", "success")
    return redirect(_version_url(version_id))


@admin_bp.post("/versions/<int:version_id>/review")
@permission_required("documents.review")
def review_version(version_id: int):
    decision = request.form.get("decision", "")
    comment = request.form.get("review_comment", "").strip()
    if decision not in {"approved", "rejected"}:
        flash("请选择审核通过或驳回。", "danger")
        return redirect(_version_url(version_id))
    if decision == "rejected" and not comment:
        flash("驳回时必须填写审核意见。", "danger")
        return redirect(_version_url(version_id))
    if len(comment) > 1000:
        flash("审核意见不能超过 1000 个字符。", "danger")
        return redirect(_version_url(version_id))

    try:
        _repo().review_version(
            version_id,
            _current_user_id(),
            _current_username(),
            decision,
            comment,
        )
    except (InvalidTransition, DocumentNotFound) as exc:
        _audit("version_reviewed", target_type="version", target_id=version_id, result="failed", detail=str(exc))
        flash(str(exc), "danger")
    else:
        _audit(
            "version_reviewed",
            target_type="version",
            target_id=version_id,
            detail="审核通过" if decision == "approved" else f"驳回：{comment}",
        )
        flash("审核通过。" if decision == "approved" else "版本已驳回。", "success")
    return redirect(_version_url(version_id))


@admin_bp.post("/versions/<int:version_id>/sync")
@permission_required("documents.sync")
def sync_version(version_id: int):
    note = request.form.get("dify_sync_note", "").strip()
    index_status = request.form.get("dify_index_status", "")
    if len(note) > 1000:
        flash("同步说明不能超过 1000 个字符。", "danger")
        return redirect(_version_url(version_id))
    try:
        _repo().record_dify_sync(version_id, _current_username(), note, index_status)
    except (InvalidTransition, DocumentError, DocumentNotFound) as exc:
        _audit("dify_synced", target_type="version", target_id=version_id, result="failed", detail=str(exc))
        flash(str(exc), "danger")
    else:
        _audit("dify_synced", target_type="version", target_id=version_id, detail=note)
        flash("已登记 Dify 同步与索引状态。", "success")
    return redirect(_version_url(version_id))


@admin_bp.post("/versions/<int:version_id>/rag")
@permission_required("documents.rag")
def rag_version(version_id: int):
    query = request.form.get("rag_test_query", "").strip()
    result = request.form.get("rag_result", "")
    note = request.form.get("rag_test_note", "").strip()
    if len(query) > 1000 or len(note) > 1000:
        flash("RAG 验证内容不能超过 1000 个字符。", "danger")
        return redirect(_version_url(version_id))
    try:
        _repo().record_rag_verification(
            version_id,
            _current_username(),
            query,
            result,
            note,
        )
    except (InvalidTransition, DocumentError, DocumentNotFound) as exc:
        _audit("rag_verified", target_type="version", target_id=version_id, result="failed", detail=str(exc))
        flash(str(exc), "danger")
    else:
        _audit("rag_verified", target_type="version", target_id=version_id, detail=query)
        flash("RAG 验证结果已登记。", "success")
    return redirect(_version_url(version_id))


@admin_bp.post("/versions/<int:version_id>/publish")
@permission_required("documents.publish")
def publish_version(version_id: int):
    try:
        _repo().publish_version(version_id, _current_username())
    except (InvalidTransition, DocumentNotFound) as exc:
        _audit("version_published", target_type="version", target_id=version_id, result="failed", detail=str(exc))
        flash(str(exc), "danger")
    else:
        _audit("version_published", target_type="version", target_id=version_id)
        flash("版本已发布，旧发布版本已自动归档。", "success")
    return redirect(_version_url(version_id))


@admin_bp.get("/versions/<int:version_id>/download")
@permission_required("documents.download")
def download_version(version_id: int):
    try:
        version = _repo().get_version(version_id)
    except DocumentNotFound:
        return _access_error(404, "版本不存在", "该版本可能已被删除。")
    data = BytesIO(version["content"].encode("utf-8"))
    return send_file(
        data,
        mimetype="text/markdown; charset=utf-8",
        as_attachment=True,
        download_name=_safe_download_name(version["document_title"], int(version["version_no"])),
    )


def _safe_download_name(title: str, version_no: int) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]+', "-", title).strip(" .-") or "document"
    return f"{cleaned}-v{version_no}.md"


# ---------------------------------------------------------------------------
# 反馈记录
# ---------------------------------------------------------------------------


@admin_bp.get("/feedback")
@permission_required("feedback.view")
def feedback_records():
    search = request.args.get("q", "").strip()
    rating = request.args.get("rating", "").strip()
    records = current_app.extensions["feedback_repo"].list_records(search=search, rating=rating)
    stats = current_app.extensions["feedback_repo"].stats()
    return render_template(
        "admin/feedback.html",
        records=records,
        stats=stats,
        search=search,
        rating=rating,
    )


# ---------------------------------------------------------------------------
# 用户与角色
# ---------------------------------------------------------------------------


def _user_form_defaults() -> dict[str, Any]:
    return {
        "username": "",
        "display_name": "",
        "role": "employee",
        "is_active": True,
    }


@admin_bp.get("/users")
@permission_required("users.manage")
def users():
    users_list = _users().list_users()
    counts = {role: 0 for role in ROLE_LABELS}
    for user in users_list:
        counts[user["role"]] = counts.get(user["role"], 0) + 1
    return render_template("admin/users.html", users=users_list, role_counts=counts)


@admin_bp.route("/users/new", methods=["GET", "POST"])
@permission_required("users.manage")
def new_user():
    if request.method == "GET":
        return render_template("admin/user_form.html", mode="new", form=_user_form_defaults(), user=None)

    form = {
        "username": request.form.get("username", "").strip(),
        "display_name": request.form.get("display_name", "").strip(),
        "role": request.form.get("role", "employee"),
        "is_active": request.form.get("is_active", "0") == "1",
    }
    password = request.form.get("password", "")
    try:
        user_id = _users().create_user(
            username=form["username"],
            display_name=form["display_name"],
            password=password,
            role=form["role"],
            is_active=form["is_active"],
        )
    except AuthError as exc:
        flash(str(exc), "danger")
        return render_template("admin/user_form.html", mode="new", form=form, user=None), 400
    _audit("user_created", target_type="user", target_id=user_id, detail=f"{form['username']} / {form['role']}")
    flash("用户创建成功。", "success")
    return redirect(url_for("admin.users"))


@admin_bp.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
@permission_required("users.manage")
def edit_user(user_id: int):
    target = _users().get_by_id(user_id)
    if target is None:
        return _access_error(404, "用户不存在", "该用户可能已被删除。")

    if request.method == "GET":
        form = {
            "username": target["username"],
            "display_name": target["display_name"],
            "role": target["role"],
            "is_active": bool(target["is_active"]),
        }
        return render_template("admin/user_form.html", mode="edit", form=form, user=target)

    form = {
        "username": target["username"],
        "display_name": request.form.get("display_name", "").strip(),
        "role": request.form.get("role", target["role"]),
        "is_active": request.form.get("is_active", "0") == "1",
    }
    new_password = request.form.get("password", "")

    if user_id == _current_user_id() and (
        form["role"] != target["role"] or not form["is_active"]
    ):
        flash("不能修改自己的角色或停用自己的账号。", "danger")
        return render_template("admin/user_form.html", mode="edit", form=form, user=target), 400

    try:
        _users().update_user(
            user_id,
            display_name=form["display_name"],
            role=form["role"],
            is_active=form["is_active"],
        )
        if new_password:
            _users().reset_password(user_id, new_password)
    except AuthError as exc:
        flash(str(exc), "danger")
        return render_template("admin/user_form.html", mode="edit", form=form, user=target), 400

    _audit(
        "user_updated",
        target_type="user",
        target_id=user_id,
        detail=f"{form['display_name']} / {form['role']} / active={form['is_active']}",
    )
    if new_password:
        _audit("password_reset", target_type="user", target_id=user_id)
    flash("用户信息已更新，相关旧 Session 已失效。", "success")
    return redirect(url_for("admin.users"))


@admin_bp.get("/roles")
@permission_required("roles.view")
def roles():
    users_list = _users().list_users()
    counts = {role: 0 for role in ROLE_LABELS}
    for user in users_list:
        counts[user["role"]] = counts.get(user["role"], 0) + 1
    return render_template("admin/roles.html", role_counts=counts)


# ---------------------------------------------------------------------------
# 操作日志
# ---------------------------------------------------------------------------


@admin_bp.get("/audit")
@permission_required("audit.view")
def audit_logs():
    search = request.args.get("q", "").strip()
    action = request.args.get("action", "").strip()
    logs = _audit_repo().list_logs(search=search, action=action)
    return render_template(
        "admin/audit.html",
        logs=logs,
        search=search,
        action=action,
    )
