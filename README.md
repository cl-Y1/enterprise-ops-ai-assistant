# 企业智能运维知识助手 V1.2

> 基于 **Dify Chatflow + DeepSeek + RAG** 的轻量企业运维知识问答页面，支持多轮对话、点赞/点踩、点踩原因与文字反馈。
>
> GitHub 仓库：<https://github.com/cl-Y1/enterprise-ops-ai-assistant>

本项目不重新开发 RAG，也不修改原有 Chatflow 的核心逻辑。V1.2 在现有 Dify 应用之上增加一个独立的 Flask Web 页面，把聊天和反馈请求统一放在后端转发，Dify API Key 不进入浏览器。

---

## 1. 项目目标

帮助普通员工查询运维知识，帮助运维人员检索故障排查方案，并把“回答是否有用”的反馈沉淀到 Dify 原生日志中。

V1.2 实现：

- 用户输入问题，调用 Dify Chatflow API；
- 展示 AI 回答，支持连续多轮对话；
- 每条 AI 回答下方有点赞、点踩按钮；
- 点踩后选择原因，并可填写补充说明；
- 反馈提交到 Dify 消息反馈 API；
- 成功、失败、超时、空回答都有中文提示；
- 不引入额外数据库，反馈直接记录在 Dify。

---

## 2. 功能清单

| 功能 | 实现方式 |
| --- | --- |
| 多轮对话 | 前端保存后端返回的 `conversation_id`，下一轮原样传回 |
| 展示回答 | 调用 `POST /v1/chat-messages`，`response_mode=blocking` |
| 单条消息反馈 | 每条 AI 消息单独保存 `message_id` |
| 点赞 | 调用 `POST /v1/messages/{message_id}/feedbacks`，`rating=like` |
| 点踩 | 弹窗选择原因，提交 `rating=dislike` 和 `content` |
| 防止重复反馈 | 前端锁定按钮 + 后端进程内登记表双重校验 |
| 密钥保护 | API Key 只在 Flask 后端环境变量中读取 |
| 异常处理 | 超时、断网、401、404、429、空回答均返回脱敏中文提示 |
| 数据存储 | 第一版使用 Dify 原生消息反馈记录，不引入数据库 |

---

## 3. 系统架构

```text
┌──────────────────────────────┐
│ Windows 浏览器                │
│ HTML + CSS + 原生 JavaScript │
│ - 聊天界面                    │
│ - 点赞/点踩弹窗               │
│ - 不接触 Dify API Key         │
└──────────────┬───────────────┘
               │ 同源 HTTP / JSON
               ▼
┌──────────────────────────────┐
│ Flask 后端 app.py             │
│ - 输入校验                    │
│ - 隐藏 API Key                │
│ - 调用 Dify App API           │
│ - 统一异常与错误脱敏           │
│ - 防重复反馈登记               │
└──────────────┬───────────────┘
               │ Authorization: Bearer {DIFY_API_KEY}
               ▼
┌──────────────────────────────┐
│ Dify Cloud Chatflow           │
│ - RAG 知识库检索              │
│ - DeepSeek 生成回答           │
│ - 原生消息反馈记录             │
└──────────────────────────────┘
```

请求链路：

1. 浏览器 `POST /api/chat` → Flask；
2. Flask 带上服务端 API Key，请求 Dify `/v1/chat-messages`；
3. Dify 执行原有 Chatflow、检索知识库、调用 DeepSeek；
4. Flask 只把 `answer`、`conversation_id`、`message_id` 返回浏览器；
5. 用户点赞/点踩 → Flask `/api/feedback` → Dify 消息反馈 API。

---

## 4. 目录结构

```text
enterprise-ops-ai-assistant/
├── app.py                  # Flask 后端：聊天、反馈、校验、异常处理
├── requirements.txt        # Python 依赖
├── .env.example            # 环境变量示例，不含真实密钥
├── .gitignore              # 排除 .env、虚拟环境、缓存
├── README.md
│
├── templates/
│   └── index.html          # 聊天页面与反馈弹窗
│
├── static/
│   ├── css/
│   │   └── style.css       # 浅色蓝色主题、消息与弹窗样式
│   └── js/
│       └── app.js          # 聊天交互、反馈提交、前端校验
│
└── tests/
    ├── __init__.py
    └── test_app.py         # 22 项自动化测试（模拟 Dify 响应）
```

---

## 5. 环境要求

