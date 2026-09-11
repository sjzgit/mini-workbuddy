# Implementation Plan: Skills 与 MCP 管理（第四阶段）

**Branch**: `004-skills-mcp-management` | **Date**: 2026-09-10 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/004-skills-mcp-management/spec.md`

> 说明：本仓库尚未启用 git，Branch 字段沿用 feature 目录名作为标识（与 002/003 一致）。

## Summary

为 mini-workbuddy 新增两个管理模块。**Skills 管理**：Skill 以文件为本——每 Skill 一个独立目录（`backend/workspace/skills/<dir>/skill.md`，YAML frontmatter 承载名称/说明 + Markdown 正文承载详细指令，文件格式主定义见 [contracts/skills-api.md](contracts/skills-api.md)），页面列表是该目录的视图；SQLite `skills` 表只持久化启用状态（目录名唯一键），手动刷新触发"重扫目录 + 同步 DB 行 + 跳过不合规目录并提示"；编辑页三区域（名称/用途说明/详细指令）保存后同步写回文件；ZIP 导入做"结构校验 + 同名拒绝 + 路径逃逸拒绝 + 大小/条目数上限"。**MCP 管理**：SQLite `mcp_servers` 表承载配置（stdio：命令/有序参数列表/环境变量；http：url/请求 Header）、启用状态与最近一次测试结果快照；环境变量与 Header 的值复用 002 的 Fernet 密钥库整体加密（两个 secret_ref 指针），对外只出掩码；测试连接经官方 MCP Python SDK 实际启动/连接 Server → 协议初始化 → `tools/list`，仅发现不执行，测试后进程与连接必清理；失败按六类区分并附脱敏诊断；配置变更后测试结果标记"配置已变更，待重新测试"。前端将 SkillsView / McpView 占位页替换为与既有管理页同范式的列表页。

## Technical Context

**Language/Version**: Python 3.12（后端，uv 管理）/ TypeScript + Vue 3（前端，Node 22）

**Primary Dependencies**: **新增两个运行必需依赖**（YAGNI 例外说明见 Constitution Check「uv 工作流」行）：

- `mcp`（官方 MCP Python SDK）：MCP 协议客户端。stdio 传输的 `StdioServerParameters` 天然以命令 + 参数数组 + 环境变量字典形态传给子进程（不拼 Shell，FR-021）；Streamable HTTP 传输支持自定义 Header；`initialize` 握手与 `tools/list`、协议错误语义、进程生命周期由 SDK 承载，手写 JSON-RPC + SSE 协议栈超出单机工具复杂度预算（research R3）。
- `python-multipart`：FastAPI 接收 ZIP 上传（multipart/form-data）的官方配套依赖，无替代方案。

其余全部复用既有栈：FastAPI、Pydantic、SQLAlchemy 2.x、Alembic、cryptography（Fernet 密钥库）、httpx；前端 Vue Router、Pinia、ant-design-vue、sass。

**Storage**: SQLite（唯一数据库），新表 `skills`（目录名 + 启用状态）、`mcp_servers`（配置 + 启用状态 + 测试结果快照，含两个 `secrets_vault` 外键指针），主定义 [data-model.md](data-model.md)；1 次 Alembic 迁移（建两表，无播种数据）+ `sql/migrations/` 存档；运行时目录 `backend/workspace/skills/`（Skill 文件，入 `.gitignore`）

**Testing**: 后端 pytest + httpx TestClient（契约测试以 [contracts/skills-api.md](contracts/skills-api.md) / [contracts/mcp-api.md](contracts/mcp-api.md) 为准；MCP 链路用内嵌 FastMCP 假 Server 脚本做真 stdio 集成测试）；前端 Vitest + @vue/test-utils

**Target Platform**: 本地单机部署（Windows 开发机），前后端经 Vite 代理联调

**Performance Goals**: 单用户本地工具，无并发指标；列表/详情/启停响应 < 500ms；测试连接总超时上限 30s（含启动 + 初始化 + 工具读取）

**Constraints**:

- 环境变量与 Header 值完整原文不出现在任何接口响应、日志、错误信息、测试结果与诊断信息中（SC-005 / FR-023）
- 测试连接无论成败，测试进程残留数为 0（SC-007 / FR-031）；仅发现工具不执行工具（FR-026）
- 启动命令与参数分开保存、直接传进程，不拼 Shell（FR-021）
- 同一 Server 同时至多一次测试（FR-030）；删除进行中测试的 Server 被拒绝
- Skill 文件是内容唯一事实来源：页面编辑写回文件，外部手工改动经刷新可见
- ZIP 解压路径逃逸 100% 拒绝；同名 Skill 不覆盖（FR-008/009）
- 前端只请求相对路径 `/api`；固定技术栈不可替换

**Scale/Scope**: 2 张新表；HTTP 端点 Skills 7 个 + MCP 7 个 + 1 个进程内 MCP 测试服务；前端 2 个占位页替换 + 2 个 store + 2 个 api 模块 + 4 个业务组件

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 宪法原则 | 检查项 | 结论 |
|---------|--------|------|
| I. Spec-First | 本 plan 基于 `spec.md`（2026-09-10 质量检查清单 16/16 通过，无 NEEDS CLARIFICATION） | ✅ 通过 |
| II. SSOT | Skill 文件格式与 ZIP 规则主定义 → `contracts/skills-api.md`；MCP 契约与测试结果分类/脱敏规则 → `contracts/mcp-api.md`；数据模型 → `data-model.md`；Skill 内容事实源 → `workspace/skills/` 文件本身；配置常量 → `core/config.py`（契约 §6 列出）；UI 令牌 → `tokens.scss`；开发约定 → `AGENTS.md`，均引用不复制 | ✅ 通过 |
| III. Contract-First | 两份契约先于编码产出；`schemas/skill.py` / `schemas/mcp.py` 与契约逐字段对齐；前端类型从契约派生；路径 `/api/skills`、`/api/mcp/servers` 经 Vite 代理 | ✅ 通过 |
| IV. Verify Before Ship | 交付前 `uv run pytest`、`uv run pyright`、`npm run build`、`npm run test:unit` 全绿；完成后跑 `/speckit-analyze` | ✅ 通过（流程排入交付门禁） |
| V. Simplicity | MCP 工具快照用 JSON 文本列（快照语义无单条查询需求，不建第三张表）；不预建 Agent 消费端点（MCP 工具聚合、Skill 注入提示词属后续阶段）；无多余抽象层 | ✅ 通过 |
| VI. Feedback Loop | 实现中发现规范问题回写 `contracts/` / `data-model.md` 再同步代码；目录约定变化回写 `AGENTS.md` | ✅ 通过 |
| 固定技术栈 | Vue3/TS/Vite/Pinia/ant-design-vue/sass + FastAPI/Pydantic/SQLAlchemy/Alembic/SQLite/uv 不变；`mcp` 是新能力的新协议客户端库（同 002 引入 httpx/cryptography、003 引入 tzdata 的先例），非对既有选型的等价替换 | ✅ 通过 |
| uv 工作流 | 新依赖以 `uv add mcp` / `uv add python-multipart` 落地（运行必需、有明确当前需求，非预建）；命令一律 `uv run` | ✅ 通过 |
| 数据库约束 | `skills`、`mcp_servers` 两表走 Alembic 迁移 + `sql/migrations/` 存档；敏感 env/headers 值入 `secrets_vault`（复用既有密钥表），不用平面文件；Skill **内容**按 spec 约定以文件为本体（需求即如此设计，页面是文件的视图），其**启用状态**等用户状态入 SQLite——两者职责划分见 research R1 | ✅ 通过 |
| 前后端联调 | 前端只请求相对路径 `/api`（复用 `request.ts`） | ✅ 通过 |
| 目录结构 | 后端 api/core/schemas/services/models 分层（新文件各归其位）；前端 views/stores/api/components 分目录；`0user chat/` 只读 | ✅ 通过 |
| UI 设计约束 | 引用 tokens.scss 变量；Table/Drawer/Modal/Switch/Upload 复用 antd；字号符合规格；无禁用视觉元素 | ✅ 通过 |
| 质量门禁 | 四项检查命令排入交付清单 | ✅ 通过 |

**Phase 1 设计后复检**：[research.md](research.md)（R1–R9）已解决全部待决项；[data-model.md](data-model.md) 两新表 + 既有 `secrets_vault` 复用，密文列长度语义已注明；[contracts/skills-api.md](contracts/skills-api.md) 与 [contracts/mcp-api.md](contracts/mcp-api.md) 枚举/结构互相引用一致；无新增违规。**Gate 结论：通过，无需 Complexity Tracking 例外。**

> **实现备注（003 先例）**：实施时发现安装的 `mcp` SDK 为 2.x——客户端流式传输函数名为 `streamable_http_client`（经 `create_mcp_http_client(headers=…)` 注入自定义 Header）、服务端装饰器为 `mcp.server.mcpserver.MCPServer`（`FastMCP` 已改名）、工具 schema 字段为 `input_schema`、异常类型为 `mcp.shared.exceptions.MCPError`。设计不变，仅 API 名称按 SDK 2.x 对齐；anyio TaskGroup 包装的 `ExceptionGroup` 在错误分类中展开取子异常归类。

## Project Structure

### Documentation (this feature)

```text
specs/004-skills-mcp-management/
├── plan.md                    # 本文件（/speckit-plan 输出）
├── research.md                # Phase 0 输出：八项技术决策（文件为本/密钥复用/SDK 选型等）
├── data-model.md              # Phase 1 输出：skills、mcp_servers 表主定义
├── quickstart.md              # Phase 1 输出：端到端验证指南
├── contracts/                 # Phase 1 输出：契约主定义
│   ├── skills-api.md          # Skills HTTP 契约 + skill.md 文件格式 + ZIP 导入规则
│   └── mcp-api.md             # MCP HTTP 契约 + 测试结果分类/脱敏规则 + 配置常量
└── tasks.md                   # Phase 2 输出（/speckit-tasks）
```

### Source Code (repository root)

```text
backend/
├── app/
│   ├── api/
│   │   ├── skills.py              # 路由层：列表/详情/编辑/启停/删除/刷新/导入
│   │   └── mcp.py                 # 路由层：列表/详情/新增/编辑/删除/启停/测试连接
│   ├── core/
│   │   └── config.py              # 新增 skills_dir / mcp_test_timeout_seconds 设置项
│   ├── models/
│   │   └── __init__.py            # 新增 SkillEntry、McpServerEntry（主定义 data-model.md）
│   ├── schemas/
│   │   ├── skill.py               # Pydantic：SkillItem/SkillDetail/SkillUpdateRequest/
│   │   │                          #   SkillRefreshResult/SkillImportResult（契约实现）
│   │   └── mcp.py                 # Pydantic：McpServerItem/McpServerDetail/McpServerUpsertRequest/
│   │                              #   McpTestResult/McpToolInfo/McpToolParam/McpToggleRequest（契约实现）
│   ├── services/
│   │   ├── skill_files.py         # skill.md 文件读写/frontmatter 解析/合规判定/目录扫描（纯文件层）
│   │   ├── skill_service.py       # Skills 业务：列表/编辑/启停/删除/刷新同步/ZIP 导入
│   │   ├── mcp_service.py         # MCP 业务：CRUD/启停/config_changed 判定/测试编排/并发锁
│   │   └── mcp_client.py          # MCP SDK 封装：stdio/http 连接→initialize→list_tools→清理；
│   │                              #   错误六分类 + 脱敏（纯 async，无 DB 依赖）
│   └── main.py                    # 注册 skills、mcp 路由
├── migrations/versions/           # 新增一条迁移：建 skills、mcp_servers 两表
├── tests/
│   ├── conftest.py                # 既有夹具扩展：skills 目录隔离 + mcp 测试超时隔离
│   ├── fake_mcp_server.py         # 内嵌 FastMCP 假 Server（正常/无工具两种模式，供 stdio 集成测试）
│   ├── test_skills_api.py         # Skills HTTP 契约测试（列表/详情/编辑/启停/删除/刷新/导入）
│   ├── test_skill_files.py        # frontmatter 解析/合规判定/路径逃逸/同名冲突单元测试
│   ├── test_mcp_api.py            # MCP HTTP 契约测试（CRUD/掩码/启停/config_changed/409）
│   ├── test_mcp_client.py         # 错误六分类 + 脱敏单元测试（不依赖真实进程）
│   └── test_mcp_test_connection.py# 测试连接集成：真 stdio 假 Server 成功/无工具/失败分类/锁互斥
└── workspace/
    └── skills/                    # Skill 目录（运行时生成，入 .gitignore）

