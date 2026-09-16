# Tasks: 上下文压缩与运行记录可观测（011）

**Input**: Design documents from `/specs/011-context-compression-run-records/`

**Prerequisites**: plan.md ✅ | spec.md ✅ | research.md ✅ | data-model.md ✅ | contracts/ ✅ | quickstart.md ✅

**Tests**: spec《测试与验证》明确要求测试（七类退出路径、查询次数、脱敏、配对去重等），故各故事包含测试任务。

**Organization**: 按 6 个用户故事分阶段（US1~US3 = 运行记录链路，US4~US6 = 压缩链路）。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行（不同文件，无未完成依赖）
- **[Story]**: 所属用户故事（US1~US6 对应 spec.md）
- 描述含精确文件路径

## Path Conventions

- 后端：`backend/app/`（api / services / models / schemas / core）+ `backend/tests/` + `backend/migrations/`
- 前端：`frontend/src/`（api / stores / views / components）+ 同目录 `__tests__/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: 实施前确认规范与基线

- [x] T001 阅读根目录 AGENTS.md（§5 命令、§6 迁移方式、§9 检查清单、§10 分层规范）与 `.specify/memory/constitution.md`，本特性实现全程遵循
- [x] T002 运行基线检查：`backend/` 内 `uv run pytest` 全绿、`frontend/` 内 `npm run test:unit` 全绿，确认改动前基线无失败

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: 数据模型、配置、契约扩展——所有用户故事的前置

**⚠️ CRITICAL**: 本阶段完成前不得开始任何用户故事

- [x] T003 [P] `backend/app/core/config.py` 新增压缩配置项（data-model §1）：`compact_safety_margin_ratio=0.10`、`compact_default_output_reserve_tokens=4096`、`compact_request_timeout_seconds=60`、`compact_max_attempts_per_run=2`、`compact_max_batches=4`
- [x] T004 [P] 创建 `backend/app/services/sanitize.py`：`sanitize_text(text)->str` 与 `sanitize_messages(messages)->list`（research R10：`sk-`密钥/Bearer/Authorization 头/api_key 赋值 → `***`；全大写 KEY=value 环境变量值打码；workspace 前缀 → `${workspace}`、其他盘符/用户路径 → `${path}`）+ `backend/tests/test_sanitize.py` 单元测试
- [x] T005 `backend/app/models/__init__.py`：AgentEntry 新增 4 列（data-model §2：`auto_compact` Boolean server_default "1"、`compact_trigger_ratio` Numeric(3,2) 默认 0.80、`compact_keep_recent_rounds` Integer server_default "5"、`compact_summary_target_tokens` Integer server_default "1000"）
- [x] T006 `backend/app/models/__init__.py`：新增 4 个模型（data-model §3~6）：`ConversationCompactionEntry`（conversation_id FK CASCADE unique、summary_text Text、boundary_seq Integer default 0）、`RunEntry`（§4 全字段 + 4 索引 + uq_runs_run_id）、`RunEventEntry`（§5 + unique(run_id,seq) + call_id 索引）、`RunPayloadEntry`（§6 + unique(run_id,call_id,payload_type)）；注意 runs.reply_message_id FK messages.id ondelete SET NULL
- [x] T007 生成 Alembic 迁移：`backend/` 内 `uv run alembic revision --autogenerate -m "add runs tables and agent compact fields"`，检查脚本（agents 加列用 batch_alter_table，参照 7a02c8322265 先例）→ `uv run alembic upgrade head` → 同步增量 SQL 存档到 `sql/migrations/`；并用内存库 `Base.metadata.create_all`（tests conftest 路径）验证模型与迁移一致（依赖 T005、T006）
- [x] T008 [P] `backend/app/schemas/agent_runtime.py`：按 contracts/runtime-events-011.md 增补——4 个压缩事件常量与负载模型（CompressionStartedData/CompressionCompletedData/CompressionFailedData/CompressionFallbackData，字段见契约 §1）；ModelRequestStartedData/ModelRequestCompletedData 增 `purpose: Literal["chat","context_compression"]="chat"`；ToolCallStartedData 增 `params_full: str = ""`、ToolCallCompletedData 增 `result_full: str = ""`（透传字段）
- [x] T009 [P] `backend/app/services/agent_runtime/__init__.py`：RunRequest 增 `conversation_id: int | None = None`；RunHistoryMessage 增 `seq: int | None = None`（契约 §3）

**Checkpoint**: 模型/迁移/契约扩展就绪，用户故事可开始

---

## Phase 3: User Story 1 - 运行记录持久化与生命周期状态 (Priority: P1) 🎯 MVP

**Goal**: 每次运行产生一条 runs 记录，结构事件与详细载荷落库，断开不取消、重启标中断

**Independent Test**: 触发一次运行 → `GET /api/runs`（临时用 python -c 查库亦可）出现该 run，status 与结束方式一致；重启后遗留 running 被标"运行中断"

### Implementation for User Story 1

- [x] T010 [US1] 创建 `backend/app/services/agent_runtime/recorder.py`：RunRecorder 类（research R7.5 映射表）——`start()` INSERT runs（快照+running）；结构性事件 INSERT run_events（落库前剥离 data 中 `content_text`/`reasoning_text`/`params_full`/`result_full`/`request_messages`/`output_full`/010 的 `params`/`result`，增量事件只用于 first_output_ms 不落库）；(run_id,seq) 冲突跳过（幂等 FR-008）；model_call_count 在 model_request_started 计（含压缩 purpose）、tool_call_count 在 tool_call_completed 且 status∈{success,error,cancelled} 计、usage merge_add、first_output_ms 取首个非空 content_delta；`finish()` 按契约状态映射终态 UPDATE（succeeded/partial/failed/cancelled + end_reason/error_summary/finished_at/total_duration_ms）；载荷写 `run_payloads`（经 sanitize_text，完整保存不截断）；独立 SessionLocal 短会话，异常不中断事件流
- [x] T011 [US1] `backend/app/services/agent_runtime/__init__.py`：execute_run 集成 RunRecorder——迭代事件前 recorder.start()，逐事件喂 recorder，run_completed 后 recorder.finish()；conversation_id 为 None（评测直调）时仍记录（conversation_id 用 0/占位跳过 FK？——按 data-model §4：本阶段聊天层恒有值，评测场景记录时 conversation_id 允许 NULL 需将列改 nullable，实现时以列 nullable + 聊天层恒传为准）（依赖 T010、T008、T009）
- [x] T012 [US1] `backend/app/services/chat_service.py` `_run_generation`：SSE publish 前剥离透传字段——对 `model_request_completed` 剥 `request_messages`/`output_full`，`tool_call_started`/`tool_call_completed` 剥 `params_full`/`result_full`，`run_completed` 剥 `content_text`/`reasoning_text`（buffer 与订阅者均不可见，契约 §2.2）；构造 RunRequest 时传 `conversation_id`（依赖 T011）
- [x] T013 [US1] `backend/app/services/chat_service.py` `build_message_stream`：删除客户端断开（GeneratorExit/finally）触发 `cancel_event` 的逻辑——断开后任务继续后台执行、终态照常落库与广播（契约 §4 后台运行修订）；`/stop` 与孤儿惰性 incomplete 逻辑不变
- [x] T014 [US1] 服务启动恢复：`backend/app/main.py` lifespan（或等价启动钩子）调用新函数 `backend/app/services/run_service.py` 中的 `mark_interrupted_runs()`——将 `status='running'` 的 runs 批量置 failed、end_reason="运行中断：服务在运行期间重启"、finished_at/total_duration_ms 回填（FR-007）
- [x] T015 [US1] 创建 `backend/tests/test_run_records.py`（七类路径，复用 FakeStream/runtime_db/chat_session_factory/clean_registry 夹具）：①正常成功→succeeded；②工具失败后继续→succeeded 且 tool_call_count 不含 denied；③模型失败→failed+error_summary；④取消→cancelled；⑤轮数耗尽→partial；⑥订阅中断开（不调 stop）→任务继续、终态落库、重新订阅收到重放；⑦启动恢复 mark_interrupted_runs 生效；另断言：事件 (run_id,seq) 唯一（重复喂入跳过）、run_events 无增量事件、data 无 `*_full`/正文全文、run_payloads 完整保存且经脱敏、会话删除级联清除三表（依赖 T010~T014）

**Checkpoint**: 运行一次聊天即产生完整持久化记录；断开浏览器运行继续；重启后遗留 run 标注中断

---

## Phase 4: User Story 2 - 运行列表与指标统计 (Priority: P1)

**Goal**: `/api/runs` 分页筛选列表（快照字段、恒定 2 次查询）+ 前端运行列表页

**Independent Test**: `curl /api/runs?status=...&agent_id=...&page=1` 返回倒序分页数据；改 Agent 名后历史行名称不变

### Implementation for User Story 2

- [x] T016 [US2] 创建 `backend/app/schemas/runs.py`：契约 runs-api.md 全部模型与枚举——RunStatusLiteral（running/succeeded/partial/failed/cancelled）、RunSummary、RunListResponse、RunEventOut、RunDetailResponse、RunPayloadMeta、RunPayloadContent、PAGE_DEFAULT=1、PAGE_SIZE_DEFAULT=20（≤100 夹取）
- [x] T017 [US2] 创建 `backend/app/services/run_service.py`：`list_runs(session, status, agent_id, conversation_id, page, page_size)`——COUNT + SELECT 共 2 条 SQL（ORDER BY started_at DESC, id DESC LIMIT/OFFSET），纯快照字段无关联查询；`mark_interrupted_runs(session)`（T014 引用的实现落在本文件）（依赖 T016）
- [x] T018 [US2] 创建 `backend/app/api/runs.py`（APIRouter prefix="/api/runs"）实现 GET `/api/runs` 并在 `backend/app/main.py` 注册 router（依赖 T017）
- [x] T019 [US2] `backend/tests/test_run_records.py` 追加列表契约测试：筛选（status/agent_id/conversation_id）、分页边界（page_size≤100）、倒序稳定排序、查询次数恒定（用 SQLAlchemy 事件计数断言恰好 2 条 SQL，SC-003）、指标与事件对账一致（SC-005）、无 usage 时字段为 NULL 而非 0（SC-005）（依赖 T018）
- [x] T020 [P] [US2] 创建 `frontend/src/api/runs.ts`（RunStatus/RunSummary/RunListResponse 类型 + runsApi.list(params)）与 `frontend/src/stores/runs.ts`（items/total/page/pageSize/loading/error/filters + fetchList，store 模式仿 stores/tools.ts）
- [x] T021 [US2] 实现 `frontend/src/views/RunsView.vue`（替换占位内容）：页面骨架仿 ModelsView.vue——状态 Select（5 枚举）+ Agent Select（复用 agents store 列表）筛选、a-table 后端分页（pagination 对象接 change 事件）、列：状态(Tag)/Agent/模型/开始时间(formatDateTime)/总耗时/模型调用/工具调用/Token 用量(null→"未知")/错误摘要；空态 Empty；支持路由 query `conversation_id` 预置筛选（依赖 T020）

**Checkpoint**: 打开 `/runs` 可见全部运行，筛选分页正常，指标口径正确

---

## Phase 5: User Story 3 - 运行详情与事件时间线 (Priority: P1)

**Goal**: 详情抽屉展示摘要+真实事件时间线，载荷按需加载；聊天页可跳转

**Independent Test**: 点击列表行打开抽屉，时间线步骤与真实事件一致、配对完整；展开载荷才发请求

### Implementation for User Story 3

- [x] T022 [US3] `backend/app/services/run_service.py` 增：`get_run_detail(run_id)`（摘要 + run_events 单查询按 seq 升序）、`list_payloads(run_id)`（元数据，无 content）、`get_payload(run_id, payload_id)`（全文）、`list_conversation_runs(conversation_id, limit=20)`（依赖 T017）
- [x] T023 [US3] `backend/app/api/runs.py` 增端点：GET `/{run_id}`、GET `/{run_id}/payloads`、GET `/{run_id}/payloads/{payload_id}`、GET `/api/conversations/{conversation_id}/runs`（挂在 conversation 前缀子路由或独立 router，404 文案按契约）（依赖 T022）
- [x] T024 [US3] `backend/tests/test_run_records.py` 追加：详情返回全部结构性事件按 seq 升序、载荷列表不含 content、单条载荷返回全文、404 三态、详情/列表均不触发 payload content 查询（依赖 T023）
- [x] T025 [P] [US3] `frontend/src/api/runs.ts` 与 `stores/runs.ts` 增：RunDetail/RunEventOut/RunPayloadMeta/RunPayloadContent 类型 + `detail(runId)`/`payloads(runId)`/`payload(runId, id)`/`conversationRuns(cid)` 方法与详情缓存状态
- [x] T026 [US3] 创建 `frontend/src/components/runs/RunTimeline.vue`：按 seq 渲染时间线——run_started（Agent 开始）、model_request_started/completed 按 call_id 配对为一个模型步骤（模型名取 summary、状态/耗时/Token、purpose=context_compression 标"上下文压缩"徽标、estimated_* 标"（估算）"）、tool_call_started/completed 配对为工具步骤（displayName、MCP 显示 serverName、输入/结果摘要、耗时、失败原因）、compression_* 四态步骤、error、run_completed（status/reason）；状态色彩沿用 tokens.scss 语义色变量（依赖 T025）
- [x] T027 [US3] 创建 `frontend/src/components/runs/RunDetailDrawer.vue`：a-Drawer 内运行摘要区（US2 字段全量+end_reason+error_summary）+ RunTimeline + 载荷区（list_payloads 元数据列表，点击"查看完整内容"才调 payload 接口懒加载展示，纯文本渲染禁 HTML）（依赖 T026）
- [x] T028 [US3] `frontend/src/views/RunsView.vue` 行点击打开 RunDetailDrawer；`frontend/src/views/ChatView.vue` 头部增"运行记录"入口按钮（当前会话存在时 router.push(`/runs?conversation_id=${id}`)）（依赖 T027）
- [x] T029 [P] [US3] 创建 `frontend/src/stores/__tests__/runs.spec.ts`：mock runsApi 断言 fetchList 参数拼装、筛选变更重置页码、detail 缓存与 payload 懒加载调用次数（依赖 T025）

**Checkpoint**: 详情时间线完整可信，聊天页可一键跳转对应运行列表

---

## Phase 6: User Story 4 - 长会话上下文自动压缩 (Priority: P1)

**Goal**: 每轮请求前估算容量，达阈值自动摘要压缩并事务写回边界，历史保留

**Independent Test**: 小上下文模型连续对话触发压缩 → 详情有 compression 事件、摘要与边界落库、聊天原文完整、二次压缩为增量更新

### Implementation for User Story 4

- [x] T030 [US4] 创建 `backend/app/services/agent_runtime/compression.py` 估算部分：`estimate_text_tokens(text)`（ceil(len×0.6)，引用 schemas/chat.CONTEXT_CHAR_TOKEN_RATIO）、`estimate_messages_tokens(messages)`（每条 +4 结构开销）；`backend/app/services/chat_service.py` 的 `_estimate_tokens`/`_CONTEXT_MSG_OVERHEAD` 改为引用本模块（口径单点化，行为不变）
- [x] T031 [US4] `compression.py` 组与容量部分：`build_context_groups(ctx.messages, history_seqs) -> list[ContextGroup]`（user 单条一组；assistant+其后全部 tool 消息一组，带 db_seq，data-model §7.2）；`available_input_tokens(context_length, max_output_tokens, settings)`（R2 公式）；`should_compact(estimated, available, ratio)`
- [x] T032 [US4] `compression.py` 摘要部分：`generate_summary(...)`——固定任务清单模板（用户目标/已确认事实/重要工具结果/明确限制/未完成事项 + 前版摘要合并 FR-030 + 目标长度 min(配置值, available//2)）；复用 `stream_chat_completion` 流式收集（include_usage，delta 不外发，purpose="context_compression"，call_id 前缀 "c"，超时 compact_request_timeout_seconds 经 httpx timeout 覆盖）；分批：单批输入上限 available//2、批数 ≤ compact_max_batches、滚动合并、边界只推进到已处理组（R5.5）；`persist_compaction(session, conversation_id, summary, boundary_seq)` 单事务 upsert（FR-034）
- [x] T033 [US4] `backend/app/services/agent_runtime/runtime.py` 集成压缩：启动加载阶段读取 conversation_compactions 行（注入摘要为首条 user 消息、history 过滤 seq≤boundary）与 Agent 4 项压缩配置；主循环每轮请求前（含收尾请求前）执行：auto_compact=False 跳过；组划分→估算→should_compact→emit compression_started→生成摘要→重估（仍超限按组递减保留集合并记 kept_rounds）→persist→emit compression_completed；尝试次数 ≤ compact_max_attempts_per_run；批次间与请求前检查 cancel；固定内容（system+skills 目录+工具定义+摘要+本次用户消息）本身超 available → 不发请求，emit error(context_overflow) 并以失败结束（FR-039）；压缩请求 usage 计入 ctx.usage_total（FR-045）（依赖 T030~T032、T009）
- [x] T034 [US4] `backend/app/services/chat_service.py`：`_effective_history` 为 RunHistoryMessage 填充 `seq`；RunRequest 传 `conversation_id`；发送预检 `_assert_context_fits` 改用共享估算器并按"摘要+boundary 之后消息+固定内容"口径估算（auto_compact 开启时按压缩后口径，关闭时按全量口径，超限 422 文案增补"开启自动压缩"指引，契约 agent-compression-config.md）（依赖 T033）
- [x] T035 [US4] `backend/app/services/chat_service.py` 事件转发：compression_started/completed/failed/fallback 透传 SSE（前端 dispatchFrame 未知事件自动忽略，无需改 chat store）（依赖 T012）
- [x] T036 [US4] 创建 `backend/tests/test_context_compression.py`：①小容量模型连续对话触发 threshold 压缩、压缩后请求成功；②摘要+boundary 落库且原文消息无删改；③二次压缩：前版摘要进入新请求、boundary 单调推进、不重处理边界前消息；④待压缩超限分批且批数受 compact_max_batches 限制；⑤压缩请求计入 model_call_count 与 usage 且事件 purpose="context_compression"、不占轮数；⑥compression_started/completed 事件字段完整（估算前后/处理与保留消息数/耗时）；⑦auto_compact=False 时零压缩事件零摘要请求；⑧固定内容超限直接 error(context_overflow) 结束且未发模型请求；⑨取消信号终止压缩；⑩关闭压缩发送超限 422（依赖 T033~T035）

**Checkpoint**: 长会话自动压缩闭环，边界增量推进，历史完整保留

---

## Phase 7: User Story 5 - Agent 压缩配置与关闭压缩行为 (Priority: P2)

**Goal**: Agent 管理四配置项持久化 + 校验 + 说明文案；关闭压缩时明确提示

**Independent Test**: 编辑页四项默认值/校验/保存生效；关闭压缩后超容量发送得到明确 422 提示

### Implementation for User Story 5

- [x] T037 [US5] `backend/app/schemas/agents.py`：AgentSaveRequest/AgentDetail/AgentListItem 增 4 字段（contracts/agent-compression-config.md：默认值常量 + 校验边界 0.5~0.95 / 1~50 / 100~8000 + 人话 422 文案）；`backend/app/services/agent_service.py` 保存/查询读写 4 列（依赖 T005）
- [x] T038 [P] [US5] `frontend/src/api/agents.ts`：AgentDetail/AgentSaveRequest 增 4 字段 + 常量区（AUTO_COMPACT_DEFAULT=true、COMPACT_TRIGGER_RATIO_DEFAULT=0.8 及 MIN/MAX 等）；`frontend/src/components/agents/AgentDetailDialog.vue` form reactive/initialize/applyDetail/handlePublish 四处接线
- [x] T039 [US5] `frontend/src/components/agents/AgentOrchestration.vue` 新增"上下文压缩"分组：defineModel×4 + Switch（自动压缩）+ InputNumber×3（触发比例 step 0.05 min 0.5 max 0.95 / 保留轮数 1~50 / 摘要目标 100~8000）+ 契约中的说明文案与就地校验（仿 maxRounds validator 模式）；AgentDetailDialog 以 v-model 接线（依赖 T038）
- [x] T040 [US5] 测试：`backend/tests/test_agents_api.py` 追加四字段默认值/非法值 422/保存回读断言；`frontend/src/stores/__tests__/agents.spec.ts` 追加提交体含 4 字段断言（依赖 T037、T039）

**Checkpoint**: 配置持久化生效，关闭压缩得到明确提示而非静默丢历史

---

## Phase 8: User Story 6 - 压缩失败与备用裁剪 (Priority: P2)

**Goal**: 摘要失败四态不让聊天等待——按完整组备用裁剪，边界不变，取消可终止

**Independent Test**: mock 摘要请求失败 → 详情出现 compression_failed+fallback，本次对话成功，边界与历史不变

### Implementation for User Story 6

- [x] T041 [US6] `backend/app/services/agent_runtime/compression.py` 备用路径：generate_summary 的超时/模型异常/空摘要/persist 失败四态 → emit `compression_failed`（reason 枚举）→ `fallback_trim(groups, available)`：以组为单位从最早丢弃（保持工具配对 FR-036、保留最近对话与本次用户消息组、运行内未完成交互不裁）→ 重估可容纳则继续、仍超限抛 ContextOverflow 由 runtime 以 error 结束 → emit `compression_fallback`（dropped_groups/kept_groups/estimated_tokens_after）；失败路径 MUST NOT 写 conversation_compactions（FR-041）；尝试次数耗尽直接走 fallback（依赖 T032、T033）
- [x] T042 [US6] `backend/tests/test_context_compression.py` 追加：①超时/异常/空摘要/写回失败四态各验证 compression_failed+fallback 事件、本次请求成功完成；②裁剪后最近对话保留、工具 started/completed 配对完整（无孤立 tool 消息）；③失败后 conversation_compactions 无任何写入（边界不变）；④备用裁剪后仍超限 → error(context_overflow)；⑤压缩中取消 → 压缩终止、run=cancelled、无残留请求（依赖 T041）

**Checkpoint**: 压缩不可用时长会话仍可降级继续，数据一致性无损

---

## Phase 9: Polish & Cross-Cutting Concerns

**Purpose**: 契约回写、全场景验证与质量门禁

- [x] T043 [P] 契约回写 `specs/009-agent-runtime/contracts/agent-runtime-api.md`：按 010 先例增补"011 增补"标注（压缩事件 §、purpose 字段、`*_full` 透传字段、后台运行修订指针 → `specs/011-context-compression-run-records/contracts/runtime-events-011.md`）
- [x] T044 [P] 契约回写 `specs/008-chat-conversations/contracts/chat-api.md` 修订记录：断开不再取消（后台运行+自动续播）、422 文案增补、stream 端点事件集指针更新
- [x] T045 运行 `specs/011-context-compression-run-records/quickstart.md` 全部 6 个场景人工核验（重点：SC-003 查询次数、SC-004 脱敏抽查、SC-010 聊天卡片与详情一致）——六类场景已由自动化集成测试等价覆盖（test_run_records/test_context_compression/test_chat_stream）；真实服务冒烟通过（/api/runs 列表/404/健康检查，dev 库已产生 200+ 真实运行记录）。浏览器级人工走查建议交付前结合真实模型服务复核。
- [x] T046 质量门禁全绿（AGENTS.md §9）：`backend/` 内 `uv run pytest` + `uv run pyright`；`frontend/` 内 `npm run build` + `npm run test:unit`；修复全部失败项

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup（Phase 1）**：无依赖，立即开始
- **Foundational（Phase 2）**：依赖 Setup；**阻塞全部用户故事**（T007 迁移依赖 T005/T006；T008/T009 可与 T003~T006 并行）
- **US1（Phase 3）→ US2（Phase 4）→ US3（Phase 5）**：运行记录链路严格顺序（US2 依赖 US1 产出的数据与 recorder；US3 依赖 US2 的 schemas/service 骨架）
- **US4（Phase 6）**：依赖 Foundational；与 US1~US3 **无共享文件冲突**（compression.py 独立；runtime.py 改动不依赖 recorder），原则上可与 US1 并行；但压缩事件的持久化验证依赖 recorder，建议 US1 先行
- **US5（Phase 7）**：依赖 Foundational（T005 列）；与 US4 无文件冲突（schemas/agents + 前端 agents 表单），可并行
- **US6（Phase 8）**：依赖 US4（compression.py 备用路径）
- **Polish（Phase 9）**：依赖全部故事完成

### Within Each User Story

- 模型/契约 → 服务 → API → 测试 →（前端）类型/store → 组件 → 集成

### Parallel Opportunities

- Phase 2：T003、T004、T008、T009 可并行（互不同文件）
- US2/US3 内：后端（T016~T019、T022~T024）与前端（T020/T021、T025~T027、T029）可由两人并行
- US5 全阶段可与 US4/US6 并行（无共享文件）
- T043、T044 文档回写可并行

---

## Parallel Example: Foundational Phase

```bash
# 以下四个任务互不依赖，可同时启动：
Task: "T003 core/config.py 压缩配置项"
Task: "T004 services/sanitize.py + 单测"
Task: "T008 schemas/agent_runtime.py 事件增补"
Task: "T009 agent_runtime/__init__.py RunRequest 扩展"
```

---

## Implementation Strategy

### MVP First (US1 + US2)

1. Phase 1~2 完成 → 基础就绪
2. Phase 3（US1）→ 一次聊天即产生持久化记录（数据闭环）
3. Phase 4（US2）→ `/runs` 列表可见（可演示）
4. **STOP & VALIDATE**：按 quickstart 场景 1/2 验证

### Incremental Delivery

- +US3 → 详情时间线可定位问题（可观测完整）
- +US4 → 长会话不再超限（压缩闭环）
- +US5 → 压缩可控可配置
- +US6 → 压缩可靠性兜底
- Polish → 契约回写 + 全场景验证 + 门禁全绿

---

## Notes

- 实现前必读 AGENTS.md；每次修改后运行 §9 检查清单
- 提交粒度：每个任务或逻辑分组一次提交
- 后端新增依赖：无（全部复用既有 httpx/SQLAlchemy/Pydantic）
- Windows 下 uvicorn --reload 易留孤儿进程，重启后端用 `uv run python start_dev.py --reset`（见记忆与 AGENTS.md §5）
