# Tasks: 统一 Agent Runtime（009）

**Input**: Design documents from `/specs/009-agent-runtime/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/agent-runtime-api.md, quickstart.md

**Tests**: 本任务清单包含测试任务——宪法 §IV 要求 `uv run pytest` / Vitest 全绿作为交付门禁；每个用户故事附带其专属测试任务。

**Organization**: 按用户故事分组，每个故事可独立实现与验证。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行（不同文件、无未完成依赖）
- **[Story]**: 所属用户故事（US1~US6，对应 spec.md）
- 描述含确切文件路径

## Path Conventions

- 后端：`backend/app/`（api/ services/ schemas/ core/）+ `backend/tests/`
- 前端：`frontend/src/`（api/ stores/ components/chat/）+ `frontend/src/**/__tests__/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: 契约落点文件与配置项就位（零依赖、零迁移）

- [x] T001 [P] 在 backend/app/schemas/agent_runtime.py 按契约 §3 定义事件 data 结构（RunStartedData/ModelRequestStartedData/DeltaData/ModelRequestCompletedData/ToolCallStartedData/ToolCallCompletedData/ErrorEventData 复用 008/UsageInfo/RunCompletedData）与 StreamErrorCategory 复用导入、事件类型常量（RUN_STARTED/MODEL_REQUEST_STARTED/REASONING_DELTA/CONTENT_DELTA/MODEL_REQUEST_COMPLETED/TOOL_CALL_STARTED/TOOL_CALL_COMPLETED/ERROR/RUN_COMPLETED，字符串值与契约 §2 表格一致）
- [x] T002 [P] 在 backend/app/core/config.py 新增三个配置项：runtime_skill_max_bytes=65536、runtime_mcp_connect_timeout_seconds=30、runtime_tool_result_summary_chars=200（data-model.md §4）
- [x] T003 在 specs/008-chat-conversations/contracts/chat-api.md 末尾追加"009 修订记录"一节：终端事件 done 由 run_completed 取代、新增事件集引用 009 契约（SSOT 双向引用，R2）

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Runtime 骨架与模型调用扩展——所有用户故事的公共前置

**⚠️ CRITICAL**: US1~US6 全部依赖本阶段

