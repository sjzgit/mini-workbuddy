# Tasks: 用户工作空间与文件系统权限（014）

**Input**: Design documents from `/specs/014-workspace-permission/`

**Prerequisites**: plan.md（必读）、spec.md、research.md（9 项决策）、data-model.md、contracts/workspace-permission-api.md、quickstart.md

**Tests**: spec 三十一/SC-009 明确要求自动化测试，故每个故事含测试任务（实现后紧随编写，保证可运行）。

**Organization**: 按用户故事分组（US1 选择工作空间 / US2 授权内放行 / US3 越界确认 / US4 运行快照 / US5 可追溯），前两个 Phase 为共享基础设施。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行（不同文件、无未完成依赖）
- **[Story]**: 所属用户故事（US1–US5，与 spec.md 编号一致）
- 描述含精确文件路径

## Path Conventions

- 后端：`backend/app/`（api / core / models / schemas / services + services/agent_runtime/），测试 `backend/tests/`
- 前端：`frontend/src/`（api / stores / components），测试 `frontend/src/stores/__tests__/`
- 命令一律在 `backend/` / `frontend/` 目录内经 uv / npm 执行（AGENTS.md §4/§5）

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: 配置、错误码、数据表列——所有故事的共同前置。

- [x] T001 在 backend/app/core/config.py 增加 `protected_paths: str = ""` 配置（追加系统保护路径，os.pathsep 分隔，注释引用 data-model.md §7）
- [x] T002 [P] 在 backend/app/schemas/tool.py 的 ToolErrorCode 增补 5 个错误码：`system_protected_path` / `permission_denied_by_user` / `path_resolution_failed` / `permission_check_failed` / `ask_user_unavailable`（注释引用 contracts/workspace-permission-api.md §3）
- [x] T003 在 backend/app/models/__init__.py 增补列：ConversationEntry +`workspace_path`（String(500) 可空）/ `workspace_source`（String(20) 可空）/ `workspace_selected_at`（DateTime 可空）；RunEntry +`workspace_path`（String(500) 可空，运行快照）；字段注释引用 specs/014-workspace-permission/data-model.md §1
- [x] T004 在 backend/ 执行 `uv run alembic revision --autogenerate -m "add workspace columns to conversations and runs"`，核对生成脚本后 `uv run alembic upgrade head`（迁移链挂在当前 head 之后）

**Checkpoint**: 表结构与配置就绪，pytest 全绿（现有用例不受影响）。

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: PathResolver 与 PermissionManager 纯逻辑核心——US2/US3 的判定引擎、US1 的路径校验复用。

**⚠️ CRITICAL**: 用户故事实现前必须完成本阶段。

- [x] T005 新建 backend/app/services/agent_runtime/permission.py：① `resolve_path(raw, base) -> Path`（expanduser → 相对路径按 base 拼接 → `Path.resolve()` → `os.path.normcase`，research R3 算法）；② `is_within(resolved, root) -> bool`（目录树包含：`resolved == root or root in resolved.parents`，禁止字符串前缀）；③ `TemporaryGrant` dataclass（path/scope="current_run"/created_at，data-model §2.2）；④ `RunPermissionContext` dataclass（system_root/session_root/protected/grants，含 `default_protected()` 平台默认保护集：Windows C:\Windows、C:\Program Files、C:\Program Files (x86)、C:\ProgramData + ~/.ssh、~/.aws、~/.gnupg，合并 settings.protected_paths）；⑤ `PermissionManager.check(path_resolved, ctx) -> PermissionDecision(decision: "allow"|"ask_user"|"deny", path, reason, error_code)`，判定顺序 = 保护集 DENY → system_root ALLOW → session_root ALLOW → grants ALLOW → ASK_USER（data-model §3 状态机）；⑥ 便捷工厂 `build_context(system_root, session_root)`（规范化入参）
- [x] T006 [P] 新建 backend/tests/test_path_resolver.py：绝对/相对路径、`..` 回溯逃逸、`.`、重复分隔符、尾分隔符等价、Windows 大小写不敏感、`D:\project` 与 `D:\project2` 前缀相似不互含、不存在路径可解析、根目录本身即可访问（spec Edge Cases 全覆盖；Windows 平台真实路径断言）
- [x] T007 新建 backend/tests/test_permission.py：系统工作空间→ALLOW、会话工作空间→ALLOW、并集→ALLOW、范围外→ASK_USER、grant 命中→ALLOW、保护集命中→DENY 且优先于一切（含会话工作空间误设为保护目录的兜底）、`resolve` 失败→DENY(path_resolution_failed)；Symlink 用例（tmp_path + os.symlink 指向外部目录，请求 link 内路径必须按解析后真实目标判定；无权限平台 `pytest.skip` 并注明）

