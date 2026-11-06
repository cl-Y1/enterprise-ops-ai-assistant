"""文档版本管理后台。

访问方式：/admin/documents
认证：HTTP Basic（ADMIN_USERNAME / ADMIN_PASSWORD）
防护：所有写操作校验 CSRF token；未配置管理员密码时后台禁用。
"""

from __future__ import annotations

import hmac
import re
import secrets
from io import BytesIO
from typing import Any

from flask import (
    Blueprint,
    current_app,
    flash,
    make_response,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)

from documents import (
    EVENT_LABELS,
    PUBLISH_LABELS,
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


def _admin_name() -> str:
    return current_app.config["ADMIN_USERNAME"]


def _access_error(status: int, title: str, message: str, challenge: bool = False):
    response = make_response(
        render_template("admin/error.html", status=status, title=title, message=message),
        status,
    )
    if challenge:
        response.headers["WWW-Authenticate"] = 'Basic realm="Ops Docs Admin", charset="UTF-8"'
    response.headers["Cache-Control"] = "no-store"
    return response


@admin_bp.before_request
def protect_admin():
    """先检查后台是否启用，再检查 Basic Auth 和 CSRF。"""
    config = current_app.config
    if not config["ADMIN_PASSWORD"]:
        return _access_error(
            503,
            "管理后台尚未启用",
            "请在 .env 中设置 ADMIN_PASSWORD 并重启 Flask。管理员密码不会出现在页面或前端代码中。",
        )

    auth = request.authorization
    username_ok = bool(auth and auth.username == config["ADMIN_USERNAME"])
    password_ok = bool(auth and auth.password is not None and hmac.compare_digest(
        str(auth.password), str(config["ADMIN_PASSWORD"])
    ))
    if not (username_ok and password_ok):
        return _access_error(
            401,
            "需要管理员登录",
            "请输入管理员账号和密码后访问文档版本管理后台。",
            challenge=True,
        )

    session.setdefault("csrf_token", secrets.token_urlsafe(32))

    if request.method == "POST":
        submitted = request.form.get("csrf_token", "") or request.headers.get("X-CSRF-Token", "")
        expected = session.get("csrf_token", "")
        if not expected or not submitted or not hmac.compare_digest(str(submitted), str(expected)):
            return _access_error(
                400,
                "表单已过期",
                "安全校验失败，请刷新页面后重新提交。",
            )
    return None


@admin_bp.context_processor
def inject_admin_context() -> dict[str, Any]:
    return {
        "csrf_token": session.get("csrf_token", ""),
        "admin_username": _admin_name(),
        "review_labels": REVIEW_LABELS,
        "publish_labels": PUBLISH_LABELS,
        "sync_labels": SYNC_LABELS,
        "event_labels": EVENT_LABELS,
    }


def _document_defaults() -> dict[str, str]:
    return {
        "title": "",
        "category": "",
        "owner": _admin_name(),
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
    return data, errors


def _validate_version_form() -> tuple[dict[str, str], list[str]]:
    data = {
        "update_reason": request.form.get("update_reason", "").strip(),
        "updated_by": _admin_name(),
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


def _render_version_form(document: Any, latest: Any, form: dict[str, str] | None = None, errors: list[str] | None = None, status: int = 200):
    default_content = latest["content"] if latest is not None else ""
    return (
        render_template(
            "admin/version_form.html",
            document=document,
            latest=latest,
            form=form or {
                "update_reason": "",
                "updated_by": _admin_name(),
                "content": default_content,
            },
            errors=errors or [],
        ),
        status,
    )


def _safe_download_name(title: str, version_no: int) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]+', "-", title).strip(" .-") or "document"
    return f"{cleaned}-v{version_no}.md"


@admin_bp.get("/")
def index():
    return redirect(url_for("admin.documents"))


@admin_bp.get("/documents")
def documents():
    search = request.args.get("q", "").strip()
    return render_template(
        "admin/documents.html",
        documents=_repo().list_documents(search),
        stats=_repo().stats(),
        search=search,
    )


@admin_bp.route("/documents/new", methods=["GET", "POST"])
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
    flash("文档创建成功，初始版本已保存为草稿。", "success")
    return redirect(url_for("admin.document_detail", document_id=document_id, version=version_id))


@admin_bp.route("/documents/<int:document_id>/edit", methods=["GET", "POST"])
def edit_document(document_id: int):
    try:
        document = _repo().get_document(document_id)
    except DocumentNotFound:
        return _access_error(404, "文档不存在", "该文档可能已被删除。")

    if request.method == "GET":
        form = {key: document[key] for key in (
            "title", "category", "owner", "description", "dify_dataset_id", "dify_document_id"
        )}
        form.update({"update_reason": "", "content": ""})
        return _render_document_form("edit", form=form, document=document)

    data, errors = _validate_document_form()
    if errors:
        return _render_document_form("edit", form=request.form.to_dict(), errors=errors, document=document, status=400)

    try:
        _repo().update_document(document_id, **data)
    except DocumentNotFound:
        return _access_error(404, "文档不存在", "该文档可能已被删除。")
    flash("文档信息已更新。", "success")
    return redirect(url_for("admin.document_detail", document_id=document_id))


@admin_bp.get("/documents/<int:document_id>")
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
    return render_template(
        "admin/document_detail.html",
        document=document,
        versions=versions,
        latest=latest,
        published=published,
        selected=selected,
        events=events,
        dify_linked=bool(document["dify_dataset_id"] and document["dify_document_id"]),
    )


@admin_bp.route("/documents/<int:document_id>/versions/new", methods=["GET", "POST"])
def add_version(document_id: int):
    try:
        document = _repo().get_document(document_id)
    except DocumentNotFound:
        return _access_error(404, "文档不存在", "该文档可能已被删除。")
    latest = _repo().get_latest_version(document_id)

    if request.method == "GET":
        return _render_version_form(document, latest)

    data, errors = _validate_version_form()
    if errors:
        return _render_version_form(document, latest, form=data, errors=errors, status=400)

    try:
        version_id = _repo().add_version(
            document_id,
            update_reason=data["update_reason"],
            updated_by=data["updated_by"],
            content=data["content"],
        )
    except DocumentNotFound:
        return _access_error(404, "文档不存在", "该文档可能已被删除。")
    flash("新版本已保存为草稿。", "success")
    return redirect(url_for("admin.document_detail", document_id=document_id, version=version_id))


def _version_target(version_id: int) -> tuple[Any, str]:
    try:
        version = _repo().get_version(version_id)
    except DocumentNotFound:
        return None, ""
    return version, url_for(
        "admin.document_detail",
        document_id=int(version["document_id"]),
        version=version_id,
    )


@admin_bp.post("/versions/<int:version_id>/submit")
def submit_version(version_id: int):
    version, target = _version_target(version_id)
    if version is None:
        return _access_error(404, "版本不存在", "该版本可能已被删除。")
    try:
        _repo().submit_version(version_id, _admin_name())
    except InvalidTransition as exc:
        flash(str(exc), "danger")
    else:
        flash("版本已提交审核。", "success")
    return redirect(target)


@admin_bp.post("/versions/<int:version_id>/review")
def review_version(version_id: int):
    version, target = _version_target(version_id)
    if version is None:
        return _access_error(404, "版本不存在", "该版本可能已被删除。")
    decision = request.form.get("decision", "")
    comment = request.form.get("review_comment", "").strip()
    if decision not in {"approved", "rejected"}:
        flash("请选择审核通过或驳回。", "danger")
        return redirect(target)
    if decision == "rejected" and not comment:
        flash("驳回时必须填写审核意见。", "danger")
        return redirect(target)
    if len(comment) > 1000:
        flash("审核意见不能超过 1000 个字符。", "danger")
        return redirect(target)

    try:
        _repo().review_version(version_id, _admin_name(), decision, comment)
    except InvalidTransition as exc:
        flash(str(exc), "danger")
    else:
        flash("审核通过。" if decision == "approved" else "版本已驳回。", "success")
    return redirect(target)


@admin_bp.post("/versions/<int:version_id>/sync")
def sync_version(version_id: int):
    version, target = _version_target(version_id)
    if version is None:
        return _access_error(404, "版本不存在", "该版本可能已被删除。")
    note = request.form.get("dify_sync_note", "").strip()
    if len(note) > 1000:
        flash("同步说明不能超过 1000 个字符。", "danger")
        return redirect(target)
    try:
        _repo().record_dify_sync(version_id, _admin_name(), note)
    except (InvalidTransition, DocumentError) as exc:
        flash(str(exc), "danger")
    else:
        flash("已登记 Dify 知识库同步，可以发布该版本。", "success")
    return redirect(target)


@admin_bp.post("/versions/<int:version_id>/publish")
def publish_version(version_id: int):
    version, target = _version_target(version_id)
    if version is None:
        return _access_error(404, "版本不存在", "该版本可能已被删除。")
    try:
        _repo().publish_version(version_id, _admin_name())
    except InvalidTransition as exc:
        flash(str(exc), "danger")
    else:
        flash("版本已发布，旧发布版本已自动归档。", "success")
    return redirect(target)


@admin_bp.get("/versions/<int:version_id>/download")
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
