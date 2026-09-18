# Tasks: Ask User 询问工具（第十三阶段）

**Input**: Design documents from `/specs/013-ask-user-tool/`

**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/ask-user-api.md ✅, quickstart.md ✅

**Tests**: 按 AGENTS.md §9 与宪法 IV，测试任务必做。

**Organization**: 按用户故事分组（US1–US5 对应 spec.md）。**零新增第三方依赖、零新表**。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行（不同文件、无依赖）
- **[Story]**: 归属用户故事（US-ALL = 跨故事）

## Path Conventions

Web app 双项目：`backend/`（uv）+ `frontend/`（npm）。后端命令在 `backend/` 内 `uv run`；前端命令在 `frontend/` 内执行（Windows 注意 AGENTS.md §5 Node 22 PATH）。

---

## Phase 1: Setup（共享基础设施）

- [x] T001 [US-ALL] `backend/app/core/config.py` 新增 `ask_user_timeout_seconds: int = 300`（FR-013 配置落点，注释注明来源契约 §6）

**Checkpoint**: 配置就绪。

---

## Phase 2: Foundational（阻塞性前置，全部故事依赖）

**⚠️ CRITICAL**: 本阶段完成前不得开始任何用户故事实现。

- [x] T002 [US-ALL] 迁移 `backend/migrations/versions/`：`INSERT INTO tools (name, enabled, ...) SELECT 'ask_user', 1 ... WHERE NOT EXISTS`（幂等补种，003 三行模式）；SQL 存档 `sql/migrations/013-ask-user-tool.sql`；`uv run alembic revision` + `upgrade head` 验证
- [x] T003 [US-ALL] `backend/app/services/tool_registry.py`：注册 `ask_user` 定义——display_name"询问用户"、purpose、params_summary、三节说明文本（契约 §1 逐字对齐）+ `AskUserParams`（question strip 1–2000 必填；options ≤10×1–200 可选，空列表按 None → 开放式；multi_select 默认 False）
- [x] T004 [US-ALL] `backend/app/schemas/agent_runtime.py` + `events.py`：`EVENT_ASK_USER = "ask_user"` 常量 + `AskUserData`（round/call_id/question/options/multi_select）；events.py 导出
- [x] T005 [US-ALL] 创建 `backend/app/services/agent_runtime/ask_user.py`：`PendingAsk`（answered Event / selected / text / cancelled）+ 模块级注册表 `{call_id: PendingAsk}` + `submit_answer(call_id, selected, text) -> bool`（格式拼装按契约 §4、置位唤醒、返回是否命中）+ `format_answer_text()` + `remove(call_id)`
- [x] T006 [US-ALL] `backend/app/services/tool_executor.py`：ask_user 显式拒绝分支（`execute("ask_user",...)` → `execution_error` + 契约 §5 文案）

**Checkpoint**: 契约 Schema、注册表、挂起模块、迁移就绪 → 用户故事可开始。

---

## Phase 3: US1（P1，工具注册与启用）

**Goal**: ask_user 作为一等内置工具进入治理体系。
**Independent Test**: 工具管理页出现"询问用户"并可启停；停用/未绑定的 Agent 目录无此工具。

### 实现任务

- [x] T007 [US1] 后端测试 `backend/tests/test_ask_user_runtime.py`（治理部分）：工具行存在且经 `build_tool_catalog`——绑定+启用出现在目录、未绑定不出现、停用不出现（复用既有 conftest 夹具）

**Checkpoint**: 治理语义测试绿（与既有工具同构）。

---

## Phase 4: US2 + US3（P1，询问端到端：开放式 + 选项式）🎯 MVP

**Goal**: 模型调用 ask_user → 事件 → 挂起；回答提交 → 结果交还 → 恢复。
**Independent Test**: quickstart 场景 2–3。

### 实现任务

