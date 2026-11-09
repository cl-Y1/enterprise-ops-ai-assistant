# 测试报告

> 项目：企业智能运维知识助手 V1.4<br>
> 测试日期：2026-11-09<br>
> 测试环境：Windows 11 · Python 3.12.6 · Flask 3.1.3 · SQLite<br>
> 测试对象：聊天/反馈、文档版本工作流、三角色权限、Session、审计

## 1. 测试结论

```text
Ran 46 tests in 32.435s
OK
```

- 46 项自动化测试全部通过；
- GitHub Actions `tests` 工作流结论：**success**；
- 浏览器实际页面验收通过；
- 原有聊天、点赞/点踩、反馈和文档功能保持可用；
- 权限越权路径均由后端拦截。

GitHub Actions run：

<https://github.com/cl-Y1/enterprise-ops-ai-assistant/actions/runs/42204837977>

对应提交：

```text
a2c93c9 feat: add role-based access control v1.4
```

## 2. 测试环境

| 项 | 值 |
| --- | --- |
| 操作系统 | Windows 11 |
| Python | 3.12.6 |
| Flask | 3.1.3 |
| requests | 2.34.2 |
| python-dotenv | 1.2.4 |
| 数据库 | SQLite（Python 标准库） |
| 浏览器验收 | Microsoft Edge Headless 1440×1000 |
| 自动化框架 | Python `unittest` |

## 3. 测试命令

```powershell
cd "D:\tmp\sop_模拟\ops_assit\enterprise-ops-ai-assistant"
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
```

结果摘要：

```text
Ran 46 tests
OK
```

## 4. 测试构成

| 测试文件 | 数量 | 覆盖范围 |
| --- | ---: | --- |
| `tests/test_app.py` | 22 | 原有聊天、点赞/点踩、反馈、Dify 异常、密钥保护 |
| `tests/test_documents.py` | 14 | 文档版本、审核、发布、Dify 索引、RAG、自审、前端隐藏 |
| `tests/test_rbac.py` | 10 | 登录、用户、角色、反馈页、审计、Session 失效 |
| **合计** | **46** | |

## 5. 需求测试对照

| # | 测试要求 | 测试结果 | 证据 |
| --- | --- | --- | --- |
| 1 | 普通员工无法进入文档管理后台 | 通过：403 | `test_employee_cannot_access_admin_or_publish` |
| 2 | 普通员工无法调用文档发布接口 | 通过：403，版本仍 unpublished | 同上 |
| 3 | 运维人员可以创建文档版本 | 通过：创建 v1 草稿 | `test_operator_can_create_and_submit_but_cannot_review_or_publish` |
| 4 | 运维人员不能审核自己提交的文档 | 通过：审核路由 403；管理员自审也拦截 | 同上；`test_admin_can_review_but_cannot_review_own_submission` |
| 5 | 运维人员不能发布文档 | 通过：403，状态不变 | 同上 |
| 6 | 管理员可以审核文档 | 通过：pending → approved | `test_admin_can_review_but_cannot_review_own_submission` |
| 7 | 管理员可以发布符合条件的版本 | 通过：审核 + 同步 + 索引 + RAG 后 published | `test_publish_requires_sync_index_and_rag_for_dify_document` |
| 8 | 未登录用户不能访问管理 API | 通过：重定向 `/login` | `test_unauthenticated_admin_is_redirected` |
| 9 | 用户退出后旧 Session 不能继续使用 | 通过：重放旧 Session 被拒绝 | `test_logout_invalidates_old_session_cookie` |
| 10 | 原有聊天、反馈、文档功能正常 | 通过：22 项回归 + 14 项工作流 | `test_app.py`、`test_documents.py` |

## 6. 文档工作流测试

| 测试 | 结果 |
| --- | --- |
| 新建文档并生成 v1 草稿 | 通过 |
| Dify 数据集/文档 ID 必须成对 | 通过 |
| 编辑文档元信息 | 通过 |
| 草稿被驳回后编辑并重提 | 通过 |
| 审核驳回必须填写意见 | 通过 |
| 审核通过 | 通过 |
| Dify 同步登记 + 索引成功 | 通过 |
| Dify 索引失败时禁止发布 | 通过 |
| RAG 未通过时禁止发布 | 通过 |
| RAG 通过后管理员发布 | 通过 |
| 新版本发布后旧版本 archived | 通过 |
| 无 Dify 关联文档的本地发布 | 通过 |
| 下载 Markdown | 通过 |
| 非法版本归属返回 404 | 通过 |
| 前端隐藏发布按钮 | 通过 |

