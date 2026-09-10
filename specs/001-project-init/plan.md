# Implementation Plan: 项目初始化（第一阶段）

**Branch**: `001-project-init` | **Date**: 2026-09-10 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/001-project-init/spec.md`

## Summary

按 spec 建立真实可运行的 mini-workbuddy 工程骨架：前端以官方脚手架初始化 Vue 3 + TS + Vite + Router + Pinia + sass + Ant Design（Vitest 测试），实现 188px 侧栏 + 8 模块路由的工作台布局与统一占位页；后端在 `backend/` 以 uv 初始化 FastAPI + SQLAlchemy + Alembic（SQLite），提供 `/api/health` 契约端点验证整条链路；全局设计令牌（暖色配色/字体/字号）集中为 CSS 变量；补全 `AGENTS.md` 作为开发规范单一事实来源。全部技术决策见 [research.md](research.md)（D1–D13），数据约定见 [data-model.md](data-model.md)，接口契约见 [contracts/api-contract.md](contracts/api-contract.md)，验收步骤见 [quickstart.md](quickstart.md)。

## Technical Context

**Language/Version**: TypeScript（前端，Node.js ≥ 20）；Python 3.12（后端，uv 管理）

**Primary Dependencies**: 前端 Vue 3、Vue Router、Pinia、sass、ant-design-vue、@fontsource/dm-sans、@fontsource/outfit、@fontsource/fira-code、Vitest；后端 FastAPI、Pydantic（pydantic-settings）、SQLAlchemy、Alembic、uvicorn、pytest、httpx、pyright（dev）

**Storage**: SQLite（`backend/app.db`，`DATABASE_URL` 可覆盖；本阶段仅 Alembic 空基线，无业务表）

**Testing**: 后端 pytest（TestClient）；前端 Vitest + @vue/test-utils

**Target Platform**: 桌面浏览器（Chromium/WebKit/Gecko 当前版）；宽度 360px–1920px 可用，<900px 菜单收起为抽屉

**Project Type**: web-application（前后端分离：`frontend/` + `backend/`，开发期 Vite 代理 `/api`）

**Performance Goals**: 开发服务器首屏可交互 < 2s；`/api/health` 本地响应 < 50ms；`npm run build` 产物 gzip 后 < 500KB（本阶段无业务，仅为防止引入重依赖的护栏）

**Constraints**: 固定技术栈不可替换（宪法）；前端仅请求相对路径 `/api`；uv 强制工作流；无整页横向滚动；无蓝紫渐变/霓虹/大面积纯黑/高饱和荧光色；无 32px 以上标题；阴影仅弹窗浮层

**Scale/Scope**: 单用户本地工作台；8 个导航模块（本阶段全部为占位页）；1 个后端端点

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| # | 原则/约束 | 结论 | 依据 |
|---|-----------|------|------|
| I | Spec-First | ✅ 通过 | 本 plan 由 `specs/001-project-init/spec.md` 驱动；布局/导航/令牌范围均出自 FR-008~FR-018 |
| II | SSOT | ✅ 通过 | 开发规范主定义 → `AGENTS.md`；UI 令牌主定义 → `frontend/src/styles/tokens.scss`；API 契约主定义 → spec `contracts/` → Pydantic → 前端类型派生；本阶段无枚举/数据模型实体 |
| III | Contract-First | ✅ 通过 | `/api/health` 契约已在实现前定义（[contracts/api-contract.md](contracts/api-contract.md)）；前后端路径统一 `/api` 前缀，与 Vite 代理规则一致 |
| IV | Verify Before Ship | ✅ 通过 | [quickstart.md](quickstart.md) 定义全部验证场景与门禁命令（pytest/pyright/build/Vitest），交付前 MUST 全绿 |
| V | Simplicity | ✅ 通过 | 后端仅建有消费方的目录（api/core/schemas，见 research D4）；不预建 models/services；前端占位页复用统一组件；请求封装用原生 fetch 零新增依赖（research D7） |
| VI | Feedback Loop | ✅ 通过 | `AGENTS.md` 为约定回写目标；实现中发现规范问题先改 SSOT 再同步下游 |
| — | 固定技术栈 | ✅ 通过 | 前后端选型与宪法清单逐项一致；新增依赖仅字体自托管包（@fontsource，为满足 FR-016 字体要求的必要资源，非框架替换） |
| — | uv 工作流 | ✅ 通过 | `uv init` + `uv add` + `uv sync` + `uv run`；README 无 pip 步骤（research D13） |
| — | 数据库约束 | ✅ 通过 | 正式 engine/session + Alembic 基线；无 JSON 替代数据库 |
| — | 联调约束 | ✅ 通过 | 前端仅 `/api` 相对路径（`request.ts` 统一前缀），Vite 代理转发 |
| — | 目录约束 | ✅ 通过 | `frontend/src` 分层（D9）、`backend/app` 分层（D4）；不写入 `0user chat/` |
| — | UI 设计约束 | ✅ 通过 | 令牌集中（D8）、布局/字号/禁用项全部落入 FR-008~FR-018 与 quickstart V3/V5 |
| — | 质量门禁 | ✅ 通过（含 1 项修正） | ⚠️ 发现根目录 `pyrightconfig.json` 的 `pythonVersion: "3.10"` 与后端声明的 Python 3.12 不一致 — 按宪法 VI 回写修正为 `"3.12"`（已列入任务清单） |

**Post-Phase 1 复查**: data-model / contracts / quickstart 产出后逐项复核，未发现新增违规；无 [NEEDS CLARIFICATION] 遗留。

## Project Structure

### Documentation (this feature)

```text
specs/001-project-init/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md        # Phase 1 output (/speckit-plan command)
├── quickstart.md        # Phase 1 output (/speckit-plan command)
├── contracts/           # Phase 1 output (/speckit-plan command)
│   └── api-contract.md
└── tasks.md             # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
backend/
├── pyproject.toml         # uv 管理（含 uv.lock）
├── app/
│   ├── main.py            # FastAPI 入口：挂载 /api 路由
│   ├── api/
│   │   └── health.py      # GET /api/health（唯一端点）
│   ├── core/
│   │   ├── config.py      # Pydantic Settings（DATABASE_URL 等）
│   │   └── db.py          # SQLAlchemy engine/session + Base
│   └── schemas/
│       └── health.py      # HealthResponse（契约实现）
├── migrations/            # Alembic 环境（env.py 指向 Base.metadata）
│   └── versions/          # 空基线迁移
└── tests/
    └── test_health.py     # 健康检查 + 数据库探测测试

