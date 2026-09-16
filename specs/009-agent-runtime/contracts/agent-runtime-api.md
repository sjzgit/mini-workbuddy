# Contract: Agent Runtime 事件与接口（009）

> 本契约是 009 阶段 Runtime 运行事件、工具命名、load_skill 与 Runtime 模块接口的**唯一主定义**。
> 前后端只消费本契约，禁止各自硬编码。字段命名 snake_case；SSE 帧格式与 008 一致（`event: <名>\ndata: <json>\n\n`）。
> 对 008 `chat-api.md` 的修订：终端事件 `done` 由 `run_completed` 取代（§5），其余 HTTP 端点语义不变。
> 对本文的 010 增补：`tool_call_started` / `tool_call_completed` 增补 `params` / `result` / `display_name` / `server_name` 字段（见 §2/§3 标注），用于聊天页工具过程卡片展示；日志仍只用脱敏摘要（FR-037 日志部分不变）。增补 diff 视图见 `specs/010-tool-execution-display/contracts/display-events.md`。
> 对本文的 011 增补与修订：①新增 4 种压缩事件（compression_started/completed/failed/fallback）；②model_request_* 增 `purpose` 字段、tool_call_* 增 `params_full`/`result_full` 透传字段、compression_* 增 `input_full`/`output_full` 透传字段（SSE 前剥离）；③RunStartedData 增 `model_name`/`model_identifier`；④RunRequest 增 `conversation_id`/`reply_message_id`、RunHistoryMessage 增 `seq`；⑤**修订** §7"连接断开→取消"废止（后台运行）。主定义见 `specs/011-context-compression-run-records/contracts/runtime-events-011.md`。

## 1. 标识约定

| 标识 | 生成方 | 语义 |
|------|--------|------|
| run_id | Runtime | 唯一运行标识（uuid4 十六进制），全部事件携带 |
| seq | Runtime | 运行内从 1 严格递增的整数，全部事件携带 |
| round | Runtime | 轮次：0 = run_started；第 N 次模型请求 = N；收尾请求 round = max_rounds + 1 |
| call_id | Runtime | 一次模型请求或一次工具调用的标识（`m`/`t` 前缀 + 短随机），开始与结束事件配对 |

## 2. 事件类型全集（SSE event 名）

| event 名 | 时机 | 必带字段 |
|----------|------|----------|
| run_started | 运行开始（恰一次，seq=1） | agent_id, agent_name |
| model_request_started | 每次模型请求发出前 | round, call_id |
| reasoning_delta | 思考过程增量 | round, call_id, text |
| content_delta | 回答正文增量 | round, call_id, text |
| model_request_completed | 每次模型请求结束（与 started 配对） | round, call_id, status, duration_ms, usage |
| tool_call_started | 工具开始执行（恰一次/调用） | round, call_id, tool_name, tool_type, params_summary, params*, display_name*, server_name* |
| tool_call_completed | 工具执行结束（与 started 配对） | round, call_id, tool_name, tool_type, status, duration_ms, result_summary, result*, display_name*, server_name* |

> 带 `*` 字段为 010 增补：`params`（完整参数文本，超限截断）、`result`（完整结果/失败人话，超限截断）、`display_name`（易读名）、`server_name`（MCP Server 名，仅 mcp 非空）。
| error | 运行级错误的人话提示（终态前发出） | category, message |
| run_completed | 运行终态（恰一次，必为最后一个事件） | status, reason, usage_total, message, stopped |

`reasoning_delta` / `content_delta` / `error` 沿用 008 命名。`content_delta` 按生成顺序到达，工具调用前后的正文片段全部保留（FR-013）。

## 3. 事件 data 结构（Pydantic 主定义：backend/app/schemas/agent_runtime.py）

所有 data 的公共字段：`run_id: str`、`seq: int`；按上表追加：

