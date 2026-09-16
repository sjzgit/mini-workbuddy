# Data Model: 上下文压缩与运行记录可观测（011）

> 主定义：实现侧 ORM（`backend/app/models/__init__.py`）字段类型 MUST 与本文一致；迁移走 Alembic（当前 head `207b5aa052ad`）。
> 既有表（models/skills/tools/mcp_servers/agents/agent_bindings/conversations/messages/secrets_vault/agent_prompt_versions）不改动，除 §2 的 agents 增列。
> 通用约定沿用项目规范：`Integer` 自增主键；时间字段 naive UTC `DateTime`（`_utcnow()` 去微秒）；`created_at` default、`updated_at` default+onupdate。

## 1. 新增配置（core/config.py，全部有默认值）

| 配置 | 类型/默认 | 说明 |
|------|-----------|------|
| `compact_safety_margin_ratio` | float = 0.10 | 安全余量占 context_length 比例（R2） |
| `compact_default_output_reserve_tokens` | int = 4096 | max_output_tokens 为空时的输出预留（R2） |
| `compact_request_timeout_seconds` | int = 60 | 摘要请求超时（R5） |
| `compact_max_attempts_per_run` | int = 2 | 单次运行压缩尝试上限（R5） |
| `compact_max_batches` | int = 4 | 摘要分批上限（R5） |

## 2. `agents` 表新增 4 列（Agent 压缩配置）

| 列 | 类型 | 默认 | 约束 | 说明 |
|----|------|------|------|------|
| `auto_compact` | Boolean | True（server_default `"1"`） | — | 自动压缩开关（FR-025） |
| `compact_trigger_ratio` | Numeric(3,2) | 0.80 | 0.50~0.95（应用层校验） | 触发比例：估算输入 / 可用输入容量（FR-025） |
| `compact_keep_recent_rounds` | Integer | 5（server_default `"5"`） | 1~50 | 保留最近完整对话轮数（每轮=用户消息+回答+工具交互，FR-025） |
| `compact_summary_target_tokens` | Integer | 1000（server_default `"1000"`） | 100~8000 | 摘要目标长度（软目标；执行时受 `min(值, available_input // 2)` 限制，FR-026） |

迁移方式：`op.batch_alter_table("agents")` 逐列 `add_column` + `server_default`（沿用 `7a02c8322265` 先例）。

## 3. 新表 `conversation_compactions`（会话压缩状态，FR-033/034）

| 列 | 类型 | 约束 | 说明 |
|----|------|------|------|
| `id` | Integer PK | autoincrement | |
| `conversation_id` | Integer | FK conversations.id, ondelete CASCADE, **unique** | 每会话至多一行；随会话级联删除 |
| `summary_text` | Text | default "" | 当前会话摘要（空串=无摘要）；进入上下文时 role=user 会话背景（FR-031） |
| `boundary_seq` | Integer | default 0（server_default `"0"`） | 已压缩覆盖的最后一条 messages.seq；history 组装只取 `seq > boundary_seq` |
| `created_at` / `updated_at` | DateTime | | |

一致性约束（FR-034）：summary_text 与 boundary_seq 必须在同一事务内更新；生成或写回失败时整体回滚，保留上一份有效值。

## 4. 新表 `runs`（运行记录，FR-001~003）

