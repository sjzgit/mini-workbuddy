# Research: 统一 Agent Runtime（009）

> 决策依据：specs/009-agent-runtime/spec.md + Clarifications（2026-09-15）+ 现有代码调研。
> 每项给出决策、理由与被否决的备选。

## R1 Runtime 模块形态与边界

**Decision**: 新建 `backend/app/services/agent_runtime/` 包（`__init__.py`、`events.py`、`skills.py`、`tools.py`、`runtime.py`），Runtime 核心为 `execute_run(request) -> AsyncIterator[RunEvent]`，入参 `RunRequest(run_id, agent_id, user_message, history, limits, cancel)`，内部自建 `SessionLocal` 会话读取 Agent/模型/绑定配置（与 008 `_run_generation` 同模式）。聊天层（`chat_service.py`）瘦身为：持久化消息 → 构造 `RunRequest`（从 DB 读历史）→ 消费事件桥接到 GenerationTask/SSE → 按 `RunResult` 落库终态。

**Rationale**: FR-004/005 要求 Runtime 不依赖 HTTP 请求对象、可被评测直接调用；包结构把事件、工具、Skill、循环四个关注点分开，避免单文件超 800 行。`SessionLocal` 独立会话沿用 008 已验证的后台任务模式。

**Alternatives considered**:
- 单文件 `agent_runtime.py`：会超 1000 行，违背简洁原则。
- Runtime 接收 conversation_id 自读历史：把 Runtime 绑死在聊天数据模型上，评测场景无法复用（违反 FR-005）。

## R2 事件契约与 008 SSE 的兼容

**Decision**: 事件类型扩展为（契约主定义见 contracts/agent-runtime-api.md）：
`run_started`、`model_request_started`、`reasoning_delta`、`content_delta`、`model_request_completed`、`tool_call_started`、`tool_call_completed`、`error`（流内错误，沿用 008 类别）、`run_completed`（终态，取代 008 的 `done`）。所有事件 data 携带 `run_id`、`seq`（运行内从 1 递增）、`round`；模型请求/工具调用相关事件带 `call_id`。008 合约 §StreamEvent 由本契约修订（终端事件改名），在 008 chat-api.md 追加修订记录。

**Rationale**: FR-031/032/033 的事件清单是硬性要求；`reasoning_delta`/`content_delta`/`error` 保留原名使前端改动最小；终端事件必须携带结束原因与状态，`done` 语义不再准确。

**Alternatives considered**:
- 保留 `done` 名称、把状态塞进 data：名字与语义不符，后续事件消费方易混淆。
- 新开 WebSocket 通道：纯实现翻新，无业务收益（YAGNI）。

## R3 模型调用扩展（工具调用 + Token 用量）

**Decision**: 扩展 `openai_client.stream_chat_completion`：新增可选参数 `tools: list[dict] | None`（OpenAI function calling 格式）与 `include_usage: bool = False`（`stream_options: {"include_usage": true}`）。新增产出类型 `ToolCallDelta(index, id, name, arguments_fragment)` 与 `UsageInfo(prompt_tokens, completion_tokens, total_tokens)`（均可为 None=未知）。运行时累积 `arguments_fragment` 得到完整 JSON 参数；`finish_reason == "tool_calls"` 触发工具执行。

**Rationale**: 复用现有调用基础设施（FR-006），只加参数不改已有行为（默认值保证 008 测试不破坏）；usage 从 API 实际返回解析，缺失即未知（FR-034）。

**Alternatives considered**:
- 另写一个 `stream_chat_with_tools`：与现有函数 90% 重复，违反 FR-006。
- 自己数 token 估算当用量：违反 FR-034"未返回时标记未知，不得填零/估算"。

## R4 工具命名与统一执行入口

**Decision**: 命名规则——内置工具保持原名（`current_time`/`shell`/`file_read_write`）；MCP 工具暴露名 = `mcp__` + 消毒后的 Server 名 + `__` + 原工具名（消毒：非法字符折叠为 `_`，总长截到 64，冲突时追加 `_2`、`_3`）；`load_skill` 为保留名（MCP 工具消毒后撞名时同样加后缀避让）。运行内维护 `暴露名 → (工具类型, 真实标识)` 映射表。统一入口在 Runtime 内做三层校验：①本次运行目录中存在 ②执行前从 DB 重新校验绑定与启用（内置走 `tool_executor.execute` 复用其启停/参数/危险命令校验；MCP 用 `jsonschema` 校验参数后 `session.call_tool`；Skill 走 skills 校验链）③取消信号检查。