```
RunStartedData          agent_id: int, agent_name: str
ModelRequestStartedData round: int, call_id: str
DeltaData               round: int, call_id: str, text: str        # reasoning_delta / content_delta 共用
ModelRequestCompleted   round: int, call_id: str,
                        status: Literal["ok","error","cancelled"],
                        duration_ms: int,
                        usage: UsageInfo | None
ToolCallStartedData     round: int, call_id: str, tool_name: str,
                        tool_type: Literal["builtin","mcp","skill"],
                        params_summary: str,                       # ≤200 字符脱敏
                        # ---- 010 增补（展示用）----
                        params: str,                               # 完整参数文本，超 runtime_tool_params_max_chars
                                                                   # (默认4000) 字符截断 + 截断标记
                        display_name: str,                         # 易读名：builtin=注册表 display_name；
                                                                   # mcp=原工具名；skill="加载 Skill"
                        server_name: str | None                    # MCP Server 显示名，仅 mcp 非空
ToolCallCompletedData   round: int, call_id: str, tool_name: str, tool_type: 同上,
                        status: Literal["success","error","denied","cancelled"],
                        duration_ms: int, result_summary: str,     # ≤200 字符脱敏
                        # ---- 010 增补（展示用）----
                        result: str,                               # 完整结果文本：成功=result_for_model；
                                                                   # 失败=人话失败信息（无堆栈）；
                                                                   # 超 runtime_tool_result_max_chars
                                                                   # (默认16000) 字符截断 + 截断标记
                        display_name: str, server_name: str | None # 同 ToolCallStartedData
ErrorEventData          category: StreamErrorCategory(008 枚举), message: str   # 沿用 008
UsageInfo               prompt_tokens: int|None, completion_tokens: int|None, total_tokens: int|None
                        # None = 接口未返回，标记未知；禁止填 0（FR-034）
RunCompletedData        status: Literal["completed","max_rounds","error","cancelled"],
                        reason: str, usage_total: UsageInfo|None,
                        content_text: str, reasoning_text: str|None,   # 全文，仅 Runtime→桥接层用于落库；
                                                                       # 桥接层转发 SSE 时剥离这两个字段
                        message: MessageOut(008)|None,             # 桥接层按终态落库结果回填；占位行被删时 null
                        stopped: bool                              # 用户主动停止 true
```

约束：
- `model_request_completed.usage` 为 None = 整次请求未获得任何用量；各项单独为 None = 该项未知。
- `usage_total` = 各请求已知项求和；全部未知时为 None。
- 事件必须按 seq 升序产出；`run_completed` 之后不再有任何事件。
- `params_summary` / `result_summary` 为脱敏摘要（截断 ≤200 字符），完整参数与结果只进模型上下文（FR-037/038）。
- 010 增补：`params` / `result` 为页面展示用完整文本（截断上限见 §3 定义），前端按不可信纯文本渲染，禁止 HTML/脚本执行；日志仍只用摘要，禁止记录 `params` / `result` 全文。
- `run_completed.content_text` / `reasoning_text` 仅供桥接层落库使用：SSE 转发时必须剥离（前端经 `content_delta` 已获得全文），落库后 `message` 回填（FR-037）。

## 4. 工具命名与映射规则

| 来源 | 暴露名规则 | 示例 |
|------|-----------|------|
| 内置工具 | 注册表原名 | `current_time`、`shell`、`file_read_write` |
| MCP 工具 | `mcp__` + 消毒(Server名) + `__` + 原工具名 | `mcp__github__create_issue` |
| Skill 加载 | 保留名 `load_skill`（仅存在可用 Skill 时提供） | `load_skill` |

消毒：非 `[A-Za-z0-9_-]` 字符折叠为 `_`；总长截断至 64；暴露名冲突（含与保留名冲突）按目录顺序追加 `_2`、`_3`…，并在日志记录映射。运行内映射表 `暴露名 → (tool_type, 真实标识, server_id)`。

统一执行入口校验链（任一失败返回结构化错误交还模型，不抛异常）：
1. 暴露名在本运行目录内（否则 `tool_not_found` 语义错误）；
2. 执行前从 DB 复核：绑定关系 + 资源启用状态（`tool_disabled` / `skill_disabled` / `skill_not_bound`）；
3. 参数校验：内置 = tool_executor 现有 pydantic 校验；MCP = jsonschema(inputSchema)；load_skill = 单字符串参数；
4. 取消信号检查：已置位则不执行（status=cancelled）。

