# Contract: Runtime 事件 011 增补与后台运行修订

> 本文件是 011 阶段对 `specs/009-agent-runtime/contracts/agent-runtime-api.md` 的**增补与修订视图**；实现侧 Pydantic 主定义同步更新至 `backend/app/schemas/agent_runtime.py`。命名与帧格式沿用 009（snake_case；`event: <名>\ndata: <json>\n\n`）。
> 修订声明：009 §7"连接断开→取消"自 011 起**废止**（见 §4）；其余 009/010 契约语义不变。

## 1. 新增事件类型（4 种压缩事件）

| event 名 | 时机 | data 结构 |
|----------|------|-----------|
| `compression_started` | 一轮压缩尝试开始 | 见 1.1 |
| `compression_completed` | 摘要生成并写回成功（或分批全部完成） | 见 1.2 |
| `compression_failed` | 摘要请求超时/模型错误/空摘要/写回失败 | 见 1.3 |
| `compression_fallback` | 转入备用裁剪，并附裁剪结果 | 见 1.4 |

全部事件携带公共字段 `run_id`、`seq`（沿用 009），`round` = 触发压缩时所在轮次（即将发起的第 N 次模型请求的 N）；`call_id` = 本次压缩尝试标识（`k` 前缀，载荷关联键——多次尝试互不冲突）。

### 1.1 CompressionStartedData

```text
trigger_reason: Literal["threshold", "precheck"]
    # threshold = 估算输入达到触发比例（每轮请求前检查，FR-038）
    # precheck  = 固定内容预检发现必须压缩才能容纳
estimated_input_tokens: int        # 压缩前估算值（估算口径 R1，非实际用量）
available_input_tokens: int        # 可用输入容量（R2）
trigger_ratio: float               | 本次生效的 Agent 配置触发比例
```

### 1.2 CompressionCompletedData

```text
estimated_tokens_before: int       # 压缩前估算输入
estimated_tokens_after: int        # 压缩后重估输入（FR-043）
messages_compressed: int           # 本次处理的消息条数（组内逐条计）
groups_compressed: int             # 处理的完整消息组数
kept_rounds: int                   # 实际保留的完整对话轮数（FR-043"实际保留数量"）
summary_estimated_tokens: int      # 新摘要估算长度
batches: int                       # 摘要请求分批数
duration_ms: int                   # 压缩总耗时（含摘要请求与写回）
boundary_seq: int                  # 写回后的压缩边界（messages.seq）
```

### 1.3 CompressionFailedData

```text
reason: Literal["timeout", "model_error", "empty_summary", "save_failed", "cancelled"]
estimated_tokens_before: int
duration_ms: int
```

### 1.4 CompressionFallbackData

```text
reason: str                        # 人话：如"摘要生成失败，已裁剪较早对话"
dropped_groups: int                # 备用裁剪丢弃的组数
kept_groups: int                   # 保留的组数
estimated_tokens_after: int        # 裁剪后估算输入
```

约束：
- 压缩事件全部**持久化**并随 SSE 转发（聊天前端可忽略，详见 §5）。
- `estimated_*` 字段一律为估算值，MUST NOT 与模型接口实际 usage 混用（FR-024）；页面展示标注"估算"。
- 备用裁剪不产生独立"成功"事件：裁剪结果在 `compression_fallback` 中（dropped/kept），边界不变（FR-041）。

## 2. 既有事件增补字段

### 2.1 ModelRequestStartedData / ModelRequestCompletedData 增 `purpose`

```text
purpose: Literal["chat", "context_compression"] = "chat"
    # context_compression = 该次模型请求用于生成会话摘要（FR-045：计入模型调用次数与
    # 实际 Token 用量、标记用途；不占用任务执行轮数）
```

- 压缩模型请求同样产生 `model_request_started`/`model_request_completed` 配对事件（call_id 前缀 `c`），其 usage 由 Recorder 计入 runs 的模型调用次数与 Token 汇总；`purpose` 字段供详情页与统计区分用途。
- 压缩请求的 delta 增量**不**转发 SSE、**不**落库（摘要全文经 `output_content` 透传字段交 Recorder）。

