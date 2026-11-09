# 角色权限矩阵

> 企业智能运维知识助手 V1.4<br>
> 以 `auth.py` 中的 `ROLE_PERMISSIONS` 和 `admin.py` 中的 `permission_required` 为准。

## 1. 角色定义

| 角色代码 | 角色 | 定位 |
| --- | --- | --- |
| `employee` | 普通员工 | 使用知识问答、点赞点踩与文字反馈 |
| `operator` | 运维人员 | 维护文档版本、Dify 同步、索引与 RAG 验证 |
| `admin` | 管理员 | 审核发布、用户角色、反馈与审计全局管理 |

## 2. 完整权限矩阵

| 能力 | 权限代码 | employee | operator | admin |
| --- | --- | :---: | :---: | :---: |
| 使用 AI 知识问答 | `chat.use` | ✓ | ✓ | ✓ |
| 点赞/点踩/文字反馈 | `feedback.submit` | ✓ | ✓ | ✓ |
| 查看反馈记录 | `feedback.view` | — | ✓ | ✓ |
| 进入管理后台 | `admin.access` | — | ✓ | ✓ |
| 查看文档与历史版本 | `documents.view` | — | ✓ | ✓ |
| 创建文档/版本 | `documents.create` | — | ✓ | ✓ |
| 编辑文档信息/草稿 | `documents.edit` | — | ✓ | ✓ |
| 提交文档审核 | `documents.submit` | — | ✓ | ✓ |
| 下载/复制 Markdown | `documents.download` | — | ✓ | ✓ |
| 登记 Dify 同步/索引 | `documents.sync` | — | ✓ | ✓ |
| 维护 Dify 数据集/文档 ID | `documents.dify` | — | ✓ | ✓ |
| 执行/登记 RAG 验证 | `documents.rag` | — | ✓ | ✓ |
| 审核/驳回文档 | `documents.review` | — | — | ✓ |
| 发布文档版本 | `documents.publish` | — | — | ✓ |
| 管理历史版本 | `documents.history` | — | — | ✓ |
| 管理用户与角色 | `users.manage` | — | — | ✓ |
| 查看角色权限矩阵 | `roles.view` | — | — | ✓ |
| 查看操作日志 | `audit.view` | — | — | ✓ |

> 说明：聊天页保留公开入口；未登录用户可以使用问答，但不能进入任何管理后台。角色权限矩阵是内置安全策略，管理员不能从页面随意修改权限定义。

## 3. 页面级权限

| 页面/动作 | 路径 | 最低要求 |
| --- | --- | --- |
| 聊天 | `GET /` | 公开 |
| 登录 | `GET/POST /login` | 公开 |
| 退出 | `POST /logout` | 登录 + CSRF |
| 文档列表 | `GET /admin/documents` | `admin.access` + `documents.view` |
| 新建文档 | `GET/POST /admin/documents/new` | `documents.create` |
| 文档详情 | `GET /admin/documents/<id>` | `documents.view` |
| 编辑文档信息 | `GET/POST /admin/documents/<id>/edit` | `documents.edit` |
| 新增版本 | `GET/POST /admin/documents/<id>/versions/new` | `documents.create` |
| 编辑草稿 | `GET/POST /admin/versions/<id>/edit` | `documents.edit` |
| 提交审核 | `POST /admin/versions/<id>/submit` | `documents.submit` |
| 审核/驳回 | `POST /admin/versions/<id>/review` | `documents.review` |
| 登记同步/索引 | `POST /admin/versions/<id>/sync` | `documents.sync` |
| 登记 RAG | `POST /admin/versions/<id>/rag` | `documents.rag` |
| 发布 | `POST /admin/versions/<id>/publish` | `documents.publish` |
| 下载版本 | `GET /admin/versions/<id>/download` | `documents.download` |
| 反馈记录 | `GET /admin/feedback` | `feedback.view` |
| 用户管理 | `GET /admin/users` | `users.manage` |
| 角色权限 | `GET /admin/roles` | `roles.view` |
| 操作日志 | `GET /admin/audit` | `audit.view` |

## 4. 后端强制规则

### 4.1 未登录

- 访问 `/admin/**` 会被重定向到 `/login`；
- 登录后只会跳到有权限的页面；
- 未登录不能通过表单或直接 POST 执行管理动作。

### 4.2 普通员工