错误码：内置沿用 008 `ToolErrorCode`（tool_not_found/tool_disabled/invalid_params/execution_error…）；MCP 失败映射 `mcp_error`（附 mcp_client 分类人话）；Skill 专用：`skill_not_found`、`skill_not_bound`、`skill_disabled`、`skill_file_missing`、`skill_unreadable`、`skill_too_large`。

## 5. load_skill 工具

```
名称: load_skill
说明: 读取指定 Skill 的完整指令。仅当任务符合某 Skill 用途时调用。
参数: { "skill_id": string }   // 取值 = Skill 目录名（稳定标识）
```

- 目录条目格式（追加于系统提示词之后，逐 Skill 一个块）：

```
<skill>
Name: {skill 名称}
ID: {dir_name}
Description: {说明}
</skill>
```

- 目录前置说明固定包含："当任务符合某个 Skill 的用途时，先调用 load_skill 加载其完整指令，再按照指令执行。"
- 成功：完整指令文本作为工具结果进入上下文；产生 tool_call_started/completed（tool_type=skill）。
- 失败：§4 错误码结构化交还，由模型决定后续处理；超过 `runtime_skill_max_bytes`（默认 64KB）报 `skill_too_large`，禁止静默截断（FR-019）。
- 不可接受文件路径：skill_id 不在目录内一律拒绝（含路径形态输入，FR-017）。

## 6. Runtime 模块接口（供聊天层与后续评测直接调用）

```python
# backend/app/services/agent_runtime/
@dataclass
class RunLimits:            # 只能收窄（data-model.md §1.2）
    max_rounds: int | None = None
    allowed_tool_names: frozenset[str] | None = None
    disabled_skill_ids: frozenset[str] = frozenset()

@dataclass
class RunHistoryMessage:
    role: str               # "user" | "assistant"
    content: str

@dataclass
class RunRequest:
    agent_id: int
    user_message: str
    history: list[RunHistoryMessage]
    limits: RunLimits = field(default_factory=RunLimits)
    cancel: asyncio.Event = field(default_factory=asyncio.Event)
    run_id: str = ""        # 空则自动生成 uuid4

async def execute_run(request: RunRequest) -> AsyncIterator[RunEvent]: ...
#   产出 §2 事件流；最后一个事件必为 run_completed（其 data 含 RunResult 全部字段）。
```

约束：
- Runtime 不 import FastAPI/Request，不开 HTTP 连接，不读浏览器状态（FR-005）。
- 轮数语义：一"轮" = 一次模型请求；有效轮数 = min(agent.max_rounds, limits.max_rounds)；达到后不再执行工具，追加一次收尾请求（不计轮数，reason=max_rounds）（FR-012）。
- 取消：cancel 置位或任务被 cancel 后尽快停止模型流、不再执行新工具、进行中的工具按平台能力终止；所有退出路径 finally 清理 MCP 连接（FR-026~029）。
- 模型请求超时/断连沿用 008 `chat_stream_*_seconds`；MCP 连接超时 `runtime_mcp_connect_timeout_seconds`。

## 7. 聊天层桥接（HTTP/SSE 修订）

- `POST /api/conversations/{id}/messages`、`POST .../regenerate`：请求/响应结构不变（008 契约 §StartReplyResponse）。
- `GET .../messages/{id}/stream`：SSE 事件集改为 §2 全集；`run_completed` 为终态（`message` 字段语义同 008 `done.message`）；`error` 仍在终态前发出。
- `POST .../stop`：语义不变；取消由聊天层转换为目标运行的取消信号。
- 连接断开：SSE 生成器检测到客户端断开时，聊天层触发与 stop 相同的取消（Runtime 本身不感知连接，FR-027）。
- 会话互斥：沿用 008 会话级互斥（生成中 409），跨客户端同样生效（FR-043）。