已在以下环境验证：

- Windows 11
- Python **3.12.6**
- Flask 3.1.3
- requests 2.34.2
- python-dotenv 1.2.4
- 可访问 `https://api.dify.ai`
- 已完成并发布一个 Dify Chatflow，且已开启 API 访问

Python 3.10 及以上均可尝试使用。

---

## 6. 快速开始（Windows PowerShell）

### 6.1 进入项目目录

```powershell
cd "D:\你的路径\enterprise-ops-ai-assistant"
```

### 6.2 创建并激活虚拟环境

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

如果 PowerShell 提示“禁止运行脚本”，只对当前窗口临时放行：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

### 6.3 安装依赖

```powershell
python -m pip install -r requirements.txt
```

如果 `python` 命令不可用，可改用 Windows 的 Python 启动器：

```powershell
py -3.12 -m venv .venv
```

### 6.4 配置环境变量

```powershell
Copy-Item .env.example .env
notepad .env
```

在 `.env` 中填入你的 **Dify 应用 API Key**：

```dotenv
DIFY_API_KEY=app-你的真实应用Key
DIFY_API_BASE_URL=https://api.dify.ai/v1
DIFY_USER_ID=demo-user-001
DIFY_TIMEOUT=60
HOST=127.0.0.1
PORT=5000
FLASK_DEBUG=0
```

获取方式：

1. 打开 Dify 中已发布的应用；
2. 进入「访问 API」或「API 访问」页面；
3. 创建一个 **应用 API Key**（通常以 `app-` 开头）；
4. 不要使用知识库 API Key，两者用途不同。

> `.env` 已被 `.gitignore` 忽略。不要把真实 Key 写入 HTML、JavaScript、README 或截图。

### 6.5 启动

```powershell
python app.py
```

看到以下地址后，在浏览器打开：

```text
http://127.0.0.1:5000
```

页面右上角会显示：

- **服务已配置**：后端读到了 `DIFY_API_KEY`（只表示已配置，不校验 Key 是否有效）；
- **待配置 API Key**：`.env` 未配置或 Key 为空；
- **服务状态未知**：Flask 服务不可达。

---

## 7. Dify 端需要检查什么

本项目 **不修改原有 Chatflow、不修改知识库、不重新开发 RAG**。只需要确认：

1. Chatflow 已发布，不要使用草稿版本；
2. 应用已开启 API 访问；
3. `.env` 中的 Key 与这个应用匹配；
4. `DIFY_USER_ID` 在聊天与反馈请求中保持一致（后端已自动保证）；
5. Dify 应用的输入表单没有必填变量。本项目发送 `inputs: {}`，如果你的 Chatflow 新增了必填输入变量，需要同步扩展前端。

官方文档：

