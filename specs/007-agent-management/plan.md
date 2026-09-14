# Implementation Plan: Agent 管理（第七阶段）

**Branch**: `007-agent-management` | **Date**: 2026-09-11 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/007-agent-management/spec.md`

## Summary

实现 Agent 管理配置层：Agent = 模型 + 系统提示词 + 工具/Skills/MCP 绑定 + 最大执行轮数的组合配置。后端新增 `agents` / `agent_bindings` / `agent_prompt_versions` 三张表与 `/api/agents` CRUD 契约，并在模型/Skills/MCP 删除链路上增加服务端引用保护；前端将 `AgentsView.vue` 从占位页升级为卡片列表 + 全屏 dialog 详情（三列：系统提示词（含版本）/ Agent 编排 / 预览与调试占位）。本阶段不实现 Agent Loop、运行记录、历史会话与预览调试交互。

## Technical Context

**Language/Version**: Python 3.12（后端，pyproject.toml 为准）；Node + TypeScript 5.x（前端，Vue 3）

**Primary Dependencies**: 后端 FastAPI + Pydantic v2 + SQLAlchemy 2.x + Alembic；前端 Vue 3（`<script setup>`）+ Vue Router + Pinia + ant-design-vue + sass

**Storage**: SQLite（`backend/app.db`，唯一数据库，禁止平面文件）

**Testing**: 后端 pytest（+ httpx TestClient，`uv run pytest`）；前端 Vitest + @vue/test-utils

**Target Platform**: 本地工作台（Windows），桌面浏览器

**Performance Goals**: 常规 CRUD，无特殊性能目标；列表与详情接口同步返回

**Constraints**: 至多一个默认 Agent（数据库层部分唯一索引保证）；提示词长度不限（TEXT 大字段）；删除保护必须在服务端执行

**Scale/Scope**: 单用户本地工作台；Agent 数量预期数十级；1 个列表页 + 1 个全屏 dialog + 3 张新表 + 1 个 Alembic 迁移 + 3 处删除保护接入

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 原则 | 状态 | 说明 |
|------|------|------|
| I. Spec-First | ✅ | spec.md 已产出并通过质量检查；本 plan 先于编码 |
| II. SSOT | ✅ | 数据模型主定义 = `data-model.md` → `backend/app/models/`；API 契约主定义 = `contracts/agents-api.md` → `schemas/agents.py` → 前端 `api/agents.ts`；开发约定沿用 AGENTS.md |
| III. Contract-First | ✅ | `contracts/agents-api.md`（含枚举常量主定义）先行，Schema 与 TS 类型从契约派生 |
| IV. Verify Before Ship | ✅ | quickstart.md 定义验收路径；交付前跑 `uv run pytest` + `npm run build` + Vitest |
| V. Simplicity | ✅ | 不预建 Agent Loop / 运行记录 / 会话表；预览与调试只留占位；绑定用一张 `agent_bindings` 通表而非三张重复表 |
| VI. Feedback Loop | ✅ | 发现偏差回写 data-model / contracts 后再改代码 |
| 固定技术栈 | ✅ | 无新增框架依赖 |
| uv 工作流 | ✅ | 无新增后端依赖；命令一律 `uv run` |
| 数据库约束 | ✅ | 新表经 Alembic 迁移落地，SQL 存档入 `sql/migrations/` |
| 前后端联调 | ✅ | 前端仅请求相对路径 `/api/agents`，Vite 代理 |
| 目录结构 | ✅ | 后端 api/services/schemas 分层；前端 view/store/api 分目录 |
| 质量门禁 | ✅ | Composition API + Pinia store + 设计令牌变量 |

**结论**：无违规项，无需 Complexity Tracking。

## Project Structure

### Documentation (this feature)

```text
specs/007-agent-management/
├── plan.md              # 本文件
├── research.md          # Phase 0 产出
├── data-model.md        # Phase 1 产出（数据模型主定义）
├── quickstart.md        # Phase 1 产出（验收指南）
├── contracts/
│   └── agents-api.md    # Phase 1 产出（API 契约与常量主定义）
└── tasks.md             # Phase 2 产出（/speckit-tasks 生成）
```

### Source Code (repository root)

```text
backend/
├── migrations/versions/
│   └── <rev>_add_agents_tables.py        # agents / agent_bindings / agent_prompt_versions
├── app/
│   ├── models/__init__.py                # + AgentEntry / AgentBinding / AgentPromptVersion
│   ├── schemas/agents.py                 # 新增：Pydantic 契约实现
│   ├── services/agent_service.py         # 新增：CRUD、版本、默认切换、删除流程
│   ├── services/agent_references.py      # 新增：引用检查（供 models/skills/mcp 删除链路复用）
│   ├── api/agents.py                     # 新增：/api/agents 路由
│   ├── api/models.py                     # 修改：删除前接入引用检查
│   ├── api/skills.py                     # 修改：删除前接入引用检查
│   ├── api/mcp.py                        # 修改：删除前接入引用检查
│   └── main.py                           # 修改：注册 agents 路由
├── sql/migrations/                       # 对应 SQL 存档
└── tests/
    ├── test_agents_api.py                # 契约测试
    └── test_agent_references.py          # 删除保护测试

frontend/src/
├── api/agents.ts                         # 新增：类型 + 请求封装（与契约对齐）
├── stores/agents.ts                      # 新增：Pinia store
├── components/agents/                    # 新增：AgentDetailDialog 及子组件
│   ├── AgentDetailDialog.vue             # 全屏 dialog（三列布局）
│   ├── AgentOrchestration.vue            # 第二列：模型/工具/Skills/MCP/轮数
│   └── ResourceSelectCards.vue           # 能力卡片多选（复用于三类资源）
├── views/AgentsView.vue                  # 重写：卡片列表 + 空状态 + 删除/默认流程
└── (styles/)                             # 沿用 tokens.scss 设计令牌，不新增独立色值
```

**Structure Decision**: 沿用既有 web 前后端结构（Option 2），后端保持 api/services/models/schemas 分层，前端保持 views/components/stores/api 分目录；绑定采用单表 + `resource_type` 判别字段而非每资源一张绑定表（三张表字段完全同构，通表更简洁，宪法 V）。

## Complexity Tracking

> 无需填写——Constitution Check 全部通过，无违规项。
