# Research: 项目初始化（第一阶段）

**Feature**: 001-project-init | **Date**: 2026-09-10 | **Status**: Complete

本阶段无外部未知依赖，所有决策均为工程初始化范围内的技术选型。以下决策依据 spec（FR-001~FR-019）、宪法约束与当前生态稳定实践作出。

## D1: 前端工程初始化方式

**Decision**: 使用 `npm create vue@latest`（官方脚手架）初始化 `frontend/`，交互选择 TypeScript + Router + Pinia + Sass；随后 `npm install ant-design-vue`，测试运行器选 Vitest。

**Rationale**: 官方脚手架生成的目录与 `frontend/src` 分层约定天然吻合（`views/`、`router/`、`stores/`、`assets/`），且 Vitest 为脚手架内建选项，避免手工拼装配置。

**Alternatives considered**:
- 手工从零搭建 Vite 配置 — 灵活但本阶段无特殊需求，徒增工作量
- 使用 Nuxt — 被宪法明令禁止

## D2: 网络字体引入方式（DM Sans / Outfit / Fira Code）

**Decision**: 通过 npm 引入 `@fontsource/dm-sans`、`@fontsource/outfit`、`@fontsource/fira-code`，在全局样式中 `@import` 对应字重，配合 `font-display: swap` 与 CSS 变量中的系统字体回退链。

**Rationale**: 自托管（打包进构建产物）不依赖外部 CDN，离线/弱网环境可用，与"字体不可用时回退系统字体"的 FR-016 要求一致；`@fontsource` 是字体自托管的事实标准方案。

**Alternatives considered**:
- Google Fonts CDN `<link>` — 引入外部依赖，离线不可用，国内网络不稳定
- 不引入字体文件只用系统字体 — 不满足 spec 的字体优先级要求

## D3: <900px 菜单收起方案（窄栏 vs 抽屉）

**Decision**: 采用**抽屉（Drawer）**方案：`<900px` 时侧栏隐藏，由悬浮按钮（或 ant-design-vue 的 Drawer 组件）呼出，遮罩层点击/路由跳转后自动关闭。

**Rationale**: 360px 级窄屏下 188px 窄栏仍会挤占过半内容区，抽屉可完整保留 188px 菜单布局与全部 8 项入口；ant-design-vue 自带 Drawer 组件，实现成本最低且交互稳定（spec 允许二选一）。

**Alternatives considered**:
- 窄栏（仅图标 48–64px） — 在 360px 宽度下内容区过窄；图标模式需维护两套菜单布局

## D4: 后端分层结构与最小入口

**Decision**: `backend/app/` 下建立分层目录：

```text
backend/app/
├── main.py            # FastAPI 应用入口（挂载路由、注册 /api 前缀）
├── api/               # 路由层（本阶段仅 health 路由）
├── core/              # 配置（数据库连接、应用配置）
└── schemas/           # Pydantic 数据校验（本阶段仅 HealthResponse）
```

本阶段不创建 `models/`（无业务表）、`services/`（无业务逻辑）、`repositories/`（无数据访问）目录 —— 遵循宪法 V（简洁务实）"不提前搭建没有消费方的目录"。

**Rationale**: spec FR-006 要求"应用入口、路由、业务逻辑、数据访问和数据校验各自放在含义明确的目录下"，但 FR-007 同时禁止空目录；故只建当前有内容的目录，后续阶段按需增加。

**Alternatives considered**:
- 一次建全 `models/services/repositories` 空目录并放 `.gitkeep` — 违反 FR-007 与宪法 V
- 全部塞进 `main.py` — 违反 FR-006 分层要求

## D5: SQLite 连接与 Alembic 基线

**Decision**:
- 数据库文件放 `backend/app.db`（SQLite，开发期单文件；`.gitignore` 已忽略 `*.db`）
- SQLAlchemy engine/session 通过 `backend/app/core/db.py` 集中定义，`sessionmaker` 以 FastAPI 依赖注入方式供后续路由使用
- `uv run alembic init migrations` 初始化迁移环境到 `backend/migrations/`，`env.py` 改为读取应用的 SQLAlchemy Base metadata 与数据库 URL，生成一条空基线迁移（`alembic revision --autogenerate` 或手写空 upgrade）

**Rationale**: "正式的数据库连接 + 迁移可重复执行"（FR-004、SC-006）的最小完整实现；空基线让后续功能建表时始终走 Alembic 流程，从一开始就确立迁移纪律。

**Alternatives considered**:
- 用 `sqlalchemy.create_engine` 每处临时创建 — 无会话管理，违反"正式连接"要求
- 延后引入 Alembic 到第一个业务表时 — 违反 FR-004 本阶段须就绪的要求

## D6: 数据库 URL 的配置管理

**Decision**: `backend/app/core/config.py` 用 Pydantic `BaseSettings` 管理配置（`DATABASE_URL` 默认 `sqlite:///./app.db`），后续所有可配置项统一走此处。

**Rationale**: 集中配置、类型校验、带默认值，是 FastAPI 生态标准做法；避免散落的硬编码 URL。

**Alternatives considered**:
- 直接在代码里写字符串常量 — 后续测试/多环境切换困难
- 用 `.env` 必填（无默认值） — 本阶段无环境差异需求，增加启动摩擦

## D7: 前端请求封装与 /api 代理

**Decision**:
- `frontend/src/api/` 下建轻量 `request.ts` 封装（基于**原生 fetch**，统一 `/api` 前缀、JSON 解析与错误语义），本阶段仅有 `health.ts` 一个调用作为模式示范
- `vite.config.ts` 配置 `server.proxy`：`'/api': { target: 'http://127.0.0.1:8000', changeOrigin: true }`

