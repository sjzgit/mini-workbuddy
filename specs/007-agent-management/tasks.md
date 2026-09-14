# Tasks: Agent 管理（第七阶段）

**Input**: Design documents from `/specs/007-agent-management/`

**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/agents-api.md ✅, quickstart.md ✅

**Tests**: 按 AGENTS.md §9 质量门禁与宪法 IV（验证驱动），测试任务为必做项。

**Organization**: 六个用户故事。US1（新建+编排）与 US2（列表+详情浏览）同为 P1 互相依存（保存后需列表确认，列表需要可创建的 Agent），合并在 Phase 3 先后落地；US3（版本）依赖 US1 保存链路；US4（默认+删除）依赖 US2 列表；US5（停用绑定）依赖 US1 绑定链路；US6（引用保护）依赖 US1 绑定写入。US5/US6 均以 US1 为前置、彼此独立可并行。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行（不同文件、无依赖）
- **[Story]**: 归属用户故事

## Path Conventions

后端改动在 `backend/`（uv 强制：`uv run` 执行 pytest/alembic/pyright）；前端改动在 `frontend/`（npm；注意 AGENTS.md §5 的 Node 22 PATH 切换）。命令一律在对应子目录内执行。

---

## Phase 1: Setup（共享基础设施）

- [x] T001 通读 [AGENTS.md](../../../AGENTS.md)（宪法要求的实施前置）并核对现状：`backend/app/models/__init__.py` 既有 ORM 惯例（`_utcnow`、部分唯一索引写法）、`backend/tests/conftest.py` 的 `db_session`/`client` fixtures、`frontend/src/views/McpView.vue` 与 `frontend/src/api/mcp.ts` 的视图/store/api 分层惯例——只读核对，作为实现基线
- [x] T002 依据 [data-model.md](data-model.md) §6 创建 Alembic 迁移 `backend/migrations/versions/<rev>_add_agents_tables.py`：新增 `agents`、`agent_bindings`、`agent_prompt_versions` 三表及全部索引（`uq_agents_single_default` 部分唯一索引 WHERE `is_default=1`、`ix_agents_updated_at`、`uq_agent_bindings_unique`、`ix_agent_bindings_resource`、`uq_agent_prompt_versions`），down 依次 drop 三表；字段与类型逐字对齐 data-model §1–§3
- [x] T003 [P] 在 `backend/app/models/__init__.py` 追加 `AgentEntry` / `AgentBinding` / `AgentPromptVersion` 三个 ORM 类，字段/类型/注释与 [data-model.md](data-model.md) §1–§3 一致（沿用 `_utcnow` 惯例；`agent_id` 外键 ON DELETE CASCADE；不建指向 tools/skills/mcp_servers 的 DB 外键）
- [x] T004 [P] 生成 SQL 存档 `backend/sql/migrations/007_add_agents_tables.sql` 与迁移文件内容对应
- [x] T005 执行 `uv run alembic upgrade head` 验证迁移可应用、`uv run alembic downgrade -1` + 再 upgrade 验证可回滚（临时库或确认 app.db 可回滚后还原）

**Checkpoint**: 数据层就绪——三表可建可回滚，ORM 类与主定义一致。

---

## Phase 2: Foundational（阻塞前置）

