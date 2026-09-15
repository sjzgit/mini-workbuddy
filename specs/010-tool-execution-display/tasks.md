# Tasks: 工具执行过程展示（010）

**Input**: Design documents from `/specs/010-tool-execution-display/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/display-events.md

**Tests**: 含测试任务——宪法质量门禁要求后端 pytest 与前端 Vitest 全绿（`.specify/memory/constitution.md` §IV），AGENTS.md §10 要求核心逻辑配套 Vitest。

**Organization**: 按用户故事分组；store 按会话运行槽重构（Clarify Q2 无缝续播的地基）归入 Foundational。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行（不同文件、无依赖）
- **[Story]**: 所属用户故事（US1~US6 对应 spec.md）
- 描述含精确文件路径

## Path Conventions

- Web app：`backend/app/`（uv）、`frontend/src/`（npm）；测试分别在 `backend/tests/`、`frontend/src/**/__tests__/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: 配置项与前端契约类型——两端各自独立起步

- [x] T001 [P] 在 backend/app/core/config.py 新增配置项 `runtime_tool_params_max_chars: int = 4000` 与 `runtime_tool_result_max_chars: int = 16000`（含注释：工具事件 params/result 字段字符上限，契约见 specs/010-tool-execution-display/contracts/display-events.md §1.3）
- [x] T002 [P] 在 frontend/src/api/chat.ts 为 `ToolCallStartedData` 增补 `params: string; display_name: string; server_name: string | null`，为 `ToolCallCompletedData` 增补 `result: string; display_name: string; server_name: string | null`（类型从 009 契约 §3 派生，null 不混用 undefined）

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: 事件字段后端链路 + 前端按会话运行槽。**完成前不得开始任何 US 任务**

**⚠️ CRITICAL**: 前端所有用户故事都构建在 T007 的运行槽之上；后端所有用户故事都依赖 T003~T005 的新字段

- [x] T003 在 backend/app/schemas/agent_runtime.py 为 `ToolCallStartedData` 增补 `params: str = ""`、`display_name: str = ""`、`server_name: str | None = None`；为 `ToolCallCompletedData` 增补 `result: str = ""`、`display_name: str = ""`、`server_name: str | None = None`（模块头注释标注契约来源 010 display-events.md §1）
- [x] T004 在 backend/app/services/agent_runtime/tools.py 扩展 `ToolCallRecord`（增补 `params_full`、`result_full`、`display_name`、`server_name` 字段）并在 `run_tool`/`_finish_record` 中填充：`params_full` = 原始 arguments 文本（`raw_text`）；`result_full` = 成功时 `result_for_model`、失败时 `_failure_result_text`（人话无堆栈）；`display_name` 按类型解析——builtin 取 `tool_registry.get_definition(ref).display_name`、mcp 取 `entry.ref`、skill 固定"加载 Skill"；`server_name` 仅 mcp 时经 session 查 `McpServerEntry.name`
- [x] T005 在 backend/app/services/agent_runtime/runtime.py 的 `EVENT_TOOL_CALL_STARTED`/`EVENT_TOOL_CALL_COMPLETED` 事件产出中携带 `params`/`result`/`display_name`/`server_name`（取自 ToolCallRecord），并新增截断助手：超过 `settings.runtime_tool_params_max_chars`/`runtime_tool_result_max_chars` 时截断并在文末追加 `\n…[已截断，完整内容共 N 字符]`（N 为截断前总字符数）
- [x] T006 在 backend/tests/test_agent_runtime.py 增补契约测试：① started/completed 事件含四个新字段；② builtin 事件 `display_name` 为注册表易读名（如"当前时间"）且 `server_name` 为 None；③ mcp 事件 `server_name` 为 Server 名；④ 超限结果被截断且文末含截断标记与总字符数；⑤ 失败路径 `result` 为人话错误（不含 Traceback）；⑥ 取消路径 completed(status=cancelled) 仍携带新字段（FR-020 不因增补回归）
- [x] T007 重构 frontend/src/stores/chat.ts 为按会话运行槽：新增 `runStates: Record<number, RunDisplayState>`（每会话独立 segments/phase/generatingReplyId）与 `activeStreams: Set<number>`（按 replyMessageId 防重复订阅）；`handleStreamEvent` 改为经 `subscribeStream` 闭包捕获 `(cid, mid)` 路由到对应槽（`runStates[cid] ??= createRunState()`）；`send`/`regenerate`/`loadMessages`/`stopGeneration` 适配槽位读写；切换会话不销毁槽、`loadMessages` 仅在 `activeStreams` 无该消息时重订阅（Q2 无缝续播）；历史加载（无活跃流）不生成卡片（FR-025）；对外导出改为 `currentRunState` 计算属性（`runStates[currentId]`）保持组件兼容
- [x] T008 更新 frontend/src/stores/__tests__/chat.spec.ts 适配运行槽结构并增补：双会话并发生成事件互不串扰（槽隔离）、同一会话重复 `loadMessages` 不产生重复订阅、`run_completed` 后槽位清理与 `activeStreams` 移除