**Rationale**: 原生 fetch 零新增依赖 —— axios 不在宪法固定技术栈清单内，本阶段无拦截器/取消等强需求（YAGNI，宪法 V）；`request.ts` 统一前缀与错误语义满足 FR-005、FR-006，后续如确需能力再评估扩展。

**Alternatives considered**:
- axios — 生态常用，但属栈外新增依赖，当前无不可替代需求
- 不做封装，组件里直接调用 — 违反 FR-006 请求封装分层要求

## D8: 全局样式与设计令牌组织

**Decision**:
- `frontend/src/styles/` 目录：`tokens.scss`（集中定义全部 CSS 变量：配色 + 字体 + 字号规范注释）→ `main.scss`（reset/基础样式，引用 tokens）
- `main.ts` 中按 `tokens → 字体 → main.scss → Ant Design` 顺序引入
- ant-design-vue 主题通过 ConfigProvider 的 `theme.token` 将主色对齐 `--accent: #c2703a`，避免组件库默认蓝与暖色系冲突

**Rationale**: 单一令牌文件即宪法要求的"UI 设计令牌主定义"，所有页面只引用变量；ConfigProvider 定制让 antd 组件（按钮、选中态）也吃同一主色，避免双色系。

**Alternatives considered**:
- 变量分散在各组件 `<style>` 内 — 违反 SSOT 与 FR-015
- 完全覆盖 antd 样式（弃用 ConfigProvider） — 工作量大且升级脆弱

## D9: 前端目录结构

**Decision**:

```text
frontend/src/
├── api/           # 请求封装 + 接口模块（request.ts、health.ts）
├── assets/        # 静态资源（字体经由 fontsource 包，不落此处）
├── components/    # 通用组件（本阶段：AppSidebar 菜单/布局壳相关组件）
├── layouts/       # 布局（WorkbenchLayout.vue：侧栏 + 内容区）
├── router/        # 路由（index.ts，8 个模块路由）
├── stores/        # Pinia（本阶段：ui.ts 管理菜单展开/收起状态）
├── styles/        # tokens.scss / main.scss
├── views/         # 页面（ChatView.vue + 7 个占位页 + NotFoundView.vue）
└── main.ts
```

**Rationale**: 与 spec FR-006"页面、路由、状态、请求封装、通用组件和样式分开放置"一一对应；`layouts/` 是 Vue Router + 脚手架生态的惯用位置。

**Alternatives considered**: 将布局并入 `App.vue` — 可行但布局随路由切换/登录态出现时会受限，且不符合"分目录放置"精神。

## D10: 路由与占位页设计

**Decision**:
- 8 个模块路由：`/chat`（默认，redirect `/` → `/chat`）、`/agents`、`/models`、`/tools`、`/mcp`、`/skills`、`/runs`、`/evaluations`
- 嵌套路由：`WorkbenchLayout` 作为父路由组件，8 个页面为子路由 —— 保证刷新任意地址布局与页面同时渲染、不白屏
- 每个占位页复用统一的 `PlaceholderCard` 组件（页面标题 + 简短说明 + "本模块将在后续阶段开发" + 当前阶段先完成什么）
- 兜底路由 `/:pathMatch(.*)*` → NotFoundView

**Rationale**: 独立地址（FR-011）+ 刷新不白屏（SC-002）由 history 模式 + 嵌套路由天然满足；统一占位组件避免 8 份重复文案，也保证"占位页面数量与模块数量一致"（SC-007）。

**Alternatives considered**: 8 个页面共用 1 个动态路由 `/(:module)` — 地址不语义化，且难以做每个模块的独立标题/说明配置。

## D11: 测试策略（本阶段）

**Decision**:
- 后端 pytest：`backend/tests/test_health.py`（`/api/health` 返回 200 与预期字段）；数据库夹具验证 engine/session 可用
- 前端 Vitest：路由配置测试（8 个路径解析正确、默认重定向）、`PlaceholderCard` 渲染测试（标题/说明/占位文案存在）

**Rationale**: 用最小测试集验证骨架的真实性（SC-003 要求测试全绿）；路由测试直接锚定 SC-002 的 8 地址可达要求。

**Alternatives considered**: 引入 E2E（Playwright 等） — 本阶段无交互流程，超出范围（宪法 V：YAGNI）。

## D12: AGENTS.md 与 README 职责划分

**Decision**:
- `AGENTS.md`：开发规范单一事实来源 —— 项目名称、固定技术栈、前后端目录、常用命令（含 uv 强制规则、迁移命令）、配色与字号入口（指向 `frontend/src/styles/tokens.scss`）、每次修改后的检查清单、前后端编码规范
- `README.md`：面向"第一次接触仓库的人"—— 项目简介、环境要求（Node.js ≥20、uv、Python 3.12）、快速启动步骤（安装→迁移→启动前后端）、目录一览

**Rationale**: spec FR-019 要求约定集中在 AGENTS.md 且"不散落"；README 承担 onboarding，两者引用而非复制（宪法 II SSOT）。

**Alternatives considered**: 两文件内容互相复制 — 违反 SSOT，后续必然漂移。

## D13: uv 初始化细节

**Decision**: 在 `backend/` 执行 `uv init --python 3.12`（生成 `pyproject.toml`），随后 `uv add fastapi uvicorn[standard] sqlalchemy pydantic-settings alembic`、`uv add --dev pytest httpx`；`.python-version` 文件由 uv 维护。

**Rationale**: `pydantic-settings` 支撑 D6 的配置管理；`httpx` 是 FastAPI `TestClient` 的依赖；全部通过 `uv add` 落实 FR-003。

**Alternatives considered**: 手写 `pyproject.toml` 再 `uv sync` — 可行但 `uv add` 自动维护 lock 与版本解析，更符合工作流要求。
