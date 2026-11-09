# 业务流程

> 企业智能运维知识助手 V1.4<br>
> 覆盖问答反馈、文档版本、审核发布、Dify 同步与 RAG 验证。

## 1. 角色旅程总览

```mermaid
flowchart TB
    START["进入系统"] --> LOGIN["登录 /login"]

    LOGIN -->|"普通员工"| EMP["聊天页"]
    LOGIN -->|"运维人员"| OPS["文档管理后台"]
    LOGIN -->|"管理员"| ADMIN["文档管理后台"]

    EMP --> ASK["提问"]
    ASK --> LIKE["点赞 / 点踩 / 文字反馈"]

    OPS --> DRAFT["创建文档 / 新增版本 / 编辑草稿"]
    DRAFT --> SUBMIT["提交审核"]

    ADMIN --> REVIEW["审核 / 驳回"]
    REVIEW -->|"通过"| SYNC["Dify 同步 + 索引"]
    REVIEW -->|"驳回"| DRAFT

    SYNC --> RAG["RAG 验证"]
    RAG -->|"通过"| PUBLISH["管理员发布"]
    RAG -->|"失败"| RAG
    PUBLISH --> ARCHIVE["旧版本自动归档"]
    PUBLISH --> VERIFY["聊天页验证 RAG"]
```

> 聊天页保留公开入口；登录后显示角色和后台菜单。所有管理动作都要求登录并由后端校验权限。

## 2. 普通员工：问答与反馈

```mermaid
flowchart LR
    A["打开聊天页"] --> B["输入运维问题"]
    B --> C["Flask 调用 Dify Chatflow"]
    C --> D["展示回答 + 点赞/点踩"]
    D -->|"点赞"| E["POST /api/feedback<br/>rating=like"]
    D -->|"点踩"| F["选择反馈原因 + 补充说明"]
    F --> G["POST /api/feedback<br/>rating=dislike"]
    E --> H["Dify 原生反馈 + 本地镜像"]
    G --> H
    H --> I["显示感谢提示"]
```

规则：

- 普通员工不能访问管理后台；
- 不能查看反馈管理记录；
- 不能创建、编辑、审核、发布文档；
- 同一条消息不能重复反馈。

## 3. 运维人员：维护文档版本

```mermaid
flowchart TB
    A["进入文档管理"] --> B{"已有文档？"}
    B -->|"否"| C["新建文档 + 初始 v1"]
    B -->|"是"| D["打开文档"]
    D --> E["新增版本"]
    D --> F["编辑草稿/已驳回版本"]
    C --> G["保存为草稿"]
    E --> G
    F --> G
    G --> H["提交审核"]
    H --> I["等待管理员审核"]
```

运维人员可以：

- 创建文档和版本；
- 编辑文档信息与草稿；
- 提交审核；
- 下载或复制 Markdown；
- 登记 Dify 同步、索引状态；
- 执行并登记 RAG 验证。

运维人员不能：

- 审核文档；
- 发布文档；
- 访问用户、角色、审计页面。

## 4. 管理员：审核与发布

```mermaid
flowchart TB
    A["收到待审核版本"] --> B["查看内容、更新原因、提交人"]
    B --> C{"审核结论"}
    C -->|"驳回"| D["填写审核意见"]
    D --> E["版本状态：rejected"]
    E --> F["运维修改草稿"]
    F --> G["重新提交审核"]
    G --> B

    C -->|"通过"| H["版本状态：approved"]
    H --> I{"关联 Dify？"}
    I -->|"否"| J["管理员可直接发布"]
    I -->|"是"| K["等待运维同步 + 索引 + RAG"]
    K --> L{"同步 synced？<br/>索引 success？<br/>RAG passed？"}
    L -->|"否"| K
    L -->|"是"| M["管理员发布"]
    J --> N["published"]
    M --> N
    N --> O["旧发布版本 archived"]
```

发布强制条件：

1. 审核状态 `approved`；
2. 提交人不能是审核人；
3. 关联 Dify 时：同步 `synced`、索引 `success`、RAG `passed`；
4. 只有管理员拥有 `documents.publish` 权限；
5. 发布后旧发布版本自动归档。

## 5. Dify 同步、索引与 RAG 验证