**Checkpoint**: 后端事件携带展示字段且测试全绿；前端双会话并发行为正确——用户故事实现可开始

---

## Phase 3: User Story 1 - 工具过程卡片实时展示 (Priority: P1) 🎯 MVP

**Goal**: 工具调用开始即在回复区出现过程卡片（易读标题 + "正在执行"），结束后更新为成功/失败并显示耗时

**Independent Test**: 向绑定内置工具的 Agent 提问 → 卡片先"正在执行"后变"成功 · {耗时}"；本地工具显示易读名、MCP 工具显示"Server名 · 工具名"

### Implementation for User Story 1

- [x] T009 [P] [US1] 新建 frontend/src/components/chat/ToolProcessCard.vue：收起态卡片（状态徽标 + 标题 + 单行摘要省略 + 耗时），状态→文案/图标映射（running"正在执行"+旋转图标、success"成功"+✓+`--success`、error/denied"失败"+✕+`--danger`、cancelled"已取消"+⏹、unknown"状态未知"+？+`--warning`，文字与图标双通道 FR-027）；标题规则：builtin=`{display_name}`、mcp=`{server_name} · {display_name}`、skill=`加载 Skill`；耗时格式化（≥1000ms 显示"X.X 秒"否则"X 毫秒"）；样式全部引用 tokens.scss 变量、气泡视觉语言（白底+`--border`+10px 圆角）
- [x] T010 [US1] 扩展 frontend/src/stores/chat.ts 的 tool 事件处理：`tool_call_started` 时卡片段记录 `displayName`/`serverName`/`toolType`/`status='running'`/`paramsSummary`/`paramsText`；`tool_call_completed` 时按 `call_id` 就地更新 `status`（success/error/denied/cancelled 映射）、`durationMs`、`resultSummary`、`resultText`
- [x] T011 [US1] 在 frontend/src/components/chat/ChatMessages.vue 中将现有 `.msg-tool` 简要文本提示替换为 `ToolProcessCard` 渲染（v-for segments 中 kind==='tool' 的片段，`:key` 用 `callId` 防止并行/多次调用错位），保持片段在消息流中的原有序列位置
- [x] T012 [US1] 新建 frontend/src/components/chat/__tests__/ToolProcessCard.spec.ts：running→success 状态流转、三种标题规则（builtin/mcp/skill）、耗时格式化（450 毫秒 / 2.3 秒）、失败态文案与图标

**Checkpoint**: US1 可独立演示——带工具对话即可看到卡片全生命周期

---

## Phase 4: User Story 2 - 正文与卡片按事件顺序交错 (Priority: P1)

**Goal**: 正文与卡片严格按 Runtime 事件顺序交错；多次调用独立展示；并行调用按开始顺序排列、完成时原位更新

**Independent Test**: 触发"文字→工具→文字→工具→文字"的回复 → 展示顺序与事件顺序一致；同工具两次调用出现两张卡片

> 实现承载于 T007（事件按到达顺序入槽）与 T011（按片段序列渲染 + callId 键），本阶段交付验收性测试；若测试暴露缺陷，修复落在 frontend/src/stores/chat.ts 对应函数。