frontend/src/
├── api/
│   ├── skills.ts                  # Skills 接口封装 + 类型（从契约派生）
│   └── mcp.ts                     # MCP 接口封装 + 类型（从契约派生）
├── stores/
│   ├── skills.ts                  # Pinia store：列表/加载态/刷新/启停/删除/导入
│   └── mcp.ts                     # Pinia store：列表/加载态/启停/删除/测试状态
├── views/
│   ├── SkillsView.vue             # 列表 + 刷新/导入 + 编辑抽屉 + 删除确认（替换占位页）
│   └── McpView.vue                # 列表 + 新增/编辑 Modal + 测试连接 + 工具弹窗（替换占位页）
└── components/
    ├── skills/
    │   └── SkillEditDrawer.vue    # 编辑抽屉：名称/用途说明/详细指令（Markdown 大输入区）
    └── mcp/
        ├── McpServerFormModal.vue # 新增/编辑表单：类型切换字段组/参数列表/键值对/示例说明
        └── McpToolsModal.vue      # 测试发现的工具列表弹窗（名称/用途/参数表）
```

**Structure Decision**: 沿用既有 Web 应用双项目结构与既定分层。后端将"文件读写"（`skill_files.py`，纯文件操作）与"业务编排"（`skill_service.py`，DB 同步 + 导入流程）分离，使文件层可独立单测；MCP 侧将"SDK 协议客户端"（`mcp_client.py`，async、无 DB）与"业务编排"（`mcp_service.py`，锁 + 快照落库）分离，使错误分类与脱敏可独立单测、集成测试聚焦真链路。前端两组模块各自 page + store + api + 业务组件，组件内再拆表单与弹窗，与 002（models/）的组织方式一致。

## Complexity Tracking

> 无 Constitution Check 违规，无需填写。
