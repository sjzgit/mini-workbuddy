# Tasks: 项目初始化（第一阶段）

**Input**: Design documents from `/specs/001-project-init/`

**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/

**Tests**: 测试任务已包含 —— spec 的 SC-003 明确要求 pytest / Vitest / build / pyright 全绿，测试为本阶段验收的一部分。

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

- **Web app**: `backend/`、`frontend/`（本仓库实际结构，见 plan.md Project Structure）

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and basic structure

- [x] T001 在 `backend/` 用 `uv init --python 3.12` 初始化项目，随后 `uv add fastapi "uvicorn[standard]" sqlalchemy pydantic-settings alembic` 与 `uv add --dev pytest httpx`；确认 `pyproject.toml` 声明 Python 3.12 与依赖、生成 `uv.lock`（research D13）
- [x] T002 在 `frontend/` 用 `npm create vue@latest` 初始化（TypeScript + Router + Pinia + Sass + Vitest），`npm install ant-design-vue @fontsource/dm-sans @fontsource/outfit @fontsource/fira-code`；确认 dev 启动正常（research D1/D2）

**Checkpoint**: 两端依赖可安装、脚手架可启动

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [x] T003 [P] 后端配置层：创建 `backend/app/core/config.py`（pydantic-settings，`DATABASE_URL` 默认 `sqlite:///./app.db`）（research D6）
- [x] T004 [P] 后端数据层：创建 `backend/app/core/db.py`（SQLAlchemy engine + sessionmaker + 声明式 Base，`connect_args={"check_same_thread": False}` 以兼容 SQLite）
- [x] T005 修正根目录 `pyrightconfig.json` 的 `pythonVersion` 为 `"3.12"`（与后端声明一致；宪法 VI 回写，见 plan.md Constitution Check 末行）
- [x] T006 Alembic：`uv run alembic init migrations` 到 `backend/migrations/`；`env.py` 接入 `core/db.py` 的 Base.metadata 与 `config.py` 的 DATABASE_URL；生成空基线迁移并验证 `uv run alembic upgrade head` 可重复执行（research D5）
- [x] T007 [P] 前端设计令牌：创建 `frontend/src/styles/tokens.scss`（spec FR-015/FR-016 全部 CSS 变量：配色 20 项 + 字体 3 项）与 `frontend/src/styles/main.scss`（reset、字号/行高规格 12.5px 正文/1.5 行高等落点、卡片基础样式）；`main.ts` 按 tokens → 字体 → main.scss → antd 顺序引入（research D8）
- [x] T008 [P] 前端请求封装：创建 `frontend/src/api/request.ts`（原生 fetch，统一 `/api` 前缀、JSON 解析、错误语义）；`vite.config.ts` 配置 `server.proxy` `/api → http://127.0.0.1:8000`（research D7）

**Checkpoint**: Foundation ready - user story implementation can now begin in parallel

---

## Phase 3: User Story 1 - 搭建可运行的前后端工程骨架 (Priority: P1) 🎯 MVP

**Goal**: 后端服务 + 数据库 + 健康检查端点 + 前端代理链路全部真实可用

**Independent Test**: 按 quickstart.md V1 执行 `curl /api/health` 返回 `{"status":"ok"}`；`uv run alembic upgrade head` 幂等成功

### Tests for User Story 1

> **NOTE**: Write these tests FIRST, ensure they FAIL before implementation

- [x] T009 [P] [US1] 创建 `backend/tests/test_health.py`：① GET `/api/health` 返回 200 与 `{"status":"ok"}`（对照 contracts/api-contract.md）；② 通过注入的 session 执行 `SELECT 1` 验证数据库连接；先运行确认失败
- [x] T010 [P] [US1] 创建 `backend/tests/conftest.py`：测试用独立 SQLite（内存或 tmp 文件）覆盖 DATABASE_URL 的夹具

### Implementation for User Story 1

- [x] T011 [P] [US1] 创建 `backend/app/schemas/health.py`：`HealthResponse`（status 字面量类型 + 可选 detail），与契约逐字段一致
- [x] T012 [P] [US1] 创建 `backend/app/api/health.py`：`GET /api/health`，经依赖注入 session 执行 `SELECT 1`；成功 200，数据库异常 503 + `{"status":"unhealthy","detail":"database unavailable"}`（不暴露内部细节）
- [x] T013 [US1] 创建 `backend/app/main.py`：FastAPI 应用入口，挂载 `/api` 前缀路由（依赖 T011、T012）
- [x] T014 [US1] 创建 `frontend/src/api/health.ts`：从契约派生 `HealthResponse` 类型与 `getHealth()` 调用（依赖 T008）
- [x] T015 [US1] 验证端到端链路：启动后端与前端 dev server，浏览器/开发者工具确认经 Vite 代理请求 `/api/health` 成功（quickstart V1 + 步骤 3-4）

**Checkpoint**: At this point, User Story 1 should be fully functional and testable independently

---

## Phase 4: User Story 2 - 统一的应用布局与模块导航 (Priority: P1)