**Rationale**: OpenAI 兼容接口的 function name 只允许 `[a-zA-Z0-9_-]{1,64}`；`mcp__` 前缀消除本地/MCP 名称冲突（FR-022）。`tool_executor.execute` 已实现"永不抛异常"的结构化失败，直接复用（FR-025）。`jsonschema` 已是 mcp SDK 传递依赖（uv.lock 已含 4.26.0），无新增依赖。

**Alternatives considered**:
- 直接用 MCP 原始工具名不加前缀：与内置工具/彼此之间冲突不可控。
- 为 MCP 参数自写校验器：重复造轮子，jsonschema 现成。

## R5 MCP 连接生命周期（并发隔离）

**Decision**: 每次运行在开始时为"已绑定且启用"的 MCP Server 各建一条独立连接（`AsyncExitStack` 托管：stdio 每次运行一个子进程 / http 每次运行一个会话），列出工具目录；运行结束（成功/失败/限制/取消任一路径）由 `finally` 关栈统一清理。连接失败不阻断运行：该 Server 的工具不出现在本次目录，记日志，模型若点名调用将得到明确的 denied 错误。

**Rationale**: 澄清答案要求"同一 MCP 工具可被多个 Runtime 同时启用、运行相互隔离"——每运行独享连接天然满足（进程级隔离，互不串扰）；`AsyncExitStack` 是现有 `mcp_client.connect_and_list` 已验证的清理模式，扩展为可复用会话即可（FR-029 覆盖所有退出路径）。

**Alternatives considered**:
- 跨运行共享连接池（引用计数 + 空闲回收）：省进程但引入池生命周期、失效重连、并发多路复用复杂度，与单机工作台定位不匹配（YAGNI）。
- 惰性连接（首次调用才连）：无法在运行开始构建完整工具目录（FR-021 要求目录含 MCP 工具）。

## R6 Skill 目录与 load_skill

**Decision**: 运行开始时从 `agent_bindings(skill) × skills.enabled` 取目录，以 XML 片段追加到系统提示词（澄清指定格式，含稳定标识）：

```
<skill>
Name: {skill名称}
ID: {dir_name}
Description: {说明}
</skill>
```

附按需加载指引。`load_skill` 参数 `{skill_id: string}`（值 = dir_name）；执行链：本次目录存在 → DB 复核绑定+启用 → `skill_files.read_skill` 读指令 → UTF-8 字节数超 `settings.runtime_skill_max_bytes`（默认 65536，即 64KB）报错不截断。错误码：`skill_not_found`/`skill_not_bound`/`skill_disabled`/`skill_file_missing`/`skill_unreadable`/`skill_too_large`，结构化错误交还模型。Agent 无可用 Skill 时目录与工具都不提供（FR-015）。

**Rationale**: 用户澄清指定了 XML 格式；模型需要稳定标识才能调用 load_skill，故在格式中补 `ID:` 行（与 spec FR-014"标识、名称和说明"一致）。64KB 落在 spec 假设的"几十 KB"量级，可经 settings 调整。

**Alternatives considered**:
- 用 skill id（数据库自增）作标识：刷新重建后 id 会变，dir_name 才是稳定标识。
- 把 load_skill 作为系统提示词指令而非工具：无法产生工具事件（FR-020 复用工具调用事件）。

## R7 轮数语义与收尾请求

**Decision**: 一"轮" = 循环内一次模型请求（含其触发的工具执行）。`有效轮数 = min(agent.max_rounds, limits.max_rounds)`。第 N 轮模型请求工具 → 执行 → 进入第 N+1 轮；模型不再请求工具 → `completed`。第 max_rounds 轮仍请求工具 → 不再执行工具，追加一次收尾请求（不计轮数、不带 tools，提示词告知已达上限需基于已有信息作答）→ 结束原因 `max_rounds`。收尾请求失败按运行级失败处理（spec Assumptions）。