- [x] T006 创建 `backend/app/services/agent_references.py`：`assert_not_referenced_by_agent(session, resource_type, resource_id) -> list[AgentOption]`——按 `(resource_type, resource_id)` join `agent_bindings` 反查引用 Agent（去重、按 id 排序，返回 `[{id, name}]`）；`raise ReferencedByAgentError(referenced_by)` 自定义异常携带引用者列表；枚举常量 `ResourceType`（tool/skill/mcp）在本模块定义唯一映射（资源表与名称/描述字段的取数规则见 contracts §数据结构 BindingItem）
- [x] T007 创建 `backend/app/schemas/agents.py`：按 [contracts/agents-api.md](contracts/agents-api.md) 实现全部 Pydantic Schema——`BindingItem`/`BindingOption`/`ModelOption`/`PromptVersionItem`/`AgentListItem`/`AgentDetail`/`AgentSaveRequest`（含校验：name 去空白 1–100、model_id 必填、max_rounds 1–100 默认 10、bindings 元素 `{resource_type, resource_id}` 枚举校验、重复绑定 422 语义在 service 判）/`AgentOption`/`DeleteResponse`（含 `cleared_default`）/`RequiresNewDefaultBody`/`ReferencedByAgentBody`/`BindingOptionsResponse`；常量 `MAX_ROUNDS_DEFAULT=10`/`MIN=1`/`MAX=100`
- [x] T008 创建 `backend/app/services/agent_service.py`：实现 `list_agents`（updated_at 倒序、含三类计数与 bindings_top 前 3 条 tool→skill→mcp/id 升序、总数）、`get_agent`（详情含全部版本升序 + 全部绑定含停用标记）、`save_agent`（新建/编辑统一入口：校验 model_id 存在；**新建**自动置默认（无任何 Agent 时）；显式 `is_default:true` 切换默认先取消旧默认；**版本规则**——新建插 v1，编辑时 payload.system_prompt ≠ 最新版本内容才插 max+1，绑定/名称/模型/轮数变化不影响版本；**绑定整体覆写**——删旧插新、resource 存在性与类型匹配校验、重复拒绝）、`delete_agent`（默认+还有其他+缺 `new_default_id` → `RequiresNewDefaultError` 附候选；`new_default_id` 非法 → `ValueError`；删最后一个默认 → 清默认返回 `cleared_default=True`；与置新默认同一事务）、`set_default`（幂等、自动取消旧默认）、`get_binding_options`（聚合 tools/skills/mcp 启用项 + models 全部项 + 编辑态 `selected` 回显）、`PROMPT_TEMPLATE` 常量（spec FR-009 六段模板原文）
- [x] T009 在 `backend/tests/conftest.py` 追加 Agent 测试共用 fixtures：`seed_model`（默认模型）、`seed_tools_skills_mcp`（若干启用/停用资源行）——不动既有 fixtures

**Checkpoint**: 契约与服务层就绪且未接线（无路由），引用检查模块可被三处删除链路复用。

---

## Phase 3: US1 + US2（P1，新建编排 + 列表详情）🎯 MVP

**Goal**: 从"新建 → 编排 → 保存 → 卡片列表 → 全屏详情查看"主链路端到端可用。
**Independent Test**: quickstart.md 场景 A/B——空状态、无模型引导、新建默认置默认、卡片信息项与 +N、详情三列与版本 v1。

### 测试任务（先写，确认失败）

- [x] T010 [P] [US1] 创建 `backend/tests/test_agents_api.py`：契约测试锁定 [contracts/agents-api.md](contracts/agents-api.md)——`GET /api/agents` 空表 `[]` 与倒序；`POST` 合法创建 201 且首个自动默认；`GET /{id}` 详情结构（prompt_versions 含 v1、bindings 含 enabled 标记）；422 分支（空名/无模型/max_rounds=0/负数/非整数/resource_type 非法/重复绑定/模型不存在）；`binding-options` 聚合（仅启用资源、selected 回显、无模型返回 `[]`）；名称/模型/绑定变化不增版本（FR-019 后端语义先于此处锁定）
- [x] T011 [P] [US2] 创建 `frontend/src/api/__tests__/agents.spec.ts` 与 `frontend/src/stores/__tests__/agents.spec.ts`：类型与请求封装对齐契约（路径、方法、payload 形状）；store 的 fetch/save/remove/setDefault/loadBindingOptions 动作与加载态（mock fetch）

### 实现任务