- 访问任何 `/admin/**` 返回 **403**；
- 不能创建、编辑、审核、发布文档；
- 不能查看反馈记录、用户、角色或审计日志；
- 仍可使用聊天、点赞、点踩和文字反馈。

### 4.3 运维人员

- 允许文档查看、创建、编辑草稿、提交审核；
- 允许下载 Markdown、登记 Dify 同步/索引、登记 RAG；
- 审核、发布、用户管理、角色、审计均为 **403**。

### 4.4 管理员

- 拥有全部权限；
- 审核、发布、用户角色、反馈和审计；
- **不能审核自己提交的版本**；
- **不能修改自己的角色或停用自己**；
- 不能停用或降级最后一个启用状态的管理员。

## 5. 文档审核与发布规则

### 审核

- 只有 `documents.review`（管理员）可以审核；
- 只有 `pending` 状态可以审核；
- 提交人记录在 `submitted_by_user_id`；
- 审核人 ID 与提交人 ID 相同 → 拒绝；
- 驳回必须填写审核意见。

### 发布

管理员发布前，后端检查：

| 条件 | 说明 |
| --- | --- |
| `review_status=approved` | 必须审核通过 |
| `submitted_by_user_id != reviewer_id` | 不能自审 |
| `dify_sync_status=synced` | 已登记同步（关联 Dify 时） |
| `dify_index_status=success` | Dify 索引成功（关联 Dify 时） |
| `rag_status=passed` | RAG 验证通过（关联 Dify 时） |
| `publish_status=unpublished` | 未发布或归档 |
| 角色为 admin | 拥有 `documents.publish` |

未关联 Dify 的本地文档：

- 审核通过后可由管理员直接发布；
- `dify_index_status` / `rag_status` 为 `not_required`。

## 6. Session 与 CSRF

| 安全点 | 实现 |
| --- | --- |
| 密码 | Werkzeug scrypt 哈希 |
| Session | Flask 签名 Cookie |
| Cookie | `HttpOnly` + `SameSite=Lax` |
| 旧会话失效 | `users.session_version` 对比 |
| 退出 | 版本 +1 + `session.clear()` |
| 改角色/停用/重置密码 | 版本 +1 |
| CSRF | 登录、退出、所有后台 POST |
| 登录失败 | 审计记录；通用错误文案 |

### 为什么退出后旧 Session 会失效

```text
登录: session.auth_version = user.session_version (例如 3)
退出: UPDATE users SET session_version = 4
旧 Cookie 再次请求:
  session.auth_version(3) != users.session_version(4)
  → session.clear() → 重新登录
```

## 7. 前端隐藏与后端校验

前端 Jinja 使用 `can(permission)` 控制：

- 管理后台菜单；
- 新建文档/版本按钮；
- 编辑草稿按钮；
- 审核/发布表单；
- Dify 同步/RAG 表单；
- 用户/角色/审计菜单；
- 退出按钮。

但是前端隐藏不是安全边界：

- 每个后台路由都有 `permission_required`；
- 每个后台 POST 都校验 CSRF；
- 直接调用发布接口的运维人员仍会得到 **403**；
- 直接调用审核接口的普通员工仍会得到 **403**。

## 8. 接口权限速查

| 接口 | 公开 | 登录 | operator | admin |
| --- | :---: | :---: | :---: | :---: |
| `POST /api/chat` | ✓ | ✓ | ✓ | ✓ |
| `POST /api/feedback` | ✓ | ✓ | ✓ | ✓ |
| `POST /logout` | — | ✓ | ✓ | ✓ |
| `GET /admin/documents` | — | — | ✓ | ✓ |
| `POST /admin/versions/<id>/review` | — | — | — | ✓ |
| `POST /admin/versions/<id>/publish` | — | — | — | ✓ |
| `GET /admin/feedback` | — | — | ✓ | ✓ |
| `GET /admin/users` | — | — | — | ✓ |
| `GET /admin/roles` | — | — | — | ✓ |
| `GET /admin/audit` | — | — | — | ✓ |

## 9. 测试对应

权限相关测试位于：

- `tests/test_documents.py`：员工越权、运维不能审核/发布、管理员审核/发布、自审拦截、前端按钮隐藏；
- `tests/test_rbac.py`：登录跳转、用户管理、角色页面、反馈页、审计页、退出失效、角色变更失效。

测试报告见 [测试报告](test-report.md)。
