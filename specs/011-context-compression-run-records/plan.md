# Implementation Plan: 上下文压缩与运行记录可观测（第十一阶段）

**Branch**: `011-context-compression-run-records` | **Date**: 2026-09-15 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/011-context-compression-run-records/spec.md`

## Summary

在统一 Agent Runtime 中补齐两块能力：

1. **运行记录持久化与可观测**：Runtime 运行过程中产生的结构性事件（运行开始/结束、模型请求、工具调用、压缩、错误）与详细载荷（模型完整输入输出、工具完整参数与结果）落库（`runs` / `run_events` / `run_payloads` 三张新表）；新增运行列表与详情 REST API（快照字段 + 恒定查询次数）；实现 `RunsView` 页面（列表 + 详情时间线 + 载荷按需加载）；浏览器断开不再取消运行（后台继续执行 + 聊天页自动续播）；服务重启时遗留运行标记"运行中断"。
2. **上下文自动压缩**：Runtime 每轮模型请求前用统一估算器（字符比 0.6，沿用 008 系数）估算输入 Token，达到 Agent 配置的触发比例（默认 80%）时把较早对话交给当前模型生成任务清单式摘要，与压缩边界（`conversation_compactions` 表）一起事务写回；下一次压缩只处理边界之后消息；摘要失败时按完整消息组备用裁剪且不推进边界；Agent 管理新增 4 个压缩配置项。

压缩事件复用现有 RunEvent 契约扩展（`compression_*` 事件 + `purpose` 字段），持久化与 SSE 转发走同一套事件；详细载荷经脱敏后完整保存（不截断）。

## Technical Context

**Language/Version**: Python 3.12（backend/pyproject.toml）；前端 TypeScript + Vue 3（`<script setup>`）

**Primary Dependencies**: FastAPI、Pydantic、SQLAlchemy 2.x、Alembic、httpx（后端）；Vue Router、Pinia、ant-design-vue、sass（前端）

**Storage**: SQLite（唯一数据库，`sqlite:///./app.db`）；所有变更走 Alembic 迁移（当前 head：`207b5aa052ad`）

**Testing**: 后端 pytest（`uv run pytest`，内存 SQLite + `FakeStream` 伪造模型流）；前端 Vitest（`npm run test:unit`）

**Target Platform**: 单用户工作台（桌面浏览器 + 本机后端，Windows 开发环境）

**Performance Goals**: 运行列表查询次数恒定（2 次查询：COUNT + SELECT，不随行数增长，SC-003）；事件落库仅结构性事件（增量不落库），单次运行事件量 O(轮数×调用数)

**Constraints**: 不引入技术栈外依赖（无 tiktoken，估算沿用字符比系数）；`0user chat/` 只读；前端始终请求相对 `/api`；密钥/环境变量/绝对路径不落库（脱敏后保存）

**Scale/Scope**: 3 张新表 + agents 表 4 列 + 1 个新页面（`/runs`，路由与菜单已预置）+ Runtime 压缩模块 + 桥接层适配；测试新增后端 2 个文件 + 前端 2~3 个 spec

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 原则 | 检查项 | 结果 |
|------|--------|------|
| I. Spec-First | spec.md 已产出并通过澄清（4 项决定回写） | ✅ 通过 |
| II. SSOT | 事件契约主定义在 `specs/009-agent-runtime/contracts/agent-runtime-api.md` 增补（沿用 010 先例）；新 REST 契约在 `contracts/runs-api.md`；数据模型主定义在 `data-model.md` → SQLAlchemy → Alembic；前端类型从后端 Schema 派生 | ✅ 通过 |
| III. Contract-First | 契约（本目录 contracts/）先于实现；路径统一 `/api` 前缀；枚举只定义一处 | ✅ 通过 |
| IV. Verify Before Ship | 交付前运行 `uv run pytest`、`uv run pyright`、`npm run build`、`npm run test:unit` | ✅ 通过 |
| V. Simplicity | 复用现有 `stream_chat_completion`、事件发射器、估算系数与测试夹具；不预建评测模块；分页是 spec 明确需求（非预建） | ✅ 通过 |
| VI. Feedback Loop | 发现规范不符时回写本目录 contracts/ 与 009 契约，不在实现层绕行 | ✅ 通过 |
| 技术栈 | 无新增依赖；SQLite + Alembic；`0user chat/` 未触碰 | ✅ 通过 |