**Checkpoint**: `uv run pytest tests/test_path_resolver.py tests/test_permission.py` 全绿；判定引擎可被故事安全复用。

---

## Phase 3: User Story 1 - 为 Session 选择工作空间 (Priority: P1) 🎯 MVP

**Goal**: 用户在 Chat 输入区为当前会话设置/更换/清除工作空间目录，随会话持久化，不同会话互相隔离。

**Independent Test**: 选目录 → 入口显示该目录 → 刷新后仍在；输入不存在路径报错且原值保留；清除后回到未选择；两个会话各设不同目录互不影响。

### Implementation for User Story 1

- [x] T008 [US1] 新建 backend/app/services/workspace_service.py（WorkspaceManager，research R7）：`get_workspace(session, conversation_id) -> ConversationWorkspaceOut`、`set_workspace(session, conversation_id, path)`（绝对路径校验 → `resolve_path` → 存在性/是目录/保护集拒绝 → 持久化三列 + `logger.info` 审计）、`clear_workspace(...)`（三列置 NULL 单事务，幂等）；异常类 `WorkspaceError(code, message)`（code ∈ workspace_not_found / invalid_workspace / workspace_protected / path_resolution_failed）；**不做 busy 检查**（运行中允许切换）
- [x] T009 [US1] 在 backend/app/schemas/chat.py 增加 `WorkspaceSetRequest`（path: str，strip 后 1–500 字符）与 `ConversationWorkspaceOut`（workspace_path / workspace_source / workspace_selected_at 均可空；契约 §1.1）；`ConversationSummary` 增补 `workspace_path: str | None = None`
- [x] T010 [US1] 在 backend/app/api/chat.py 增加三端点：`GET/PUT/DELETE /api/conversations/{conversation_id}/workspace`，异常映射（404 会话不存在；WorkspaceError→400 带 detail；契约 §1.2 错误表），路由层薄、复用 get_session
- [x] T011 [US1] 在 backend/app/services/chat_service.py 的 `_to_summary` 输出 `workspace_path`（workspace_service 只读引用，避免循环导入）
- [x] T012 [P] [US1] 新建 backend/tests/test_workspace_service.py：设置/更换/清除、持久化（重查仍生效）、不同会话隔离、相对路径拒绝、不存在路径拒绝、文件路径（非目录）拒绝、保护目录拒绝、busy 场景（生成中标志存在时）仍可设置
- [x] T013 [US1] 新建 backend/tests/test_workspace_api.py：三端点契约（200/404/400 detail 文案）、PUT 后 GET 一致、DELETE 幂等、ConversationSummary 列表接口携带 workspace_path
- [x] T014 [US1] 在 frontend/src/api/chat.ts 增加 `WorkspaceInfo` 类型与 `chatApi.getWorkspace / setWorkspace / clearWorkspace`（相对路径 `/api/conversations/{id}/workspace`；类型对齐 contracts §1.1）；`ConversationSummary` 接口 +`workspace_path: string | null`
- [x] T015 [US1] 在 frontend/src/stores/chat.ts 增加当前会话工作空间状态（从 currentConversation.workspace_path 派生；`setWorkspace(path)` / `clearWorkspace()`：成功后 upsertConversation 刷新、失败抛错保留原值——FR-017 前端不出现与后端不一致）
- [x] T016 [US1] 在 frontend/src/components/chat/ChatComposer.vue 输入区底部 actions 行（Agent 选择器旁）增加「📁 当前工作空间」入口：无会话显示灰色"未选择（需先有会话）"；有会话显示路径或"未选择工作空间"；点击弹 ant-design-vue Popover（当前工作空间 + Input 输入目录 + 确认按钮 + 「清除当前工作空间」按钮；样式只引用设计令牌变量，字号 12–13.5px）
- [x] T017 [P] [US1] 在 frontend/src/stores/__tests__/chat.spec.ts 增补：setWorkspace 成功更新摘要、失败保留原值并抛错、clearWorkspace 后显示未选择

