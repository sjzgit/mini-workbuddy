# Implementation Plan: 统一 Agent Runtime（009）

**Branch**: `009-agent-runtime` | **Date**: 2026-09-15 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/009-agent-runtime/spec.md`

## Summary

在后端建立统一 Agent Runtime（`services/agent_runtime/` 包），把 Agent Loop（模型调用 + 工具循环 + Skill 按需加载 + 取消清理 + 统一事件）从聊天层剥离：聊天接口瘦身为"接收请求 + 转发事件"，通过消费 `execute_run` 的事件流桥接到既有 SSE 通道；复用现有模型调用（openai_client 扩展工具调用与 usage）与工具执行基础设施（tool_executor），MCP 按运行独享连接（AsyncExitStack）实现并发隔离；本阶段无数据库变更、无评测模块、无运行记录持久化。

## Technical Context

**Language/Version**: Python 3.12（backend/pyproject.toml）；前端 TypeScript + Vue 3

**Primary Dependencies**: FastAPI、Pydantic、SQLAlchemy、httpx、mcp（SDK）、jsonschema（mcp 传递依赖，用于 MCP 参数校验）；前端 Pinia、Vitest

**Storage**: SQLite（既有表，零迁移）；Skill 指令以 workspace/skills/ 文件为本体

**Testing**: 后端 pytest + httpx TestClient（假模型流/假 MCP 连接）；前端 Vitest；门禁 pytest + pyright + build + vitest 全绿

**Target Platform**: Windows/单机本地工作台，单进程单事件循环

**Performance Goals**: 取消后 ≤3 秒停止模型输出（SC-008）；流式增量无锁队列直通（沿用 008 GenerationTask 模式）

**Constraints**: 运行记录不持久化（FR-007）；Runtime 不依赖 HTTP 对象（FR-005）；聊天接口不自维护模型/工具循环（FR-004）；会话级互斥 409（FR-043）

**Scale/Scope**: 多浏览器客户端并发（每会话至多 1 个运行）；工具目录 = 绑定∩启用的内置工具 + MCP 工具 + load_skill

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 原则 | 结论 | 依据 |
|------|------|------|
| I. Spec-First | ✅ | spec.md 已产出并澄清（含 5 条 Clarifications） |
| II. SSOT | ✅ | 事件/工具命名/load_skill 主定义在 contracts/agent-runtime-api.md；schemas/agent_runtime.py 为代码侧落点；008 chat-api.md 追加修订记录避免双源冲突；无数据模型变更 |
| III. Contract-First | ✅ | 本计划先产出契约与 schema 设计，后实现；SSE 事件集修订已在契约中显式声明 |
| IV. Verify Before Ship | ✅ | quickstart.md 门禁 = AGENTS.md §9 四项全绿 |
| V. Simplicity | ✅ | 零新依赖（jsonschema 为 mcp 传递依赖）；零新表零迁移；MCP 每运行独享连接而非连接池（YAGNI）；无并发上限队列 |
| VI. Feedback Loop | ✅ | 008 契约被修订处在 009 契约中显式登记 |
| uv 工作流 / 技术栈 | ✅ | 无新依赖、无栈外框架 |

## Project Structure

### Documentation (this feature)

```text
specs/009-agent-runtime/
├── plan.md              # 本文件
├── research.md          # R1~R12 决策
├── data-model.md        # 运行期内存实体 + 配置项（零迁移）
├── quickstart.md        # S1~S8 验证场景
├── contracts/
│   └── agent-runtime-api.md   # 事件契约主定义（唯一新增契约）
└── tasks.md             # /speckit-tasks 产出
```

### Source Code (repository root)

```text
backend/
├── app/
│   ├── core/config.py                    # +3 个 runtime 配置项
│   ├── schemas/agent_runtime.py          # 新增：事件 data 结构（契约 §3 落点）
│   ├── services/
│   │   ├── openai_client.py              # 扩展：tools 参数、ToolCallDelta、UsageInfo
│   │   ├── chat_service.py               # 重构：直答生成 → 消费 execute_run 事件桥接
│   │   └── agent_runtime/                # 新增：Runtime 包
│   │       ├── __init__.py               # 公共接口（RunRequest/RunLimits/execute_run）
│   │       ├── events.py                 # RunEvent、事件类型常量、seq 调度
│   │       ├── skills.py                 # Skill 目录 + load_skill 执行链
│   │       ├── tools.py                  # 工具目录/命名映射/统一执行入口（内置+MCP+skill）
│   │       └── runtime.py                # RunContext + Agent Loop + 取消清理
│   └── api/chat.py                       # 微调：stream 端点断开检测传入
└── tests/
    ├── test_agent_runtime.py             # 新增：循环/工具/Skill/取消/事件单测
    ├── test_chat_runtime_api.py          # 新增：SSE 新事件与终态落库
    ├── test_chat_stream.py               # 更新：done → run_completed
    └── test_chat_api.py                  # 更新：受影响断言

frontend/
├── src/api/chat.ts                       # 事件联合类型扩展 + run_completed
├── src/stores/chat.ts                    # toolStatus/phase('tool')/run_completed 处理
├── src/components/chat/ChatMessages.vue  # "正在调用工具：×"简要提示
└── src/stores/__tests__/chat.spec.ts     # 用例更新
```

**Structure Decision**: Runtime 以 `services/agent_runtime/` 包落地（R1）：四个子模块分关切点，公共接口收敛在 `__init__.py`；聊天层仅经 `execute_run` 消费事件，保证 FR-004/005 的边界。测试文件与现有命名风格一致。

## Complexity Tracking

> 无宪法违规，不需要豁免。

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| （空） | — | — |