| 列 | 类型 | 约束 | 说明 |
|----|------|------|------|
| `id` | Integer PK | autoincrement | |
| `run_id` | String(64) | **unique**, not null | uuid4 hex，事件关联键 |
| `conversation_id` | Integer | FK conversations.id, ondelete CASCADE, **nullable**, index | 级联删除（011 澄清）；聊天链路恒有值，NULL 仅供后续评测直调场景（RunRequest 可选传入）。注：生产库 SQLite PRAGMA foreign_keys 默认 OFF（项目既有约定，应用层显式清理为准）；会话删除入口落地时需启用 PRAGMA 或在应用层清理三表 |
| `reply_message_id` | Integer | FK messages.id, ondelete SET NULL, nullable | 关联占位回复行；占位行被删时置 NULL |
| `agent_id` | Integer | nullable | 业务引用（快照辅助，不建外键） |
| `agent_name` | String(100) | not null | Agent 名称运行时快照（FR-012） |
| `model_name` | String(100) | not null | 模型 display_name 快照（FR-012） |
| `model_identifier` | String(200) | not null | 模型标识快照（排障用） |
| `status` | String(20) | not null, index | `running / succeeded / partial / failed / cancelled`（枚举主定义 contracts/runs-api.md） |
| `end_reason` | String(500) | default "" | 结束原因人话（与 status 分开保存，FR-003） |
| `error_category` | String(30) | nullable | StreamErrorCategory（失败时） |
| `error_summary` | String(500) | nullable | 脱敏错误摘要（FR-011/020） |
| `started_at` | DateTime | not null, index | 列表按此倒序（FR-010） |
| `finished_at` | DateTime | nullable | |
| `total_duration_ms` | Integer | nullable | finished_at − started_at（FR-014） |
| `model_call_count` | Integer | default 0 | 实际发出的模型请求次数（含失败与压缩请求，FR-014/045） |
| `tool_call_count` | Integer | default 0 | 进入执行入口的次数（denied 不计，FR-014） |
| `prompt_tokens` / `completion_tokens` / `total_tokens` | Integer | nullable | 各次请求实际用量 merge_add；任一未知 → NULL（FR-015，禁止 0 冒充） |
| `first_output_ms` | Integer | nullable | 首个非空 content_delta 距开始毫秒数；无正文输出 NULL（FR-014/015） |
| `created_at` / `updated_at` | DateTime | | |

索引：`ix_runs_started_at`、`ix_runs_status`、`ix_runs_conversation_id`、`uq_runs_run_id`。

## 5. 新表 `run_events`（持久化运行事件，FR-005/008）

| 列 | 类型 | 约束 | 说明 |
|----|------|------|------|
| `id` | Integer PK | autoincrement | 落库顺序（稳定顺序字段之一） |
| `run_id` | String(64) | FK runs.run_id, ondelete CASCADE, not null | |
| `seq` | Integer | not null | 运行内严格递增（事件契约 009 §1） |
| `event_type` | String(40) | not null | 事件类型（contracts/runtime-events-011.md 全集） |
| `round` | Integer | nullable | |
| `call_id` | String(40) | nullable, index | 开始/结束配对键（FR-008） |
| `data` | JSON | not null | 安全负载：剥离 `content_text`/`reasoning_text`/`*_full` 与 010 的 `params`/`result` 展示字段；增量事件不落库 |
| `created_at` | DateTime | | |

约束：**unique(run_id, seq)** —— 重复投递幂等跳过（FR-008）。持久化事件类型：`run_started`、`model_request_started`、`model_request_completed`、`tool_call_started`、`tool_call_completed`、`compression_started`、`compression_completed`、`compression_failed`、`compression_fallback`、`error`、`run_completed`（11 种；`reasoning_delta`/`content_delta` 除外）。

## 6. 新表 `run_payloads`（详细载荷，FR-017/021）

| 列 | 类型 | 约束 | 说明 |
|----|------|------|------|
| `id` | Integer PK | autoincrement | 详情页按需读取的定位 id |
| `run_id` | String(64) | FK runs.run_id, ondelete CASCADE, not null | |
| `call_id` | String(40) | not null | 关联调用（模型请求/工具调用/压缩请求） |
| `payload_type` | String(30) | not null | `model_input / model_output / tool_params / tool_result / compression_input / compression_output` |
| `content` | Text | not null | 脱敏后完整内容；**大字段完整保存、不截断**（011 澄清决定，SQLite Text 容量≈1GB） |
| `char_count` | Integer | not null | 脱敏后字符数（列表元数据展示） |
| `created_at` | DateTime | | |