```mermaid
sequenceDiagram
    participant OP as 运维人员
    participant UI as 文档详情页
    participant KB as Dify 知识库
    participant CHAT as 聊天页
    participant DB as SQLite
    participant AD as 管理员

    OP->>UI: 下载/复制当前 Markdown
    OP->>KB: 替换文档并等待索引
    KB-->>OP: 索引 completed / error
    OP->>UI: 登记同步说明 + 索引结果
    UI->>DB: dify_sync_status=synced, index=success/failed
    alt 索引成功
        OP->>CHAT: 用本次内容相关问题测试
        CHAT-->>OP: RAG 回答
        OP->>UI: 登记 RAG 问题 + passed/failed
        UI->>DB: rag_status=passed/failed
        alt RAG 通过
            AD->>UI: 发布
            UI->>DB: version published + old archived
        end
    else 索引失败
        OP->>KB: 修复索引
        OP->>UI: 重新登记
    end
```

V1.4 不自动调用 Dify 知识库写接口。完整操作手册见 [Dify 知识库更新衔接流程](dify-sync-workflow.md)。

## 6. 文档状态机

```mermaid
stateDiagram-v2
    [*] --> draft: 新建 / 新增版本
    draft --> pending: 提交审核
    rejected --> pending: 修改后重新提交
    pending --> approved: 管理员审核通过
    pending --> rejected: 管理员驳回
    approved --> published: 管理员发布（满足条件）
    published --> archived: 新版本发布
    archived --> [*]
```

### 发布状态

```text
unpublished
  ├── published
  │      └── archived（新版本发布时自动归档）
  └── archived（历史不可重新发布）
```

> 归档版本不可重新发布；回滚应创建新版本，保留历史链路。

## 7. 反馈记录流程

```mermaid
flowchart LR
    A["用户点赞/点踩"] --> B["Flask 调用 Dify Feedback API"]
    B -->|"成功"| C["写入 SQLite 本地镜像"]
    C --> D["运维/管理员查看反馈页"]
    B -->|"失败"| E["返回脱敏错误提示"]
    D --> F["Dify 日志仍是权威来源"]
```

反馈页只对运维人员和管理员开放，普通员工访问返回 403。

## 8. 用户与角色管理流程

```mermaid
flowchart TB
    A["管理员进入用户管理"] --> B["新建用户"]
    B --> C["填写唯一账号 + 显示名"]
    C --> D["选择角色：employee/operator/admin"]
    D --> E["设置初始密码（scrypt 哈希）"]
    E --> F["启用账号"]
    F --> G["用户登录"]
    G --> H["旧 Session 校验 session_version"]

    A --> I["编辑用户"]
    I --> J["改角色 / 停用 / 重置密码"]
    J --> K["session_version + 1"]
    K --> L["该用户旧会话全部失效"]
```

安全限制：

- 只有一个启用管理员时，不能停用或降级该管理员；
- 管理员不能修改自己的角色或停用自己；
- 管理员不能审核自己提交的版本；
- 角色变更、停用和密码重置都会让旧 Session 失效。

## 9. 操作审计流程

关键操作写入 `audit_logs`：

- 登录成功 / 失败、退出；
- 创建/编辑用户、重置密码；
- 创建/编辑文档、创建/编辑版本、提交审核；
- 审核通过 / 驳回；
- 登记 Dify 同步、索引、RAG 验证；
- 发布版本。

审计记录字段：

```text
操作人 + 操作时间 + 操作类型 + 对象 + 结果 + 说明 + IP
```

管理员可以在 `/admin/audit` 查看和筛选；其他角色不可访问。

## 10. 失败与回滚

| 场景 | 处理 |
| --- | --- |
| Dify 索引失败 | 不登记 RAG 通过，不发布；修复 Dify 后重新登记 |
| RAG 验证失败 | 修正知识库或测试问题；重新验证 |
| 发布内容错误 | 下载上一个归档版本，新建版本回滚，重新走审核/同步/RAG/发布 |
| 用户被停用 | 旧 Session 失效，无法登录 |
| 角色变更 | 旧 Session 失效，按新角色重新加载菜单 |
| 管理员自审 | 后端拒绝，换另一位管理员 |

详细状态与字段见 [系统架构](architecture.md) 和 [权限矩阵](permissions.md)。