- [x] T004 创建 backend/app/services/agent_runtime/__init__.py：定义 RunLimits（max_rounds/allowed_tool_names/disabled_skill_ids，默认不收窄）、RunHistoryMessage（role/content）、RunRequest（agent_id/user_message/history/limits/cancel/run_id 空则 uuid4）并导出 execute_run 符号占位（签名按契约 §6；实现由 T009 提供）
- [x] T005 [P] 创建 backend/app/services/agent_runtime/events.py：RunEvent dataclass（run_id/seq/event/round/call_id/data）+ RunEventEmitter（run_id 注入、seq 从 1 自增分配、emit(type, round, call_id, **data) → RunEvent，保证严格递增）
- [x] T006 [P] 扩展 backend/app/services/openai_client.py：stream_chat_completion 新增可选参数 tools: list[dict] | None = None（OpenAI function calling 格式，payload 注入 tools 与 tool_choice:"auto"）与 include_usage: bool = False（stream_options）；新增 ToolCallDelta(index/id/name/arguments_fragment) 产出类型；解析 choices[].delta.tool_calls 与 finish_reason=="tool_calls"透传；解析末尾 usage chunk 为 UsageInfo(prompt_tokens/completion_tokens/total_tokens | None)（无 chunk 则 None）；默认参数下行为与现状完全一致（008 回归不破坏）
- [x] T007 创建 backend/app/services/agent_runtime/tools.py：①TOOL_TYPE_BUILTIN/MCP/SKILL 常量与 load_skill 保留名；②sanitize_server_name（非 [A-Za-z0-9_-] 折叠 _、截 64）与 build_tool_catalog(session, agent_id, limits) →（目录条目列表 ToolCatalogEntry、暴露名映射 dict、skill 目录列表、mcp server_id 列表；内置=绑定∩tools.enabled、MCP=绑定∩mcp_servers.enabled 的 tools_json 快照展开、Skill=绑定∩skills.enabled；limits 只能收窄：allowed_tool_names 过滤暴露名、disabled_skill_ids 过滤 skill）；③mcp 暴露名 mcp__{消毒Server名}__{原名}+冲突后缀；④run_tool(call, ctx) 统一执行入口骨架：目录内查名 → DB 复核绑定与启用 → 按类型分发（内置委托 tool_executor.execute；MCP 用 jsonschema 校验后 mcp_client 会话 call_tool，失败映射 mcp_error+人话；skill 委托 skills 模块）→ 返回 ToolCallRecord（result_for_model/summary≤200 截断/status），全程不抛异常、先查 ctx.cancel 置位
- [x] T008 创建 backend/app/services/agent_runtime/skills.py：build_skill_catalog_section（目录条目列表 → 契约 §5 XML 片段 + 按需加载指引一句）；load_skill(session, ctx, skill_id) 执行链：ctx 目录存在性 → DB 复核绑定+启用 → skill_files.read_skill 读指令 → 字节数 > settings.runtime_skill_max_bytes 报 skill_too_large（不截断）→ 返回指令全文或结构化错误（错误码 skill_not_found/skill_not_bound/skill_disabled/skill_file_missing/skill_unreadable/skill_too_large，人话中文文案）
- [x] T009 创建 backend/app/services/agent_runtime/runtime.py：RunContext（run_id/agent_id/emitter/cancel/limits/目录与映射/MCP 连接栈/messages 累积/正文与思考缓冲/usage 累计）+ execute_run(request) 主循环：自建 SessionLocal 读 Agent/模型/密钥 → 有效轮数=min(agent.max_rounds, limits.max_rounds) → 组装系统提示词（XML Skill 目录按 FR-014 追加）+ history + user_message → 逐轮 stream_chat_completion（enable_thinking 映射沿用 008）→ 产出 §2 全部事件（run_started 恰一次 seq=1 → run_completed 恰一次收尾）→ 无工具即 completed；tool_calls 逐个 run_tool 后结果以 role=tool 消息追加上下文再进下一轮 → 轮数耗尽仍请求工具则收尾请求（round=max_rounds+1、无 tools、不计轮数、reason=max_rounds）→ cancel 事件与 asyncio.CancelledError 在增量粒度、工具前后、轮间检查 → finally 关闭 MCP AsyncExitStack 全路径清理 → usage 求和（未知项保持 None）
- [x] T010 更新 backend/tests/conftest.py：新增 runtime_env 夹具——隔离 workspace/skills 目录、播种启用状态的 Agent/模型/绑定行、假流工厂（monkeypatch app.services.openai_client.stream_chat_completion 为脚本化 FakeStream，按测试剧本产出 ContentDelta/ReasoningDelta/ToolCallDelta/UsageInfo 序列）
- [x] T011 后端基础单测 backend/tests/test_agent_runtime.py（本阶段先覆盖基础设施）：emitter seq 严格递增、run_started/run_completed 恰一次；假流直答：事件序列完整（run_started→model_request_started→content_delta*→model_request_completed→run_completed）、completed 状态、usage 汇总与未知 None；content/reasoning 全文正确

**Checkpoint**: Runtime 可对无工具 Agent 完成一次完整运行并产出契约事件流；模型层扩展可注入 tools 与解析 usage；后续故事在此骨架上展开

---

## Phase 3: User Story 1 - 聊天经由统一 Runtime 完成直答运行 (Priority: P1) 🎯 MVP

**Goal**: 聊天链路直答改经 execute_run，聊天接口只收请求、转发事件；SSE 输出新事件集

**Independent Test**: 未绑定工具/Skill 的 Agent 发送一条消息 → 流式回复完整 → 日志有 run_id 与 run_started/run_completed（quickstart S1）

### Implementation for User Story 1