- [x] T008 [US2/US3] `backend/app/services/agent_runtime/tools.py`：run_tool 增加 `ask_user` 专用异步分支 `_run_ask_user`——①目录命中（builtin, ref=ask_user）②`reply_message_id is None` → 立即失败 `ask_user_unavailable`（契约 §4 文案，FR-014）③注册 PendingAsk → 发 EVENT_ASK_USER ④`asyncio.wait` 三路：answered / ctx.cancel / `asyncio.timeout(settings.ask_user_timeout_seconds)` ⑤组装 outcome：回答→success（format_answer_text）、取消→cancelled、超时→`ask_user_timeout`（文案含秒数）；finally `remove(call_id)`；分发处对该 ref 走 await 分支（其余 builtin 保持同步路径不变）
- [x] T009 [US2/US3] `backend/app/services/chat_service.py`：桥接转发白名单加入 `EVENT_ASK_USER`（原样转发，无透传字段）
- [x] T010 [US2/US3] `backend/app/schemas/chat.py` + `backend/app/api/chat.py` + `chat_service.py`：`AskAnswerRequest`（call_id 必填；selected 可选；text 可选）+ 端点 `POST /api/conversations/{cid}/messages/{mid}/ask-answers`——404（消息不存在 / call_id 未命中等待）、422（selected 空且 text strip 空）、409（该消息生成已终态：registry 无 running 任务即迟到）、成功 `{"resolved": true}`；提交前校验任务 running（`get_running_by_conversation`）
- [x] T011 [US2/US3] `backend/app/services/agent_runtime/recorder.py`：`ask_user` 事件分支 → `_insert_event`（run_events 落库；result 经既有 tool_call_completed 的 tool_result 完整保存，FR-016）
- [x] T012 [US2/US3] 后端测试 `test_ask_user_runtime.py`（运行部分）：参数校验（缺 question / 空 options 降级开放式 / options 超限）；等待→回答恢复（answer 后 outcome.success、result 文本与契约 §4 一致——开放式/多选"/"连接/其他前缀/组合格式）；等待中 cancel → cancelled 且无回答交还；超时（monkeypatch `ask_user_timeout_seconds=0`）→ `ask_user_timeout`；无人值守（reply_message_id=None）→ 立即 `ask_user_unavailable` 且注册表零残留；运行结束注册表零残留
- [x] T013 [US2/US3] 后端测试 `backend/tests/test_chat_ask_answers_api.py`：端点契约——成功 200 resolved、call_id 未命中 404、空回答 422、消息不存在 404、生成结束后 409；假流注入验证 `ask_user` 事件出现在 SSE 流（含 question/options/multi_select 字段）
- [x] T014 [P] [US2/US3] 前端 `frontend/src/api/chat.ts`：`AskUserData` 类型 + StreamEvent 联合 `ask_user` + dispatchFrame case + `chatApi.answerAsk(cid, mid, payload)`（POST ask-answers）
- [x] T015 [US2/US3] 前端 `frontend/src/stores/chat.ts`：`RunDisplayState.pendingAsk: { callId; question; options: string[]; multiSelect: boolean } | null`——ask_user 事件置位；tool_call_completed（同 call_id）与 finalizeRun 清位；`submitAskAnswer` action（调 API + submitting 状态 + 失败不清 pendingAsk）
- [x] T016 [US2/US3] 前端 `frontend/src/components/chat/AskUserModal.vue`：Modal（:closable=false :mask-closable=false :keyboard=false）——开放式 textarea；选项式 Radio.Group / Checkbox.Group + 末尾固定"其他，我手动输入"+ 选中其他时下方 textarea；提交按钮：空回答禁用 + submitting loading + 失败 message 提示且弹窗不关；样式全引用 tokens.scss（AGENTS.md §8）
- [x] T017 [US2/US3] 前端 `frontend/src/views/ChatView.vue`：挂载 AskUserModal（绑定当前会话 run.pendingAsk；无则不渲染）
- [x] T018 [US2/US3] 前端 Vitest `frontend/src/components/chat/__tests__/askUserModal.spec.ts`：四类场景渲染与提交 payload——开放式文本、单选一项、多选多项、选其他→输入框联动且 payload 含 text；空回答提交禁用
- [x] T019 [US2/US3] 前端 Vitest（chat store 追加用例）：ask_user 事件置位 pendingAsk / completed 同 call_id 清位 / 提交失败弹窗保留

