# Tasks: 聊天功能（第八阶段）

**Input**: Design documents from `/specs/008-chat-conversations/`

**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/chat-api.md, quickstart.md

**Tests**: 宪法 IV / AGENTS.md §9 要求交付门禁（`uv run pytest`、`npm run build`、`npm run test:unit`），故每个用户故事包含配套测试任务（沿用 007 的"契约测试先行于该故事完成"模式）。

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

本项目为 web-application 双目录（plan.md Structure Decision）：

- 后端：`backend/app/`（api / services / schemas / models 分层）、`backend/tests/`
- 前端：`frontend/src/`（api / stores / components/chat / views 分层）
- SQL 存档：`sql/migrations/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: 依赖安装与 SQL 存档准备

- [x] T001 [P] 在 frontend/ 安装新依赖：`npm install markdown-it dompurify` 与 dev 依赖 `@types/markdown-it`（frontend/package.json；Windows + nvm 按 AGENTS.md §5 切 node 22；无其他新增依赖）
- [x] T002 [P] 按 data-model.md §1/§2 编写建表 SQL 存档 sql/migrations/008-chat-conversations.sql（conversations、messages 两表 + 索引 uq_messages_conversation_seq / ix_conversations_updated_at，与后续 Alembic 迁移对应，参考 sql/migrations/007 的存档格式）

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: 两新表 ORM/迁移 + 契约 Schema + 配置常量，全部用户故事的前置

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [x] T003 在 backend/app/models/__init__.py 新增 ConversationEntry 与 MessageEntry ORM 模型（严格按 data-model.md §1/§2 字段/类型/索引：uq_messages_conversation_seq 唯一约束、ix_conversations_updated_at；agent_id 无 DB 外键；时间用既有 _utcnow() naive UTC；conversation_id 外键 ON DELETE CASCADE）
- [x] T004 生成并执行 Alembic 迁移：backend/ 内 `uv run alembic revision --autogenerate -m "add conversations and messages tables"`，核对生成脚本与 data-model.md 一致后 `uv run alembic upgrade head`（backend/migrations/versions/）
- [x] T005 [P] 新建 backend/app/schemas/chat.py 实现 contracts/chat-api.md 契约：Role / MessageStatus / StreamErrorCategory 枚举、TITLE_DEFAULT="新会话"、TITLE_MAX_CHARS=20、MESSAGE_MAX_CHARS=32000、CONTEXT_CHAR_TOKEN_RATIO=0.6、STREAM_PING_INTERVAL_SECONDS=15 常量，ConversationSummary / MessageOut / SendMessageRequest（去空白 1~32000）/ StartReplyResponse / StopResponse 模型（类型与契约逐字段对齐）
- [x] T006 [P] 在 backend/app/core/config.py 新增聊天配置常量：上游连接超时 connect 10s、读间隔 120s（注释标注 contracts/chat-api.md"生成任务内部约定"节）
- [x] T007 在 backend/tests/conftest.py 新增聊天夹具：seed_agent（沿用 seed_model 建一个默认 Agent）、seed_conversation（建一个指定 Agent 的会话）——供全部聊天测试复用

**Checkpoint**: 数据库两表就绪、契约 Schema 就绪——用户故事可以开始

---

## Phase 3: User Story 1 - 与选定的 Agent 发起对话并获得流式回复 (Priority: P1) 🎯 MVP

**Goal**: 用户在会话中发送消息，后端以 Agent 的模型配置与系统提示词发起真实流式请求，前端增量渲染思考过程与正文（Markdown），支持复制与重新生成。

**Independent Test**: 用 seed 夹具建会话 → POST 发送消息 → 订阅 SSE 流观察到 reasoning_delta / content_delta 按序到达 → done 事件返回 completed 落库的消息；页面上发送一句话能看到流式回复。

### Implementation for User Story 1

- [x] T008 [P] [US1] 在 backend/app/services/openai_client.py 新增异步流式调用 `stream_chat_completion`（async 生成器，逐行解析 `data:` SSE 块的 delta.content 与 delta.reasoning_content，产出 ContentDelta / ReasoningDelta 数据类；请求体按 research R2 映射 thinking 参数；logging INFO 实时打印请求摘要与增量进度、不含 Authorization 与密钥（FR-011/FR-025）；httpx.HTTPStatusError / TimeoutException / 流中断原样上抛供分类）
- [x] T009 [US1] 新建 backend/app/services/generation_registry.py：进程内生成注册表（research R4）——GenerationTask 持有 asyncio.Task、thinking/content 缓冲、订阅者队列；提供 start / subscribe（先重放缓冲再实时跟随，终态直接发 done/error）/ publish / finish / cancel 接口；单例 get_registry()
- [x] T010 [US1] 新建 backend/app/services/chat_service.py 持久化与上下文部分：create_conversation（标题"新会话"）、get_messages（seq 升序）、send_message 单事务完成——内容校验 → 会话生成互斥 409 → Agent 可用性 400 → 上下文容量估算（research R3：有效历史=全部 user + completed 的 assistant，本条消息仅出现一次；字符×0.6+max_output_tokens 超出 context_length 则 422 文案按契约）→ 落库 user 消息(seq=n) + generating 占位回复(seq=n+1, 快照 agent_id/agent_name) → 首条消息截标题（research R7：前 20 字符+…，仅当标题仍为"新会话"）→ 更新会话 updated_at（依赖 T003/T005）
- [x] T011 [US1] 在 backend/app/services/chat_service.py 新增生成编排部分：_run_generation 任务——组装 [system?]+有效历史（content only）请求 openai_client.stream_chat_completion（T008），每个增量 publish 到注册表并追加缓冲；流正常结束→回复行 UPDATE 为 completed；ChatHttpError/TimeoutException 等按 contracts StreamErrorCategory 分类→error 事件+终态处理（缓冲非空→incomplete，空→删行）；任务收尾从注册表摘除（依赖 T008/T009/T010）
- [x] T012 [US1] 新建 backend/app/api/chat.py 会话与消息端点并注册：POST /api/conversations（201 返回摘要；agent 不存在 400）、GET /api/conversations/{id}/messages（404）、POST /api/conversations/{id}/messages（201 StartReplyResponse 并启动生成任务；409/400/422 错误映射）——薄路由层，异常→HTTP 状态；在 backend/app/main.py include chat 路由（依赖 T005/T010/T011）
- [x] T013 [US1] 在 backend/app/api/chat.py 新增流式订阅与重新生成端点：GET /api/conversations/{id}/messages/{message_id}/stream（StreamingResponse text/event-stream：订阅注册表重放+跟随，空闲 `: ping` 心跳；404/409 映射；孤儿 generating 任务惰性标 incomplete 后发 done，research R4）、POST /api/conversations/{id}/regenerate（原地重置最后一条 assistant 回复为 generating 后启动任务，research R8；404/409 映射）（依赖 T009/T011/T012）
- [x] T014 [P] [US1] 在 backend/tests/conftest.py 新增假流注入工具：受控 async 生成器工厂（可编排增量序列/延迟/中途异常/HTTP 错误），monkeypatch openai_client.stream_chat_completion 用（research R9；依赖 T003，可与 T008-T013 并行编写）
- [x] T015 [US1] 新建 backend/tests/test_chat_api.py REST 契约测试：新建会话 201 与 400、发送消息 201 响应结构（user_message/reply_message_id/conversation 标题截取）、GET messages 按 seq 排序、发送空/纯空白/超长 422、上下文超限 422 文案、生成中重复发送 409（用假流阻塞维持 generating）——断言遵循 contracts/chat-api.md（依赖 T010/T012/T014）
- [x] T016 [US1] 新建 backend/tests/test_chat_stream.py 流式与终态测试：订阅重放+实时增量顺序、reasoning/content 分区正确、done 返回 completed 且落库内容一致、regenerate 原地重置（seq 不变内容重置）、HTTP 401/400 映射 auth_error/model_not_found 的 error 事件且错误文本不入 content、error 后收到 incomplete 终态 done（依赖 T011/T013/T014）
- [x] T017 [P] [US1] 新建 frontend/src/api/chat.ts：契约类型（ConversationSummary / MessageOut / StartReplyResponse / StreamEvent 等，与 contracts 逐字段对齐）+ REST 封装 + `streamReply` 封装（fetch POST→GET stream 用 fetch+ReadableStream 解析 SSE 帧：事件名/data JSON/注释行忽略，暴露 onEvent 回调；依赖 T005 的契约）
- [x] T018 [P] [US1] 新建 frontend/src/utils/markdown.ts 及测试：markdown-it（html:false、linkify 开启）渲染 + DOMPurify 二次清洗导出单函数（research R6），测试 frontend/src/utils/__tests__/markdown.spec.ts 覆盖代码块/表格/链接与 `<script>` 注入剥离（依赖 T001）
- [x] T019 [US1] 新建 frontend/src/stores/chat.ts 核心：当前会话 id、消息列表（按 seq）、生成状态（idle/thinking/generating）、流缓冲（thinkingContent/content 增量累积）、发送动作（POST messages→订阅 streamReply→终态刷新消息）、regenerate 动作（依赖 T017）
- [x] T020 [US1] 新建 frontend/src/components/chat/MessageBubble.vue：用户靠右/Agent 靠左布局、Agent 回复顶部显示 agent_name 快照、思考过程与正文分区展示（思考区可折叠）、正文 v-html 经 markdown.ts 清洗渲染、复制按钮（写正文源文本）、仅最后一条 assistant 消息显示"重新生成"（依赖 T018）
- [x] T021 [US1] 新建 frontend/src/components/chat/ChatMessages.vue：消息列表容器（气泡间 12~16px 间距、配色字号引用 tokens.scss 变量）、"正在思考/正在生成"状态行、新消息与流式追加时自动滚动到底部（用户上滚查看历史时不强制跟随）（依赖 T019/T020）
- [x] T022 [US1] 新建 frontend/src/components/chat/ChatComposer.vue：多行输入框（Enter 发送 / Shift+Enter 换行 / IMU compositionstart-end 期间 Enter 不发送 / 空白禁发送）、发送按钮、Agent 选择下拉（复用 stores/agents 列表）、`@` 唤起 Agent 快捷选择、无可用 Agent 时禁用发送并提供前往 Agent 管理入口（FR-029）、发送失败保留输入内容并提示（FR-009）（依赖 T019）
- [x] T023 [US1] 重写 frontend/src/views/ChatView.vue：左右两栏布局（左侧栏区域本阶段先留空容器、右侧聊天区），顶部会话标题栏、中部 ChatMessages、底部 ChatComposer；整页占满高度无横向滚动，样式全部引用设计令牌（依赖 T019/T021/T022）
- [x] T024 [P] [US1] 新建前端测试：frontend/src/api/__tests__/chat.spec.ts（SSE 帧解析：分片边界、多事件、注释行、reasoning/content 事件分发）与 frontend/src/stores/__tests__/chat.spec.ts（发送→thinking→generating→completed 状态流转、缓冲累积、发送失败保留输入）（依赖 T017/T019）

**Checkpoint**: 用假流（后端测试）与真实模型（手动）均可完成"发送→流式回复→落库→刷新可见"闭环；US1 可独立验收

---

## Phase 4: User Story 2 - 会话列表管理与聊天记录持久化 (Priority: P1)

**Goal**: 左侧会话列表可用：新建会话、列表按更新时间倒序、点击加载记录、刷新后恢复。

**Independent Test**: 新建会话发送两条消息 → 刷新页面 → 列表仍在（倒序）→ 点击会话记录完整并自动滚到底部 → 继续发送成功。

### Implementation for User Story 2

- [x] T025 [US2] 在 backend/app/services/chat_service.py 新增 list_conversations（只返回摘要字段、updated_at 倒序 id 倒序并列稳定，FR-006）并在 backend/app/api/chat.py 加 GET /api/conversations（依赖 T010/T012）
- [x] T026 [US2] 新建 frontend/src/components/chat/ConversationSidebar.vue：顶部"新建会话"按钮、会话列表项（标题+最后更新时间，相对时间展示）、当前项高亮、空状态引导；样式引用设计令牌（依赖 T027）
- [x] T027 [US2] 扩展 frontend/src/stores/chat.ts 会话列表部分：conversations 列表、fetchConversations、createConversation（成功后加入列表并自动选中，标题"新会话"）、selectConversation（加载消息）、发送新消息后本地更新会话 updated_at 并重排（仅查看不改排序）（依赖 T019/T025）
- [x] T028 [US2] ChatView.vue 集成侧栏与刷新恢复：挂载时 fetchConversations → 恢复上次活跃会话（无则列表第一个/提示新建）→ 加载消息并自动滚到底部；新建按钮走 store（依赖 T023/T026/T027）
- [x] T029 [P] [US2] 补充测试：backend/tests/test_chat_api.py 增加列表摘要契约用例（字段完整、倒序、不含消息）；frontend/src/stores/__tests__/chat.spec.ts 增加新建自动选中/排序更新用例（依赖 T025/T027）

**Checkpoint**: US1+US2 同时可用——完整"会话管理 + 对话"体验，可独立验收（MVP+）

---

## Phase 5: User Story 3 - 多轮上下文与 Agent 切换 (Priority: P2)

**Goal**: 同会话连续追问带有效历史；会话内切换 Agent 只影响后续请求；恢复会话恢复 Agent 选择。

**Independent Test**: 连续追问两轮模型能理解上文；切换 Agent 后回复体现新提示词且历史完整；删除原 Agent 后旧记录可看、发送前要求重选。

### Implementation for User Story 3

- [x] T030 [US3] 在 backend/app/services/chat_service.py 新增 switch_agent + 在 backend/app/api/chat.py 加 PUT /api/conversations/{id}（请求体 agent_id；Agent 不存在/不可用 400、生成中 409、成功返回摘要）（依赖 T010/T012）
- [x] T031 [US3] 前端切换联动：ChatComposer 的 Agent 选择变更时调用 PUT（生成中禁切）；stores/chat.ts 打开会话时以 conversation.agent_id 回显选择；会话 Agent 已删除（不在可用列表）时显示"请重新选择 Agent"并禁发送，历史照常展示（FR-019/切换 Agent 节）（依赖 T027/T030）
- [x] T032 [P] [US3] 补充测试：backend/tests/test_chat_stream.py 增加上下文断言用例（假流捕获请求 payload：system 为当前 Agent 提示词、历史只含有效消息、本轮消息仅一次、incomplete 不入上下文、跨会话隔离）；backend/tests/test_chat_api.py 增加 PUT 切换 200/400/409；frontend store 切换回显用例（依赖 T011/T030）

**Checkpoint**: US1~US3 全部可用，多轮与切换可独立验收

---

## Phase 6: User Story 4 - 生成控制：停止与后台继续 (Priority: P2)

**Goal**: 生成中可停止（后端尽力终止上游并清理）；切换会话/离开页面后台继续生成。

**Independent Test**: 发送长文生成→点停止→输出立即止、已生成部分显示未完成；另发一次→切走再切回→回复完整。

### Implementation for User Story 4

- [x] T033 [US4] 停止生成后端：在 backend/app/api/chat.py 加 POST /api/conversations/{id}/messages/{message_id}/stop（调用注册表 cancel→Task.cancel() 关闭上游流；缓冲非空→incomplete 落库、空→删占位行；对已终态幂等 200；404/409 映射）（依赖 T009/T013）
- [x] T034 [US4] 前端停止与生成互斥：ChatComposer 生成中发送按钮切换为"停止"调用 store.stopGeneration；生成期间禁用发送与 Agent 切换（FR-020）；停止后恢复操作并保留部分内容展示未完成标识（依赖 T019/T022/T033）
- [x] T035 [US4] 前端后台继续：stores/chat.ts 的流订阅生命周期独立于组件——ChatView 卸载不断开订阅（订阅在 store 层持有）；切换/新建会话后再回到原会话，按消息状态重新订阅 stream 完成重放（FR-022）（依赖 T019/T027）
- [x] T036 [P] [US4] 补充测试：backend/tests/test_chat_stream.py 停止用例（假流阻塞→stop→incomplete 落库/空缓冲删行/幂等 200）；frontend/src/stores/__tests__/chat.spec.ts 后台订阅与重放恢复用例（依赖 T033/T035）

**Checkpoint**: US1~US4 全部可用，生成控制可独立验收

---

## Phase 7: User Story 5 - 异常与失败状态处理 (Priority: P3)

**Goal**: 连接失败/超时/空回复/流中断等异常独立提示，错误不入聊天记录，等待状态必结束。

**Independent Test**: 配错密钥发送→独立"认证失败"提示；用户消息仍在；记录无错误气泡；界面可继续操作。

### Implementation for User Story 5

- [x] T037 [US5] 异常分类补全：backend/app/services/chat_service.py 生成编排中补 empty_response（流正常结束但思考与正文均空）、stream_interrupted（增量解析异常/乱序检测，research R3 兜底）、context_overflow（服务商 400 且 body 含上下文关键词时映射，FR-018）；确认所有分类路径错误文案不含密钥/上游敏感信息（依赖 T011）
- [x] T038 [US5] 前端异常展示：stores/chat.ts 处理 error 事件→按 category 显示独立错误条（contracts 错误文案直接展示，FR-023），等待状态结束、输入可继续；MessageBubble 对 incomplete 消息渲染"未完成"标识（生成中断/已停止文案区分）；错误文本永不渲染为气泡正文（依赖 T019/T020）
- [x] T039 [P] [US5] 补充测试：backend/tests/test_chat_stream.py 异常分支用例（假流：首 token 前 401→auth_error；中途抛异常→stream_interrupted；空流→empty_response；各用例断言用户消息保留、无 completed 回复产生或 incomplete 正确落库）；frontend store error 终态用例（依赖 T037/T038）

**Checkpoint**: 全部用户故事完成——异常路径可独立验收

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: 跨故事收尾与交付门禁

- [x] T040 交付门禁全绿：backend/ `uv run pytest` 与 `uv run pyright`；frontend/ `npm run build` 与 `npm run test:unit`；修复全部问题（AGENTS.md §9）
- [ ] T041 按 specs/008-chat-conversations/quickstart.md 完成手动走查（场景 A~E，需真实模型配置）；核对 SC-001~SC-007；确认后端日志与前端响应无 API Key（FR-025）、SSE 心跳与 Vite 代理转发正常

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**：无依赖，T001/T002 可立即并行
- **Foundational (Phase 2)**：T003 → T004；T005/T006/T007 可与 T003 后并行——**BLOCKS 所有用户故事**
- **US1 (Phase 3)**：依赖 Foundational；内部 T008→T009→T010→T011→T012→T013 主线（T014/T017/T018 可并行插入），T015/T016 收口后端，T019→T020/T021/T022→T023 前端主线，T024 收口
- **US2 (Phase 4)**：依赖 US1 的 store/service 底座（T019/T010）
- **US3 (Phase 5)**：依赖 US1 的生成编排（T011）与 US2 的 store（T027）
- **US4 (Phase 6)**：依赖 US1 的注册表（T009）与 US2 的会话切换（T027）
- **US5 (Phase 7)**：依赖 US1 的错误分类骨架（T011）
- **Polish (Phase 8)**：依赖全部故事完成

### User Story Dependencies

- US1 是所有后续故事的地基（发送/流式/注册表），必须最先完成
- US2 依赖 US1；US3/US4/US5 相互独立，可按任意顺序在 US2 之后并行推进（单人建议按 P2→P2→P3 顺序：US3→US4→US5）

### Within Each User Story

- 后端 service → api 路由 → 测试；前端 api 封装 → store → 组件 → 视图 → 测试
- 测试任务置于该故事实现任务之后，但编写时先跑通失败再实现（契约测试锁 contracts/chat-api.md）

### Parallel Opportunities

- Phase 1：T001 ∥ T002
- Phase 2：T005 ∥ T006 ∥ T007（T003 完成后）
- Phase 3：T008 ∥ T014 ∥ T017 ∥ T018；前端组件与后端流管线两条线并行
- US3/US4/US5 的测试任务（T032/T037/T040）均标 [P]

---

## Parallel Example: User Story 1

```text
# 后端流管线（串行主线）：
T008 openai_client.stream_chat_completion → T009 generation_registry → T010 chat_service 持久化 → T011 生成编排 → T012 REST 端点 → T013 SSE/regenerate

