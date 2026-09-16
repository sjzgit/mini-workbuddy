# API Contract: 聊天功能（第八阶段）

**Base Path**: `/api/conversations` | **Date**: 2026-09-14

本文件是前后端接口契约的**主定义**（宪法 II/III）。后端 `backend/app/schemas/chat.py`（Pydantic）与前端 `frontend/src/api/chat.ts`（TypeScript 类型）MUST 与本文逐字段对齐，变更先改这里。

**通用约定**（与 002~007 阶段一致）：

- 所有 JSON 响应；错误统一 `{"detail": "人话错误信息"}`；校验失败 `422`、业务冲突 `409`、资源不存在 `404`。
- Agent 候选复用既有 `GET /api/agents`（007 契约），本契约不再定义。
- 时间字段为 ISO 8601 字符串（naive UTC，无时区后缀）。

## 枚举与常量（唯一主定义，实现侧只消费）

```text
Role:
  user       用户消息
  assistant  Agent 回复

MessageStatus:
  generating  生成中（占位行；同一会话至多一条）
  completed   已完成（终态，可进上下文）
  incomplete  未完成——停止/失败/中断产生（终态，不进上下文）

StreamEvent:
  reasoning_delta  思考过程增量   data: { "text": string }
  content_delta    回答正文增量   data: { "text": string }
  done             生成终态       data: { "message": MessageOut | null, "stopped": bool }
  error            失败终态       data: { "category": StreamErrorCategory, "message": string }

StreamErrorCategory:
  unreachable        服务地址不可访问
  timeout            请求超时
  auth_error         认证失败（密钥无效/无权限）
  model_not_found    模型标识不存在
  bad_response       响应无法解析为 Chat Completions 结构
  empty_response     流正常结束但正文与思考均为空
  stream_interrupted 流式输出中断/乱序异常
  context_overflow   上下文超过模型容量（服务商侧拒绝）
  unknown            暂无法确定原因

TITLE_MAX_CHARS   = 20      会话标题截取长度（截断补 "…"）
TITLE_DEFAULT     = "新会话" 新建会话初始标题
MESSAGE_MAX_CHARS = 32000   单条消息输入上限（去首尾空白后）
CONTEXT_CHAR_TOKEN_RATIO = 0.6   上下文估算系数（字符→token，research R3）
STREAM_PING_INTERVAL_SECONDS = 15   SSE 心跳注释行间隔
```

## 数据结构

### ConversationSummary（会话摘要：列表项 / 新建与切换返回）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | integer | 会话 id |
| `title` | string | 标题（默认 `"新会话"`） |
| `agent_id` | integer | 当前选择的 Agent（业务引用；Agent 可能已删除，前端须对照候选列表判可用） |
| `updated_at` | string (ISO 8601) | 最后更新时间（列表排序依据，倒序） |
| `created_at` | string (ISO 8601) | 创建时间 |

> 列表接口**只返回摘要**，不含消息（spec FR-006）。排序：`updated_at` 倒序、`id` 倒序稳定并列。

### MessageOut（消息，读取与终态事件返回）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | integer | 消息 id |
| `conversation_id` | integer | 所属会话 |
| `role` | Role | |
| `agent_id` | integer \| null | 生成时刻 Agent 标识快照（user 为 null） |
| `agent_name` | string \| null | 生成时刻 Agent 名称快照（user 为 null；Agent 后续改名/删除不影响本值） |
| `reasoning_content` | string \| null | 思考过程全文（无则 null/空串） |
| `content` | string | 正文 |
| `status` | MessageStatus | |
| `seq` | integer | 会话内顺序号（展示与读取排序唯一依据） |
| `created_at` | string (ISO 8601) | 创建时间 |

### SendMessageRequest（POST /api/conversations/{id}/messages 请求体）

| 字段 | 类型 | 说明 |
|------|------|------|
| `content` | string | 去首尾空白后 1~32000 字符；纯空白 422 |

### StartReplyResponse（POST /messages 与 /regenerate 返回，201）

| 字段 | 类型 | 说明 |
|------|------|------|
| `user_message` | MessageOut \| null | 本次用户消息（/regenerate 为 null） |
| `reply_message_id` | integer | 占位回复行 id——随后以其为键订阅流与停止 |
| `conversation` | ConversationSummary | 最新会话摘要（标题可能已截取更新、updated_at 已前移） |