**Post-Design Re-check**（Phase 1 完成后）：数据模型与契约逐字段对齐；压缩逻辑全部位于统一 Runtime（聊天与后续评测复用，页面不裁剪上下文，符合 FR-023）；运行记录由 Runtime 侧 RunRecorder 依据真实事件产生（聊天与评测同一记录入口，符合 FR-005）。✅ 通过。

## Project Structure

### Documentation (this feature)

```text
specs/011-context-compression-run-records/
├── plan.md              # 本文件
├── research.md          # Phase 0 决策记录
├── data-model.md        # Phase 1 数据模型（新表 + agents 增列）
├── quickstart.md        # Phase 1 验证指南
├── contracts/
│   ├── runtime-events-011.md      # 事件契约 011 增补（压缩事件/purpose/载荷字段/后台运行修订）
│   ├── runs-api.md                # 运行记录 REST API 契约
│   └── agent-compression-config.md # Agent 压缩配置字段契约
└── tasks.md             # Phase 2 产出（/speckit-tasks）
```

### Source Code (repository root)

```text
backend/
├── app/
│   ├── core/config.py                        # [改] 新增压缩相关配置项
│   ├── models/__init__.py                    # [改] RunEntry/RunEventEntry/RunPayloadEntry/ConversationCompactionEntry + AgentEntry 4 列
│   ├── schemas/
│   │   ├── agent_runtime.py                  # [改] 压缩事件负载、purpose、载荷透传字段
│   │   ├── agents.py                         # [改] AgentSaveRequest/AgentDetail 增 4 字段与校验
│   │   ├── chat.py                           # [改] 上下文超限提示文案增补
│   │   └── runs.py                           # [新] 运行记录 API 契约实现
│   ├── services/
│   │   ├── agent_runtime/
│   │   │   ├── __init__.py                   # [改] RunRequest 增 conversation_id / history seq
│   │   │   ├── runtime.py                    # [改] 压缩检查切入点、purpose 传递、载荷透传
│   │   │   ├── compression.py                # [新] 容量估算 + 摘要生成 + 备用裁剪
│   │   │   └── recorder.py                   # [新] RunRecorder：事件/载荷/指标持久化
│   │   ├── sanitize.py                       # [新] 载荷与错误摘要统一脱敏
│   │   ├── run_service.py                    # [新] 运行列表/详情/载荷查询
│   │   ├── chat_service.py                   # [改] 断开不取消、历史带 seq、压缩状态预检
│   │   └── startup_recovery.py               # [新] 启动时"运行中断"标记（或并入 main lifespan）
│   ├── api/
│   │   ├── runs.py                           # [新] /api/runs 路由
│   │   └── main.py 注册                      # [改] 挂载 runs router + 启动恢复钩子
│   └── main.py
├── migrations/versions/<new>_add_runs_tables_and_agent_compact_fields.py   # [新] Alembic
└── tests/
    ├── test_run_records.py                   # [新] 持久化/配对去重/列表查询次数/级联删除/中断恢复
    ├── test_context_compression.py           # [新] 触发/边界增量/摘要合并/备用裁剪/取消/配置关闭
    └── conftest.py                           # [改] 压缩与运行记录夹具

frontend/
├── src/
│   ├── api/runs.ts                           # [新] 运行记录 API 封装与类型
│   ├── api/agents.ts                         # [改] 压缩配置字段与默认值常量
│   ├── api/chat.ts                           # [改] 压缩事件类型（前向兼容）
│   ├── stores/runs.ts                        # [新] 运行记录 store
│   ├── stores/chat.ts                        # [改]（仅类型/事件透传，续播机制已存在）
│   ├── views/RunsView.vue                    # [改] 占位页 → 运行列表页
│   ├── components/runs/RunDetailDrawer.vue   # [新] 运行详情抽屉（摘要 + 时间线 + 载荷按需加载）
│   ├── components/runs/RunTimeline.vue       # [新] 事件时间线
│   ├── components/agents/AgentDetailDialog.vue  # [改] 表单 4 字段
│   └── components/agents/AgentOrchestration.vue # [改] 压缩配置表单区
└── src/stores/__tests__/runs.spec.ts         # [新] 等 Vitest
```

**Structure Decision**: 全部沿用既有分层（api → services → models/schemas）；压缩与记录逻辑在 `services/agent_runtime/` 内实现（聊天与评测复用同一入口，FR-005/023）；前端沿用元数据驱动路由（`/runs` 已注册，替换占位组件即可）。

## Complexity Tracking

> 无宪法违规，不需要 justification。

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| （无） | — | — |