- [x] T013 [US2] 扩展 frontend/src/stores/__tests__/chat.spec.ts：① content→tool→content 事件序列产生三段交错 segments（顺序保持）；② 同一工具两次 started（不同 call_id）产生两张独立卡片且各自状态更新不串扰；③ 并行两工具"先开始后结束/后开始先结束"时卡片保持开始顺序、完成只原位更新不重排；④ completed 使用错误 call_id 时不影响已有卡片（防错位）

**Checkpoint**: US1 + US2 均独立可验证——顺序正确性有回归保护

---

## Phase 5: User Story 3 - 卡片详情展开与内容整理 (Priority: P2)

**Goal**: 展开卡片查看整理后的输入与结果：JSON 缩进、纯文本换行、长内容截断标注、二进制只报类型大小、失败人话无堆栈

**Independent Test**: 展开成功卡片 → 参数为格式化 JSON；读取超长文件 → 截断标注；失败卡片 → 人话原因无堆栈

### Implementation for User Story 3

- [x] T014 [US3] 扩展 frontend/src/components/chat/ToolProcessCard.vue 展开态：`输入参数`/`执行结果` 两个独立折叠分区；渲染分派——合法 JSON（对象/数组）`JSON.stringify(_, null, 2)` 等宽缩进（`--font-mono`）、其他文本 `pre-wrap` 纯文本、含 NUL 或不可打印字符占比 >30% 显示"二进制内容（约 N KB），类型未知"、单字段渲染上限 20000 字符超出提示"未展示全部（共 N 字符）"、后端截断标记 `…[已截断，完整内容共 N 字符]` 原样展示；渲染一律文本插值禁止 v-html（FR-015）；内部暴露名 `tool_name` 以次要文字显示在详情内（排障用，不作标题）
- [x] T015 [US3] 扩展 frontend/src/components/chat/__tests__/ToolProcessCard.spec.ts：JSON 缩进渲染、非法 JSON 按纯文本保留换行、二进制内容提示（构造含   输入）、20000 字符渲染上限提示、含 `<script>` 文本被转义为纯文本（不可信文本不执行）、失败卡片展示人话错误且不含"Traceback"

**Checkpoint**: US1~US3 可独立验证——详情安全性与可读性齐备

---

## Phase 6: User Story 4 - 滚动跟随与交互 (Priority: P2)

**Goal**: 底部自动跟随、上滚暂停、回到最新按钮、展开/收起阅读位置不跳动

**Independent Test**: 长回复生成中上滚 → 不拉回且按钮出现；点击按钮回底并恢复跟随；展开卡片无跳动

### Implementation for User Story 4

- [x] T016 [US4] 扩展 frontend/src/components/chat/ChatMessages.vue：① "回到最新消息"悬浮按钮（`userScrolledUp===true` 时显示，点击滚至底部并置 `userScrolledUp=false`，样式引用 tokens：`--bg-surface`+`--border`+阴影仅浮层）；② 滚动容器 watch `scrollHeight` 突变补偿——`userScrolledUp` 为 true 时 `scrollTop += newHeight - oldHeight`（覆盖卡片展开/收起与长内容展开的阅读位置保持，FR-019）；保留现有距底 80px 跟随判定
- [ ] T017 [US4]（未完成，见备注）滚动行为组件级测试：jsdom 无布局引擎（scrollHeight 恒为 0），scrollToBottom/补偿逻辑无法在组件测试中有效断言；该行为的验证归入 quickstart.md 场景 5 人工走查。补偿逻辑本身已由 T016 实现且经 build/类型检查。

**Checkpoint**: US1~US4 可独立验证——长回复场景阅读体验完整

---

## Phase 7: User Story 5 - 取消与中断的明确终态 (Priority: P3)

**Goal**: 取消 → "已取消"；断流无法确认 → "状态未知"；任何路径不停留"正在执行"、不误标成功

**Independent Test**: 执行中点停止 → "已取消"；执行中断网 → "状态未知"

### Implementation for User Story 5