- [x] T012 [US1] 创建 `backend/app/api/agents.py`：按契约实现 7 个端点（列表/详情/新建/编辑/删除/设默认/binding-options）；异常映射——`AgentNotFound→404`、`RequiresNewDefaultError→409 {requires_new_default, candidates}`、`ReferencedByAgentError→409 {referenced_by_agents}`、校验失败走 Pydantic 422；在 `backend/app/main.py` 注册 router
- [x] T013 [US1] 跑通 T010 全部用例（`uv run pytest tests/test_agents_api.py`）并修复至全绿
- [x] T014 [P] [US1] 创建 `frontend/src/api/agents.ts`：TS 类型（AgentListItem/AgentDetail/AgentSaveRequest/BindingItem/BindingOption/ModelOption/PromptVersionItem/AgentOption/BindingOptionsResponse 及删除 409 响应体）与请求函数（list/get/create/update/remove/setDefault/getBindingOptions），复用 `request.ts` 封装
- [x] T015 [P] [US1] 创建 `frontend/src/stores/agents.ts`：Pinia store——列表 state、fetchAgents、bindingOptions 缓存、save/remove/setDefault 动作、加载/提交中标志
- [x] T016 [US2] 重写 `frontend/src/views/AgentsView.vue`：卡片列表（`a-card` 网格 + `a-empty` 空状态新建入口）；卡片三段——顶部（名称、说明、模型名称+标识、三类计数、默认 `a-tag`、更新时间）、中部绑定条目至多 3 条（tool→skill→mcp 顺序，超出 `+N`，N=total−3；停用绑定照常计数）、底部编辑/删除按钮；点卡片其他区域打开详情；删除走确认 modal，默认 Agent 且多 Agent 时进入"选新默认"流程（见 T019）；配色字号引用 tokens 变量
- [x] T017 [P] [US2] 创建 `frontend/src/components/agents/ResourceSelectCards.vue`：可复用能力卡片多选组件——props（options/selectedIds/disabled）、emit toggle；卡片展示名称+用途说明 + `a-checkbox`；`enabled:false` 项渲染"已停用，不可用"标记且不可勾选（仅绑定区使用该标记，候选项本就只含启用资源）
- [x] T018 [US1] 创建 `frontend/src/components/agents/AgentOrchestration.vue`：第二列编排区——模型卡片单选（名称+标识+默认标识；无模型时渲染引导卡"先添加模型" + 跳转 `/models`）；工具/Skills/MCP 三个 `ResourceSelectCards` 多选区；最大执行轮数 `a-input-number`（1–100，默认 10，字段旁说明"限制后续 Agent Loop 的执行轮数"）；校验失败信息落到字段旁
- [x] T019 [US1] 创建 `frontend/src/components/agents/AgentDetailDialog.vue`：全屏 `a-modal`（width 100%，无边距）三列 grid——第一列系统提示词 `a-textarea` 铺满高度、右上角版本下拉（切换查看/基于历史编辑）、默认模板预填（新建）；第二列 `AgentOrchestration`；第三列"预览与调试"占位卡（文案"本模块将在后续阶段开发"）；顶部基本信息（名称/说明/是否默认 switch）+ 发布按钮（提交整体保存）；校验：名称必填、模型必选、轮数 1–100；无模型保存引导；新建/编辑共用（mode prop）
- [x] T020 [US2] 手动验证 quickstart 场景 A/B 全部步骤；确认与既有页面视觉一致（字体、间距、卡片风格）

**Checkpoint**: MVP 达成——不依赖 US3+ 即可完整演示创建、浏览、详情；后端 pytest 与前端 Vitest 对应用例全绿。

---

## Phase 4: US3（P2，系统提示词版本管理）

**Goal**: 版本切换查看、基于历史版本编辑、仅内容变化递增版本号的完整前端表现。
**Independent Test**: quickstart.md 场景 C——改内容 v1→v2、仅改名版本不变、基于 v1 编辑产生 v3（内容不同）、历史版本可回看。

> 后端版本规则已在 T008/T010 落地并锁定；本阶段主要是前端版本选择器交互与端到端验证。

### 实现任务