约束：unique(run_id, call_id, payload_type)。读取入口仅 `GET /api/runs/{run_id}/payloads/{payload_id}`（contracts/runs-api.md），列表与详情默认不加载（FR-018）。

## 7. 运行期实体扩展（`agent_runtime` 包）

### 7.1 RunRequest 增字段（`__init__.py`）

| 字段 | 类型 | 说明 |
|------|------|------|
| `conversation_id` | int \| None = None | 压缩状态读写定位；None（评测直调）时跳过压缩 |
| （RunHistoryMessage 增）`seq` | int \| None = None | 该消息的 messages.seq；None=运行内消息，不参与边界推进 |

### 7.2 ContextGroup（压缩用消息组，`compression.py`，内存实体）

| 字段 | 类型 | 说明 |
|------|------|------|
| `messages` | list[dict] | 该组全部消息（user 单条；assistant + 其后全部 tool 消息） |
| `db_seq` | int \| None | 组内最后一条消息的 messages.seq；None=运行内新增组 |
| `estimated_tokens` | int | 组文本估算值（R1 口径） |

组划分满足 FR-036：工具请求与结果同组同裁，无孤立配对。

### 7.3 RunRecorder 映射（`recorder.py`）

| 事件 | 动作 |
|------|------|
| run_started | INSERT runs（status=running，快照字段） |
| content_delta（非空） | 更新 first_output_ms（仅首次） |
| model_request_started | model_call_count += 1；记录 purpose |
| model_request_completed | 合并 usage；写 model_input/model_output 载荷（透传字段） |
| tool_call_started | （配对缓存） |
| tool_call_completed | status∈{success,error,cancelled} → tool_call_count += 1；写 tool_params/tool_result 载荷；INSERT run_events |
| compression_started/completed/failed/fallback | INSERT run_events；completed 合并估算前后值 |
| error | INSERT run_events；更新 error_category/error_summary |
| run_completed | 剥离正文全文后 INSERT run_events；终态 UPDATE runs（status 映射、end_reason、finished_at、total_duration_ms、Token 汇总） |

## 8. 状态机

### 8.1 Run 状态映射（唯一主定义）

| Runtime status（009） | runs.status | 语义 |
|----------------------|-------------|------|
| （运行中） | running | 已开始未结束 |
| completed | succeeded | 正常完成 |
| max_rounds | partial | 轮数耗尽等限制结束（部分完成） |
| error | failed | 模型错误/内部异常 |
| cancelled | cancelled | 用户主动停止 |
| （启动恢复） | failed（end_reason="运行中断：服务在运行期间重启"） | 服务重启遗留（FR-007） |

### 8.2 压缩流程状态（单次压缩尝试内）

```
idle ──估算≥阈值──▶ compressing ──摘要+写回成功──▶ done（更新 summary+boundary）
                        │─超时/模型错误/空摘要/写回失败─▶ failed ─▶ fallback（备用裁剪，边界不变）
                        │─尝试次数耗尽──────────────▶ fallback
fallback ──裁剪后可容纳──▶ done（本次请求有效）；仍超限 ─▶ error(context_overflow) 终止运行
```

## 9. 实体关系

```
conversations 1 ──── 0..1 conversation_compactions   （CASCADE）
conversations 1 ──── 0..* runs                       （CASCADE）
messages      1 ──── 0..1 runs（reply_message_id，SET NULL）
runs          1 ──── 0..* run_events                 （CASCADE，unique(run_id,seq)）
runs          1 ──── 0..* run_payloads               （CASCADE，unique(run_id,call_id,payload_type)）
agents        1 ──── 0..* runs                       （业务引用 agent_id + agent_name 快照）
```

## 10. SQL 存档

Alembic 迁移同时导出增量 SQL 到 `sql/migrations/`（宪法数据库约束），文件名与 revision 对应。