## 7. RBAC 测试

| 测试 | 结果 |
| --- | --- |
| 管理员/运维/员工登录后跳转 | 通过 |
| 登录失败提示 | 通过 |
| 密码保存为 scrypt/pbkdf2 哈希 | 通过 |
| 管理员创建用户 | 通过 |
| 员工不能访问用户/角色/审计 | 通过 |
| 运维可看反馈，但不可看用户/角色/审计 | 通过 |
| 管理员可看全部后台页面 | 通过 |
| 角色变更使旧 Session 失效 | 通过 |
| 退出使旧 Session 失效 | 通过 |
| 本地反馈镜像可查看 | 通过 |
| 未登录 POST 管理路由被拒绝 | 通过 |

## 8. 聊天/反馈回归

原有 22 项测试继续通过，包含：

- `/api/chat` 请求契约；
- 多轮 `conversation_id`；
- 点赞/点踩请求；
- 反馈原因 + 补充说明拼接；
- 重复反馈拦截；
- 空问题、超长内容、非法 UUID；
- Dify 401/404/429/超时/断网；
- 空回答；
- API Key 不出现在 HTML/JS/CSS/错误响应；
- 安全响应头。

## 9. 浏览器验收

使用 Edge Headless 实际访问本地服务，完成：

1. 打开登录页；
2. 使用管理员账号登录；
3. 查看管理员文档后台；
4. 查看用户管理；
5. 查看角色权限矩阵；
6. 打开文档审核页；
7. 以运维人员登录；
8. 查看 Dify 同步 / RAG 验证页；
9. 在聊天页提问并查看回答；
10. 点击点踩并打开反馈弹窗。

截图：

- [登录页](../screenshots/01-login.png)
- [文档管理](../screenshots/02-document-management.png)
- [文档审核](../screenshots/03-document-review.png)
- [角色权限](../screenshots/04-role-permissions.png)
- [用户管理](../screenshots/05-user-management.png)
- [运维 RAG 验证](../screenshots/06-operator-rag.png)
- [聊天与反馈按钮](../screenshots/07-chat.png)
- [点踩原因弹窗](../screenshots/08-feedback.png)

> 截图来自实际运行页面，数据为本地演示数据。聊天截图使用本地模拟 Dify 回答，仅用于界面验收，不代表真实知识库回答质量。

## 10. 安全测试

| 项 | 结果 |
| --- | --- |
| 密码明文存储 | 未发现；使用 scrypt 哈希 |
| API Key 前端暴露 | 未发现 |
| 未登录访问后台 | 重定向登录 |
| 员工越权后台 | 403 |
| 运维越权审核/发布 | 403 |
| 提交人自审 | 后端拒绝 |
| 退出后旧 Session | 版本失效 |
| 改角色/停用后旧 Session | 版本失效 |
| CSRF | 后台 POST 必需 |
| `.env` 进入 Git | 未发生；已忽略 |
| SQLite/截图进入 Git | 运行数据和验收截图分别按策略处理 |

## 11. 已知测试限制

- 自动化测试通过 `unittest.mock` 模拟 Dify；没有在 CI 中调用真实 Dify 知识库；
- 真实 RAG 回答质量、Dify 索引状态和真实知识库同步需要在配置真实 Key 后人工验收；
- 浏览器截图使用本地模拟 Dify 回答做界面验证；
- 没有进行压力测试和多实例并发测试；
- SQLite 单机部署，未测试 PostgreSQL/Redis 改造。

## 12. 复现说明

```powershell
# 1. 安装依赖
python -m pip install -r requirements.txt

# 2. 运行测试
python -m unittest discover -s tests -v

# 3. 启动应用
python app.py
```

测试不要求真实 Dify Key；聊天相关测试会 mock Dify 响应。

## 13. 相关文档

- [系统架构](architecture.md)
- [业务流程](business-flow.md)
- [角色权限矩阵](permissions.md)
- [Dify 更新衔接流程](dify-sync-workflow.md)