**Checkpoint**: quickstart 场景 2–3 人工验证通过 + 前后端测试绿。

---

## Phase 5: US4 + US5（P2，取消/恢复 + 上限/无人值守）

**Goal**: 等待期间取消、刷新恢复、超时收尾、无人值守 fail-fast（后端逻辑 T008/T012/T013 已含大部分；本阶段补前端恢复与运行记录展示）。
**Independent Test**: quickstart 场景 4–5。

### 实现任务

- [x] T020 [US4] 前端恢复语义验证与补线：刷新后重订阅（既有 subscribeStream 缓冲重放）→ ask_user 事件再次到达 → pendingAsk 重新置位；补 Vitest：缓冲重放含 ask_user 时 pendingAsk 恢复；停止运行（既有 stop）→ 终态 finalizeRun 清 pendingAsk（弹窗关闭）
- [x] T021 [US5] 后端测试补强：评测直调路径（复用 012 评测测试模式）——模型调用 ask_user 运行不挂起、事件流无 ask_user 事件、 outcome 为 `ask_user_unavailable`、评测 Case 正常出分
- [x] T022 [US4/US5] 前端 `frontend/src/components/runs/RunTimeline.vue`：ask_user 事件行（"向用户提问：{question}"）+ 对应 tool_call_completed 行显示回答（既有 result 展示已覆盖，验证即可）

**Checkpoint**: quickstart 场景 4–5 人工验证通过。

---

## Phase 6: 收尾与交付门禁

- [x] T023 [P] [US-ALL] `README.md` 特性列表补第三阶段后增量一行（Ask User 工具简述）；`AGENTS.md` 无目录变更则不更新
- [x] T024 [US-ALL] 人工走查 [quickstart.md](quickstart.md) 场景 1–5：场景 1（治理）与场景 5 的无人值守路径已由自动化测试覆盖（test_ask_user_runtime / test_chat_ask_answers_api）；场景 2–4 的真实模型对话走查留待用户按 quickstart.md 操作验证
- [x] T025 [US-ALL] 交付门禁四连（AGENTS.md §9）：`uv run pytest` + `uv run pyright`（0 错误）+ `npm run build`（零错误）+ `npm run test:unit` 全绿；UI 改动人工核对 §8 设计令牌条目
- [ ] T026 [US-ALL] 运行 `/speckit-analyze` 跨文档一致性分析并处理发现项

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 → 2 顺序**；Phase 2 内 T002→T003 链，T004/T005/T006 可并行 [P]（不同文件）
- **Phase 3 依赖 Phase 2**（T007 只依赖注册表与迁移）
- **Phase 4 依赖 Phase 2**（T008 依赖 T003/T004/T005；T010 依赖 T005；前端 T014–T019 依赖后端事件契约定稿 T004）
- **Phase 5 依赖 Phase 4**（恢复/评测测试复用 US2 链路）；T021 可与 T020 并行
- **Phase 6 最后**，T026 在 T025 全绿后

### Parallel Opportunities

- Phase 2：T004 ∥ T005 ∥ T006；T002→T003 链
- Phase 4：后端 T008→T009→T010→T011 与前端 T014→T015→T016/T017 双线并行；T012/T013 依赖各自后端任务
- Phase 5：T020 ∥ T021

## Implementation Strategy

### MVP First（Phase 1–4）

1. Setup + Foundational → 契约/注册/挂起模块就绪
2. US1 治理测试 → 工具可见可管
3. US2+US3 端到端 → **STOP and VALIDATE**（quickstart 场景 2–3）
4. US4+US5 补齐健壮性 → 全场景验证 → 门禁 → analyze

## Notes

- 每完成任务勾选复选框（/speckit-implement 维护）
- 提交粒度：每个 Phase 或逻辑分组一次提交
- 实现中发现规范问题 → 先回写 `contracts/ask-user-api.md` / `data-model.md` 再同步代码（宪法 VI）
- 等待/取消/超时三退出路径是测试重点；注册表残留（finally）必须有专项断言