- [x] T012 [US1] 重构 backend/app/services/chat_service.py：删除 _run_generation/_finalize_generation/_build_llm_messages/_classify_http_error 中的模型直调逻辑，改为——send_message/regenerate 落库后启动 _start_generation_task：①创建 CancelEvent 存入注册表 ②异步任务内构造 RunRequest（history 从 DB 读 user+completed assistant）→ 遍历 execute_run 事件：model/content/reasoning 增量与错误桥接到既有 GenerationTask.publish 通道（reasoning_delta/content_delta/error 直接转发）→ 消费 RunCompleted：按 data-model.md §2.2 映射落库（completed/max_rounds→completed；error/cancelled 有正文→incomplete、无正文→删占位行）→ 组装并 publish run_completed 终态（含 MessageOut/stopped/usage_total）③保留 008 孤儿标记/心跳/重订阅机制不动
- [x] T013 [US1] 更新 backend/app/services/generation_registry.py：GenerationTask 增加 run_id 字段与 cancel_event（asyncio.Event）字段；stop_generation 改为置位 cancel_event + task.cancel() 双通道（R8）；_assert_not_busy 会话互斥逻辑保持不变
- [x] T014 [US1] 更新 backend/app/api/chat.py 与 chat_service.build_message_stream：stop 路由行为不变（走注册表）；stream 生成器增加客户端断开检测（生成器 finally 中置位该任务 cancel_event——等待事件间隙用 asyncio.wait_for 包裹 request.is_disconnected 轮询或依赖 finally 兜底，保证 Runtime 不感知 HTTP（FR-027））
- [x] T015 [US1] 事件桥接层脱敏核对：chat_service 转发的事件 data 中 params_summary/result_summary 沿用 Runtime 产出的 ≤200 字符摘要，不新增完整内容透传；后端日志 [runtime] 行含 run_id/round/call_id/tool_name/status/duration（R9）
- [x] T016 [US1] 更新 backend/tests/test_chat_stream.py 与 test_chat_api.py：done→run_completed 断言、事件序含 run_started/model_request_*、usage 非 0 断言（null 或正整数）、停止→cancelled+stopped=true；确保全部回归通过
- [x] T017 [US1] 前端 frontend/src/api/chat.ts：扩展 StreamEvent 联合（run_started/model_request_started/model_request_completed/tool_call_started/tool_call_completed/run_completed data 类型按契约 §3）；dispatchFrame 增加分支；DoneEventData 移除、RunCompletedData（status/reason/usage_total/message/stopped）
- [x] T018 [US1] 前端 frontend/src/stores/chat.ts：handleStreamEvent 处理 run_completed（等价原 done 分支：终态消息 upsert、phase=idle、清缓冲）与 run_started（记录 agent 名可选）；未知事件忽略不抛错
- [x] T019 [US1] 前端测试 frontend/src/stores/__tests__/chat.spec.ts 与 frontend/src/api/__tests__/chat.spec.ts：run_completed 终态用例替换 done 用例；SseParser 新事件解析用例

**Checkpoint**: 直答链路 100% 经 Runtime；SSE 输出契约 §2 事件集；前端正常展示流式回复与终态（MVP 可用）

---

## Phase 4: User Story 2 - 工具调用循环 (Priority: P1)

**Goal**: 绑定工具的 Agent 在聊天中完成模型→工具→再模型的循环，正文跨轮保留

**Independent Test**: 绑定 current_time 的 Agent 问时间 → 工具开始/完成事件出现、前后正文按序保留、最终回答引用工具结果（quickstart S2）

### Implementation for User Story 2

- [x] T020 [US2] backend/app/services/agent_runtime/runtime.py 补全工具循环分支：finish_reason==tool_calls 时逐 ToolCallDelta 聚合参数 → run_tool → 产出 tool_call_started/completed（call_id 配对、params_summary/result_summary 脱敏）→ role=tool 消息追加（完整 result_for_model）→ 轮间检查取消 → 下一轮请求带 tools；正文片段跨轮累积不清空（FR-013）
- [x] T021 [US2] backend/tests/test_agent_runtime.py 增加 US2 用例：单工具调用循环（事件配对、role=tool 追加、最终回答含工具结果）；多轮交错正文跨轮保留且顺序正确；轮数=max_rounds 后仍请求工具→收尾请求（round=max_rounds+1、无 tools、不计轮数、reason=max_rounds、status=max_rounds）；模型幻觉未知工具名→denied 错误交还、运行继续
- [x] T022 [US2] 前端 frontend/src/stores/chat.ts：tool_call_started/completed 写入 toolStatus（ref：{name,status} | null）；phase 增加 'tool'；run_completed 清空 toolStatus
- [x] T023 [US2] 前端 frontend/src/components/chat/ChatMessages.vue：生成占位区显示"正在调用工具：{name}"（toolStatus 驱动，完成后显示"已完成：{name}"或直接消失，不影响正文流式区，brief 提示样式与既有 token 一致）
- [x] T024 [US2] 前端测试：stores/__tests__/chat.spec.ts 增加 tool 事件用例（状态写入/清理/phase 切换）

**Checkpoint**: 工具循环、正文保留、轮数收尾、拒绝反馈全链路可用（后端 US2 用例 + 手动 S2/S5）

---

## Phase 5: User Story 3 - Skills 发现与按需加载 (Priority: P1)

**Goal**: Skill 目录以 XML 进上下文、load_skill 按需加载指令，无 Skill 不提供工具