frontend/
├── vite.config.ts         # /api 代理 → 127.0.0.1:8000
├── src/
│   ├── api/
│   │   ├── request.ts     # fetch 封装（统一 /api 前缀与错误语义）
│   │   └── health.ts      # 契约派生类型 + 调用
│   ├── components/
│   │   ├── AppSidebar.vue # 8 项菜单（含抽屉模式）
│   │   └── PlaceholderCard.vue # 统一占位卡片
│   ├── layouts/
│   │   └── WorkbenchLayout.vue # 188px 侧栏 + 内容区 + <900px 抽屉
│   ├── router/
│   │   └── index.ts       # 嵌套路由：/ → /chat 重定向 + 8 模块 + NotFound 兜底
│   ├── stores/
│   │   └── ui.ts          # Pinia：菜单收起状态
│   ├── styles/
│   │   ├── tokens.scss    # 设计令牌主定义（CSS 变量：配色/字体）
│   │   └── main.scss      # reset + 基础样式（字号/行高规格落点）
│   ├── views/             # 8 个模块页（ChatView + 7 占位）+ NotFoundView
│   ├── App.vue            # ConfigProvider 主题（主色 #c2703a）
│   └── main.ts
└── [tests 随脚手架]        # router / PlaceholderCard 测试

AGENTS.md                  # 开发规范 SSOT（本阶段补全）
README.md                  # onboarding：环境要求与快速启动
sql/                       # SQL 存档目录（本阶段空，保留）
```

**Structure Decision**: 前后端分离单仓库（spec 既定 `frontend/` + `backend/`）。前端在脚手架标准结构上按 FR-006 增设 `api/`、`layouts/`、`styles/`（research D9）；后端采用分层最小集 `api/ core/ schemas/`，业务目录（models/services）待首个业务模块按需建立（research D4）。

## Complexity Tracking

无宪法违规需要豁免（Constitution Check 全部通过），本节不适用。