- [x] T021 [US3] 修改 `frontend/src/components/agents/AgentDetailDialog.vue`：版本下拉渲染 `prompt_versions`（"v1 · 2026-09-11 10:00"格式）；切换版本 → textarea 载入该版本内容并提示"正在编辑历史版本，保存后将生成新版本"；保存后刷新详情重拉版本列表，当前选中指向最新版；补 Vitest 用例：版本列表渲染、切换载入内容、保存后版本刷新（mock store）
- [x] T022 [US3] 手动验证 quickstart 场景 C 全部步骤（含"内容相同保存不产生新版本"）

**Checkpoint**: US1–US3 全部可独立演示。

---

## Phase 5: US4（P2，默认 Agent 与删除流程）

**Goal**: 唯一默认不变式 + 三种删除分支（普通确认 / 默认先选新默认 / 最后一个清空回空状态）。
**Independent Test**: quickstart.md 场景 D——切默认互斥、删普通确认、删默认弹选新默认、删最后回空状态。

### 测试任务（先写，确认失败）

- [x] T023 [P] [US4] 在 `backend/tests/test_agents_api.py` 追加删除与默认用例：设默认幂等且旧默认取消；删普通 Agent 200；删默认缺 `new_default_id` → 409 `requires_new_default` + 候选列表；携带非法 `new_default_id` → 400；携带合法 `new_default_id` → 删除成功且新默认生效（同一事务）；删最后一个 → `cleared_default:true`；任意操作后 `COUNT(is_default=1) ≤ 1` 不变式断言

### 实现任务

- [x] T024 [US4] 跑通 T023 用例并修复至全绿（若 T008/T012 实现偏差在此收敛）
- [x] T025 [US4] 修改 `frontend/src/views/AgentsView.vue` + `frontend/src/stores/agents.ts`：默认切换入口（卡片或详情）调 setDefault 并刷新；删除流程三分支——普通 Agent `Modal.confirm`；默认 Agent 先发删除收 409 `requires_new_default` → 渲染候选选择 modal（列出 candidates）→ 选定后带 `new_default_id` 重发；删除最后一个成功且 `cleared_default` → 回空状态；补/改 Vitest 用例覆盖删除分支状态流转
- [x] T026 [US4] 手动验证 quickstart 场景 D 全部步骤

**Checkpoint**: 默认与删除一致性经后端不变式测试 + 前端三分支验证。

---

## Phase 6: US5（P2，已停用能力的绑定保持）— 可与 Phase 5 并行

**Goal**: 停用绑定保留 + "已停用，不可用"标记 + 计数含停用。
**Independent Test**: quickstart.md 场景 E——停用后绑定仍在且有标记、保留保存成功、计数含停用、恢复启用标记消失。

### 测试任务（先写，确认失败）

- [x] T027 [P] [US5] 在 `backend/tests/test_agents_api.py` 追加停用绑定用例：绑定后停用资源 → 详情中该绑定 `enabled:false` 仍在；binding-options 中该资源消失；不移除保存（bindings 不含它亦可/含它亦可）→ 绑定保留；资源恢复启用 → `enabled:true`；列表计数含停用绑定

### 实现任务

- [x] T028 [US5] 跑通 T027 用例并修复至全绿（核对 get_agent/get_binding_options/save_agent 对停用资源的三态处理与 research R6 一致：无快照、实时 join）
- [x] T029 [P] [US5] 修改 `frontend/src/components/agents/AgentDetailDialog.vue` 绑定区：`enabled:false` 的绑定项渲染"已停用，不可用"标记（不可勾选但可移除）；确认卡片计数与 +N 含停用绑定；手动验证 quickstart 场景 E

**Checkpoint**: 停用场景前后端表现一致，无自动清除路径。

---

## Phase 7: US6（P3，被引用资源的删除保护）— 可与 Phase 6 并行

**Goal**: 模型/Skills/MCP 删除链路服务端引用保护 + 人话提示含 Agent 名称。
**Independent Test**: quickstart.md 场景 F——三处删除被拒且提示 Agent 名、绕过前端直发同样被拒、移除引用后可删、默认模型先查引用。