**Checkpoint**: US1 独立可用——选目录/清除/校验/持久化全链路通（pytest + vitest + 手动 quickstart 场景 A）。

---

## Phase 4: User Story 2 - 工作空间内文件与 Shell 操作自动放行 (Priority: P1)

**Goal**: Agent 在授权范围（系统工作空间 ∪ 会话工作空间）内的 file_read_write / shell 操作直接执行，无需确认。

**Independent Test**: 设工作空间后让 Agent 读/写目录内文件与以该目录为 cwd 执行命令 → 全部直接成功，无询问弹窗；未选择工作空间时系统目录行为与现状一致。

### Implementation for User Story 2

- [x] T018 [US2] 在 backend/app/services/agent_runtime/tools.py：ToolContext 增加字段 `permission: "RunPermissionContext | None" = None`（最小 ExecutionContext，research R2/R8）；在 backend/app/services/agent_runtime/runtime.py 的 `run_agent_loop` ① 阶段：request.conversation_id 非空时读取 ConversationEntry.workspace_path → `build_context(settings.authorized_dir, workspace_path)` 构造快照挂入 ctx.tool_ctx（快照后运行期不可变）
- [x] T019 [US2] 工具实现层适配：backend/app/services/file_tool.py 移除内部 `_resolve_within_root` 的白名单拒绝（`path_outside_root` 职责上移 PermissionManager；read/write 文件逻辑保留，相对路径仍按系统授权目录拼接解析）；backend/app/services/shell_tool.py 的 `run(params, cwd: str | None = None)` 增加 cwd 参数传入 `subprocess.run(..., cwd=cwd)`；backend/app/services/tool_executor.py 的 `_dispatch` 对 shell 透传 cwd（file/shell 直调场景无运行上下文，仅系统目录白名单语义：file_tool 保留系统目录内校验作为直调兜底——在模块 docstring 声明「运行时权限统一由 AgentRuntime PermissionManager 承担」）
- [x] T020 [US2] 在 backend/app/services/agent_runtime/tools.py 的 run_tool 增加**权限检查阶段**（目录查名之后、分发之前，仅 builtin 的 file_read_write / shell）：① file 提取 `arguments["path"]` 以系统目录为 base 解析；shell 取 cwd（缺省=会话工作空间快照，否则系统目录）解析 + 正则提取命令文本中的显式路径参数（Windows 盘符路径 / POSIX 绝对路径）逐个解析；② 逐个 `PermissionManager.check` → 全部 allow → 进入原有分发（shell 把执行基准 cwd 传入 outcome 处理）；③ 任一 deny → 结构化失败（`denied`，error_code 取 decision.error_code）；④ 任一 ask_user → 本任务先按**拒绝占位**返回（`permission_denied_by_user`，US3 替换为真实挂起），保证本阶段行为闭合
- [x] T021 [US2] 更新 backend/tests/test_file_tool.py 与 backend/tests/test_shell_tool.py：直调语义调整（file 相对路径仍限系统目录；shell cwd 参数生效）；新增：授权内绝对路径读写成功、会话工作空间内读写成功
- [x] T022 [US2] 新建 backend/tests/test_workspace_runtime.py（runtime 集成，复用 conftest 假流/runtime_db/recorder_db 模式）：会话已设工作空间 → 假流脚本让模型调用 file_read_write 读目录内文件 → 工具 success 无挂起；shell 以工作空间为 cwd 执行成功；未选工作空间的会话 → 系统目录内操作 success

**Checkpoint**: US2 独立可用——授权内全自动放行（pytest 全绿；范围外暂为安全拒绝，US3 打开询问）。

---

## Phase 5: User Story 3 - 工作空间外路径触发用户确认 (Priority: P1)

**Goal**: 范围外路径复用 013 Ask User 挂起机制确认：允许 → 当前运行内临时授权并继续；拒绝 → 本次工具失败、运行继续；保护路径直接 DENY 不可绕过。

**Independent Test**: 让 Agent 读范围外文件 → 弹询问 → 允许后读出且同运行内再访问免询问；新消息再访问重新询问；拒绝则卡片失败但回复继续；保护路径不弹询问直接失败。

### Implementation for User Story 3