# 可并行插入（不同文件，无相互依赖）：
T014 conftest 假流工具    T017 api/chat.ts    T018 utils/markdown.ts

# 前端 UI 主线（T017 之后）：
T019 store → T020/T021/T022（组件，可并行）→ T023 ChatView 集成 → T024 前端测试
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. 完成 Phase 1 + Phase 2（两表迁移 + 契约 Schema）
2. 完成 Phase 3（US1：发送→流式回复→落库）
3. **STOP and VALIDATE**：假流测试全绿 + 真实模型手动发一条消息看到流式回复
4. 此时已可演示核心价值（会话暂靠后端接口创建）

### Incremental Delivery

1. Setup + Foundational → 地基就绪
2. US1 → 独立验收（核心对话闭环）
3. US2 → 侧栏与刷新恢复（完整可用产品形态）
4. US3 → US4 → US5 逐个叠加，每个故事独立验收不破坏既有
5. Polish 全量门禁 + quickstart 走查后交付

### 单人执行建议

按任务编号顺序线性执行即可（编号即推荐执行序）；T001/T002/T005/T006/T007/T014/T017/T018 等标 [P] 任务如有多上下文可并行派发。

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- 契约主定义 contracts/chat-api.md 与数据模型主定义 data-model.md 是实现比对基准；发现不符先改主定义（宪法 VI）
- 每个任务或逻辑分组完成即提交一次（AGENTS.md §10）
- Stop at any checkpoint to validate story independently
- Avoid: vague tasks, same file conflicts, cross-story dependencies that break independence