### 测试任务（先写，确认失败）

- [x] T030 [P] [US6] 创建 `backend/tests/test_agent_references.py`：Agent 引用模型/Skill/MCP 后分别 DELETE 三类资源 → 409 且 `referenced_by_agents` 含正确 Agent 名；无引用资源删除成功；删除默认模型被引用 → 409（引用检查先于默认切换，FR-029 顺序断言）；移除绑定/删除 Agent 后删除成功；多 Agent 引用同一资源时列表去重完整
- [x] T031 [P] [US6] 在 `backend/tests/test_models_api.py`（或既有模型测试文件）追加回归用例：未被引用的默认模型删除仍走既有默认切换规则（引用保护不破坏 002 行为）

### 实现任务

- [x] T032 [US6] 接入三处删除链路——`backend/app/services/model_service.py` 的 `delete_model` 最前端（先于默认切换）、`backend/app/services/skill_service.py` 的 `delete_skill`（先于目录删除）、`backend/app/api/mcp.py` 删除分支（先于清理）调用 `agent_references.assert_not_referenced_by_agent`；API 层映射 `ReferencedByAgentError → 409 {detail 人话, referenced_by_agents}`；错误文案格式「<资源名>」正被 Agent「A」「B」使用，请先在对应 Agent 中移除绑定或更换模型后重试
- [x] T033 [US6] 修改三个前端管理视图的删除错误处理（`frontend/src/views/ModelsView.vue`、`SkillsView.vue`、`McpView.vue`）：409 时展示 detail 全文（含 Agent 名称），不阻断其他操作；手动验证 quickstart 场景 F

**Checkpoint**: 引用保护在服务端闭环，既有删除行为无回归。

---

## Phase 8: Polish & 交付门禁

- [x] T034 全量门禁（AGENTS.md §9）：`backend` 内 `uv run pytest` 全绿 + `uv run pyright` 无错误；`frontend` 内 `npm run build` 零错误 + `npx vitest run` 全绿；修复所有失败项
- [ ] T035 按 [quickstart.md](quickstart.md) 场景 A–G 完成人工端到端验证（含持久化场景 G：刷新 + 重启服务）并记录结果
- [ ] T036 运行 `/speckit-analyze` 跨文档一致性分析并处理发现项

---

## Dependencies & Execution Order

### Phase 依赖

- **Phase 1（Setup）**: 无前置，立即开始；T001 先行（读 AGENTS.md 是宪法硬性要求）
- **Phase 2（Foundational）**: 依赖 Phase 1（T006–T008 依赖 ORM 类与迁移）；T006/T007/T008/T009 可并行推进（不同文件）
- **Phase 3（US1+US2 MVP）**: 依赖 Phase 2；测试任务（T010/T011）先写并确认失败，实现后转绿
- **Phase 4–7（US3–US6）**: 均依赖 Phase 3 完成（版本/删除/停用/引用都以主链路为前置）；Phase 5/6/7 彼此独立可并行
- **Phase 8（Polish）**: 依赖全部故事完成

### Parallel Opportunities

- Phase 1 内：T003/T004 与 T002 并行（不同文件）
- Phase 2 内：T006/T007/T008/T009 四个新文件并行
- Phase 3 内：T010/T011（测试先行）并行；T014/T015/T017 并行；后端（T012/T013）与前端（T014–T017）两条线并行
- Phase 5/6/7 三个故事可由三人并行（测试任务 T023/T027/T030/T031 也可先行并行）

## Implementation Strategy

- **MVP first**: Phase 1–3 交付即演示价值（建 Agent、看卡片、进详情），US3+ 增量叠加
- **测试先行**: 每个 US 的测试任务先写先跑（失败→实现→转绿），契约测试是 SSOT 的执行面
- **单事务一致性**: 默认切换、删除+置新默认、绑定覆写全部收敛在 `agent_service` 单事务内，前端不做补偿逻辑
- **无快照原则**: 停用状态实时 join（research R6），避免快照漂移类缺陷
