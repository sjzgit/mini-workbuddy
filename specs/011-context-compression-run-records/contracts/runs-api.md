# Contract: 运行记录 API（011）

**Base Path**: `/api/runs` | **Date**: 2026-09-15

本文件是运行记录 REST 接口的**唯一主定义**。后端 `backend/app/schemas/runs.py`（Pydantic）与前端 `frontend/src/api/runs.ts`（TypeScript 类型）MUST 与本文逐字段对齐。
通用约定沿用 008：JSON 响应；错误统一 `{"detail": "人话信息"}`；校验失败 `422`、不存在 `404`；时间字段为 ISO 8601 字符串（naive UTC）；数据模型主定义见 [data-model.md](../data-model.md) §4~6。

## 枚举与常量（唯一主定义，实现侧只消费）

```text
RunStatus:                    # runs.status（映射自 Runtime 终态，见 data-model §8.1）
  running     运行中
  succeeded   成功
  partial     部分完成（轮数耗尽等限制结束）
  failed      失败（模型服务错误/内部异常/运行中断）
  cancelled   已取消

RunSort                       固定 started_at 倒序、id 倒序稳定并列
PAGE_DEFAULT    = 1           页码（≥1）
PAGE_SIZE_DEFAULT = 20       每页（1~100，超界取边界值）
```

## 数据结构

### RunSummary（列表项；全部来自 runs 行快照，无关联查询）

| 字段 | 类型 | 说明 |
|------|------|------|
| `run_id` | string | 运行标识 |
| `conversation_id` | integer | 所属会话（可能已删除前置为空？否——级联删除保证不出现） |
| `agent_name` | string | Agent 快照（FR-012） |
| `model_name` | string | 模型 display_name 快照 |
| `status` | RunStatus | |
| `end_reason` | string | 结束原因人话（正常完成可为空串） |
| `error_summary` | string \| null | 脱敏错误摘要；成功运行为 null（FR-011） |
| `started_at` | string (ISO) | |
| `finished_at` | string \| null | 运行中为 null |
| `total_duration_ms` | integer \| null | |
| `model_call_count` | integer | 含失败请求与压缩请求（FR-014） |
| `tool_call_count` | integer | 不含校验拒绝（FR-014） |
| `prompt_tokens` / `completion_tokens` / `total_tokens` | integer \| null | 任一未知 → null（页面显示"未知"，禁止 0，FR-015） |
| `first_output_ms` | integer \| null | 无正文输出 → null（页面显示"无正文输出"） |

### RunListResponse（GET /api/runs 响应）

| 字段 | 类型 | 说明 |
|------|------|------|
| `items` | RunSummary[] | started_at 倒序 |
| `total` | integer | 筛选条件下的总数 |
| `page` / `page_size` | integer | 回显 |

### RunEventOut（详情时间线事件）

| 字段 | 类型 | 说明 |
|------|------|------|
| `seq` | integer | 运行内顺序（排序依据） |
| `event_type` | string | 事件类型（contracts/runtime-events-011.md 全集） |
| `round` | integer \| null | |
| `call_id` | string \| null | 开始/结束配对键 |
| `data` | object | 安全负载（不含任何 `*_full`/正文全文/增量） |
| `created_at` | string (ISO) | 落库时间 |

### RunDetailResponse（GET /api/runs/{run_id} 响应）

| 字段 | 类型 | 说明 |
|------|------|------|
| `summary` | RunSummary | |
| `events` | RunEventOut[] | 按 seq 升序；**默认只返回本结构与摘要，不含载荷**（FR-018） |

### RunPayloadMeta（载荷元数据）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | integer | 载荷定位 id |
| `call_id` | string | 关联调用 |
| `payload_type` | string | `model_input / model_output / tool_params / tool_result / compression_input / compression_output` |
| `char_count` | integer | 内容字符数（供前端提示体积） |

### RunPayloadContent（GET 单条载荷响应）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` / `call_id` / `payload_type` / `char_count` | 同上 | |
| `content` | string | 脱敏后完整内容（后端已完整保存，不截断） |

## 端点

### GET /api/runs —— 运行列表

- Query：`status`（RunStatus，可选）、`agent_id`（可选）、`conversation_id`（可选）、`page`（默认 1）、`page_size`（默认 20，≤100）。
- **200** `RunListResponse`。
- 查询约束（SC-003）：固定筛选与分页条件下，处理请求数据库查询次数恒定（COUNT + SELECT 共 2 次），MUST NOT 随返回行数增长；MUST NOT 关联 agents/models/events 逐行查询（快照字段齐全）。

### GET /api/runs/{run_id} —— 运行详情

- **200** `RunDetailResponse`（摘要 + 全部结构性事件）。
- **404** `{"detail": "运行记录不存在"}`。

### GET /api/runs/{run_id}/payloads —— 载荷元数据列表

- **200** `RunPayloadMeta[]`（不含 content）。

### GET /api/runs/{run_id}/payloads/{payload_id} —— 载荷全文（按需加载）

- **200** `RunPayloadContent`。
- **404** 运行或载荷不存在。
- 本端点是详细载荷的唯一读取入口（受控，FR-021）。

### GET /api/conversations/{conversation_id}/runs —— 会话维度运行列表

- **200** `RunSummary[]`（最近 20 条，started_at 倒序；聊天页"查看运行记录"入口使用）。
- **404** 会话不存在。

## 错误响应约定

| 状态码 | 场景 | body |
|--------|------|------|
| 404 | 运行/载荷/会话不存在 | `{"detail": "运行记录不存在"}` / `{"detail": "载荷不存在"}` / `{"detail": "会话不存在"}` |
| 422 | 分页参数非法 | `{"detail": "<人话信息>"}` |

错误文案不得包含密钥、Authorization、上游 URL 查询串（沿用 008 约束）。

## 查询实现约束（性能验收）

- 列表 = `COUNT(*)` + `SELECT ... FROM runs WHERE ... ORDER BY started_at DESC, id DESC LIMIT/OFFSET`，共 2 条 SQL。
- 列表/详情接口 MUST NOT 在同一请求中读取 `run_payloads.content`。
- 详情接口单条 SELECT 事件（一次查询），MUST NOT 按事件逐条查询。

### GET /api/conversations/{conversation_id}/run-replays —— 会话运行过程回放（011 优化①）

- **200** `RunReplay[]`（按 started_at 倒序，最多 50 条，仅含已终态且关联回复消息的运行）：

| 字段 | 类型 | 说明 |
|------|------|------|
| `run_id` | string | |
| `reply_message_id` | integer \| null | 关联回复消息（聊天页按此挂接过程片段） |
| `status` | RunStatus | |
| `items` | ReplayItem[] | 按事件 seq 排列的回放条目，还原"轮内思考/正文 → 工具卡片 → 下一轮"交错序 |

`ReplayItem`：
- `{ kind: "reasoning" | "content", round, text }` —— 来自 model_output 载荷（JSON `{content, reasoning, tool_calls}`；旧格式纯文本降级为 content）
- `{ kind: "tool", round, callId, toolName, displayName, toolType, serverName, status, durationMs, paramsSummary, resultSummary, paramsText, resultText }` —— 工具卡片，`paramsText`/`resultText` 为完整文本（tool_params/tool_result 载荷）

聊天页刷新后经本接口回显历史运行全过程（工具卡片不再丢失）；载荷原文仍按需加载。