- [x] T018 [US5] 扩展 frontend/src/stores/chat.ts 终态兜底（写在运行槽辅助函数中，作用于对应槽）：① `subscribeStream` 异常断开且无终态 → 该槽所有 `status==='running'` 卡片置 `unknown`（FR-021）；② `run_completed(stopped=true)` → 残留 running 置 `cancelled`；③ `run_completed(status='error')` 或桥接兜底终态 → 残留 running 置 `unknown`；正常 completed(status) 映射不变（FR-020/022）
- [x] T019 [US5] 扩展 frontend/src/stores/__tests__/chat.spec.ts：流抛错后 running→unknown、run_completed(stopped) 残留卡片→cancelled、run_completed(error) 残留卡片→unknown、正常取消路径 completed(cancelled)→已取消、任意终态后不存在 running 状态卡片（FR-022 不变量断言）

**Checkpoint**: 异常路径终态有回归保护，FR-022 不变量可机检

---

## Phase 8: User Story 6 - 页面内状态保留 (Priority: P3)

**Goal**: 切换会话再返回：卡片/状态/顺序完整；生成中切换不被取消、返回无缝续播；历史会话与刷新后无卡片且无报错

**Independent Test**: 会话 A 生成中切到 B 再回 A → 无缝续播；切历史会话 → 只有正文无卡片

> 实现承载于 T007（槽不销毁 + activeStreams 防重订阅 + 闭包路由），本阶段交付验收性测试。

- [x] T020 [US6] 扩展 frontend/src/stores/__tests__/chat.spec.ts：① 会话 A 生成中 `selectConversation(B)` 再回 A：A 槽 segments/phase 保留、未发起新订阅（activeStreams 已登记）、期间 B 会话事件写入 B 槽不影响 A；② 加载历史会话（消息 status 为 completed/incomplete 且无活跃流）时 segments 为空数组（FR-025 不还原卡片）；③ `run_completed` 后切走再返回无残留生成态

**Checkpoint**: 全部用户故事独立可验证

---

## Phase 9: Polish & Cross-Cutting Concerns

**Purpose**: 门禁收口与文档同步

- [x] T021 运行完整门禁并修复至全绿：backend 内 `uv run pytest` + `uv run pyright`；frontend 内 `npm run build` + `npm run test:unit`（Windows+ nvm 需按 AGENTS.md §5 切换 node 22）
- [x] T022 [P] 按 quickstart.md 七个手动场景走查真实后端+前端联调；发现规范偏差按宪法 Feedback Loop 回写（契约/spec 优先），并在 specs/010-tool-execution-display/checklists/requirements.md 记录验证结果

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1（Setup）**: 无依赖，T001/T002 可并行
- **Phase 2（Foundational）**: T003→T004→T005→T006 后端链（顺序）；T007→T008 前端链（顺序）；两链之间可并行。**阻塞所有 US**
- **Phase 3（US1）**: 依赖 Phase 2；T009 与 T010 可并行，T011 依赖 T009+T010，T012 依赖 T009
- **Phase 4（US2）**: 依赖 T007/T011；纯验收测试
- **Phase 5（US3）**: 依赖 T009/T010（组件与数据就绪）；T014→T015
- **Phase 6（US4）**: 依赖 T011（卡片渲染就绪后高度补偿才有意义）
- **Phase 7（US5）**: 依赖 T007/T010；可与 US3/US4 并行
- **Phase 8（US6）**: 依赖 T007/T008
- **Phase 9**: 依赖全部 US 完成

### Parallel Opportunities

- T001 ∥ T002（Setup）
- 后端链（T003~T006）∥ 前端链（T007~T008）
- T009 ∥ T010；T014~T015 ∥ T016~T017 ∥ T018~T019（不同文件）

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Phase 1 + Phase 2（Setup + Foundational）
2. Phase 3（US1）→ **STOP & VALIDATE**：带工具对话可见卡片全生命周期
3. 此时已具备演示价值；US2 顺序正确性由既有架构保证，可随后补测试

### Incremental Delivery

1. Foundational 完成 → 后端事件字段就绪、前端多会话正确
2. +US1（卡片）→ +US2（顺序回归保护）→ +US3（详情与安全）→ +US4（滚动体验）→ +US5（异常终态）→ +US6（保留验证）
3. Phase 9 门禁全绿后交付

### Notes

- [P] = 不同文件、无未完成依赖
- 每个任务或逻辑分组后提交一次（AGENTS.md §10）
- 提交信息结尾附 `Co-Authored-By: Claude Code <noreply@anthropic.com>`
- `0user chat/` 目录禁止读写