**Goal**: 188px 侧栏 + 8 模块路由 + 默认聊天页 + 刷新不白屏 + <900px 抽屉

**Independent Test**: 按 quickstart.md V2/V3 逐一访问 8 个地址并刷新，全部正常渲染（SC-002/SC-005）

### Tests for User Story 2

- [x] T016 [P] [US2] 前端路由测试（如 `frontend/src/router/__tests__/router.spec.ts`）：`/` 重定向到 `/chat`；8 个路径均解析到对应视图；`/:pathMatch(.*)*` 命中 NotFound（先确认失败）
- [x] T017 [P] [US2] `frontend/src/stores/ui.ts` 的 Pinia store 测试：菜单收起/展开状态迁移

### Implementation for User Story 2

- [x] T018 [US2] 创建 `frontend/src/stores/ui.ts`（Pinia：`sidebarCollapsed` 状态与切换 action）（依赖 T017 意图，实际依赖仅 T002 脚手架）
- [x] T019 [US2] 创建 `frontend/src/router/index.ts`：嵌套路由（WorkbenchLayout 为父），`/`→`/chat` 重定向，8 个模块路径 `/chat /agents /models /tools /mcp /skills /runs /evaluations`，`/:pathMatch(.*)*` → NotFoundView（research D10；依赖 T018、T021、T022）
- [x] T020 [P] [US2] 创建 `frontend/src/components/AppSidebar.vue`：8 项菜单（顺序与文案严格对照 spec FR-010），项高约 32px、图标/文字/选中背景对齐、选中态用 `--bg-active`；顶部产品名 mini-workbuddy + 圆形字母标记（Outfit `--font-display`）；<900px 时由抽屉包裹（依赖 T007、T018）
- [x] T021 [US2] 创建 `frontend/src/layouts/WorkbenchLayout.vue`：整页高度、无横向滚动；桌面侧栏固定 188px + 右侧内容区自适应；<900px 侧栏转抽屉（遮罩点击/路由跳转自动关闭，主内容不被遮挡）；监听 resize 在 900px 断点切换（依赖 T020）
- [x] T022 [P] [US2] 创建 `frontend/src/views/NotFoundView.vue` 兜底页（依赖 T007）
- [x] T023 [US2] 更新 `frontend/src/App.vue`：ConfigProvider 主题 token 将 antd 主色对齐 `--accent: #c2703a`；挂载 router（依赖 T019、T021）

**Checkpoint**: At this point, User Stories 1 AND 2 should both work independently

---

## Phase 5: User Story 3 - 诚实的占位页面 (Priority: P2)

**Goal**: 8 个模块页统一结构：标题 + 一句说明 + 占位卡片（无虚构内容）

**Independent Test**: 按 quickstart.md V2.4 逐一检查 8 页文案；SC-007 占位页数量 = 8

### Implementation for User Story 3

- [x] T024 [P] [US3] 创建 `frontend/src/components/PlaceholderCard.vue`：接收 `title` / `description` / `current-stage` props；渲染"本模块将在后续阶段开发"与当前阶段先完成什么；白底 + `--border` 浅边框卡片，无阴影（依赖 T007）
- [x] T025 [P] [US3] 创建 8 个模块视图 `frontend/src/views/`：`ChatView.vue`（占位，注明本模块将在后续阶段开发、当前先完成工程初始化）与 `AgentsView.vue`、`ModelsView.vue`、`ToolsView.vue`、`McpView.vue`、`SkillsView.vue`、`RunsView.vue`、`EvaluationsView.vue` —— 每页顶部标题（18px/650）+ 一句简短说明（`--text-secondary`）+ PlaceholderCard（依赖 T024）

### Tests for User Story 3

- [x] T026 [P] [US3] `PlaceholderCard` 渲染测试：标题/说明/占位文案/当前阶段文案均渲染；不含虚构统计数字、对话、列表结构（先确认失败）

**Checkpoint**: All user stories should now be independently functional

---

## Phase 6: User Story 4 - 统一视觉设计令牌 (Priority: P2)

**Goal**: 配色/字体/字号全站统一引用变量，antd 主题同源，字体可回退

**Independent Test**: quickstart.md V3/V4/V5；SC-004/SC-005 抽查全过

### Implementation for User Story 4

- [x] T027 [US4] 视觉走查与修正：逐页核对颜色仅引用 `tokens.scss` 变量（无散落相近色硬编码）、字号/字重符合 FR-017 规格、无 32px+ 标题、无蓝紫渐变/霓虹/大面积纯黑/高饱和荧光色、阴影仅弹窗浮层（依赖 T007、T019-T025 全部完成）
- [x] T028 [US4] 字体回退验证：确认 `@fontsource` 引入带 `font-display: swap`；屏蔽网络字体资源后页面回退系统字体仍可用（quickstart V4）
- [x] T029 [US4] 响应式验证：360px–1920px 拖动无整页横向滚动；<900px 抽屉可用且 8 入口可达、主内容不被遮挡（quickstart V3；依赖 T021）

