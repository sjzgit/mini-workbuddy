# mini-workbuddy Constitution

## Core Principles

### I. Spec-First（规范先行）

所有功能开发 **MUST** 从规范出发，禁止未经规范化直接编码。

- 每个 Feature **MUST** 先产出 `spec.md`，明确用户故事、功能边界和业务规则
- 规范是唯一真相源，代码是规范的实现
- 任何需求变更 **MUST** 先更新 `spec.md`，再同步实现
- 禁止以"先写代码再补文档"的方式推进
- specify 生成的所有文档尽量使用**中文**

### II. SSOT（单一事实来源 Single Source of Truth）

一项事实只能有一个正式主定义，下游 **MUST** 引用而非复制。

- 数据模型主定义：Feature spec 的 `data-model.md` → `backend/app/models/`（SQLAlchemy ORM 实现），实现侧字段类型 MUST 与设计文档一致
- API 契约主定义：`backend/app/schemas/`（Pydantic）→ 自动生成 OpenAPI → `frontend/src/api/`（TypeScript 类型），前端类型 MUST 从后端 Schema 派生而非手动复制
- 枚举与权限主定义：Feature spec 的 `contracts/` 目录，实现侧只消费不重复定义
- 开发规范主定义：根目录 `AGENTS.md`（固定技术栈、目录约定、常用命令、配色与字号入口、修改后的检查清单），后续开发约定变化只更新这一个文件，禁止让相同规则散落在各任务说明中
- UI 设计令牌主定义：全局 CSS 变量（配色、字体、字号），所有页面和组件 MUST 引用变量，禁止在页面内写相近色或独立字号
- 冲突时按层级优先级裁决：`contracts > data-model > spec > 口头约定`

### III. Contract-First（契约先行）

机器可消费的契约 **MUST** 在实现之前定义完成。

- Pydantic Schema **MUST** 在 API 编码前产出，作为前后端协作的唯一接口约定
- 枚举值和配置常量 **MUST** 先写入 `contracts/`，实现侧只消费不定义
- 数据模型 **MUST** 先在 `data-model.md` 中设计，再落地为 SQLAlchemy ORM 与 Alembic 迁移
- 前后端接口路径统一以 `/api` 为前缀，开发环境由 Vite 代理转发，契约中的路径 MUST 与实际代理规则一致
- 契约变更 **MUST** 经过审查，因为影响全局一致性

### IV. Verify Before Ship（验证驱动）

实现完成后 **MUST** 对比代码与规范的一致性，不一致不得视为完成。

- 接口路径/方法/字段 **MUST** 与 Pydantic Schema / OpenAPI 契约一致
- 数据模型字段/类型 **MUST** 与 `data-model.md` 一致
- 前端 API 调用类型 **MUST** 与后端 Schema 对齐
- 交付前 **MUST** 运行 `AGENTS.md` 中定义的检查（后端 `uv run pytest`、前端构建与 Vitest 等）并全部通过
- 使用 `/speckit-analyze` 进行跨文档一致性分析

### V. Simplicity（简洁务实）

紧凑工作台，不是宣传落地页；每一行代码和文件都要有当前用途。

- 禁止为了显得完整而创建大量空文件或空目录；暂无业务内容的模块只保留一个写明"本模块将在后续阶段开发"的占位页面
- 不提前搭建没有消费方的后端目录、抽象层或配置
- 不引入技术栈清单之外的框架；YAGNI 优先，需求未到不预建
- 占位页面禁止出现虚构的统计数字、对话和列表

### VI. Feedback Loop（回写闭环）

实现过程中发现规范问题时，**MUST** 回写正式主定义修正，不得在实现层绕行。

- 发现 spec 与实际情况不符时，先定位正式的 SSOT 主定义文件
- 按 SSOT 优先级判定哪个文件是正式口径
- 修正正式主定义后，再同步受影响的下游文件（data-model → Schema → TypeScript 类型 → 实现代码）
- 开发约定层面的变更回写 `AGENTS.md`，而非写进某次任务说明

---

## Technology & Implementation Constraints

### 固定技术栈

- **前端**：Vue 3、TypeScript、Vite、Vue Router、Pinia、sass、npm（管理依赖）、Ant Design（ant-design-vue）；测试使用 Vitest
- **后端**：Python 3.12、FastAPI、Pydantic、SQLAlchemy、Alembic、SQLite；测试使用 pytest
- **禁止引入**：React、Next.js、Nuxt、Django、Flask；禁止用 pip 直接管理后端依赖
- 换用等价替代库（如其他 UI 组件库、其他 ORM）视为违反宪法

### uv 工作流（后端强制）