**Independent Test**: 绑定 Skill 的 Agent 执行相关任务 → load_skill 调用与指令加载事件出现，模型按指令继续（quickstart S3）

### Implementation for User Story 3

- [x] T025 [US3] backend/app/services/agent_runtime/runtime.py 接入 Skill 目录：build_tool_catalog 产出 skill 条目时仅当目录非空追加 load_skill 工具定义（参数 JSON Schema {skill_id: string} 必填）；系统提示词追加 build_skill_catalog_section 输出（Name/ID/Description XML 块 + 指引句）
- [x] T026 [US3] backend/tests/test_agent_runtime.py 增加 US3 用例：有 Skill→目录含 load_skill、系统提示词含 XML 块与 ID 行；load_skill 成功→tool_type=skill 事件、指令全文进入 role=tool 结果、模型继续；无 Skill→工具列表无 load_skill；各错误码路径（不存在/未绑定/停用/文件缺失/超限 skill_too_large 不截断）
- [x] T027 [US3] 手动验证路径核对（quickstart S3）：Skill 停用后运行 → 目录与工具均不含 load_skill；日志确认目录为空（该断言并入 T026 自动化，本任务为 quickstart 演练记录）

**Checkpoint**: Skill 按需加载闭环（US3 用例全绿）

---

## Phase 6: User Story 4 - 工具权限校验与拒绝反馈 (Priority: P2)

**Goal**: 执行前复核拒绝未绑定/停用/不存在/参数非法调用；命名映射无冲突

**Independent Test**: 伪造各类非法调用 → 全部拒绝且错误明确，工具零执行（quickstart S4）

### Implementation for User Story 4

- [x] T028 [US4] backend/tests/test_agent_runtime.py 增加 US4 用例：运行中把 tools 表行改 enabled=False 后模型再调 → denied/tool_disabled 错误交还且工具未执行（side effect 探针）；Skill 同理 skill_disabled；参数非法（内置 invalid_params 文案、MCP jsonschema 失败）→ 结构化错误；limits.allowed_tool_names 收窄后白名单外调用被拒；limits 只能收窄——白名单包含未绑定工具不生效；mcp__ 命名冲突（两个 Server 同名工具、与内置同名）→ 目录映射唯一、调用解析到正确实现
- [x] T029 [US4] 按用例修补 backend/app/services/agent_runtime/tools.py 执行链缺口（如有）：确保 DB 复核发生在每次执行前（非仅目录构建时）、MCP 参数校验失败映射 invalid_params 语义、denied 结果同样产生 tool_call_completed（status=denied）事件——不新增文件，仅补实现
- [x] T030 [US4] limits 收窄实现核对：build_tool_catalog 与 runtime 轮数取 min 双路径（FR-003）在 test_agent_runtime.py 中断言（若 T028 已覆盖则此任务为复核项）

**Checkpoint**: 权限边界与命名唯一性有自动化保障（S4）

---

## Phase 7: User Story 5 - 取消与资源清理 (Priority: P2)

**Goal**: 取消信号贯通模型流/工具/循环；四类退出路径全清理 MCP 资源

**Independent Test**: 停止生成/断开页面 → 数秒内终止；成功/失败/限制/取消路径后无残留连接（quickstart S6）

### Implementation for User Story 5

- [x] T031 [US5] backend/tests/test_agent_runtime.py 增加 US5 用例：模型流中置位 cancel → 增量停止、run_completed(status=cancelled, stopped=true)、有正文缓冲；工具执行中取消（假工具挂起后置位）→ status=cancelled 且工具不再继续、后续轮不发起；四类退出路径（completed/error/max_rounds/cancelled）断言 MCP AsyncExitStack 已关闭（假连接对象 closed 标志）；收尾请求阶段取消 → 不发起新请求直接 cancelled
- [x] T032 [US5] 按 T031 结果修补 backend/app/services/agent_runtime/runtime.py 取消与清理缺口（如有）：cancel 检查点覆盖增量/工具前后/轮间/收尾前；finally 与 CancelledError 路径都产出 run_completed（恰一次）后再退出

**Checkpoint**: 取消与清理路径有自动化保障（S6 手动配合）

---

## Phase 8: User Story 6 - 运行事件契约与日志规范 (Priority: P2)

**Goal**: 事件契约字段完备、配对、用量真实、脱敏到位、并发隔离

**Independent Test**: 含工具与 Skill 的运行逐条核对事件（quickstart S7/S8）

### Implementation for User Story 6