- [发送对话消息](https://docs.dify.ai/zh/api-reference/chat-messages/send-chat-message)
- [提交消息反馈](https://docs.dify.ai/zh/api-reference/feedback/submit-message-feedback)
- [查看日志](https://docs.dify.ai/zh/cloud/use-dify/monitor/logs)

---

## 8. 后端接口说明

### 8.1 `GET /api/health`

仅检查后端是否已读取到 Key，不验证 Key 是否有效，也不会返回 Key。

```json
{
  "ok": true,
  "configured": true,
  "service": "企业智能运维知识助手",
  "version": "1.2"
}
```

### 8.2 `POST /api/chat`

请求：

```json
{
  "query": "CBS 与 TDH 数据记录数量不一致时，应该如何排查？",
  "conversation_id": ""
}
```

首次对话传空字符串；后续把上一轮返回的 `conversation_id` 传回。

成功响应：

```json
{
  "ok": true,
  "answer": "建议按以下顺序排查……",
  "message_id": "9da23599-e713-473b-982c-4328d4f5c78a",
  "conversation_id": "45701982-8118-4bc5-8e9b-64562b4555f2"
}
```

后端实际发往 Dify 的请求：

```json
{
  "inputs": {},
  "query": "用户问题",
  "response_mode": "blocking",
  "user": "demo-user-001",
  "conversation_id": "上一轮返回的会话 ID，第一轮省略"
}
```

错误状态：

| HTTP | 场景 | 页面提示 |
| --- | --- | --- |
| 400 | 空问题、超长问题、非法会话 ID | 具体校验提示 |
| 409 | `conversation_id` 失效 | 点击「新对话」后重试 |
| 429 | Dify 限流 | 当前咨询人数较多 |
| 502 | Dify 不可达、空回答、返回字段不完整 | 通用提示 |
| 503 | 未配置 Key、Key 无效 | 联系管理员检查服务端配置 |
| 504 | 请求超时 | 稍后重试 |

错误响应不会包含 Dify 原始报错、API Key、内部地址或堆栈。

### 8.3 `POST /api/feedback`

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

后端会组合为 Dify 的 `content`：

```text
反馈原因：答案不准确；补充说明：缺少 Service 日志检查步骤
```

实际发往 Dify 的请求：

```json
{
  "rating": "dislike",
  "user": "demo-user-001",
  "content": "反馈原因：答案不准确；补充说明：缺少 Service 日志检查步骤"
}
```

成功响应：

```json
{
  "ok": true,
  "rating": "like",
  "message": "感谢你的认可！"
}
```

点踩成功提示：

```text
感谢反馈，我们将持续优化知识助手。
```

反馈原因限定为：

- 答案不准确
- 回答内容不完整
- 操作步骤已经过时
- 没有解决我的问题
- 知识库没有相关内容
- 其他

同一条 `message_id` 只允许成功提交一次。前端会锁定两个按钮，后端也会拦截重复请求。

---

## 9. 如何在 Dify 控制台查看反馈记录

1. 打开 Dify，进入对应应用；
2. 打开左侧的 **「日志」** 或 **「日志与标注」→「日志」**；
3. 查看日志列表中的 **「用户反馈」** 列，它会汇总该会话的点赞/点踩；
4. 点击对应会话行，打开完整消息记录；
5. 在具体 AI 回答上查看反馈状态、点踩评论和该次运行的追踪信息。

通过 API 产生的聊天也会出现在日志中。用户列显示的是本项目 `.env` 中配置的 `DIFY_USER_ID`（默认 `demo-user-001`），不是浏览器登录账号。

> Dify Cloud 不同版本的菜单名称可能略有差异，但入口都在应用内的日志页面。官方说明：[日志](https://docs.dify.ai/zh/cloud/use-dify/monitor/logs)。

如果日志中能看到问答，但看不到反馈：

- 确认点赞/点踩请求返回了成功提示；
- 确认查看的是同一个 Dify 应用；
- 确认 `DIFY_USER_ID` 没有在聊天与反馈之间变化；
- 刷新日志页面；
- 检查后端控制台是否有 `Dify feedback failed` 日志。

---

## 10. 安全设计

| 要求 | 实现 |
| --- | --- |
| API Key 只在后端 | `app.py` 从 `.env` / 环境变量读取，前端只请求 Flask |
| 不写入 HTML/JS | 页面与 `app.js` 中没有任何 Key；自动化测试会检查 |
| 不上传 `.env` | `.gitignore` 排除 `.env`，保留空白的 `.env.example` |
| 输入校验 | 问题 ≤ 2000 字，补充说明 ≤ 300 字，UUID、rating、reason 白名单校验 |
| 异常脱敏 | 原始 Dify 错误只写服务端日志，浏览器只收到中文通用提示 |
| 模拟数据 | 示例问题均为运维练习场景，不含公司真实 IP、账号、密码 |
| 本地访问 | 默认 `127.0.0.1:5000`，不对公网开放 |
| 浏览器防护 | CSP、`X-Content-Type-Options`、`X-Frame-Options`、API `no-store` |

补充说明：

- 当前 `DIFY_USER_ID` 是演示用固定用户。接入企业登录后，应改为从登录态派生用户 ID，并确保聊天与反馈始终一致；
- 防重复反馈登记表保存在 Flask 进程内存中，重启后清空；多进程部署时应改为 Redis 或数据库；
- 本项目没有实现用户系统、权限系统、审计后台和反馈管理后台，属于 V1.2 轻量版本范围。

---

## 11. 测试记录

### 11.1 自动化测试

在项目根目录运行：

```powershell
python -m unittest discover -s tests -v
```

本次开发环境结果：

```text
Ran 22 tests
OK
```

覆盖范围：

- Dify Chatflow 请求地址、Header、请求体契约；
- 首次对话省略 `conversation_id`；
- 第二轮对话正确复用 `conversation_id`；
- 点赞请求契约与成功文案；
- 点踩原因 + 补充说明拼接；
- 无补充说明时的点踩内容；
- 重复反馈不会二次发送；
- 反馈超时后允许重试；
- 空问题、超长补充说明、非法 message_id、非法会话 ID；
- Dify 401、404、429、超时、断网、空回答；
- API Key 不出现在首页、JS、CSS、健康检查与错误响应中；
- 安全响应头与 API `no-store`。

> 自动化测试通过 `unittest.mock` 模拟 Dify 响应，验证的是本项目与 Dify API 的契约和异常处理，不能代替真实知识库回答质量验收。

### 11.2 本地 HTTP 契约联调（模拟 Dify）

开发时额外启动了一个本地模拟 Dify 服务，让 Flask 通过真实 HTTP 完成以下链路（2026-11-06 执行）：

| 验证项 | 实际结果 |
| --- | --- |
| 首轮聊天 | HTTP 200，返回 `answer`、`conversation_id`、`message_id` |
| 第二轮聊天 | HTTP 200，模拟 Dify 收到与首轮相同的 `conversation_id` |
| 点赞 | HTTP 200，模拟 Dify 收到 `{"rating":"like","user":"demo-user-001"}` |
| 点踩 + 补充说明 | HTTP 200，`content` 为“反馈原因：回答内容不完整；补充说明：缺少 Service 日志检查步骤” |
| 重复反馈 | HTTP 200 + `duplicate: true`，模拟 Dify 端只收到 2 条反馈，没有第三次请求 |
| 真实 Dify 无效 Key | 用故意无效的 Key 请求真实 Dify，返回 401；本项目返回 503 中文鉴权提示，响应中不含该 Key |
| 未配置 Key | `/api/chat` 返回 503，提示联系管理员配置服务端 Key |
| 联调结论 | `E2E_CONTRACT_TEST=PASS` |

> 此联调验证网络请求、参数、错误映射和重复拦截；模拟回答不是 RAG 结果，不能当作知识库质量测试。

### 11.3 浏览器 UI 烟雾测试

使用本机 Edge 无头模式 + DevTools Protocol 实际操作页面（2026-11-06）：

- 在输入框输入 CBS/TDH 问题并点击发送；
- 渲染 AI 回答、Markdown 步骤列表和反馈按钮；
- 点击“有帮助”，等待“已点赞”和“感谢你的认可！”；
- 输入第二个问题，确认第二轮请求完成；
- 点击第二条回答的“没帮助”，打开反馈弹窗；
- 选择“答案不准确”，填写“缺少 Service 日志检查步骤”并提交；
- 等待“已反馈”和“感谢反馈，我们将持续优化知识助手。”。

结果：

```text
/api/chat      200
/api/feedback  200
/api/chat      200
/api/feedback  200
模拟 Dify 收到反馈数：2
浏览器脚本错误：[]
UI_SMOKE_TEST=PASS
```

反馈成功后，同一条消息的点赞、点踩按钮均为禁用状态；后端也只收到两条反馈请求。测试截图不参与 Git 提交。

> 本次 UI 测试使用本地模拟 Dify 的模拟回答，不是真实 RAG 内容。

### 11.4 10 项验收清单

| # | 测试项 | 操作 | 预期结果 | 当前状态 |
| --- | --- | --- | --- | --- |
| 1 | CBS/TDH RAG 回答 | 输入“CBS 与 TDH 数据记录数量不一致时，应该如何排查？” | 返回知识库相关回答，不是空回答 | 待真实 Key 验收（模拟链路已通） |
| 2 | 多轮对话 | 继续追问第二个问题 | 能结合上一轮上下文回答 | 契约已通过，真实上下文待验 |
| 3 | 点赞 | 对回答点击“有帮助” | 显示“感谢你的认可！”，Dify 记录 like | 契约已通过，Dify 记录待验 |
| 4 | 点踩原因 | 点击“没帮助”，选择“答案不准确”并提交 | 显示“感谢反馈，我们将持续优化知识助手。” | 契约已通过，Dify 记录待验 |
| 5 | 点踩补充说明 | 选择“回答内容不完整”，填写补充说明 | Dify 的 `content` 包含原因和补充说明 | 内容拼接已通过，Dify 记录待验 |
| 6 | 防止重复反馈 | 同一条消息再次点击点赞/点踩 | 按钮已锁定，后端返回 duplicate，不重复发送 | 已通过（自动化 + HTTP 联调） |
| 7 | 错误 API Key | 使用无效 Key 启动并提问 | 页面只显示鉴权失败提示，不泄露 Key | 已通过（真实 Dify 401） |
| 8 | 网络异常 | 断开网络或模拟 ConnectionError | 显示网络提示，不展示堆栈 | 已通过（自动化模拟断网） |
| 9 | Key 前端暴露检查 | 浏览器开发者工具查看 HTML/JS/Network | 请求中无 Dify API Key，只有本地 Flask 请求 | 已通过（自动化检查） |
| 10 | Dify 反馈查询 | 按第 9 节路径查看日志 | 能看到点赞/点踩和文字反馈 | 待真实 Key 验收 |

**为什么 1–5、10 还没有全部勾选**：这些项目必须调用你账号下的真实 Dify 应用，才能确认知识库内容、Chatflow 输出和 Dify 日志记录。当前开发环境没有你的 API Key，不能伪造真实 RAG 结果或 Dify 控制台数据。配置 `.env` 后，按上表逐项操作即可完成最终验收。

---

## 12. 常见问题

### 页面显示“待配置 API Key”

确认项目根目录存在 `.env`，并且：

```dotenv
DIFY_API_KEY=app-...
```

保存后重启 Flask。注意 `.env` 必须在 `app.py` 同级目录。

### 提问后提示“鉴权失败”

- 可能填了知识库 API Key，而不是应用 API Key；
- Key 与应用不匹配；
- 应用被删除、禁用或工作空间异常；
- Key 已失效。请到 Dify 重新生成。

### 提示“当前会话已失效”

`conversation_id` 在 Dify 侧不存在。点击页面右上角「新对话」重新开始即可。

### 回答很慢或超时

阻塞模式必须等待完整答案生成。可以：

- 调大 `.env` 的 `DIFY_TIMEOUT`；
- 检查 Dify 中 DeepSeek 模型和知识库检索耗时；
- 后续版本改为流式返回（streaming）。

### 5000 端口被占用

修改 `.env`：

```dotenv
PORT=5001
```

重启后访问 `http://127.0.0.1:5001`。

### 点踩提交失败

- 查看 Flask 控制台中的 `Dify feedback failed` 日志；
- 确认消息来自同一个 Dify 应用的同一个 `DIFY_USER_ID`；
- 确认反馈曾提交成功，避免重复提交；
- 如果消息已过期或会话被删除，刷新页面重新提问。

---

## 13. 已知限制与后续版本

V1.2 有意保持轻量：

- 刷新页面后不保留聊天记录；`conversation_id` 只存在当前页面内存中；
- 不支持流式输出，长回答需要等待；
- 使用固定演示用户 `demo-user-001`，未接入企业登录；
- 防重复反馈只在单进程内有效；
- 没有自建反馈数据库或管理后台，查询依赖 Dify 日志；
- 没有文件上传、语音、引用来源展示。

可演进方向：

- V1.3：SSE 流式输出、引用来源卡片、会话本地恢复；
- V1.4：企业登录、用户 ID 映射、反馈后台、Redis 幂等；
- 生产化：HTTPS、反向代理、限流、审计、监控和密钥托管。

---

## 14. 上传 GitHub 前检查

```powershell
git init
git add .
git status
```

确认暂存区 **没有 `.env`**、`.venv`、日志和真实截图，然后：

```powershell
git commit -m "feat: enterprise ops AI assistant v1.2 with Dify feedback"
git branch -M main
git remote add origin https://github.com/你的用户名/enterprise-ops-ai-assistant.git
git push -u origin main
```

再次确认 `.env` 没有被跟踪：

```powershell
git check-ignore .env
git ls-files | Select-String -Pattern "^\.env$"
```

第二条命令应该没有输出。

如果不小心提交了真实 Key：

1. 立即到 Dify 撤销/轮换该 Key；
2. 从 Git 历史中移除，而不是只删除最新文件；
3. 检查 GitHub 的 secret scanning 告警。

---

## 15. 开发边界说明

- 未修改 Dify 原有 Chatflow 的节点、提示词、知识库和检索配置；
- 未重新实现 RAG；
- 未引入额外数据库；
- 所有示例问题与页面文案均为演示/练习用途；
- 代码中的注释与 README 均使用中文，便于后续维护。

---

**版本**：V1.2 · **技术栈**：HTML + CSS + 原生 JavaScript / Python Flask / Dify Cloud API / DeepSeek / RAG
