# Implementation Plan: 工具执行过程展示（第十阶段）

**Branch**: `010-tool-execution-display` | **Date**: 2026-09-15 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/010-tool-execution-display/spec.md`

## Summary

在现有聊天页以"过程卡片"形式实时展示 Agent Loop 的工具执行过程：卡片随工具事件出现/更新（正在执行 → 成功/失败/已取消/状态未知 + 耗时），正文与卡片按事件顺序交错排列，收起显示摘要、展开查看整理后的输入与结果（JSON 缩进 / 纯文本 / 截断标注 / 二进制提示），并配套滚动跟随、"回到最新消息"、生成中切换会话无缝续播。技术上复用 009 事件流增补展示字段（params/result/display_name/server_name），前端 store 重构为按会话的运行展示槽；不新增持久化（Clarify Q1/Q3 已确认）。

## Technical Context

**Language/Version**: 前端 TypeScript（Vue 3 + Vite）；后端 Python 3.12

**Primary Dependencies**: 前端 Vue 3 / Pinia / Vitest；后端 FastAPI / Pydantic / pytest（全部既有栈，零新增依赖）

**Storage**: 无新增（本阶段不持久化运行记录；沿用 008 会话/消息表）

**Testing**: 后端 pytest（`uv run pytest`）；前端 Vitest（`npm run test:unit`）+ `npm run build`

**Target Platform**: 桌面浏览器（现有工作台 SPA）+ 本地 FastAPI 服务

**Performance Goals**: 单次运行 20+ 工具调用、单条结果 1MB 文本时页面保持可滚动可交互（SC-004，靠后端事件字段截断 4000/16000 字符兜底）

**Constraints**: 不引入技术栈清单外依赖；工具返回内容按不可信文本渲染（禁止 v-html）；卡片样式全部引用 tokens.scss 设计令牌

**Scale/Scope**: 单用户工作台；改动集中在聊天页组件、chat store、事件 Schema 与 Runtime 工具事件产出路径

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 原则 | 检查 | 结果 |
|------|------|------|
| I. Spec-First | spec.md 已产出并经 clarify（3 问已回写） | ✅ |
| II. SSOT | 事件字段增补直接更新主定义 009 契约 + `schemas/agent_runtime.py`，前端类型派生对齐；本阶段无数据模型变更 | ✅ |
| III. Contract-First | 契约先行：`contracts/display-events.md` + 009 契约修订先于编码；无新 HTTP 端点、无 DB 变更 | ✅ |
| IV. Verify Before Ship | 交付前运行 `uv run pytest` / `uv run pyright` / `npm run build` / `npm run test:unit` | ✅ |
| V. Simplicity | 零新增依赖；不建持久化（Q1）；不还原历史卡片（Q3）；无新目录/空文件 | ✅ |
| VI. Feedback Loop | 009 FR-037"展示事件仅摘要"的演进以契约修订方式回写主定义并注明边界（日志不变） | ✅ |

## Project Structure

### Documentation (this feature)

```text
specs/010-tool-execution-display/
├── plan.md              # 本文件
├── research.md          # Phase 0 决策（R1~R9）
├── data-model.md        # 事件增补字段 + 前端展示实体
├── quickstart.md        # 验证指南
├── contracts/
│   └── display-events.md  # 事件增补 diff + 前端展示行为契约
└── tasks.md             # Phase 2 产出（/speckit-tasks）
```

### Source Code (repository root)

```text
backend/
├── app/
│   ├── core/config.py                     # + runtime_tool_params/result_max_chars
│   ├── schemas/agent_runtime.py           # ToolCallStarted/CompletedData 增补字段
│   └── services/agent_runtime/
│       ├── tools.py                       # ToolCallRecord 扩展 + run_tool 填充全量字段/易读名
│       └── runtime.py                     # 事件产出带新字段（含截断）
└── tests/
    ├── test_agent_runtime.py              # 新字段契约断言
    └── test_agent_runtime_fixtures.py     # 夹具适配

frontend/
├── src/
│   ├── api/chat.ts                        # 事件类型增补字段派生
│   ├── stores/chat.ts                     # 按会话运行槽 + activeStreams + 终态兜底映射
│   └── components/chat/
│       ├── ChatMessages.vue              # 卡片渲染接入 + 滚动增强 + 回到底部按钮
│       └── ToolProcessCard.vue           # 新组件：过程卡片（状态/摘要/展开详情）
└── src/components/chat/__tests__/         # 组件与 store 测试
```

**Structure Decision**: 遵循既有分层（AGENTS.md §3）；前端新组件放 `components/chat/`，状态进 Pinia chat store，无新页面与路由。后端不新增模块，仅扩展现有 Runtime 事件路径。

## Complexity Tracking

> 无宪法豁免项：本方案零新增依赖、零持久化、零新端点。
