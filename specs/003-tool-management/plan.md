# Implementation Plan: 工具管理（第三阶段）

**Branch**: `003-tool-management` | **Date**: 2026-09-10 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/003-tool-management/spec.md`

> 说明：本仓库尚未启用 git，Branch 字段沿用 feature 目录名作为标识（与 002 一致）；仓库启用 git 后由分支策略统一处理。

## Summary

为 mini-workbuddy 新增"工具管理"模块：三类内置工具（当前时间 / Shell 命令 / 文件读写）的元信息展示、启停管理与统一执行入口。工具元数据（标识、用途、参数、场景/要求/限制说明）主定义在 `contracts/tool-definitions.md`，由后端代码注册表承载（说明与实现同源演化）；SQLite `tools` 表持久化注册事实与启停状态（迁移播种三行），清空数据即空列表。统一执行入口为**进程内服务** `tool_executor.execute(name, params)`：执行前完成"存在（注册表）→ 启用（DB）→ 参数（Pydantic）"三查，返回统一的 `ToolExecutionResult`（success / error_code / message / output / extra），全链路异常兜底、后端零崩溃。Shell 工具在执行层以"规范化 + 六类危险规则表"拦截危险命令（不依赖对模型的提示约束），配合 60s 超时与 20000 字符输出截断；文件工具以 `./workspace` 授权目录 + resolve 包含性校验兜底，UTF-8 文本、覆盖写、1MB 上限。前端将 ToolsView 占位页替换为列表（Table + Switch 确认启停 + 空状态）与详情抽屉。**本阶段零新增第三方依赖**（标准库 zoneinfo / subprocess / pathlib 全覆盖）。

## Technical Context

**Language/Version**: Python 3.12（后端，uv 管理）/ TypeScript + Vue 3（前端，Node 22）

**Primary Dependencies**: **零新增**。后端复用 FastAPI、Pydantic、SQLAlchemy 2.x、Alembic、pydantic-settings（时区用标准库 `zoneinfo`，命令执行用标准库 `subprocess`，路径用 `pathlib`）；前端复用 Vue Router、Pinia、ant-design-vue、sass。唯一潜在例外：Windows 上 `zoneinfo` 需要 `tzdata` 包，若运行时缺失则 `uv add tzdata`（运行必需，非预建，见 research R7）。

**Storage**: SQLite（唯一数据库），新表 `tools`（注册与启停状态，主定义 [data-model.md](data-model.md)）；1 次 Alembic 迁移（建表 + 播种）+ `sql/migrations/` 存档；运行时目录 `backend/workspace/`（授权目录，入 `.gitignore`，不存数据库内容）

**Testing**: 后端 pytest + httpx TestClient（契约测试以 [contracts/api-contract.md](contracts/api-contract.md) 为准；执行入口走服务层测试）；前端 Vitest + @vue/test-utils

**Target Platform**: 本地单机部署（Windows 开发机），前后端经 Vite 代理联调

**Project Type**: web-service（前后端分离工作台）

**Performance Goals**: 单用户本地工具，无并发指标；工具列表/详情/启停响应 < 500ms；Shell 命令超时上限 60s；输出截断 20000 字符；文件上限 1MB

**Constraints**:
- 六类危险命令执行层拦截率 100%，且拦截不依赖工具说明对模型的约束（SC-003 / FR-016）
- 授权目录外读写 100% 拒绝（含 `..` 穿越与绝对路径，SC-004 / FR-020）
- 任何执行失败（不存在/停用/参数错/执行错/超时）不得使后端进程崩溃（SC-002 / FR-012）
- 统一入口为进程内服务函数，本阶段不暴露 HTTP 执行端点、不提供工具删除/用途修改接口（research R6 / FR-007）
- 前端只请求相对路径 `/api`；固定技术栈不可替换

**Scale/Scope**: 3 个内置工具；1 张新表 + 3 个 HTTP 接口（列表/详情/启停）+ 1 个进程内执行入口；前端 1 页面 + 1 抽屉 + 1 store + 1 api 模块

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 宪法原则 | 检查项 | 结论 |
|---------|--------|------|
| I. Spec-First | 本 plan 基于 `spec.md`（2026-09-10 已过质量检查清单 16/16，无 NEEDS CLARIFICATION） | ✅ 通过 |
| II. SSOT | 工具元数据/参数/错误码主定义 → `contracts/tool-definitions.md`（代码注册表消费）；HTTP 契约 → `contracts/api-contract.md`；数据模型 → `data-model.md`；配置常量 → `contracts/tool-definitions.md` §6（`core/config.py` 实现）；UI 令牌 → `frontend/src/styles/tokens.scss`；开发约定 → `AGENTS.md`，均引用不复制 | ✅ 通过 |
| III. Contract-First | 两份契约先于编码产出；`schemas/tool.py` 与契约逐字段对齐；前端类型从契约派生；路径 `/api/tools` 经 Vite 代理；危险类别/错误码枚举先入契约 | ✅ 通过 |
| IV. Verify Before Ship | 交付前 `uv run pytest`、`uv run pyright`、`npm run build`、`npm run test:unit` 全绿；完成后跑 `/speckit-analyze` | ✅ 通过（流程排入交付门禁） |
| V. Simplicity | 零新增第三方依赖；不暴露无消费方的 HTTP 执行端点；无删除/编辑接口；文件数贴合三工具+入口+规则的最小集；单用户无权限层 | ✅ 通过 |
| VI. Feedback Loop | 实现中发现规范问题回写 `contracts/` / `data-model.md` 再同步代码 | ✅ 通过 |
| 固定技术栈 | Vue3/TS/Vite/Pinia/ant-design-vue/sass + FastAPI/Pydantic/SQLAlchemy/Alembic/SQLite/uv；新能力全部标准库实现，无违宪替代 | ✅ 通过 |
| uv 工作流 | 无新依赖（唯一潜在 `uv add tzdata` 属运行必需）；测试 `uv run pytest` | ✅ 通过 |
| 数据库约束 | `tools` 表走 Alembic 迁移（建表+播种）+ `sql/migrations/` 存档；启停状态入 SQLite，不用平面文件 | ✅ 通过 |
| 前后端联调 | 前端只请求相对路径 `/api`（复用 `request.ts`） | ✅ 通过 |
| 目录结构 | 后端 api/core/schemas/services/models 分层（新增文件各归其位）；前端 views/stores/api/components 分目录；`0user chat/` 只读 | ✅ 通过 |
| UI 设计约束 | 引用 tokens.scss 变量；Table/Drawer/Switch 复用 antd；字号符合规格；无禁用视觉元素 | ✅ 通过 |
| 质量门禁 | 四项检查命令排入交付清单 | ✅ 通过 |

**Phase 1 设计后复检**：[research.md](research.md)（R1–R9）已解决全部待决项；[data-model.md](data-model.md) 单表无外键、与契约 name 键对齐；[contracts/tool-definitions.md](contracts/tool-definitions.md) 与 [contracts/api-contract.md](contracts/api-contract.md) 枚举/结构互相引用一致；无新增违规。**Gate 结论：通过，无需 Complexity Tracking 例外。**

## Project Structure

### Documentation (this feature)

```text
specs/003-tool-management/
├── plan.md                    # 本文件（/speckit-plan 输出）
├── research.md                # Phase 0 输出：九项技术决策（注册表/拦截规则/入口形态等）
├── data-model.md              # Phase 1 输出：tools 表主定义
├── quickstart.md              # Phase 1 输出：端到端验证指南
├── contracts/                 # Phase 1 输出：契约主定义
│   ├── api-contract.md        # HTTP 接口（列表/详情/启停）
│   └── tool-definitions.md    # 工具元数据/参数/执行结果/错误码/配置常量
└── tasks.md                   # Phase 2 输出（/speckit-tasks，本命令不创建）
```

### Source Code (repository root)

```text
backend/
├── app/
│   ├── api/
│   │   └── tools.py               # 路由层：GET /api/tools、GET/{name}、PUT/{name}/enabled
│   ├── core/
│   │   └── config.py              # 新增 default_timezone/authorized_dir/shell_timeout_seconds/
│   │                              #   shell_output_max_chars/file_max_bytes 五个设置项
│   ├── models/
│   │   └── __init__.py            # 新增 ToolEntry（tools 表，主定义 data-model.md）
│   ├── schemas/
│   │   └── tool.py                # Pydantic：ToolItem/ToolDetail/ToolParam/ToolToggleRequest/
│   │                              #   ToolExecutionResult（契约实现）
│   ├── services/
│   │   ├── tool_registry.py       # 三工具元数据注册表 + 各自参数校验模型（契约实现）
│   │   ├── tool_service.py        # DB 侧：列表/详情/启停 + ensure_seeded 幂等播种
│   │   ├── tool_executor.py       # 统一执行入口：三查 → 分发 → 统一结果 → 异常兜底
│   │   ├── danger_rules.py        # 危险命令规则表（六类，正则+结构化 token）
│   │   ├── time_tool.py           # current_time 实现（zoneinfo）
│   │   ├── shell_tool.py          # shell 实现（subprocess + 超时 + 截断 + 拦截调用）
│   │   └── file_tool.py           # file_read_write 实现（授权目录 + 路径包含性校验）
│   └── main.py                    # 注册 tools 路由
├── migrations/versions/           # 新增一条迁移：建 tools 表 + 播种三行
├── tests/
│   ├── conftest.py                # 既有夹具扩展：tools 播种 + workspace 隔离目录
│   ├── test_tools_api.py          # HTTP 契约测试（列表/详情/启停/404/422/无删除路由）
│   ├── test_tool_executor.py      # 统一入口五场景 + 异常兜底不冒泡
│   ├── test_danger_rules.py       # 六类危险规则 + 普通命令对照组
│   ├── test_time_tool.py          # 时区正确性/默认回退/CST 拒绝
│   ├── test_shell_tool.py         # 正常命令/非零退出码/超时/截断/六类拦截
│   └── test_file_tool.py          # 授权目录内读写/越界拒绝/穿越拒绝/不存在/覆盖
└── workspace/                     # 授权目录（运行时生成，入 .gitignore）

frontend/src/
├── api/
│   └── tools.ts                   # 工具接口封装 + 类型（从契约派生）
├── stores/
│   └── tools.ts                   # Pinia store：列表/加载态/启停
├── views/
│   └── ToolsView.vue              # 列表 + 空状态 + 启停开关（替换占位页）
├── components/
│   └── tools/
│       └── ToolDetailDrawer.vue   # 详情抽屉：参数表 + 场景/要求/限制三节
└── styles/                        # 复用既有 tokens.scss，不新增令牌文件
```

**Structure Decision**: 沿用既有 Web 应用双项目结构（`backend/` + `frontend/`）与既定分层，只新增本阶段有消费方的文件：三个工具实现各自独立成文件（对应独立测试套），危险规则独立成纯函数模块（对应六类拦截单测），注册表/服务/入口三层分离对应契约的"元数据 / 状态 / 执行"职责划分（research R1/R6）。另随交付更新两处既有文件：`.gitignore`（追加 `backend/workspace/`）与 `AGENTS.md` §3 目录树（补 workspace 一行，宪法 VI 回写）。

## Complexity Tracking

> 无 Constitution Check 违规，无需填写。
