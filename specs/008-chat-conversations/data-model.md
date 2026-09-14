# Data Model: 聊天功能（第八阶段）

**Date**: 2026-09-14 | **Feature**: `008-chat-conversations` | **Spec**: [spec.md](spec.md)

本文件是 conversations / messages 两表的数据模型**主定义**（宪法 II SSOT）。实现侧 `backend/app/models/__init__.py`（SQLAlchemy ORM）字段与类型 MUST 与本文一致，变更先改本文再落 Alembic 迁移。SQL 存档：`sql/migrations/008-chat-conversations.sql`。

时间约定与既有表一致：SQLite DateTime 不带时区，统一存 naive UTC（`_utcnow()`），ISO 8601 序列化后交付前端。

## §1 conversations 表 —— 会话

一次连续对话的载体。会话间消息相互隔离（spec FR-017）。

| 字段 | 类型（SQLAlchemy） | 约束 | 说明 |
|------|--------------------|------|------|
| `id` | `Integer` PK | autoincrement | 会话 id |
| `title` | `String(100)` | NOT NULL，default `"新会话"` | 会话标题；首条用户消息落库时截取覆盖（research R7），此后不再变更 |
| `agent_id` | `Integer` | NOT NULL | 当前选择的 Agent（业务引用，**不建 DB 外键**，与 `agents.model_id` 同风格；Agent 删除不做引用保护——会话仍可查看，发送前须重选可用 Agent，spec FR 切换 Agent 节） |
| `created_at` | `DateTime` | NOT NULL，default `_utcnow` | 创建时间 |
| `updated_at` | `DateTime` | NOT NULL，default `_utcnow` / `onupdate` | 最后更新时间；**仅消息写入路径更新**（用户消息落库、回复终态落库），仅查看不更新（spec FR-005） |

索引：

- `ix_conversations_updated_at` (`updated_at`) —— 列表按最后更新时间倒序的高频排序。

## §2 messages 表 —— 消息

会话中的一条发言（用户消息或 Agent 回复）。

| 字段 | 类型（SQLAlchemy） | 约束 | 说明 |
|------|--------------------|------|------|
| `id` | `Integer` PK | autoincrement | 消息 id（同时是流订阅与停止操作的定位键） |
| `conversation_id` | `Integer` | NOT NULL，FK → `conversations.id` ON DELETE CASCADE | 所属会话 |
| `role` | `String(10)` | NOT NULL | `user` \| `assistant`（枚举主定义见 contracts/chat-api.md `Role`） |
| `agent_id` | `Integer` | NULL | 生成时刻的 Agent 标识快照（assistant 必填、user 为 NULL）；业务引用无 DB 外键——Agent 删除/改名不影响历史归属（spec FR-003） |
| `agent_name` | `String(100)` | NULL | 生成时刻的 Agent 名称快照（assistant 必填、user 为 NULL）；前端展示归属直接读本值 |
| `reasoning_content` | `Text` | NULL | 思考过程全文（assistant；模型未输出思考时为空）；**不进后续上下文**（research R2） |
| `content` | `Text` | NOT NULL，default `""` | 回答正文 / 用户消息全文 |
| `status` | `String(12)` | NOT NULL | `generating` \| `completed` \| `incomplete`（枚举主定义见 contracts；user 消息恒为 `completed`） |
| `seq` | `Integer` | NOT NULL | 会话内稳定顺序号，从 1 起递增；读取排序唯一依据（spec FR-002，禁止仅按时间戳排序） |
| `created_at` | `DateTime` | NOT NULL，default `_utcnow` | 创建时间 |

索引与约束：

- `uq_messages_conversation_seq` (`conversation_id`, `seq`) UNIQUE —— 同会话内 seq 唯一，兜底顺序一致性。
- `ix_messages_conversation_seq` (`conversation_id`, `seq`) —— 按会话加载消息的主查询路径（唯一索引本身可服务该查询，单独普通索引不重复建）。

> 说明：assistant 消息生成期间行已存在（占位），完成/停止/失败时单次 UPDATE `content` / `reasoning_content` / `status`；流式增量**不逐条写库**（research R4）。消息无 `updated_at`：排序看 `seq`，展示时间看 `created_at`。

## §3 关系与引用图

```text
conversations 1 ──── N messages            (DB 外键，ON DELETE CASCADE 兜底)
conversations N ──── 1 agents              (业务引用 agent_id，无 DB 外键)
messages      N ──── 1 agents              (快照引用 agent_id + agent_name，无 DB 外键)
```

- Agent 删除**不阻断**：conversations.agent_id 与 messages.agent_id 均无 DB 外键、无应用层引用保护（与 007 的 model/agent 引用保护相反——聊天场景允许历史留存，spec 明确"仍可查看聊天记录，但继续发送前需要选择可用 Agent"）。
- 会话无删除入口（spec 范围外），CASCADE 仅为数据完整性兜底。

## §4 状态机

### 消息状态（MessageStatus）

```text
                    创建（用户消息）──────────────► completed（终态）

assistant 消息：
   [POST /messages 或 /regenerate 创建占位行]
        │
        ▼
   generating ──(流完成, 内容落库)──► completed   ──终态──
        │
        ├──(用户停止, 缓冲非空)──► incomplete     ──终态──
        ├──(失败, 缓冲非空)──────► incomplete     ──终态──
        ├──(停止/失败, 缓冲为空)──► 行删除（不产生空白回复, FR-024）
        └──(进程重启, 任务丢失)──► incomplete（下次访问时惰性标记, 提示"生成中断"）
```

规则：

- `generating` 是唯一可流转出的非终态；`completed` / `incomplete` 均为终态，不可再变更。
- `incomplete` 消息不进入后续上下文（FR-017）；错误提示文本永远不写入 `content`（FR-023）。
- 会话同一时刻至多一条 `generating` 回复（生成互斥，FR-020，由生成注册表 + 会话检查共同保证）。

### 会话标题状态（隐式）

`title == "新会话"`（且首条用户消息落库）→ 截取覆盖；其余路径只读。

## §5 seq 分配规则

- 分配 = `SELECT COALESCE(MAX(seq), 0) + 1 FROM messages WHERE conversation_id = ?`，在"保存用户消息 + 创建占位回复"的同一事务内完成（一次发送产生 seq = n 的用户消息与 seq = n+1 的占位回复）。
- 重新生成不分配新 seq（原地重置，research R8）。
- 并发防护：同一会话生成期间禁止新发送（FR-020）+ 注册表互斥，单用户场景下不存在 seq 竞争；唯一索引兜底。

## §6 校验规则汇总（实现侧 Pydantic 落点）

| 规则 | 值 / 约定 | 主定义 |
|------|-----------|--------|
| 会话标题默认值 | `"新会话"` | contracts/chat-api.md 常量节 |
| 标题截取长度 | 前 20 字符 + 截断补 `…` | 同上（`TITLE_MAX_CHARS = 20`） |
| role 枚举 | `user` \| `assistant` | contracts `Role` |
| status 枚举 | `generating` \| `completed` \| `incomplete` | contracts `MessageStatus` |
| 发送内容非空 | 去首尾空白后长度 ≥ 1；上限 32000 字符 | contracts `SendMessageRequest` |
| SSE 事件类型 | `reasoning_delta` \| `content_delta` \| `done` \| `error` | contracts SSE 节 |
| 错误类别 | `unreachable` \| `timeout` \| `auth_error` \| `model_not_found` \| `bad_response` \| `empty_response` \| `stream_interrupted` \| `context_overflow` \| `unknown` | contracts `StreamErrorCategory` |