### 2.2 透传字段（Recorder 专用，SSE 转发时必须剥离）

沿用 `RunCompletedData.content_text/reasoning_text` 的"透传-剥离"先例：

| 事件 | 新增 data 字段 | 剥离方 | 去向 |
|------|----------------|--------|------|
| model_request_completed | `request_messages: list[dict] \| None`（该次请求完整 messages 数组） | SSE 桥接 | 载荷 model_input |
| model_request_completed | `output_content: str \| None` / `output_reasoning: str \| None` / `output_tool_calls: list[{name, arguments}] \| None`（该次响应正文/思考/工具调用，结构化分离） | SSE 桥接 | 载荷 model_output（JSON：`{content, reasoning, tool_calls}`） |
| tool_call_started | `params_full: str`（完整参数文本，不截断） | SSE 桥接 | 载荷 tool_params |
| tool_call_completed | `result_full: str`（完整结果文本，不截断） | SSE 桥接 | 载荷 tool_result |
| compression_started | `input_full: str`（摘要请求完整输入文本） | SSE 桥接 | 载荷 compression_input |
| compression_completed | `output_full: str`（最终摘要全文） | SSE 桥接 | 载荷 compression_output |

约束：
- 透传字段写入 `run_payloads` 前经统一脱敏（`services/sanitize.py`，R10）；**完整保存、不截断**（011 澄清决定）。
- SSE 消费者（前端）永远收不到透传字段与 `content_text`/`reasoning_text`。
- `run_events.data` 落库前同样剥离上述字段与 010 的 `params`/`result` 展示字段（工具步骤完整内容一律走载荷接口按需加载，FR-017/018）。

## 3. RunRequest 增字段（Runtime 公开接口）

```python
@dataclass
class RunRequest:
    ...
    conversation_id: int | None = None        # None（评测直调）时跳过压缩逻辑

@dataclass
class RunHistoryMessage:
    role: str
    content: str
    seq: int | None = None                    # messages.seq；None=运行内消息
```

压缩所需的 Agent 配置（auto_compact 等 4 项）由 Runtime 在启动加载阶段随 Agent 配置一并读取，调用方无需传递。

## 4. 后台运行修订（对 009 §7 的修订，FR-006）

- **废止**：009 §7"连接断开：SSE 生成器检测到客户端断开时，聊天层触发与 stop 相同的取消"。
- **新语义**：客户端断开（页面关闭/网络中断）**不取消**运行；任务继续在后台执行，结构事件照常持久化，终态照常落库（消息 + run）。
- 用户主动停止仍走 `POST .../stop`（语义不变）；会话互斥（生成中 409）不变。
- **自动续播**：`GenerationTask.buffer` 无订阅者期间持续累积事件；重新订阅（`GET .../stream`）按 008 语义先重放已产生事件再实时跟随——前端既有"发现 generating 消息即重订阅"逻辑即完成续播，无新增接口。
- 服务重启遗留的运行：启动时批量将 `runs.status='running'` 置为 `failed`、end_reason="运行中断：服务在运行期间重启"（FR-007）；对应 generating 消息沿用 008 惰性 incomplete 机制。

## 5. 前端消费约定

- 聊天页（stores/chat.ts）：对 `compression_*` 事件与 `purpose` 字段**忽略即可**（dispatchFrame 未知事件丢弃，前向兼容）；可选在生成中状态区展示"正在压缩上下文"轻提示。
- 运行详情页：`run_events` 渲染 §1 全部事件；模型步骤读取 `purpose` 区分"对话请求/上下文压缩"；估算字段展示带"（估算）"。
- 枚举消费：`runs.status`、`payload_type`、压缩 `reason` 等枚举以 `contracts/runs-api.md` 与本文为唯一主定义，前端不得自行扩展取值。
