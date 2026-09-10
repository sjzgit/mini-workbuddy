# Implementation Plan: 模型管理（第二阶段）

**Branch**: `002-model-management` | **Date**: 2026-09-10 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/002-model-management/spec.md`

## Summary

为 mini-workbuddy 新增"模型管理"模块：用户可以登记和维护兼容 OpenAI Chat Completions 接口的模型服务（显示名称、模型标识、服务地址、密钥、上下文/输出长度、温度、三项价格），并进行测试连接、默认模型切换与删除。密钥通过独立的本地加密密钥库（主密钥派生 Fernet 加密，存储于业务表之外）保存，任何接口响应只暴露"密钥是否已配置"。默认模型的唯一性与存在性由数据库约束（部分唯一索引 + 事务）保证。前端在既有 `ModelsView` 占位页位置替换为真实的列表 + 新增/编辑表单 + 测试连接/删除交互，全部使用项目设计令牌与 ant-design-vue 组件。

## Technical Context

**Language/Version**: Python 3.12（后端，uv 管理）/ TypeScript + Vue 3（前端，Node 22）

**Primary Dependencies**:
- 后端（新增）：`cryptography`（Fernet 对称加密，密钥本地加密保存）；HTTP 调用复用测试栈已有的 `httpx`
- 后端（既有）：FastAPI、Pydantic、SQLAlchemy 2.x、Alembic、pydantic-settings
- 前端（既有）：Vue Router、Pinia、ant-design-vue、sass；测试 Vitest

**Storage**: SQLite（唯一数据库），模型配置持久化为 `models` 表；密钥以 Fernet 加密后存于 `secrets_vault` 独立表（不含明文，与业务表分离），主密钥存于 `backend/` 下本地文件 `secret.key`（不入库，加入 `.gitignore`）

**Testing**: 后端 pytest + httpx TestClient（契约测试以 [contracts/api-contract.md](contracts/api-contract.md) 为准）；前端 Vitest + @vue/test-utils

**Target Platform**: 本地单机部署（Windows 开发机），前后端经 Vite 代理联调

**Project Type**: web-service（前后端分离工作台）

**Performance Goals**: 单用户本地工具，无并发指标；测试连接请求设置 30s 超时；模型列表/CRUD 响应 < 500ms

**Constraints**:
- 密钥正文不得出现在任何接口响应、日志、错误信息、前端持久化存储（SC-002）
- 任意时刻默认模型 ≤ 1 且不指向已删除记录（SC-003）
- 前端禁止硬编码后端绝对地址；接口路径以 `/api` 为前缀
- 固定技术栈不可替换；新增依赖仅限 `cryptography`（密钥加密的当前明确需求）

**Scale/Scope**: 单用户，模型数量预期 < 20；1 个新页面 + 6 个后端接口 + 2 张表 + 1 次迁移

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 宪法原则 | 检查项 | 结论 |
|---------|--------|------|
| I. Spec-First | 本 plan 基于 `spec.md`（2026-09-10 已过质量检查清单） | ✅ 通过 |
| II. SSOT | 数据模型主定义 → 本目录 `data-model.md`；API 契约主定义 → 本目录 `contracts/`；枚举/常量 → `contracts/`；UI 令牌 → `frontend/src/styles/tokens.scss`；开发约定 → `AGENTS.md`，均引用不复制 | ✅ 通过 |
| III. Contract-First | `contracts/api-contract.md` 先于编码产出；Pydantic Schema 与契约逐字段对齐；前端类型从契约派生；路径 `/api/models` 经 Vite 代理 | ✅ 通过 |
| IV. Verify Before Ship | 交付前 `uv run pytest`、`uv run pyright`、`npm run build`、`npm run test:unit` 全绿；完成后跑 `/speckit-analyze` | ✅ 通过（流程已排入 tasks） |
| V. Simplicity | 本阶段只建模型管理所需文件：`models.py`、`model_schemas`、`model_service`、密钥库、1 个路由文件、1 个迁移、前端 1 页面 + 1 store + 1 api 模块；无预建空目录；单用户无权限层 | ✅ 通过 |
| VI. Feedback Loop | 实现中发现规范问题回写 `data-model.md` / `contracts/` 再同步代码 | ✅ 通过 |
| 固定技术栈 | Vue3/TS/Vite/Pinia/ant-design-vue/sass + FastAPI/Pydantic/SQLAlchemy/Alembic/SQLite/uv，无违宪替代 | ✅ 通过 |
| uv 工作流 | 新增依赖用 `uv add cryptography`；测试 `uv run pytest` | ✅ 通过 |
| 数据库约束 | 新表走 Alembic 迁移 + `sql/migrations/` 存档；禁止 JSON 文件代替数据库 | ✅ 通过 |
| 前后端联调 | 前端只请求相对路径 `/api` | ✅ 通过 |
| 目录结构 | 后端 api/core/schemas/services/models 分层；前端 views/stores/api 分目录 | ✅ 通过 |
| UI 设计约束 | 引用 tokens.scss 变量；字号符合规格；无禁用视觉元素 | ✅ 通过 |
| 质量门禁 | 四项检查命令排入交付清单 | ✅ 通过 |

**Gate 结论**：无违规，无需 Complexity Tracking 例外。

## Project Structure

### Documentation (this feature)

```text
specs/002-model-management/
├── plan.md              # 本文件（/speckit-plan 输出）
├── research.md          # Phase 0 输出：密钥存储等技术决策
├── data-model.md        # Phase 1 输出：数据模型主定义
├── quickstart.md        # Phase 1 输出：端到端验证指南
├── contracts/           # Phase 1 输出：API 契约主定义
│   └── api-contract.md
└── tasks.md             # Phase 2 输出（/speckit-tasks，本命令不创建）
```

### Source Code (repository root)

```text
backend/
├── app/
│   ├── api/
│   │   └── models.py            # 路由层：/api/models CRUD + default + test-connection
│   ├── core/
│   │   ├── config.py            # 新增 secret_vault_path 设置项
│   │   └── secret_vault.py      # 密钥库：主密钥管理 + Fernet 加解密 + secrets_vault 表访问
│   ├── models/
│   │   └── __init__.py          # models 表 ORM（首业务表，目录自此建立）
│   ├── schemas/
│   │   └── model.py             # Pydantic 契约实现（ModelCreate/Update/Item/Detail/TestResult…）
│   ├── services/
│   │   └── model_service.py     # 业务逻辑：CRUD、默认模型一致性、测试连接分类
│   │   └── openai_client.py     # OpenAI Chat Completions 兼容调用（唯一调用逻辑）
│   └── main.py                  # 注册 models 路由
├── migrations/versions/         # 新增一条迁移：models + secrets_vault
└── tests/
    ├── conftest.py              # 既有夹具扩展（隔离 DB、密钥库临时目录）
    ├── test_models_api.py       # 契约测试
    └── test_model_service.py    # 业务规则测试（默认模型一致性、删除清理）

frontend/src/
├── api/
│   └── models.ts                # 模型接口封装 + 类型（从契约派生）
├── stores/
│   └── models.ts                # Pinia store：列表/加载态/默认切换
├── views/
│   └── ModelsView.vue           # 列表 + 空状态 + 操作入口（替换占位页）
├── components/models/
│   ├── ModelFormModal.vue       # 新增/编辑表单弹窗（校验 + 字段说明）
│   ├── DeleteModelModal.vue     # 删除确认（默认模型时先选新默认）
│   ├── TestConnectionPanel.vue  # 测试连接结果内联面板（research R7）
│   ├── formRules.ts             # 表单校验规则（与后端校验语义对齐）
│   └── testConnection.ts        # 错误分类展示文案映射
└── styles/                      # 复用既有 tokens.scss，不新增令牌文件
```

**Structure Decision**: 采用既有 Web 应用双项目结构（`backend/` + `frontend/`），在第一阶段骨架的既定分层内新增文件；后端 `models/`、`services/` 目录按宪法"有业务后再建"原则于本阶段建立。

## Complexity Tracking

> 无 Constitution Check 违规，无需填写。