- 后端项目 **MUST** 在 `backend/` 目录中用 uv 初始化，生成并持续维护 `pyproject.toml` 与 `uv.lock`
- 添加依赖 **MUST** 使用 `uv add`；安装依赖 **MUST** 使用 `uv sync`；运行后端命令（含 uvicorn、Alembic、pytest）**MUST** 使用 `uv run`
- `README.md` 中 **MUST NOT** 出现要求用户直接运行 pip 的步骤
- Python 解释器版本以 `pyproject.toml` 声明的 3.12 为准

### 数据库约束

- SQLite 是本项目 **唯一** 数据库，**MUST** 在后端准备正式的数据库连接（SQLAlchemy engine/session）
- 所有 Schema 变更 **MUST** 通过 Alembic 迁移落地，Alembic 命令通过 `uv run` 执行
- 后续所有功能的数据 **MUST** 写入数据库，**禁止** 用 JSON 文件或其他平面文件代替数据库
- SQL 存档统一放在 `sql/` 目录（增量脚本放 `sql/migrations/`），与 Alembic 迁移保持对应

### 前后端联调约束

- 前端在开发环境中 **MUST** 始终请求相对路径 `/api`，由 Vite 转发到后端
- **禁止** 在前端代码中硬编码后端绝对地址（localhost:8000 等）

### 目录结构约束

- 前端代码放在 `frontend/src`，页面、路由、状态、请求封装、通用组件和样式 **MUST** 分目录放置，不得混写
- 后端代码放在 `backend/app`，采用**分层架构**:应用入口、路由、业务逻辑、数据访问和数据校验 **MUST** 各自放在含义明确的目录下（如 `api/`、`services/`、`models/`、`schemas/`）
- `0user chat/` 目录由用户主动维护，Agent **MUST NOT** 写入或修改该目录内容

### 质量门禁

- 后端代码 **MUST** 通过 `uv run pytest` 全部测试后方可视为完成
- 后端 **SHOULD** 通过 pyright 类型检查（配置见根目录 `pyrightconfig.json`）
- 前端代码 **MUST** 构建无错误（`npm run build`）后方可视为完成；含测试的改动 **MUST** 通过 Vitest
- 前端组件 **MUST** 使用 Composition API（`<script setup>`），优先复用 ant-design-vue 组件
- 全局状态 **MUST** 通过 Pinia Store 管理，禁止跨组件直接传递复杂状态对象
- UI 变更 **MUST** 符合「UI 设计约束」中的配色、字体、字号、布局规范
- 每次修改后需要运行的检查以 `AGENTS.md` 中的清单为准

---

## Development Workflow

每个 Feature 的完整生命周期（不得跳过 Specify、Plan 和 Tasks）：

| 步骤 | 命令 | 输入 → 产出 |
|------|------|------------|
| 1. **Specify** | `/speckit-specify` | 自然语言需求 → 结构化 `spec.md` |
| 2. **Clarify**（可选） | `/speckit-clarify` | 含糊点 → 澄清问题 → 回写 `spec.md` |
| 3. **Plan** | `/speckit-plan` | `spec.md` → 技术方案 + `data-model.md` + `contracts/` |
| 4. **Tasks** | `/speckit-tasks` | plan → 可执行任务清单 `tasks.md` |
| 5. **Implement** | `/speckit-implement` | `tasks.md` → 按任务清单逐步实现代码（MUST 先阅读 `AGENTS.md`） |
| 6. **Analyze** | `/speckit-analyze` | spec/plan/tasks + 代码 → 一致性与质量分析报告 |
| 7. **Converge**（按需） | `/speckit-converge` | 实现与任务清单的偏差 → 补齐剩余任务 |

> 跳过中间步骤 **MUST** 有明确理由并记录在 `plan.md` 中。**不得跳过 Specify、Plan 和 Tasks。**
>
> 实现完成后运行 `AGENTS.md` 定义的检查命令，全部通过后方可交付。

---

## Governance

本宪法是 mini-workbuddy 的最高开发准则，优先级高于任何其他开发实践文档。所有 Feature 开发 **MUST** 遵循。

- **修订流程**：任何对宪法的修订 MUST 说明变更动机、影响范围及模板同步检查结果；固定技术栈（前端/后端技术选型）的变更 MUST 由用户明确发起
- **版本策略**：遵循语义化版本（SemVer）
  - **MAJOR**：原则删除或重新定义，向后不兼容（如更换技术栈）
  - **MINOR**：新增原则/章节或显著扩展现有原则
  - **PATCH**：措辞澄清、错字修正、非语义性调整
- **合规审查**：每个 Feature Spec 的 Plan 阶段 MUST 通过 Constitution Check（见 `plan-template.md`），确认不违反核心原则后方可进入研发
- **冲突仲裁**：当实现细节与宪法冲突时，宪法优先；当 SSOT 主定义之间冲突时，按 `contracts > data-model > spec` 优先级裁决
- **运行时指导**：开发实施细节参见 `AGENTS.md`（编码规范、命令清单、设计令牌入口）

**Version**: 1.0.0 | **Ratified**: 2026-09-10 | **Last Amended**: 2026-09-10