- [x] T033 [P] [US6] backend/tests/test_agent_runtime.py 增加 US6 用例：一次含工具+Skill 的运行全事件审计——seq 严格递增无空洞、started/completed 按 call_id 配对、run_completed 恰一次且为最后事件、model_request_completed.usage 各项非 0 即 None（假流给 usage=None 断言 null 不为 0）、ToolCallRecord.summary 截断 ≤200
- [x] T034 [P] [US6] backend/tests/test_agent_runtime.py 并发用例：同一会话并发两次 send → 第二次 409（沿用注册表互斥）；两个会话并行运行 → 各自 run_id/seq 独立、事件不串扰（两个 execute_run 并发消费收集后分别审计）；共享同一 MCP Server 的两个运行并发调用 → 各自结果正确（假 MCP 连接按 run 隔离断言）
- [x] T035 [US6] 日志脱敏核对：backend/app/services/agent_runtime/runtime.py 与 tools.py 的 [runtime] 日志行核对——不含 Skill 指令正文、不含完整上下文与未截断工具结果、不含密钥（R9）；不足则补，无缺口则复核通过即可

**Checkpoint**: 事件契约、脱敏、并发隔离全部门禁自动化（S7/S8）

---

## Phase 9: Polish & Cross-Cutting Concerns

**Purpose**: 收尾、回归与交付门禁

- [x] T036 [P] 全量回归后端：cd backend && uv run pytest && uv run pyright——全绿；失败按最小修复原则处理并保持零迁移
- [x] T037 [P] 全量回归前端：cd frontend && npm run build && npm run test:unit——零错误全通过
- [ ] T038 对照 specs/009-agent-runtime/quickstart.md S1~S8 手动演练一轮（S7 需两个浏览器窗口；MCP 场景可用任一已配置 Server），结果记录到 tasks.md 本任务下 —— ⚠️ 需真实模型与浏览器环境，待使用者执行（自动化门禁已全部通过）
- [x] T039 核对 spec FR/SC 反向追踪：FR-001~043 与 SC-001~010 在实现与测试中的落点齐全（重点 SC-001 聊天无自维护循环、SC-005 四路径清理、SC-010 直调 Runtime 通道 = execute_run 签名即评测入口）；偏差回写 spec（宪法 §VI）

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (T001~T003)**: 无依赖，T001/T002/T003 可并行
- **Foundational (T004~T011)**: 依赖 Setup；T004→T005（T009 依赖两者）、T006/T007/T008 可并行、T009 依赖 T004~T008、T010→T011 依赖 T009
- **US1 (T012~T019)**: 依赖 Foundational（Runtime 直答骨架即用）；后端 T012~T016 串行推进，前端 T017→T018→T019 可与后端并行（事件契约已冻结）
- **US2 (T020~T024)**: 依赖 US1（桥接通道就绪）；后端 T020→T021，前端 T022→T023→T024
- **US3 (T025~T027)**: 依赖 US2（循环内执行 load_skill）
- **US4 (T028~T030)**: 依赖 US2/US3（执行链与 Skill 链就绪后才能测拒绝）
- **US5 (T031~T032)**: 依赖 US2（工具执行中的取消）
- **US6 (T033~T035)**: 依赖 US3（最复杂事件流可审计）；T033/T034 可并行
- **Polish (T036~T039)**: 依赖全部故事

### Parallel Opportunities

- Setup 三个任务互相独立
- Foundational：T005/T006/T007/T008 四文件互不重叠
- US1 前端三任务与后端解耦（契约冻结后）
- US6 的 T033/T034 同文件不同用例组，可先后连续完成或双人分工

---

## Implementation Strategy

### MVP First (US1 only)

1. Setup + Foundational → Runtime 骨架可用
2. US1 → 直答链路经 Runtime、新事件集上线
3. **STOP & VALIDATE**: quickstart S1 + pytest 全绿

### Incremental Delivery

1. US1（MVP）→ 2. US2 工具循环 → 3. US3 Skill → 4. US4 权限 → 5. US5 取消清理 → 6. US6 契约审计 → Polish 门禁
- 每个故事独立可测：后端故事用例在该故事 Phase 内补齐，US1 前端改造与后端解耦

### Notes

- 零迁移、零新依赖贯穿全部任务；改契约先改 contracts/agent-runtime-api.md（SSOT）
- 每完成一个故事运行一次 `uv run pytest` 快速回归；AGENTS.md §9 四项门禁在 Phase 9 统一收口