**Checkpoint**: 视觉与响应式全站达标

---

## Phase 7: User Story 5 - 开发规范单一事实来源 (Priority: P3)

**Goal**: `AGENTS.md` 成为开发约定 SSOT，README 承担 onboarding

**Independent Test**: 新开发者仅凭 AGENTS.md + README 完成环境搭建、启动与修改后检查（spec US5 场景 1）

### Implementation for User Story 5

- [x] T030 [P] [US5] 补全根目录 `AGENTS.md`：项目名称、固定技术栈、前后端目录、常用启动与测试命令（uv 强制规则、Alembic 经 `uv run`）、数据库迁移方式、配色与字号入口（指向 `frontend/src/styles/tokens.scss`）、每次修改后需运行的前后端检查清单、前后端编码规范（Composition API `<script setup>`、Pinia 状态、分层层级等）（对照 FR-019 逐项；research D12）
- [x] T031 [P] [US5] 补全根目录 `README.md`：项目简介、环境要求（Node.js ≥20 / uv / Python 3.12）、快速启动步骤（uv sync → alembic upgrade head → 双端启动）、目录一览；全程无 pip 步骤（research D12）

**Checkpoint**: 文档 SSOT 就位

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Improvements that affect multiple user stories

- [x] T032 工程整洁检查：无空文件/空目录（后端未预建 models/services 等），占位页数量 = 8，`pyproject.toml` 与 `uv.lock` 一致（SC-007/FR-007）
- [x] T033 质量门禁全绿：`uv run pytest`、`uv run pyright`（backend 内）、`npm run build`、Vitest（frontend 内）全部通过（SC-003）
- [x] T034 按 `specs/001-project-init/quickstart.md` 全流程走查一遍（V1–V5 + 门禁 + 整洁检查），确认 SC-001~SC-007 全部满足
- [x] T035 [P] 代码清理：移除脚手架示例组件/演示代码（HelloWorld 等），确保无残留未引用文件

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: T001 与 T002 相互独立，可并行
- **Foundational (Phase 2)**: T003/T004/T007/T008 可并行；T005 独立；T006 依赖 T003+T004 —— BLOCKS all user stories
- **User Stories (Phase 3+)**: 均依赖 Phase 2 完成
  - US1（Phase 3）与 US2（Phase 4）可并行推进（后端/前端不同文件）；US1 的 T014/T015 依赖 T008
  - US3（Phase 5）依赖 T019 存在路由（但可先做组件后接入）
  - US4（Phase 6）依赖 US2+US3 页面全部就位（走查性质）
  - US5（Phase 7）与 US2/US3 可并行（不同文件）
- **Polish (Phase 8)**: 依赖全部用户故事完成

### User Story Dependencies

- **US1 (P1)**: T009-T010 测试先行 → T011/T012 并行 → T013 汇合 → T014/T015 链路验证
- **US2 (P1)**: T016/T017 测试先行 → T018 store → T020 侧栏（可与 T022 并行）→ T019 路由（依赖视图文件建立）→ T021 布局 → T023 App 汇合。注意 T019 声明的视图在 T025 创建，可先建 8 个空壳视图文件占位再填内容，或调整执行顺序为 T024→T025→T019
- **US3 (P2)**: T024 组件 → T025 八页接入 → T026 测试
- **US4 (P2)**: 纯走查修正，最后执行
- **US5 (P3)**: 独立文档任务，任意时点可做（建议在命令定稿后、Phase 8 前）

### Within Each User Story

- Tests (if included) MUST be written and FAIL before implementation
- Schema/contract before endpoint（宪法 III）
- 组件/工具函数 before 页面接入
- Story complete before moving to next priority

### Parallel Opportunities

- T001 ∥ T002；T003 ∥ T004 ∥ T007 ∥ T008 ∥ T005
- T009 ∥ T010；T011 ∥ T012；T016 ∥ T017；T020 ∥ T022
- T024 ∥ T025 内部八页互不依赖；T030 ∥ T031
- 前端 US2 与后端 US1 可由两端并行推进

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup（T001、T002）
2. Complete Phase 2: Foundational（T003-T008）
3. Complete Phase 3: User Story 1（后端骨架 + 健康检查 + 代理链路）
4. **STOP and VALIDATE**: quickstart V1 + pytest 全绿 —— 工程骨架 MVP 成立
5. 继续.US2（布局导航）→ US3（占位页）→ US4（视觉走查）→ US5（文档）→ Phase 8

### Incremental Delivery

每完成一个 Story 即可独立验收（quickstart 对应小节），前后端可分开交付演示。

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- 测试先行：T009/T010/T016/T017/T026 均要求先失败后实现
- 宪法约束提醒：不写入 `0user chat/`；不用 pip；不硬编码后端绝对地址（`request.ts` 与 `vite.config.ts` 中的代理 target 除外 —— target 属开发代理配置而非业务请求代码）
- Commit after each task or logical group（仓库启用 git 后适用）
- Stop at any checkpoint to validate story independently
