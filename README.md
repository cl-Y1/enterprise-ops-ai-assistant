# 企业智能运维知识助手 V1.4

> 基于 **Dify Chatflow + DeepSeek + RAG** 的企业运维知识问答与文档版本治理平台，新增普通员工、运维人员、管理员三类角色权限。
>
> GitHub 仓库：<https://github.com/cl-Y1/enterprise-ops-ai-assistant><br>
> [![tests](https://github.com/cl-Y1/enterprise-ops-ai-assistant/actions/workflows/tests.yml/badge.svg)](https://github.com/cl-Y1/enterprise-ops-ai-assistant/actions/workflows/tests.yml)

V1.4 **只增加权限管理，不重写已有功能**。以下能力继续保留：

1. Dify Chatflow 问答；
2. 点赞、点踩和反馈原因；
3. 文档版本管理；
4. 文档审核、Dify 同步登记、RAG 验证和版本发布。

新增：

- 用户登录、退出、Session 失效；
- 普通员工 / 运维人员 / 管理员三角色；
- 用户管理、角色权限矩阵、反馈记录、操作日志；
- 后端逐路由权限校验与前端菜单/按钮隐藏；
- 提交人不可自审、运维人员不可发布；
- 发布前必须通过审核、Dify 同步、索引成功和 RAG 验证。

---

## 1. 角色权限矩阵

| 能力 | 普通员工 employee | 运维人员 operator | 管理员 admin |
| --- | :---: | :---: | :---: |
| 使用 AI 知识问答 | ✓ | ✓ | ✓ |
| 点赞、点踩、文字反馈 | ✓ | ✓ | ✓ |
| 查看反馈记录 | — | ✓ | ✓ |
| 进入管理后台 | — | ✓ | ✓ |
| 查看文档与历史版本 | — | ✓ | ✓ |
| 创建文档/版本 | — | ✓ | ✓ |
| 编辑文档信息和草稿 | — | ✓ | ✓ |
| 提交文档审核 | — | ✓ | ✓ |
| 下载/复制 Markdown | — | ✓ | ✓ |
| 登记 Dify 同步与索引状态 | — | ✓ | ✓ |
| 执行并登记 RAG 验证 | — | ✓ | ✓ |
| 审核/驳回文档 | — | — | ✓ |
| 发布文档版本 | — | — | ✓ |
| 管理全部历史版本 | — | 查看/下载 | ✓ |
| 查看全部反馈 | — | ✓ | ✓ |
| 管理用户与角色 | — | — | ✓ |
| 查看角色权限矩阵 | — | — | ✓ |
| 查看操作日志 | — | — | ✓ |

### 关键约束

- 普通员工访问任何 `/admin` 路由都会返回 403；
- 前端隐藏按钮，但后端每个路由独立校验，不能只靠隐藏；
- 提交人不能审核自己的版本；管理员也一样；
- 运维人员不能审核、不能发布；
- 只有管理员能发布；
- 关联 Dify 的版本发布前必须满足：
  1. 审核状态 `approved`；
  2. Dify 同步状态 `synced`；
  3. Dify 索引状态 `success`；
  4. RAG 验证状态 `passed`；
- 未关联 Dify 的本地文档只需审核通过即可由管理员发布。

---

## 2. 系统架构

```text
┌─────────────────────────────────────────────────────────────┐
│ 浏览器                                                      │
│  - 聊天页（公开，保留既有问答体验）                          │
│  - 登录页 / 登出                                            │
│  - 管理后台：按角色显示菜单和操作按钮                        │
└───────────────┬─────────────────────────────────────────────┘
                │ Flask signed Session
                ▼
┌─────────────────────────────────────────────────────────────┐
│ Flask                                                       │
│ app.py       聊天/反馈代理、Session 加载、配置               │
│ auth.py      用户、角色、密码哈希、登录/退出、CSRF、审计     │
│ admin.py     按权限保护的后台路由                            │
│ documents.py 文档版本、审核、同步、索引、RAG、发布状态机     │
│ feedback_store.py 本地反馈镜像                               │
└───────────────┬─────────────────────────────────────────────┘
                │
                ├── Dify Chatflow API（原样保留）
                └── SQLite
                    users / audit_logs / feedback_records
                    documents / document_versions / version_events
```

---

## 3. 技术栈与目录

- 前端：HTML + CSS + 原生 JavaScript
- 后端：Python 3.12 + Flask
- 数据库：SQLite（Python 标准库）
- 认证：Flask 签名 Session + `session_version`
- 密码：Werkzeug `scrypt` 哈希
- AI：Dify Cloud Chatflow + DeepSeek + RAG
- 测试：`unittest` + GitHub Actions

```text
enterprise-ops-ai-assistant/
├── app.py                       # Flask 工厂、聊天、反馈、Session 上下文
├── auth.py                      # 用户/角色/登录/CSRF/审计
├── admin.py                     # 后台路由与权限校验
├── documents.py                 # 文档版本状态机
├── feedback_store.py            # 本地反馈镜像
├── requirements.txt
├── .env.example
├── .gitignore
├── README.md
│
├── templates/
│   ├── index.html
│   ├── auth/login.html
│   └── admin/
│       ├── base.html
│       ├── documents.html
│       ├── document_form.html
│       ├── version_form.html
│       ├── document_detail.html
│       ├── feedback.html
│       ├── users.html
│       ├── user_form.html
│       ├── roles.html
│       ├── audit.html
│       └── error.html
│
├── static/
│   ├── css/style.css
│   ├── css/admin.css
│   ├── css/login.css
│   └── js/app.js / admin.js
│
├── tests/
│   ├── test_app.py              # 22 项聊天/反馈
│   ├── test_documents.py        # 14 项文档工作流/RBAC
│   └── test_rbac.py             # 10 项账号/角色/审计
│
├── docs/dify-sync-workflow.md
└── .github/workflows/tests.yml
```

---

## 4. 快速开始

### 4.1 安装

```powershell
cd "D:\你的路径\enterprise-ops-ai-assistant"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

### 4.2 配置 `.env`

```powershell
Copy-Item .env.example .env
notepad .env
```

至少填写：

```dotenv
DIFY_API_KEY=app-你的Dify应用Key

INITIAL_ADMIN_USERNAME=admin
INITIAL_ADMIN_PASSWORD=至少8位的强密码
INITIAL_ADMIN_DISPLAY_NAME=系统管理员

SECRET_KEY=一段足够长的随机字符串
```

生成 `SECRET_KEY`：

```powershell
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

说明：

- 只有当 `users` 表为空时，`INITIAL_ADMIN_*` 才会创建初始管理员；
- 创建完成后建议清空 `INITIAL_ADMIN_PASSWORD`，账号已经保存的是 scrypt 哈希；
- 兼容旧版 `.env` 的 `ADMIN_USERNAME` / `ADMIN_PASSWORD`：首次启动且无用户时会迁移为初始管理员；旧密码可能不足 8 位，登录后请在用户管理中重置；
- 新密码策略仍为至少 8 位。

### 4.3 启动

```powershell
python app.py
```

访问：

```text
登录：  http://127.0.0.1:5000/login
聊天：  http://127.0.0.1:5000/
后台：  http://127.0.0.1:5000/admin/documents
```

首次启动自动创建：

```text
instance/ops_assistant.sqlite3
```

### 4.4 另一种初始化方式

不配置初始管理员密码时，可以用隐藏输入的命令创建：

```powershell
.\.venv\Scripts\python.exe -m flask --app app create-admin
```

密码只通过隐藏输入读取，保存 scrypt 哈希，不写入代码或日志。

---

## 5. 登录、退出与 Session

### 登录

- 账号由管理员在「用户管理」中创建；
- 登录成功后：

| 角色 | 登录后跳转 |
| --- | --- |
| 普通员工 | 聊天页面 `/` |
| 运维人员 | 文档管理 `/admin/documents` |
| 管理员 | 文档管理 `/admin/documents` |

### Session 安全

- Flask 签名 Session Cookie，`HttpOnly` + `SameSite=Lax`；
- 数据库 `users.session_version` 做服务端失效校验；
- 退出时递增 `session_version`，**旧的登录 Cookie 立即失效**；
- 修改角色、停用账号、重置密码也会递增版本，让旧会话失效；
- Session 默认有效期 8 小时，可通过 `SESSION_HOURS` 调整。

### 聊天页公开性

为保留既有问答体验，聊天页和聊天 API 保持公开；登录后聊天页会显示当前角色和后台入口。**所有管理路由都要求登录并做角色校验。**

---

## 6. 管理后台页面

| 页面 | 路径 | 权限 |
| --- | --- | --- |
| 文档管理 | `/admin/documents` | operator/admin |
| 文档详情 | `/admin/documents/<id>` | operator/admin |
| 新建文档 | `/admin/documents/new` | operator/admin |
| 新增版本 | `/admin/documents/<id>/versions/new` | operator/admin |
| 编辑草稿 | `/admin/versions/<id>/edit` | operator/admin |
| 反馈记录 | `/admin/feedback` | operator/admin |
| 用户管理 | `/admin/users` | admin |
| 角色权限 | `/admin/roles` | admin |
| 操作日志 | `/admin/audit` | admin |

### 文档工作流

```text
新建 v1 草稿
  → 运维/管理员提交审核
  → 管理员审核通过 / 驳回
  → 运维下载 Markdown 并更新 Dify
  → 运维登记同步说明 + 索引结果
  → 运维在聊天页做 RAG 验证并登记结果
  → 管理员发布
  → 旧发布版本自动归档
```

发布条件由后端强制：

- 审核通过；
- Dify 同步已登记；
- Dify 索引成功；
- RAG 验证通过；
- 提交人不能是审核人；
- 发布人必须是管理员。

### 反馈记录

- Dify 仍是反馈权威来源；
- 每次 Dify 反馈成功后，本地额外保存一份镜像；
- 运维人员和管理员可查看；
- 普通员工不可访问。

### 用户管理

- 创建唯一账号；
- 分配 employee/operator/admin；
- 启用/停用；
- 重置密码；
- 不能停用或降级最后一个启用状态的管理员；
- 管理员不能修改自己的角色或停用自己；
- 密码只保存 scrypt 哈希。

### 角色权限

页面展示三角色完整权限矩阵。角色定义是系统安全边界，不开放随意改权限；管理员通过「用户管理」为用户分配角色。

### 操作日志

记录：

- 登录成功/失败、退出；
- 创建用户、修改用户、重置密码；
- 创建文档、新增/编辑版本、提交审核；
- 审核、Dify 同步、RAG 验证、发布；
- 操作人、时间、对象、结果、IP 和说明；
- 不记录密码、Token 或 API Key。

---

## 7. 接口权限说明

### 公开接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/` | 聊天页面，保持公开 |
| GET/POST | `/login` | 登录页和登录提交 |
| POST | `/api/chat` | Dify 问答代理 |
| POST | `/api/feedback` | 点赞/点踩，成功后写本地镜像 |
| GET | `/api/health` | 配置状态 |

### 登录后接口

| 方法 | 路径 | 最低权限 |
| --- | --- | --- |
| POST | `/logout` | 已登录 + CSRF |
| GET | `/admin/documents` | admin.access + documents.view |
| GET/POST | `/admin/documents/new` | documents.create |
| GET | `/admin/documents/<id>` | documents.view |
| GET/POST | `/admin/documents/<id>/edit` | documents.edit |
| GET/POST | `/admin/documents/<id>/versions/new` | documents.create |
| GET/POST | `/admin/versions/<id>/edit` | documents.edit |
| POST | `/admin/versions/<id>/submit` | documents.submit |
| POST | `/admin/versions/<id>/review` | documents.review（仅 admin） |
| POST | `/admin/versions/<id>/sync` | documents.sync |
| POST | `/admin/versions/<id>/rag` | documents.rag |
| POST | `/admin/versions/<id>/publish` | documents.publish（仅 admin） |
| GET | `/admin/versions/<id>/download` | documents.download |
| GET | `/admin/feedback` | feedback.view |
| GET | `/admin/users` | users.manage（仅 admin） |
| GET | `/admin/roles` | roles.view（仅 admin） |
| GET | `/admin/audit` | audit.view（仅 admin） |

所有后台 POST 都要求有效 CSRF token。未登录访问后台会重定向登录；普通员工访问后台返回 403。

### 聊天/反馈 API

原有接口契约不变：

```text
POST /api/chat
POST /api/feedback
```

Dify 请求仍使用 `.env` 中 `DIFY_API_KEY`，不会进入前端。

---

## 8. 数据模型

同一个 SQLite 文件：

### `users`

账号、显示名、scrypt 密码哈希、角色、启用状态、`session_version`、最后登录时间。

### `documents` / `document_versions`

文档元信息、Dify 数据集/文档 ID，以及每个版本的：

- 更新原因、更新人、内容 SHA-256；
- 提交人/提交时间；
- 审核状态、审核人、审核意见；
- 发布状态、发布时间；
- Dify 同步、索引状态；
- RAG 验证问题、结果、验证人/时间。

### `feedback_records`

本地反馈镜像：`message_id`、rating、reason、comment、反馈人、时间。

### `audit_logs`

登录、用户管理、文档工作流的关键操作记录。

### `version_events`

单个版本的操作时间线（创建、编辑、提交、审核、同步、RAG、发布、归档）。

---

## 9. Dify 衔接流程

完整指导：[docs/dify-sync-workflow.md](docs/dify-sync-workflow.md)

V1.4 是**人工确认同步**：

1. 运维新增版本并提交审核；
2. 管理员审核通过；
3. 运维下载/复制 Markdown；
4. 在 Dify 替换对应文档，等待重新分段和索引；
5. 运维在后台登记同步说明与索引结果；
6. 运维在聊天页执行 RAG 测试，登记验证结果；
7. 管理员发布；
8. 旧版本自动归档。

不自动调用 Dify 知识库写接口，因为写操作需要独立 Knowledge API Key，且索引是异步的。官方接口：

```text
POST /datasets/{dataset_id}/documents/{document_id}/update-by-text
```

参考：[Dify Update Document by Text](https://docs.dify.ai/en/api-reference/documents/update-document-by-text)

---

## 10. 安全设计

| 要求 | 实现 |
| --- | --- |
| 密码不明文 | Werkzeug scrypt 哈希 |
| 安全 Session | 签名 Cookie + `session_version` 服务端校验 |
| 未授权访问 | 每个后台路由权限装饰器 |
| 前端隐藏 | Jinja 根据 `can()` 隐藏菜单/按钮 |
| CSRF | 登录、退出和所有后台 POST 校验 |
| 初始管理员 | `INITIAL_ADMIN_*` 或隐藏输入 CLI |
| 旧版兼容 | 旧 `ADMIN_PASSWORD` 仅用于首次迁移，建议重置 |
| 防自审 | 提交人 ID 与审核人 ID 比较 |
| 防越权发布 | 只有 `documents.publish`（admin）可发布 |
| Dify 发布门槛 | 审核 + 同步 + 索引 + RAG 全部满足 |
| 敏感信息 | `.env`、SQLite、截图、虚拟环境均 Git 忽略 |
| 日志 | 不记录密码/Token/API Key |

---

## 11. 测试结果

```powershell
python -m unittest discover -s tests -v
```

结果：

```text
Ran 46 tests
OK
```

构成：

- 22 项原有聊天/反馈回归；
- 14 项文档工作流 + 角色边界；
- 10 项认证/用户/角色/反馈/审计。

覆盖要求中的场景：

1. 普通员工无法进入后台；
2. 普通员工无法调用发布接口；
3. 运维人员可以创建文档版本；
4. 运维人员不能审核（包括自己提交的版本）；
5. 运维人员不能发布；
6. 管理员可以审核；
7. 管理员可以发布满足条件的版本；
8. 未登录不能访问管理路由；
9. 退出后旧 Session 失效；
10. 原有聊天、反馈、文档工作流正常。

GitHub Actions 会执行同一套测试。

---

## 12. 常见问题

### 没有账号 / 登录页提示未初始化

设置 `.env`：

```dotenv
INITIAL_ADMIN_PASSWORD=至少8位密码
```

重启，或运行：

```powershell
.\.venv\Scripts\python.exe -m flask --app app create-admin
```

### 旧版 ADMIN_PASSWORD 还能用吗

如果数据库还没有用户，旧版 `ADMIN_PASSWORD` 会被兼容迁移为初始管理员。旧密码可能少于 8 位，登录后请在「用户管理 → 编辑」重置为强密码。之后建议改用 `INITIAL_ADMIN_*` 并删除旧变量。

### 管理员不能审核某个版本

如果该版本是你自己提交的，系统会阻止自审。请让另一位管理员审核。

### 运维人员看不到发布按钮

这是设计行为。运维人员只负责同步、索引和 RAG 验证，最终发布必须由管理员完成。

### Dify 索引成功但还不能发布

需要再完成 RAG 验证并登记 `passed`。

### 后台 403

- 普通员工不能访问后台；
- 运维人员不能访问用户、角色、审计页面；
- 确认当前账号角色。

### 5000 端口占用

```dotenv
PORT=5001
```

---

## 13. 已知限制

- 聊天页保持公开，管理后台强制登录；
- 三角色权限矩阵内置，不支持页面自由编辑权限；
- 没有邮件/企业微信通知；
- SQLite 适合单机/小团队，不适合高并发多实例；
- Dify 知识库更新仍为人工确认流程；
- 没有版本 diff 和文件上传；
- Session 版本机制会让同账号在修改角色/退出后，其他设备的旧会话同时失效。

---

## 14. GitHub

```powershell
git status
git add .
git commit -m "feat: add RBAC for roles and document workflow"
git push
```

提交前确认：

```powershell
git check-ignore .env instance/ .venv
```

**版本**：V1.4 · Python Flask / SQLite / Dify Cloud / DeepSeek / RAG
