# Implementation Plan: Agent 评测系统（Phase 11：Agent Evaluation）

**Branch**: `012-agent-evaluation` | **Date**: 2026-09-17 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/012-agent-evaluation/spec.md`

## Summary

在现有 Agent Runtime 之上构建评测基础设施：评测数据集管理（Case CRUD + JSON 导入导出与校验）→ 评测任务定义与三类快照固化（Agent/数据集/评分器）→ 评测运行（经统一入口 `execute_run` 逐 Case 顺序执行、失败隔离、LLM 评分与精确匹配评分、评分严格校验与一次重试）→ 结果聚合与轨迹下钻（CaseRun ↔ AgentRun）→ 运行控制（暂停/取消/恢复/失败 Case 重试）与重启恢复（running → interrupted）。评测子系统只负责数据集管理、任务编排、评分与聚合；Agent 执行完全复用现有 Runtime，不实现第二套执行循环。

## Technical Context

**Language/Version**: 后端 Python 3.12（FastAPI + Pydantic + SQLAlchemy 2.x + Alembic + SQLite，uv 工作流）；前端 Vue 3 + TypeScript + Vite + Pinia + Ant Design Vue

**Primary Dependencies**: 全部复用现有模块，零新增第三方依赖：
- `app/services/agent_runtime.execute_run` —— 唯一 Agent 执行入口（`RunRequest.conversation_id=None` 的评测直调场景 011 已显式支持）
- `app.services.agent_runtime.recorder.RunRecorder` —— AgentRun 三表（runs/run_events/run_payloads）自动持久化，评测无需重复实现
- `app.services.openai_client.stream_chat_completion` —— LLM 评分器的模型调用封装
- `app/services/run_service` / `components/runs/RunDetailDrawer.vue` —— 轨迹查询与前端下钻复用

**Storage**: SQLite（唯一数据库）；新增 5 张表（evaluation_datasets / evaluation_cases / evaluation_tasks / evaluation_runs / evaluation_case_runs），Alembic 迁移 + `sql/migrations/` 存档

**Testing**: pytest（后端，沿用 conftest 的内存库 + TestClient + 假流注入模式）+ Vitest（前端）

**Target Platform**: 本地工作台（后端 uvicorn:8218，前端 Vite 代理 `/api`）

**Project Type**: Web 应用（frontend + backend）

**Performance Goals**: 一次评测 ≥50 Case 顺序执行记录完整（SC-007）；评测在后台 asyncio 任务中执行，不阻塞 API 事件循环

**Constraints**: 单实例；单 Case 失败不阻塞运行（失败隔离率 100%）；评分器输出非法时恰好重试一次；评测 MUST NOT 自建 Agent 执行循环/工具调用/上下文构建（Invariants 1/2）；启动/取消/重试幂等

**Scale/Scope**: 单用户内部工作台；后端 1 个路由模块 + 1 个服务子包 + 5 张表；前端 1 页面 3 区域 + 组件子目录

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 原则 | 结论 | 说明 |
|------|------|------|
| I. Spec-First | ✅ | spec.md 已产出并通过质量清单；Agent 快照执行语义的澄清按回写闭环同步进 spec（见 research D3、spec 变更记录） |
| II. SSOT | ✅ | 数据模型主定义 = 本 feature `data-model.md` → `backend/app/models/__init__.py`；API 契约主定义 = `contracts/evaluation-api.md` → `backend/app/schemas/evaluation.py` → `frontend/src/api/evaluation.ts`，三层对齐 |
| III. Contract-First | ✅ | `contracts/evaluation-api.md` 与 Pydantic Schema 在编码前产出；路径以 `/api` 为前缀，与 Vite 代理一致 |
| IV. Verify Before Ship | ✅ | 交付门禁：`uv run pytest`、`uv run pyright`、`npm run build`、`npm run test:unit` 全绿 |
| V. Simplicity | ✅ | 零新增依赖；不预建并发策略/分布式调度；仅交付 2 种评分器；复用 RunRecorder/RunDetailDrawer，不新建轨迹查看器 |
| VI. Feedback Loop | ✅ | 研究阶段发现 spec 对「Agent 快照执行」表述过强 → 已回写修正 spec（US2 场景 2 / FR-006），先改主定义再实现 |
| 固定技术栈 | ✅ | 未引入清单外框架；依赖管理走 uv / npm |
| 数据库约束 | ✅ | SQLite 唯一数据库；Schema 变更走 Alembic；SQL 存档同步 `sql/migrations/` |
| 目录分层 | ✅ | `api/evaluation.py`（薄路由）+ `services/evaluation/`（业务子包，先例 `agent_runtime`）+ `models/` + `schemas/` |
| 前端规范 | ✅ | Composition API + ant-design-vue + 设计令牌变量 + Pinia；`/api` 相对路径 |
| `0user chat/` 只读 | ✅ | 仅作需求来源读取，不写入 |

**Post-design re-check（Phase 1 后）**: ✅ 数据模型 5 表与契约经复核未引入违例；评测执行严格经 `execute_run`（Invariant 1/2 在 design 层成立）。

## Project Structure

### Documentation (this feature)

```text
specs/012-agent-evaluation/
├── plan.md              # 本文件
├── research.md          # Phase 0 产出：D1~D11 决策
├── data-model.md        # Phase 1 产出：5 表 + 状态机 + 聚合口径
├── quickstart.md        # Phase 1 产出：端到端验证指南
├── contracts/
│   └── evaluation-api.md # Phase 1 产出：评测 API 契约
└── tasks.md             # Phase 2 产出（/speckit-tasks）
```

### Source Code (repository root)

```text
backend/
├── app/
│   ├── api/evaluation.py            # 路由：/api/evaluation/datasets|tasks|runs（薄路由层）
│   ├── schemas/evaluation.py        # Pydantic 契约实现（枚举唯一主定义在契约）
│   ├── models/__init__.py           # +5 ORM 模型（EvaluationDatasetEntry 等）
│   └── services/evaluation/
│       ├── __init__.py              # 异常类型导出
│       ├── dataset_service.py       # 数据集/Case CRUD + JSON 导入导出与校验
│       ├── task_service.py          # 任务 CRUD + 三类快照固化
│       ├── run_service.py           # 发起/暂停/取消/恢复/重试 + 聚合 + 重启恢复
│       ├── runner.py                # EvaluationRunner + ExecutionStrategy（顺序策略）
│       └── evaluators.py            # Evaluator 抽象 + LLMJudgeEvaluator + ExactMatchEvaluator
├── migrations/versions/             # +1 迁移（5 表）
└── tests/
    ├── conftest.py                  # +评测共用夹具（数据集/任务/快照）
    └── test_evaluation_*.py         # 数据集/快照/执行/评分/聚合/恢复/重试

frontend/src/
├── api/evaluation.ts                # 契约类型与调用封装
├── views/EvaluationsView.vue        # 评测工作台：数据集/任务/运行三 Tab
└── components/evaluation/
    ├── DatasetPanel.vue / DatasetCasesDrawer.vue / DatasetImportModal.vue
    ├── TaskPanel.vue / TaskCreateModal.vue
    ├── RunPanel.vue / EvaluationRunDetailDrawer.vue / CaseDetailDrawer.vue
    └── __tests__/                   # Vitest

sql/migrations/012-agent-evaluation-evaluation-tables.sql  # 变更 SQL 存档
```

**Structure Decision**: 严格沿用 AGENTS.md §3 分层；评测服务以 `services/evaluation/` 子包组织（先例：`services/agent_runtime/`）；轨迹下钻复用 `components/runs/RunDetailDrawer.vue`，不新建轨迹查看器（FR-030）。

## Complexity Tracking

> 无宪法违例，无需记录。

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| （无） | — | — |
