# 企业智能运维知识助手 V1.3

> 基于 **Dify Chatflow + DeepSeek + RAG** 的企业运维知识问答页面，支持多轮对话、点赞/点踩、反馈原因，以及带审核、发布、归档和 Dify 同步衔接的文档版本管理。
>
> GitHub 仓库：<https://github.com/cl-Y1/enterprise-ops-ai-assistant><br>
> [![tests](https://github.com/cl-Y1/enterprise-ops-ai-assistant/actions/workflows/tests.yml/badge.svg)](https://github.com/cl-Y1/enterprise-ops-ai-assistant/actions/workflows/tests.yml)

本项目不重新开发 RAG，也不修改原有 Chatflow 的核心逻辑。V1.3 在现有 Dify 应用之上提供两个模块：

1. **智能问答**：Flask 后端代理 Dify Chatflow，支持多轮对话和消息反馈；
2. **文档版本管理**：SQLite 保存文档、版本、审核、发布、Dify 同步登记和操作审计。

聊天与反馈仍使用 Dify 原生记录；文档治理数据保存在本地 SQLite，二者互不破坏。

---

## 1. 功能清单

### 智能问答

- 调用 Dify `POST /v1/chat-messages`，阻塞模式获取回答；
- 正确保存并传递 `conversation_id`，支持连续多轮；
- 每条 AI 回答关联独立 `message_id`；
- 点赞、点踩按钮；
- 点踩选择六种原因，并可填写补充说明；
- 反馈提交到 Dify 原生消息反馈 API；
- 前后端双重防止重复反馈；
- 超时、断网、401、404、429、空回答均有脱敏中文提示。

### 文档版本管理

- 文档基础信息：标题、分类、负责人、说明、Dify 数据集/文档 ID；
- 自动版本号：`v1`、`v2`……；
- 每个版本记录：更新原因、更新人、内容快照、SHA-256；
- 审核状态：草稿、待审核、审核通过、已驳回；
- 发布状态：未发布、已发布、已归档；
- 审核通过后，若关联 Dify，必须先登记同步才能发布；
- 发布新版本时，旧发布版本自动归档，历史内容永久保留；
- 历史版本下载为 `.md`；
- 操作审计：创建、提交审核、审核、Dify 同步、发布、自动归档；
- 简洁管理后台，Basic Auth + CSRF 防护；
- 详细 Dify 衔接流程见 [docs/dify-sync-workflow.md](docs/dify-sync-workflow.md)。

---

## 2. 系统架构

```text
┌──────────────────────────────┐        ┌──────────────────────────────┐
│ 聊天页面                     │        │ 文档版本管理后台              │
│ HTML + CSS + 原生 JavaScript │        │ /admin/documents              │
│ 点赞 / 点踩 / 反馈弹窗       │        │ 审核 / 发布 / 归档 / 下载     │
└──────────────┬───────────────┘        └──────────────┬───────────────┘
               │ 同源 HTTP / JSON                      │ Basic Auth + CSRF
               ▼                                       ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Flask app.py / admin.py                                             │
│ - 聊天与反馈代理                                                    │
│ - 文档版本状态机                                                    │
│ - 输入校验、错误脱敏                                                │
│ - SQLite 文档/版本/审计数据                                         │
└──────────────┬──────────────────────────────────────────────────────┘
               │ Authorization: Bearer {DIFY_API_KEY}
               ▼
┌──────────────────────────────┐        ┌──────────────────────────────┐
│ Dify Cloud Chatflow           │        │ 本地 SQLite                  │
│ - RAG 知识库检索              │        │ instance/ops_assistant.db    │
│ - DeepSeek 生成回答           │        │ 文档 / 版本 / 状态 / 审计    │
│ - 原生消息反馈记录             │        └──────────────────────────────┘
└──────────────────────────────┘
               ▲
               │ 人工确认同步：下载 Markdown → Dify 替换 → 索引完成 → 后台登记 → 发布
               │
┌──────────────┴───────────────┐
│ 管理员 / 知识库负责人          │
└──────────────────────────────┘
```

Dify 知识库写入是**人工确认流程**，V1.3 不会自动覆盖生产知识库。原因和后续自动同步扩展点见 [Dify 衔接流程](docs/dify-sync-workflow.md)。

---

## 3. 技术栈

- 前端：HTML + CSS + 原生 JavaScript
- 后端：Python 3.12 + Flask
- 数据库：SQLite（Python 标准库，不额外安装）
- AI 服务：Dify Cloud Chatflow + DeepSeek + RAG
- 测试：Python `unittest`，GitHub Actions

---

## 4. 目录结构

```text
enterprise-ops-ai-assistant/
├── app.py                         # Flask 工厂、聊天、反馈、健康检查
├── admin.py                       # 文档管理后台路由、认证、CSRF
├── documents.py                   # SQLite 数据层、版本状态机、审计
├── requirements.txt
├── .env.example
├── .gitignore
├── README.md
│
├── templates/
│   ├── index.html                 # 聊天页面
│   └── admin/
│       ├── base.html
│       ├── documents.html         # 文档列表
│       ├── document_form.html     # 新建/编辑文档
│       ├── version_form.html      # 新增版本
│       ├── document_detail.html   # 版本详情、审核、发布、Dify 同步
│       └── error.html
│
├── static/
│   ├── css/
│   │   ├── style.css              # 聊天页样式
│   │   └── admin.css              # 管理后台样式
│   └── js/
│       ├── app.js                 # 聊天/反馈交互
│       └── admin.js               # 复制、发布确认
│
├── tests/
│   ├── __init__.py
│   ├── test_app.py                # 22 项聊天/反馈测试
│   └── test_documents.py          # 14 项文档模块测试
│
├── docs/
│   └── dify-sync-workflow.md      # Dify 知识库更新作业指导书
│
└── .github/
    └── workflows/
        └── tests.yml              # GitHub Actions 单元测试
```

`instance/` 数据库、`.env`、`.venv` 和本地截图都会被 `.gitignore` 排除。

---

## 5. 环境要求

已在以下环境验证：

- Windows 11
- Python 3.12.6
- Flask 3.1.3
- requests 2.34.2
- python-dotenv 1.2.4
- 可访问 `https://api.dify.ai`
- 已发布 Dify Chatflow，并开启应用 API 访问

Python 3.10 及以上可尝试使用。

---

## 6. 快速开始（Windows PowerShell）

### 6.1 进入项目并创建虚拟环境

```powershell
cd "D:\你的路径\enterprise-ops-ai-assistant"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

如果 PowerShell 禁止运行脚本：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

### 6.2 安装依赖

```powershell
python -m pip install -r requirements.txt
```

### 6.3 配置环境变量

```powershell
Copy-Item .env.example .env
notepad .env
```

最少需要填写：

```dotenv
DIFY_API_KEY=app-你的Dify应用Key
ADMIN_USERNAME=admin
ADMIN_PASSWORD=设置一个足够强的管理员密码
```

建议同时设置固定的会话密钥：

```powershell
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

把输出填入：

```dotenv
SECRET_KEY=上一步生成的随机字符串
```

说明：

- `DIFY_API_KEY` 是聊天应用 API Key，不要填知识库 API Key；
- `ADMIN_PASSWORD` 留空时管理后台会返回 503，不会暴露默认密码；
- `SECRET_KEY` 留空会每次启动随机生成，重启后管理员会话需重新建立；
- `.env` 已被 `.gitignore` 忽略，严禁提交。

### 6.4 启动

```powershell
python app.py
```

访问：

```text
聊天页面：http://127.0.0.1:5000/
文档管理：http://127.0.0.1:5000/admin/documents
```

管理后台会弹出浏览器 Basic Auth 登录框，输入 `ADMIN_USERNAME` / `ADMIN_PASSWORD`。

首次启动会自动创建：

```text
instance/ops_assistant.sqlite3
```

不需要手动建库。

---

## 7. 环境变量

| 变量 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `DIFY_API_KEY` | 是 | 空 | Dify 应用 API Key，只放后端 |
| `DIFY_API_BASE_URL` | 否 | `https://api.dify.ai/v1` | Dify API 地址 |
| `DIFY_USER_ID` | 否 | `demo-user-001` | 聊天与反馈的终端用户标识 |
| `DIFY_TIMEOUT` | 否 | `60` | Dify 请求读取超时（秒） |
| `ADMIN_USERNAME` | 否 | `admin` | 文档后台用户名 |
| `ADMIN_PASSWORD` | 是 | 空 | 文档后台密码；为空则后台禁用 |
| `SECRET_KEY` | 建议 | 随机生成 | Flask 会话签名密钥 |
| `DATABASE_PATH` | 否 | `instance/ops_assistant.sqlite3` | SQLite 文件位置 |
| `MAX_DOCUMENT_CONTENT` | 否 | `200000` | 单篇文档内容上限 |
| `HOST` | 否 | `127.0.0.1` | 本地监听地址 |
| `PORT` | 否 | `5000` | 本地端口 |
| `FLASK_DEBUG` | 否 | `0` | 生产/演示保持 0 |

---

## 8. Dify 端需要检查什么

本项目不修改原有 Chatflow、知识库和 RAG。只需要确认：

1. Chatflow 已发布，未使用草稿版本；
2. 应用已开启 API 访问；
3. `DIFY_API_KEY` 与应用匹配；
4. `DIFY_USER_ID` 在聊天和反馈中保持一致（后端自动保证）；
5. Chatflow 没有新增必填输入变量，本项目发送 `inputs: {}`；
6. 文档版本管理中的 Dify 数据集 ID、文档 ID 与 Dify 控制台一致。

### 8.1 Dify 数据集/文档 ID 在哪里

- **数据集 ID**：打开 Dify 知识库，从页面 URL 的 `/datasets/` 后复制；
- **文档 ID**：在知识库文档详情或文档列表中获取。

V1.3 不自动调用知识库写接口。正式自动同步需要额外的知识库 API Key，接入方式见 [Dify 衔接流程](docs/dify-sync-workflow.md)。

---

## 9. 文档版本管理后台

### 9.1 入口与认证

访问：

```text
http://127.0.0.1:5000/admin/documents
```

认证方式：HTTP Basic Auth。

- 未配置 `ADMIN_PASSWORD`：返回 503，后台禁用；
- 用户名或密码错误：返回 401；
- 所有写操作都有 CSRF token 校验；
- 管理页面不显示密码、API Key 或数据库路径。

> Basic Auth 在本地演示足够；如果部署到公网，必须使用 HTTPS。

### 9.2 创建文档

进入「新建文档」，填写：

- 文档标题；
- 分类、负责人、说明；
- 可选：Dify 数据集 ID + 文档 ID（必须成对填写）；
- 初始版本 v1 的更新原因和内容。

创建后初始版本为「草稿 / 未发布」。

### 9.3 版本与审核流程

```text
草稿 draft
  │ 提交审核
  ▼
待审核 pending
  ├── 审核通过 → approved
  └── 审核驳回 → rejected → 修改后重新提交
```

审核通过后才允许进入发布阶段。审核意见、审核人和审核时间会记录在版本中。

### 9.4 发布与历史归档

```text
未发布 unpublished
  │ 发布
  ▼
已发布 published
  │ 新版本发布
  ▼
已归档 archived
```

发布条件：

- 审核状态必须是「审核通过」；
- 如果文档关联了 Dify，`dify_sync_status` 必须是「已登记同步」；
- 未关联 Dify 的文档审核通过后可以直接发布。

新版本发布时：

- 当前版本变为 `published`；
- 之前的 `published` 版本自动变为 `archived`；
- 所有版本内容继续保留，可下载追溯；
- 写入操作记录。

### 9.5 历史版本下载

在版本内容区点击「下载 .md」，文件名类似：

```text
CBS-与-TDH-数据一致性排查手册-v2.md
```

可用于 Dify 知识库替换或本地归档。

### 9.6 Dify 同步衔接

完整作业指导书：[docs/dify-sync-workflow.md](docs/dify-sync-workflow.md)

简要流程：

1. 新增版本并提交审核；
2. 审核通过；
3. 下载/复制 Markdown；
4. 在 Dify 知识库替换对应文档；
5. 等待 Dify 重新分段和索引完成；
6. 回后台填写同步说明，点击「确认已同步」；
7. 点击「发布此版本」；
8. 旧版本自动归档；
9. 在聊天页面验证 RAG 回答。

同步说明示例：

```text
2026-11-06 17:00 在 Dify 替换文档，索引状态 completed；操作人：admin
```

### 9.7 状态速查

| 审核状态 | 中文 |
| --- | --- |
| `draft` | 草稿 |
| `pending` | 待审核 |
| `approved` | 审核通过 |
| `rejected` | 已驳回 |

| 发布状态 | 中文 |
| --- | --- |
| `unpublished` | 未发布 |
| `published` | 已发布 |
| `archived` | 已归档 |

| Dify 同步状态 | 中文 |
| --- | --- |
| `pending` | 待同步 |
| `synced` | 已登记同步 |
| `not_required` | 无需同步 |

---

## 10. 聊天与反馈 API

### 10.1 `GET /api/health`

只检查后端是否读取到配置，不验证 Key 有效性，不返回密钥。

```json
{
  "ok": true,
  "configured": true,
  "service": "企业智能运维知识助手",
  "version": "1.3",
  "document_management": true
}
```

### 10.2 `POST /api/chat`

```json
{
  "query": "CBS 与 TDH 数据记录数量不一致时，应该如何排查？",
  "conversation_id": ""
}
```

成功：

```json
{
  "ok": true,
  "answer": "建议按以下顺序排查……",
  "message_id": "9da23599-e713-473b-982c-4328d4f5c78a",
  "conversation_id": "45701982-8118-4bc5-8e9b-64562b4555f2"
}
```

后端发往 Dify：

```json
{
  "inputs": {},
  "query": "用户问题",
  "response_mode": "blocking",
  "user": "demo-user-001",
  "conversation_id": "上一轮会话 ID，首轮省略"
}
```

### 10.3 `POST /api/feedback`

点赞：

```json
{
  "message_id": "9da23599-e713-473b-982c-4328d4f5c78a",
  "rating": "like"
}
```

点踩：

```json
{
  "message_id": "9da23599-e713-473b-982c-4328d4f5c78a",
  "rating": "dislike",
  "reason": "答案不准确",
  "comment": "缺少 Service 日志检查步骤"
}
```

服务端组合后发往 Dify：

```text
反馈原因：答案不准确；补充说明：缺少 Service 日志检查步骤
```

同一条 `message_id` 只允许成功提交一次，前端按钮锁定，后端登记表再次拦截。

### 10.4 管理后台路由

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/admin/documents` | 文档列表、搜索、统计 |
| GET/POST | `/admin/documents/new` | 新建文档和初始版本 |
| GET | `/admin/documents/<id>` | 文档详情、版本、审核、发布 |
| GET/POST | `/admin/documents/<id>/edit` | 编辑文档元信息 |
| GET/POST | `/admin/documents/<id>/versions/new` | 新增版本 |
| POST | `/admin/versions/<id>/submit` | 提交审核 |
| POST | `/admin/versions/<id>/review` | 审核通过/驳回 |
| POST | `/admin/versions/<id>/sync` | 登记 Dify 同步 |
| POST | `/admin/versions/<id>/publish` | 发布版本并归档旧版本 |
| GET | `/admin/versions/<id>/download` | 下载版本 Markdown |

所有 POST 都需要 CSRF token 和 Basic Auth。

---

## 11. 数据模型

SQLite 三张表：

### `documents`

文档元信息、Dify 数据集/文档 ID、当前发布版本 ID。

### `document_versions`

每个版本的：

- 版本号、更新原因、更新人；
- 内容、内容 SHA-256；
- 审核状态、审核人、审核意见、审核时间；
- 发布状态、发布时间；
- Dify 同步状态、同步说明、同步登记人/时间。

### `version_events`

不可变操作记录：创建、提交审核、审核通过/驳回、Dify 同步、发布、自动归档。

---

## 12. 安全设计

| 要求 | 实现 |
| --- | --- |
| Dify API Key 只在后端 | 环境变量读取，前端只请求 Flask |
| 管理员密码 | `ADMIN_PASSWORD`，留空则后台禁用 |
| 写操作防护 | Basic Auth + Session CSRF token |
| Cookie | `HttpOnly` + `SameSite=Lax` |
| 输入校验 | 标题、内容长度、Dify ID 格式、版本状态转换 |
| 错误脱敏 | Dify 原始错误只写服务端日志 |
| 数据库 | `instance/*.sqlite3` 被 Git 忽略 |
| 浏览器防护 | CSP、`X-Frame-Options`、API/后台 `no-store` |
| 本地访问 | 默认绑定 `127.0.0.1` |

补充：

- Basic Auth 不是企业级 SSO。正式环境建议接入公司登录、角色权限和 HTTPS；
- 单一管理员账号无法实现职责分离，V1.3 仅用于轻量实践；
- 归档版本不可重新发布，回滚应创建新版本，保持历史链路。

---

## 13. 测试记录

### 13.1 自动化测试

```powershell
python -m unittest discover -s tests -v
```

结果：

```text
Ran 36 tests
OK
```

包含：

- 原有聊天/反馈 22 项回归测试；
- 文档模块 14 项测试：
  - Basic Auth、后台禁用、CSRF；
  - 文档创建、版本创建；
  - 审核通过/驳回与重新提交；
  - Dify 同步前置条件；
  - 发布与旧版本自动归档；
  - 下载 `.md`；
  - 搜索、编辑、非法版本归属；
  - 管理页面不泄露密码。

GitHub Actions 会运行同一套测试，徽章显示在 README 顶部。

### 13.2 聊天回归

原有 10 项聊天验收清单仍适用：

1. CBS/TDH 真实 RAG 回答；
2. 多轮对话；
3. 点赞；
4. 点踩原因；
5. 点踩补充说明；
6. 防止重复反馈；
7. 错误 API Key；
8. 网络异常；
9. 前端不暴露 Key；
10. Dify 控制台查看反馈。

其中 1–5、10 需要真实 Dify Key 才能最终验收；自动化已覆盖接口契约和异常路径。

### 13.3 文档模块验收清单

| # | 测试 | 预期 |
| --- | --- | --- |
| 1 | 未配置 `ADMIN_PASSWORD` 访问后台 | 返回 503，后台禁用 |
| 2 | 错误密码访问 | 返回 401 |
| 3 | 新建文档 | 生成 v1 草稿 |
| 4 | 提交审核 | 状态变为待审核 |
| 5 | 驳回但未填意见 | 操作被拒绝 |
| 6 | 审核通过 | 状态变为审核通过 |
| 7 | 关联 Dify 但未登记同步就发布 | 被拦截 |
| 8 | 登记 Dify 同步后发布 | 发布成功 |
| 9 | 创建 v2 并发布 | v1 自动归档，v2 发布 |
| 10 | 下载历史版本 | 返回 `.md` 内容 |
| 11 | 搜索文档 | 只显示匹配结果 |
| 12 | 无 Dify 关联的文档 | 审核通过后可直接发布 |

---

## 14. 在 Dify 控制台查看聊天反馈

1. 打开 Dify 对应应用；
2. 进入「日志」或「日志与标注 → 日志」；
3. 查看「用户反馈」列；
4. 点击会话行查看具体消息反馈；
5. 通过 API 产生的反馈以 `DIFY_USER_ID` 记录。

官方文档：[Dify 日志](https://docs.dify.ai/zh/cloud/use-dify/monitor/logs)。

---

## 15. 常见问题

### 后台显示 503「管理后台尚未启用」

在 `.env` 中设置：

```dotenv
ADMIN_USERNAME=admin
ADMIN_PASSWORD=你的密码
```

保存后重启 Flask。

### 忘记管理员密码

修改 `.env` 中的 `ADMIN_PASSWORD`，重启 Flask。密码无法从页面找回。

### 发布按钮不出现

检查：

- 版本是否已审核通过；
- 关联 Dify 时，是否已登记同步；
- 当前版本是否已经发布或归档。

### Dify 文档更新后，聊天仍引用旧内容

- 检查 Dify 索引是否完成；
- 检查是否更新了正确的数据集/文档 ID；
- 在 Dify 中执行召回测试；
- 必要时在 Dify 侧重建索引；
- 本地发布状态不会自动改变 Dify，二者需要按流程配合。

### 数据库在哪里

默认：

```text
instance/ops_assistant.sqlite3
```

备份时复制该文件即可；不要提交到 GitHub。

### 5000 端口被占用

修改 `.env`：

```dotenv
PORT=5001
```

访问 `http://127.0.0.1:5001`。

---

## 16. 已知限制与后续版本

V1.3 有意保持轻量：

- 单一管理员账号，没有多角色权限；
- Basic Auth，不是 SSO；
- Dify 知识库同步是人工确认流程，不自动调用写接口；
- SQLite 适合单机/小团队，不适合高并发多实例；
- 没有版本内容 diff 视图；
- 没有文件上传，文档内容通过 Markdown/纯文本粘贴维护；
- 聊天历史刷新后不保留（原 V1.2 限制仍存在）。

后续方向：

- 对接企业登录和角色权限；
- 可选的 Dify `update-by-text` 自动同步 + 索引轮询；
- 版本 diff、附件上传、批量导入；
- 审批流通知（邮件/企业微信）；
- PostgreSQL/Redis 和多实例部署。

---

## 17. 上传 GitHub

```powershell
git status
git add .
git commit -m "feat: add document version management"
git push
```

提交前确认：

```powershell
git check-ignore .env instance/ .venv
```

应该不会把 `.env`、数据库或虚拟环境加入提交。

如果真实 Key 误提交：

1. 立即在 Dify 撤销/轮换 Key；
2. 从 Git 历史中移除；
3. 不要只删除最新文件。

---

**版本**：V1.3 · **技术栈**：HTML + CSS + 原生 JavaScript / Python Flask / SQLite / Dify Cloud API / DeepSeek / RAG
