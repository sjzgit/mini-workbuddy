# Implementation Plan: 用户工作空间与文件系统权限（第十四阶段）

**Branch**: `014-workspace-permission` | **Date**: 2026-09-18 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/014-workspace-permission/spec.md`

## Summary

让用户在 Chat 会话中选择一个本地目录作为 **Session Workspace**，与系统默认授权目录（`settings.authorized_dir`，即 **System Workspace**）共同构成文件系统授权范围；`file_read_write` / `shell` 两个内置工具在执行前经统一 **PermissionManager** 做三值权限判定（ALLOW / ASK_USER / DENY），判定基于**规范化真实路径**（resolve `..`、符号链接、平台路径语义，禁止字符串前缀）。范围外路径复用 013 的 Ask User 挂起机制向用户确认——允许则生成**仅当前 AgentRun 生效的临时授权**（Temporary Grant），拒绝则该次工具调用失败、运行继续。AgentRun 启动时快照工作空间，运行中切换不影响进行中的运行。系统保护路径（可配置策略）一律 DENY 且不可被确认绕过。零新增第三方依赖。

## Technical Context

**Language/Version**: 后端 Python 3.12（FastAPI + Pydantic + SQLAlchemy 2.x + Alembic + SQLite，uv 工作流）；前端 Vue 3 + TypeScript + Vite + Pinia + Ant Design Vue

**Primary Dependencies**: 全部复用现有模块，零新增第三方依赖：
- `agent_runtime.tools.run_tool` —— 新增 builtin `file_read_write` / `shell` 分发前权限检查阶段（提取目标路径 → PermissionManager 判定 → ASK_USER 挂起）
- `agent_runtime.ask_user` 挂起注册表 + 主循环 ask 分支 —— 权限确认**完整复用**（注册/事件/等待/回答端点/前端面板零改造，仅回答后的去向分支）
- `RunEventEmitter` + 事件桥接（chat_service 白名单）+ `RunRecorder` —— 新事件 `permission_checked` 接线（011/013 先例）
- `settings.authorized_dir` —— System Workspace 唯一来源（不改变其定义）
- `danger_rules` —— shell 危险命令拦截保持前置，与本功能正交

**Storage**: SQLite；`conversations` 表 +3 列（workspace_path / workspace_source / workspace_selected_at）、`runs` 表 +1 列（workspace_path 运行快照）；临时授权为**进程内运行期结构**（随 AgentRun 存亡，不落盘）

**Testing**: pytest（后端：内存库 + TestClient + 假流注入 + tmp_path 真实目录/Symlink）+ Vitest（前端 store）

**Target Platform**: 本地工作台（后端 uvicorn:8218，Windows 主要部署，路径逻辑保持跨平台）；前端 Vite 代理 `/api`

**Project Type**: Web 应用（frontend + backend）

**Performance Goals**: 权限判定为进程内路径运算 + 一次快照读取，单次 < 10ms；设置工作空间 API < 200ms

**Constraints**:
- 权限判断只来自 PermissionManager（Invariant 2）；LLM/提示词不参与（Invariant 3）
- 路径判定一律 resolve 后做目录树包含判断（Invariant 7），覆盖 `..`、符号链接、前缀相似目录、大小写、分隔符
- Temporary Grant 仅当前 AgentRun 内有效，不落盘、不跨消息（Invariant 5）
- AgentRun 启动快照工作空间，运行中切换不回读（Invariant 6）
- 系统保护路径 DENY 不进确认流程（Invariant 8）
- shell 为应用层路径检查，**明确不是 OS 级沙箱**（文档如实声明，预留 ExecutionBackend 扩展点，Invariant 10）
- 运行中（busy）允许切换工作空间（切换不影响进行中的运行，这正是快照语义的验收场景）

**Scale/Scope**: 单用户本地工作台；后端 2 个新服务模块 + 3 个新端点 + 1 次迁移 + 1 个新事件；前端输入区工作空间入口 + store/api 接线

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 原则 | 结论 | 说明 |
|------|------|------|
| I. Spec-First | ✅ | spec.md 已产出并通过质量清单（16/16）；FR-032「工作空间变更事件」的落点在 plan 阶段明确（见下方映射说明） |
| II. SSOT | ✅ | Workspace/权限端点、事件、错误码主定义 = `contracts/workspace-permission-api.md` → `schemas/chat.py` / `schemas/agent_runtime.py` / `schemas/tool.py` / 前端 `api/chat.ts` 四层对齐；数据模型主定义 = `data-model.md` → ORM → Alembic |
| III. Contract-First | ✅ | 契约先于编码；路径 `/api/conversations/{id}/workspace` 沿用现有 REST 风格与 Vite 代理前缀 |
| IV. Verify Before Ship | ✅ | 交付门禁四连（pytest/pyright/build/vitest）；路径规范化边界（`..`/前缀相似/Symlink）设专项测试 |
| V. Simplicity | ✅ | 零新增依赖；复用 013 挂起机制与事件三件套；不做沙箱/RBAC/审批流；ToolContext 扩展即最小 ExecutionContext，不重构 Runtime |
| VI. Feedback Loop | ✅ | file_tool 内部 root 白名单上移 PermissionManager 属权限职责归位，003 契约的 path 参数说明随本契约同步更新 |
| 固定技术栈 | ✅ | 未引入清单外框架 |
| 数据库约束 | ✅ | SQLite 唯一数据库；Alembic 迁移 + `sql/migrations/014-workspace-permission.sql` 存档 |
| 目录分层 | ✅ | 权限/工作空间运行内逻辑入 `services/` 与 `services/agent_runtime/`；路由薄；schemas 各归其位 |
| 前端规范 | ✅ | Composition API + ant-design-vue + 设计令牌 + Pinia store；`/api` 相对路径 |
| `0user chat/` 只读 | ✅ | 需求来自该目录，未写入 |

**FR-032 实现口径（Spec→设计映射，非违例记录）**: spec 要求「在已有事件/Trace 体系中记录工作空间变更事件」。设计落点为：① `run_started` 事件与 `runs.workspace_path` 列携带**运行时快照**（Trace 中每个运行可见其工作空间，US4-3/US5 直接受益）；② 工作空间设置/清除在 API 层记审计日志，响应携带 `source`/`selected_at`。**不新建** workspace_changed 事件类型与会话级事件总线——工作空间变更发生在 REST 域而非 Run 域，为其建跨域事件机制属过度设计（宪法 V）。此映射在实现与汇报中如实说明。

**Post-design re-check（Phase 1 后）**: ✅ 契约/数据模型/事件三件套复核无违例；权限检查收敛在 run_tool 单点，file_tool 内部检查移除后 003 既有用例随契约更新，未留双头判定。

## Project Structure

### Documentation (this feature)

```text
specs/014-workspace-permission/
├── plan.md                                # 本文件
├── research.md                            # Phase 0：九项决策
├── data-model.md                          # Phase 1：表列增补 + 运行期结构 + 事件负载 + 状态机
├── contracts/workspace-permission-api.md  # Phase 1：Workspace API/权限事件/错误码/工具契约变更
├── quickstart.md                          # Phase 1：端到端验证指南
└── tasks.md                               # Phase 2 输出（/speckit-tasks）
```

### Source Code (repository root)

```text
backend/
├── app/
│   ├── core/config.py                     # +protected_paths（追加保护路径，os.pathsep 分隔）
│   ├── models/__init__.py                 # ConversationEntry +3 列；RunEntry +workspace_path
│   ├── schemas/
│   │   ├── agent_runtime.py               # +EVENT_PERMISSION_CHECKED、PermissionCheckedData；RunStartedData +workspace_path
│   │   ├── chat.py                        # +ConversationWorkspaceOut / WorkspaceSetRequest
│   │   └── tool.py                        # +错误码：system_protected_path / permission_denied_by_user /
│   │                                      #  permission_check_failed / path_resolution_failed / ask_user_unavailable
│   ├── services/
│   │   ├── workspace_service.py           # 【新】WorkspaceManager：get/set/clear + 路径校验 + 持久化
│   │   ├── file_tool.py                   # 移除内部 root 白名单（权限上移）；read/write 逻辑保留
│   │   ├── shell_tool.py                  # +cwd 参数（执行基准目录）
│   │   ├── tool_executor.py               # dispatch 传参适配（file/shell）
│   │   ├── chat_service.py                # _to_summary 带 workspace_path；桥接白名单 +permission_checked
│   │   └── agent_runtime/
│   │       ├── permission.py              # 【新】PathResolver（resolve/contains）+ PermissionManager
│   │       │                              #      （RunPermissionContext/TemporaryGrant/check 三值判定）
│   │       ├── tools.py                   # ToolContext +permission；run_tool 权限检查阶段；权限挂起与 resume
│   │       ├── runtime.py                 # RunContext +workspace 快照；主循环 ask 分支改调 resume_pending_tool
│   │       ├── events.py                  # 导出 EVENT_PERMISSION_CHECKED
│   │       └── recorder.py                # permission_checked 落 run_events；run_started 快照写 runs.workspace_path
│   ├── api/chat.py                        # +GET/PUT/DELETE /{conversation_id}/workspace
│   └── main.py                            # （无变更）
├── migrations/versions/                   # +conversations 工作空间三列、runs.workspace_path
├── tests/
│   ├── conftest.py                        # +session_workspace 等夹具（如需）
│   ├── test_path_resolver.py              # 【新】规范化边界（.. / 前缀相似 / Symlink / 大小写 / 分隔符）
│   ├── test_permission.py                 # 【新】三值判定 / 临时授权 / 保护路径 / 授权并集
│   ├── test_workspace_service.py          # 【新】WorkspaceManager 全场景 + 会话隔离 + 持久化
│   ├── test_workspace_api.py              # 【新】三端点契约 + busy 切换允许
│   ├── test_file_tool.py                  # 更新：path_outside_root 用例迁移至权限层；新增授权外读写删除流
│   ├── test_shell_tool.py                 # 更新：cwd 传参；授权外路径拒绝
│   └── test_workspace_runtime.py          # 【新】runtime 集成：ASK_USER 挂起→允许→grant→拒绝→denied→不跨 run
└── sql/migrations/014-workspace-permission.sql  # 迁移存档

frontend/src/
├── api/chat.ts                            # +WorkspaceInfo 类型 + get/set/clearWorkspace API；permission_checked 事件 case
├── stores/chat.ts                         # +workspace 状态（当前会话）+ setWorkspace/clearWorkspace + 失败保留原值
├── components/chat/ChatComposer.vue       # 输入区底部「当前工作空间」入口（📁 路径 + 设置/清除 Popover）
└── stores/__tests__/chat.spec.ts          # +workspace 接线用例
```

**Structure Decision**: 权限运行时逻辑入 `agent_runtime/permission.py`（与 ask_user.py 同级，009/013 先例）；会话工作空间 CRUD 入 `services/workspace_service.py`（与 chat_service 同级，REST 域）；HTTP 契约入 `schemas/chat.py` + `api/chat.py`。既有文件全部为定向扩展，唯一新文件是两个 service 模块与对应测试。

## Complexity Tracking

> 无 Constitution Check 违规。一处显式映射：FR-032 的工作空间变更记录 = runs 快照 + API 审计日志（见上，理由：变更发生在 REST 域，新建跨域事件机制违反 Simplicity）。
