# Implementation Plan: Ask User 询问工具（第十三阶段）

**Branch**: `013-ask-user-tool` | **Date**: 2026-09-18 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/013-ask-user-tool/spec.md`

## Summary

在工具管理体系中新增内置工具 `ask_user`（询问用户）：模型经 Runtime 工具循环调用后，运行挂起等待——聊天界面通过新增的 `ask_user` SSE 事件弹出询问弹窗（开放式输入框 / 选项式单选多选 + 自动追加"其他，我手动输入"），使用者经新端点提交回答，答案作为工具结果交还模型、运行恢复推进。等待机制为进程内挂起注册表 + asyncio 三路等待（回答 / 取消 / 超时 300s 可配）；无人值守场景（评测直调，`reply_message_id is None`）立即返回明确失败结果。工具治理（启停/绑定/目录）与运行记录（问答入 run_events + tool_result payload）全部复用既有机制，**零新增数据库表、零新增第三方依赖**。

## Technical Context

**Language/Version**: 后端 Python 3.12（FastAPI + Pydantic + SQLAlchemy 2.x + Alembic + SQLite，uv 工作流）；前端 Vue 3 + TypeScript + Vite + Pinia + Ant Design Vue

**Primary Dependencies**: 全部复用现有模块，零新增第三方依赖：
- `agent_runtime.tools.run_tool` —— 新增 ask_user 专用异步分支（挂起/等待/取消/超时）
- `RunEventEmitter` + 事件桥接（chat_service 白名单转发）+ `RunRecorder` —— 新事件 `ask_user` 三件套接线（011 先例）
- `generation_registry.GenerationTask.buffer` —— 事件缓冲重放，刷新恢复免费获得（FR-012）
- `tool_registry` + `tools` 表 + `agent_bindings` —— 治理复用（003/007 机制）

**Storage**: SQLite；**无新表**，仅 `tools` 表幂等补种一行（`ask_user`, enabled=1）；等待状态为进程内注册表（先例 generation_registry，单实例假设）

**Testing**: pytest（后端：内存库 + TestClient + 假流注入，评测/聊天测试既有模式）+ Vitest（前端 store 与组件）

**Target Platform**: 本地工作台（后端 uvicorn:8218，前端 Vite 代理 `/api`）

**Project Type**: Web 应用（frontend + backend）

**Performance Goals**: 回答提交 → 运行恢复 < 1s（进程内事件唤醒）；等待上限默认 300s（`ask_user_timeout_seconds` 可配）

**Constraints**:
- 等待回答期间运行零事件产出（FR-010）；运行结束时挂起注册表零残留（finally 兜底）
- 取消不经回答路径：cancelled 不作为有效回答交还模型（FR-011）
- 无人值守 100% fail-fast 不挂起（FR-014，判定 = reply_message_id is None）
- 空回答双层拦截（前端禁用提交 + 服务端 422）
- ask_user 不接入 tool_executor 同步入口（显式人话拒绝，research R6）

**Scale/Scope**: 单用户本地工作台；后端 1 个新服务模块 + 1 个新端点 + 1 条数据迁移 + 事件契约扩展；前端 1 个弹窗组件 + store/api 接线

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 原则 | 结论 | 说明 |
|------|------|------|
| I. Spec-First | ✅ | spec.md 已产出并通过质量清单（16/16）；等待上限/无人值守判定留给 plan 的项均已在 research 定值 |
| II. SSOT | ✅ | 工具定义/事件/端点/结果文本格式主定义 = `contracts/ask-user-api.md` → `tool_registry` / `schemas/agent_runtime.py` / `schemas/chat.py` 三层对齐；等待注册表为运行期结构（data-model.md §2 主定义）；无新数据表 |
| III. Contract-First | ✅ | 契约先于编码；`ask_user` 事件负载与回答端点 Schema 逐字段对齐；路径 `/api/conversations/...` 沿用 Vite 代理前缀 |
| IV. Verify Before Ship | ✅ | 交付门禁四连 + `/speckit-analyze`；等待/取消/超时三退出路径均有专项测试 |
| V. Simplicity | ✅ | 零新增依赖；零新表；无人在场判定复用既有 RunRequest 字段；治理/记录/取消全部复用既有机制，不自建第二套 |
| VI. Feedback Loop | ✅ | 契约变更先改 ask-user-api.md 再同步实现；实现中发现 spec 偏差回写主定义 |
| 固定技术栈 | ✅ | 未引入清单外框架；uv / npm 依赖管理 |
| 数据库约束 | ✅ | SQLite 唯一数据库；仅数据迁移（幂等补种一行）并存档 `sql/migrations/` |
| 目录分层 | ✅ | 运行内新逻辑入 `services/agent_runtime/ask_user.py`（先例：模块化子包）；路由薄；schemas 各归其位 |
| 前端规范 | ✅ | Composition API + ant-design-vue + 设计令牌 + Pinia 槽位状态；`/api` 相对路径 |
| `0user chat/` 只读 | ✅ | 本特性需求来自用户消息，未写入该目录 |

**Post-design re-check（Phase 1 后）**: ✅ 契约/数据模型/事件三件套经复核无违例；ask_user 走 run_tool 专用分支而非改 tool_executor 同步语义，未破坏 003 既有契约（其直调行为在 ask-user-api.md §5 显式定义）。

## Project Structure

### Documentation (this feature)

```text
specs/013-ask-user-tool/
├── plan.md                    # 本文件
├── research.md                # Phase 0：八项决策（等待机制/无人值守/格式等）
├── data-model.md              # Phase 1：种子行 + 挂起注册表 + 事件负载 + 状态机
├── contracts/ask-user-api.md  # Phase 1：工具定义/事件/端点/结果文本主定义
├── quickstart.md              # Phase 1：端到端验证指南
└── tasks.md                   # Phase 2 输出（/speckit-tasks）
```

### Source Code (repository root)

```text
backend/
├── app/
│   ├── core/config.py                     # +ask_user_timeout_seconds=300
│   ├── models/__init__.py                 # （无变更，tools/agent_bindings 既有）
│   ├── schemas/
│   │   ├── agent_runtime.py               # +EVENT_ASK_USER 常量与 AskUserData 负载
│   │   └── chat.py                        # +AskAnswerRequest / AskAnswerResponse
│   ├── services/
│   │   ├── tool_registry.py               # +ask_user 定义与 AskUserParams
│   │   ├── tool_executor.py               # ask_user 直调 → 显式人话拒绝（R6）
│   │   ├── chat_service.py                # 桥接白名单 +EVENT_ASK_USER；迟到回答 409 判定辅助
│   │   └── agent_runtime/
│   │       ├── ask_user.py                # 【新】PendingAsk 注册表 + 回答提交 + 文本格式化
│   │       ├── tools.py                   # run_tool +ask_user 分支（等待/取消/超时三路）
│   │       ├── events.py                  # 导出 EVENT_ASK_USER
│   │       └── recorder.py                # ask_user 事件落 run_events
│   ├── api/chat.py                        # +POST /{cid}/messages/{mid}/ask-answers
│   └── main.py                            # （无变更，chat 路由已注册）
├── migrations/versions/                   # +add ask_user tool seed（幂等 INSERT WHERE NOT EXISTS）
├── tests/
│   ├── conftest.py                        # （复用既有夹具；如需挂起注册表隔离则补 fixture）
│   ├── test_ask_user_runtime.py           # 【新】等待/回答/取消/超时/无人值守/参数校验/目录治理
│   └── test_chat_ask_answers_api.py       # 【新】回答端点契约（成功/404/422/409）+ 桥接转发

frontend/src/
├── api/chat.ts                            # StreamEvent 联合 + ask_user case + answerAsk API + 类型
├── stores/chat.ts                         # RunDisplayState +pendingAsk；ask_user/completed/终态接线
├── components/chat/
│   ├── AskUserModal.vue                   # 【新】弹窗（开放式/单选/多选/其他输入/防重复提交）
│   └── __tests__/askUserModal.spec.ts     # 【新】弹窗校验逻辑（空回答拦截/其他联动/格式拼装）
├── views/ChatView.vue                     # 挂载 AskUserModal（按当前会话 pendingAsk 渲染）
└── components/runs/RunTimeline.vue        # ask_user 事件时间线展示（问题+回答行）
```

**Structure Decision**: 全部变更落在既有分层位置——运行内语义进 `agent_runtime/` 子包（009 先例），HTTP 契约进 `schemas/chat.py` + `api/chat.py`，前端走 store 槽位 + 组件。唯一新文件是挂起注册表模块与弹窗组件，其余为既有文件的定向扩展。

## Complexity Tracking

> 无 Constitution Check 违规，无需填写。