- [x] T023 [US3] 在 backend/app/services/agent_runtime/tools.py 实现权限确认挂起：run_tool 权限阶段 ask_user 分支——无人值守判定（`reply_message_id is None` → `ask_user_unavailable` 失败，同 013 口径）；`ask_registry.register(call_id)` + `AskPendingInfo` 增加字段 `permission: PermissionAskInfo | None`（含 resolved_path 与 ctx.permission 引用；question=权限请求文案含路径与原因，options=["允许本次访问", "拒绝"]，单选）；新增 `async def resume_pending_tool(record, outcome, ctx, session) -> ToolCallRecord`：`ask.permission is None` → 原样走 `finish_ask_user_record`（013 行为不变）；权限分支读 `ask.pending.selected`——含「允许本次访问」→ `ctx.permission.grants.append(TemporaryGrant(path))` → 重执行原工具调用并按结果 `_finish_record`；否则（拒绝/超时/取消）→ `permission_denied_by_user` 失败记录；在 backend/app/services/agent_runtime/runtime.py 主循环 ask 分支把 `finish_ask_user_record` 替换为 `await resume_pending_tool(...)`
- [x] T024 [US3] 补齐 backend/tests/test_workspace_runtime.py 确认流用例：范围外 → ask_user 挂起事件发出（question 含路径、options 正确）；提交允许 → grant 生成本次运行内后续访问免询问；新 AgentRun（新 run_id）同路径 → 再次挂起；提交拒绝 → 工具记录 denied、`permission_denied_by_user`，运行继续产出回复；超时/取消路径 → denied 且注册表零残留；保护路径（C:\Windows 下文件）→ 直接 denied（system_protected_path）**无** ask_user 事件；grant 不落库（run 结束后无任何持久化痕迹）

**Checkpoint**: US3 独立可用——询问/授权/拒绝/保护路径全链路通（quickstart 场景 C/E）。

---

## Phase 6: User Story 4 - 运行中的 AgentRun 不受工作空间切换影响 (Priority: P2)

**Goal**: AgentRun 启动快照工作空间；运行中切换只影响后续运行；Trace 反映启动时的工作空间。

**Independent Test**: 运行慢任务中切换工作空间 → 进行中任务按旧范围完成；新消息按新范围；运行记录显示启动时工作空间。

### Implementation for User Story 4

- [x] T025 [US4] 快照可见性接线：在 backend/app/schemas/agent_runtime.py 的 RunStartedData 增补 `workspace_path: str | None = None`；runtime.py 的 run_started 事件填充快照值；backend/app/services/agent_runtime/recorder.py 在 run_started 落库分支写入 `runs.workspace_path`；backend/app/api/runs.py 与 backend/app/schemas/runs.py 的运行详情输出增补 `workspace_path`（可空）
- [x] T026 [US4] 补齐 backend/tests/test_workspace_runtime.py 快照用例：运行启动后修改 DB 中会话工作空间 → 运行内后续判定仍用旧快照（构造第二次工具调用断言）；run_started 事件与 runs 行的 workspace_path 等于启动时值；busy 中 PUT workspace 成功（US1 已测 API，此处断言运行不受影响）

**Checkpoint**: US4 独立可用——快照语义经测试固化（quickstart 场景 D）。

---

## Phase 7: User Story 5 - 权限决策可追溯 (Priority: P2)

**Goal**: 每次权限判定产出 `permission_checked` 事件（SSE + run_events 落库），工作空间快照随 run_started 可见（T025 已落），审计不含文件内容。

**Independent Test**: 触发若干判定后查 run_events：每条含工具/路径/决策/原因；SSE 流含该事件；记录中无文件内容。

### Implementation for User Story 5

- [x] T027 [US5] 在 backend/app/schemas/agent_runtime.py 增加 `EVENT_PERMISSION_CHECKED = "permission_checked"` 与 `PermissionCheckedData(round, call_id, decision: Literal["allow","ask_user","deny"], tool_name, path, reason)`（契约 §2.1）；backend/app/services/agent_runtime/events.py 导出常量
- [x] T028 [US5] 在 run_tool 权限阶段每次判定后 emit 事件（ctx.emitter；含 allow——审计要求覆盖每次判定，SC-008）；backend/app/services/chat_service.py 桥接白名单 +EVENT_PERMISSION_CHECKED；backend/app/services/agent_runtime/recorder.py 增加 permission_checked → run_events 落库分支（data 仅含安全字段，天然无文件内容）
- [x] T029 [P] [US5] 在 frontend/src/api/chat.ts 增加 `PermissionCheckedData` 类型与 StreamEvent 联合 `permission_checked` case（本期聊天页不消费，前向兼容）
- [x] T030 [US5] 测试：backend/tests/test_workspace_runtime.py 断言判定事件按序产出（allow/ask_user/deny 各至少一条、字段齐全）；backend/tests/test_run_records.py 增补 run_events 落库断言（decision/path/reason 存在且无文件内容字段）