**Rationale**: 与 spec FR-012 及澄清答案 B 一致；"收尾请求不计轮数"避免 max_rounds=1 时出现零轮对话的退化。

**Alternatives considered**:
- 直接掐断：使用者拿不到结论（澄清已否决）。

## R8 取消与资源清理

**Decision**: 取消双通道——①聊天层沿用 `asyncio.Task.cancel()`（停止接口触发）；②运行内 `cancel: asyncio.Event`，在每个模型增量、工具执行前后与轮间检查，收尾阶段不再发起新请求。清理统一放 `finally`：MCP AsyncExitStack 关闭、模型 HTTP 客户端随上下文退出；任何异常路径（含 CancelledError）都先产出终态事件再退出。浏览器断开：SSE 流生成器在心跳间隙检查 `request.is_disconnected()`，触发与"停止生成"相同的取消调用。

**Rationale**: `Task.cancel()` 无法中断 `asyncio.to_thread` 中的同步工具，事件检查保证工具返回后立即停止；`finally` + ExitStack 是 Python 清理的标准答案（FR-026~029）。

**Alternatives considered**:
- 只靠 Task.cancel 不设事件：工具线程完成后循环可能继续一轮，取消不彻底。
- Runtime 内监听 websocket/httpx 断开：违反 FR-027（Runtime 不监听浏览器连接）。

## R9 脱敏摘要与日志

**Decision**: 展示事件与日志只携带摘要：工具参数摘要 = 参数 JSON 截断至 200 字符；工具结果摘要 = 结果文本截断至 200 字符；Skill 指令正文、完整上下文、未处理工具结果不进事件与日志（模型上下文保留完整结果，FR-037/038）。日志行沿用现有 `logger.info("[runtime] ...")` 风格，记录 run_id、round、call_id、tool_name、status、duration、用量。

**Rationale**: 页面需要的是"正在调用工具：X / 成功（耗时）"级别的信息；完整结果仅供模型，两者分流（FR-038）。

**Alternatives considered**:
- 事件携带完整工具结果：前端不需要且泄露执行细节，违背 FR-037。

## R10 并发与会话互斥

**Decision**: 运行 = 独立 asyncio.Task，各自持有 RunContext（上下文数组、seq 计数、MCP 连接、取消事件），天然并发隔离（FR-039/040）。会话互斥沿用 008 `GenerationRegistry.get_running_by_conversation` → 409（满足 FR-043，服务端会话级互斥），无需新锁。注册表按键仍为 reply_message_id，同时记录 run_id 便于排障。

**Rationale**: 单事件循环内 Task 间无共享可变状态即隔离；会话互斥 008 已实现并测试，不重复造。

**Alternatives considered**:
- 全局并发上限/排队队列：单机工作台 YAGNI，SQLite 与事件循环足够。

## R11 前端接入

**Decision**: `api/chat.ts` 扩展事件联合类型（新事件 + `run_completed` 替代 `done`）；`stores/chat.ts` 增加 `toolStatus` 状态与 `phase: 'tool'`，处理 `tool_call_started/completed` 与 `run_completed`；`ChatMessages.vue` 在生成占位区显示"正在调用工具：×××"简要提示（不影响正文流式区）。Vitest 用例同步更新。

**Rationale**: spec Assumptions 要求简要状态提示且不干扰正文顺序；store 已是事件汇聚点，改动集中。

**Alternatives considered**:
- 工具调用过程持久化/回放：spec 明确本阶段不持久化运行记录。

## R12 测试策略

**Decision**: 后端 pytest：运行时单测（monkeypatch `stream_chat_completion` 用假流驱动直答/工具循环/Skill 加载/轮数收尾/取消/拒绝/事件顺序）；API 层沿用 TestClient + 内存 SQLite 夹具验证 SSE 新事件与终态落库；MCP 用假连接对象替换（不打真实进程）。前端 Vitest：store 事件处理与 api 类型解析。交付门禁按 AGENTS.md §9（pytest + pyright + build + vitest 全绿）。

**Rationale**: 与 008 测试基建（stream_env 夹具、假流模式）一致，成本低、可控性强。

**Alternatives considered**:
- 集成真实 MCP Server 的端到端测试：环境依赖重，quickstart 手动场景覆盖。