### StopResponse（POST .../stop 返回）

| 字段 | 类型 | 说明 |
|------|------|------|
| `stopped` | boolean | 恒 true；停止是异步的——终态以流内 `done`/`error` 事件或消息行最终状态为准 |

## 端点

### GET /api/conversations —— 会话列表（摘要）

- **200** `ConversationSummary[]`：`updated_at` 倒序。

### POST /api/conversations —— 新建会话

- 请求体：`{ "agent_id": integer }`（Agent 必须存在且可用，否则 `400`）。
- **201** `ConversationSummary`：标题 `"新会话"`，落库后返回；前端选中该会话。
- 无默认 Agent 的引导逻辑在前端（禁用发送 + 跳转入口，FR-029），后端只校验。

### PUT /api/conversations/{id} —— 切换会话 Agent

- 请求体：`{ "agent_id": integer }`（必须存在且可用）。
- **200** `ConversationSummary`。
- **409** 该会话存在 `generating` 回复（生成互斥，FR-020）。
- **404** 会话不存在；**400** Agent 不存在。

### GET /api/conversations/{id}/messages —— 会话消息（按 seq 升序）

- **200** `MessageOut[]`。
- **404** 会话不存在。

### POST /api/conversations/{id}/messages —— 发送消息（先落库，后异步生成）

处理顺序（事务 1）：会话存在性 → 会话无 `generating` 回复（否则 **409**）→ 内容校验 → 会话 Agent 可用性（**400**，提示重选）→ 上下文容量前置估算（超限 **422** `{"detail": "会话历史过长，已超出该模型可用的上下文容量。请缩短输入或新建会话。"}`）→ 落库用户消息（seq=n）+ 创建 generating 占位回复（seq=n+1，快照当前 agent_id/agent_name）→ 更新会话 `updated_at` 与首条标题截取（FR-007）→ 启动生成任务（research R4）。

- **201** `StartReplyResponse`。
- 错误：`404` 会话不存在 / `409` 生成中 / `400` Agent 不可用 / `422` 内容校验或上下文超限。
- 模型调用的一切失败**不在本接口暴露**——订阅流后经 `error` 事件获知（FR-009：保存成功才算发送成功）。

### POST /api/conversations/{id}/regenerate —— 重新生成最后一条回复

前置：最后一条 assistant 消息存在且非 `generating`；会话无其他生成中回复。

- 行为：原地重置该回复（清空内容、`status=generating`，seq 不变，research R8）→ 启动生成任务。
- **201** `StartReplyResponse`（`user_message` 为 null）。
- 错误：`404` 会话不存在 / `409` 已在生成中或最后一条消息不是已完成的 assistant 消息。

### GET /api/conversations/{id}/messages/{message_id}/stream —— 订阅生成流（SSE）

- 响应：`200`，`Content-Type: text/event-stream`。
- 事件语义（research R1/R4）：
  - 订阅即**重放**：先按序发送该任务已产生的全部 `reasoning_delta` / `content_delta`，再实时跟随；任务已终态则直接收到 `done` / `error`。
  - `done`：`{ "message": MessageOut | null, "stopped": bool }`——终态消息（已完成 / incomplete）已落库；占位行因停止/失败且无正文被删除时为 `null`；`stopped=true` 表示因用户停止结束。`done` 是流的最后一个事件。
  - `error`：`{ "category": StreamErrorCategory, "message": string }`——人话文案直接可展示；随后同样收到终态 `done`（`message.status=incomplete`，或占位行被删除时 `message` 为 `null`）。错误文本**永远不会**出现在任何 `content_delta` 中（FR-023）。
  - 心跳：空闲期发送 SSE 注释行 `: ping`（间隔 `STREAM_PING_INTERVAL_SECONDS`），客户端忽略。
- 幂等：多客户端 / 断线重连订阅同一 `message_id` 均合法。
- **404** 会话或消息不存在；**409** 该消息不是 assistant 回复。
- 订阅 `status != generating` 的历史消息：视为任务已终结——若 completed 直接收到 `done`；若 generating 但任务不存在（进程重启）→ 惰性标记 `incomplete` 后发 `done`（提示"生成中断"，research R4）。