**Checkpoint**: US5 独立可用——决策全程可追溯。

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: 契约文本、SQL 存档、全量门禁。

- [x] T031 更新 backend/app/services/tool_registry.py 工具描述（契约 §4）：file_read_write 的 path 参数说明改为「相对系统授权目录的相对路径，或绝对路径（绝对路径经统一权限判定，范围外将请求用户确认）」；shell 增加 cwd 参数定义（可选 string，缺省=会话工作空间或系统授权目录）与 restrictions 补充「应用层路径检查，非 OS 级沙箱」；同步 003 契约描述字段与注册表逐字对齐口径
- [x] T032 新建 sql/migrations/014-workspace-permission.sql 存档（与 Alembic 迁移对应：conversations 三列 + runs 一列，SQLite ALTER TABLE ADD COLUMN 幂等写法，参照 013 存档格式带注释头）
- [x] T033 全量门禁与核对：backend/ `uv run pytest` + `uv run pyright`；frontend/ `npm run build` + `npm run test:unit` 全绿；按 quickstart.md 手动走场景 A–E；确认 AGENTS.md §9 清单全部通过

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup（Phase 1）**: 无依赖，立即开始（T001→T003→T004 顺序；T002 可并行）
- **Foundational（Phase 2）**: 依赖 Phase 1（T005 依赖 T001/T002）；T006 可与 T005 并行编写、T007 依赖 T005
- **US1（Phase 3）**: 依赖 Phase 2（workspace_service 复用 resolve_path/保护集）
- **US2（Phase 4）**: 依赖 Phase 2；不依赖 US1（无会话工作空间时走系统目录，行为闭合）——但 US1 的 API 是完整体验前提，建议 US1 先行
- **US3（Phase 5）**: 依赖 US2（权限检查阶段已存在，替换占位拒绝为挂起）
- **US4（Phase 6）**: 依赖 US2（快照已构造）；测试依赖 US1（API 切换）
- **US5（Phase 7）**: 依赖 US2/US3（事件在权限检查阶段发出）
- **Polish（Phase 8）**: 依赖全部故事完成

### User Story Dependencies

```text
Phase 1 → Phase 2 → US1 → US2 → US3 → US4 → US5 → Polish
                     └──────┬──────┘（US2 起 runtime 链路串行；US1 与 Phase 2 可交叠推进）
```

### Parallel Opportunities

- T002（错误码）与 T001/T003 并行
- T006（PathResolver 测试）可与 T005 并行编写（实现后一起跑绿）
- T012 / T017 等纯测试编写任务与同故事实现任务可交错（先写后跑）
- T029（前端事件类型）与后端 US5 其余任务并行

---

## Implementation Strategy

### MVP First（US1 单独交付）

1. Phase 1 + Phase 2 完成
2. Phase 3（US1）：工作空间选择全链路（含前端入口）
3. **STOP & VALIDATE**：quickstart 场景 A + pytest/vitest 绿 → 已是可演示增量

### Incremental Delivery

- +US2：授权内自动放行（核心价值闭环）
- +US3：越界确认与临时授权（安全交互闭环）
- +US4：快照一致性（正确性保障）
- +US5：可追溯（审计增强）
- Polish：门禁全绿后交付

## Notes

- 权限判断唯一入口 = run_tool 权限阶段调 PermissionManager（Invariant 2/9）；file_tool/shell_tool 实现层不自查运行时权限
- LLM/提示词不参与权限判定（Invariant 3）；三值决策禁止压成布尔（Invariant 4）
- 临时授权仅存于 RunPermissionContext，不落盘、不跨运行（Invariant 5）
- 快照在 run_agent_loop ① 阶段构造后不可变（Invariant 6）
- Windows 主要部署：Symlink/junction 测试在无权限环境 pytest.skip 并注明，不假装通过
- 每个 Phase 完成后跑一次对应测试再前进；全部完成后跑四连门禁（AGENTS.md §9）
