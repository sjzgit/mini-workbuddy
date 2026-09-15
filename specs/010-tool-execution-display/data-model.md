# Data Model: 工具执行过程展示（010）

> 本阶段**无数据库变更**（Q1 已确认不持久化）：不新增 ORM 模型、不新增 Alembic 迁移。
> 本文描述三类运行期/展示期数据结构：后端事件契约增补（主定义见 `contracts/` 与 `backend/app/schemas/agent_runtime.py`）、后端运行期记录扩展、前端展示状态实体。

## 1. 事件契约增补（对 009 `agent-runtime-api.md` 的修订）

主定义已直接更新至 `specs/009-agent-runtime/contracts/agent-runtime-api.md`（标注"010 增补"），增补字段如下：

### 1.1 ToolCallStartedData 增补

| 字段 | 类型 | 语义 |
|------|------|------|
| `params` | `str` | 完整参数 JSON 文本（原始 arguments 原样序列化）；超过 `runtime_tool_params_max_chars`（默认 4000）截断并追加 `\n…[已截断，完整内容共 N 字符]` |
| `display_name` | `str` | 易读名称：内置 = tool_registry `display_name`；MCP = 原工具名（`entry.ref`）；skill = "加载 Skill" |
| `server_name` | `str \| None` | MCP Server 显示名（`McpServerEntry.name`）；仅 `tool_type="mcp"` 时非空 |

### 1.2 ToolCallCompletedData 增补

| 字段 | 类型 | 语义 |
|------|------|------|
| `result` | `str` | 完整结果文本：成功 = `result_for_model`（交还模型的完整结果）；失败/拒绝 = 人话失败信息（错误码 + 说明，无堆栈）；超过 `runtime_tool_result_max_chars`（默认 16000）截断并追加同款标记 |
| `display_name` / `server_name` | 同 1.1 | 与 started 事件一致 |

**修订声明**：009 FR-037"展示事件仅含脱敏摘要"由本阶段修订为"日志仅含脱敏摘要；工具事件为页面展示增补完整 `params`/`result` 字段"。009 FR-038（模型上下文完整结果与展示摘要分开）不变；日志仍只用 `params_summary`/`result_summary`。

### 1.3 前端卡片状态机（纯展示层，不进事件契约）

```
running ──tool_call_completed──▶ success | error | denied | cancelled
running ──run_completed(stopped=true) 残留──▶ cancelled
running ──run_completed(status=error) 残留──▶ unknown
running ──流断开且无 run_completed──▶ unknown
```

展示文案与视觉标识（FR-027 文字 + 图标双通道）：正在执行 / 成功 / 失败 / 已取消 / 状态未知。

## 2. 后端运行期记录扩展（内存对象，非持久化）

### 2.1 ToolCallRecord 增补（`backend/app/services/agent_runtime/tools.py`）

| 字段 | 类型 | 语义 |
|------|------|------|
| `params_full` | `str` | 原始参数文本（run_tool 已有 `raw_text`，改为同时保存全量） |
| `result_full` | `str` | 完整结果文本（成功 = result_for_model；失败 = `_failure_result_text`） |
| `display_name` | `str` | 易读名称（R3 来源） |
| `server_name` | `str \| None` | MCP Server 显示名 |

### 2.2 配置项（`backend/app/core/config.py`）

| 配置 | 默认 | 语义 |
|------|------|------|
| `runtime_tool_params_max_chars` | `4000` | 工具事件 `params` 字段字符上限 |
| `runtime_tool_result_max_chars` | `16000` | 工具事件 `result` 字段字符上限 |

## 3. 前端展示状态实体（Pinia store 内存态，刷新即清空）

### 3.1 运行展示槽 RunDisplayState（按会话隔离，`Record<conversationId, RunDisplayState>`）

| 属性 | 类型 | 语义 |
|------|------|------|
| `segments` | `ToolCardSegment[]` | 正文/思考/卡片按事件顺序交错（沿用 009 StreamSegment 结构，tool 段扩展） |
| `phase` | `GenerationPhase` | idle / thinking / generating / tool |
| `generatingReplyId` | `number \| null` | 生成中的回复消息 id（订阅与停止键） |

### 3.2 工具卡片段 ToolCardSegment（StreamSegment 的 tool 形态扩展）

| 属性 | 类型 | 语义 |
|------|------|------|
| `callId` | `string` | 工具调用标识（事件关联键，不作标题，FR-003） |
| `round` | `number` | 轮次（排障用） |
| `toolName` | `string` | 内部暴露名 |
| `displayName` | `string` | 易读名称（卡片标题主体） |
| `toolType` | `'builtin' \| 'mcp' \| 'skill'` | 类型 |
| `serverName` | `string \| null` | MCP Server 名（MCP 卡片与 displayName 联合展示） |
| `status` | `'running' \| 'success' \| 'error' \| 'denied' \| 'cancelled' \| 'unknown'` | 卡片状态（§1.3 状态机） |
| `durationMs` | `number \| null` | 实际耗时（完成事件填入） |
| `paramsSummary` / `resultSummary` | `string` | 收起态摘要（FR-014 直接取事件摘要字段） |
| `paramsText` / `resultText` | `string` | 展开态完整内容（后端已截断） |

## 4. 实体关系

- 一次会话（conversation）在本页面生命周期内至多一个活跃运行 → 至多一个 RunDisplayState；
- 一次运行 → 有序 `segments` 数组（正文段 / 思考段 / 卡片段按 seq 顺序交错）；
- 一次工具调用 ↔ 恰一 张卡片（`callId` 关联 started/completed，FR-007）；
- 刷新页面 → 全部 §3 实体清空，历史消息按 008 持久化正文展示，不还原卡片（FR-024/025）。