### POST /api/conversations/{id}/messages/{message_id}/stop —— 停止生成

- 行为：取消生成任务、关闭上游模型连接（尽力而为，FR-021 / research R5）；缓冲非空 → `incomplete` 落库，缓冲为空 → 删除占位行。
- **200** `StopResponse`；对已终态消息调用同样返回 200（幂等）。
- 错误：`404` 会话/消息不存在；**409** 消息不是 assistant 回复。

## 错误响应约定（HTTP 层）

| 状态码 | 场景 | body |
|--------|------|------|
| 400 | 会话指定 Agent 不存在/不可用 | `{"detail": "该 Agent 已不可用，请重新选择 Agent"}` |
| 404 | 会话/消息不存在 | `{"detail": "会话不存在"}` / `{"detail": "消息不存在"}` |
| 409 | 会话生成中重复发送 / 切换 Agent / 重新生成 | `{"detail": "当前会话正在生成回复，请等待完成或先停止生成"}` |
| 409 | 重新生成对象非法 | `{"detail": "仅最后一条 Agent 回复可以重新生成"}` |
| 422 | 内容为空/超长、上下文超限 | `{"detail": "<人话信息，含缩短输入或新建会话指引>"}` |

错误文案（含流内 `error.message`）不得包含 API Key、Authorization 头、上游 URL 查询串等敏感信息（FR-025）。

## 生成任务内部约定（后端单进程，前端不感知）

- 请求体：OpenAI Chat Completions 兼容，`stream: true`；`messages` = `[system?]` + 有效历史（`content` only，seq 升序，research R2/R3）+ 本次用户消息（已在库中，仅出现一次）。
- 深度思考参数：`enable_deep_thinking && thinking_level != "off"` → `"thinking": {"type": "enabled"}`，否则 `{"type": "disabled"}`。
- 每个上游增量到达后立刻转为 SSE 事件广播；后端同时以 `logging` INFO 级实时打印第三方 API 请求响应摘要（请求：URL 路径、模型标识、消息数；响应：增量长度与累计长度、finish_reason；**不含** Authorization 头与完整密钥，FR-011/FR-025）。
- 上游读取超时：连接 10s，读间隔 120s（首字可能较慢）；会话级互斥由注册表保证。

## 009 修订记录（specs/009-agent-runtime）

> 自 009 阶段（统一 Agent Runtime）起，本契约的流事件集由 `specs/009-agent-runtime/contracts/agent-runtime-api.md` 扩展与修订，修订内容以该契约为准：

- 终端事件 `done` 由 `run_completed` 取代（原 `message`/`stopped` 字段语义保留于 `RunCompletedData`）。
- 新增事件：`run_started`、`model_request_started`、`model_request_completed`、`tool_call_started`、`tool_call_completed`；`reasoning_delta` / `content_delta` / `error` 保留原名。
- 全部事件 data 追加公共字段 `run_id`、`seq`（运行内从 1 递增）；模型请求与工具调用事件带 `round`、`call_id`。
- HTTP 端点（列表/新建/切换/消息/发送/流/停止/重新生成）路径与请求响应结构不变；流订阅端点的事件集以 009 契约 §2 为准。

## 011 修订记录（specs/011-context-compression-run-records）

> 自 011 阶段（上下文压缩与运行记录可观测）起，本契约有以下修订，详见 `specs/011-context-compression-run-records/contracts/runtime-events-011.md` §4：

- **连接断开不再取消生成**：订阅断开（页面关闭/网络中断）后任务继续在后台执行，终态照常落库；重新订阅按原重放语义续播（自动续播）。用户主动停止仍走 `POST .../stop`。
- 发送/重新生成的 422 上下文超限文案增补"开启自动压缩"指引（Agent 开启压缩时历史由运行时压缩兜底，前置校验仅拦截固定内容与本次输入）。
- 流事件集继续以 009 契约（含 010/011 增补）为准：新增 `compression_started` / `compression_completed` / `compression_failed` / `compression_fallback` 事件转发（前端可忽略）。
