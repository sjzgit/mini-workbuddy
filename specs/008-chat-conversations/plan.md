# Implementation Plan: 聊天功能（第八阶段）

**Branch**: `008-chat-conversations` | **Date**: 2026-09-14 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/008-chat-conversations/spec.md`

## Summary

在现有工作台实现聊天功能：左侧会话列表 + 右侧聊天区，用户选择 Agent 发送消息，后端以该 Agent 绑定的模型配置与系统提示词发起 OpenAI Chat Completions 兼容的流式请求，回复随生成进度以 SSE 事件推送到前端增量渲染（思考过程与正文分区、Markdown 展示）。会话与消息持久化到 SQLite（conversations / messages 两表），支持多轮上下文、会话内切换 Agent、停止生成与后台继续生成（进程内生成注册表 + 断线重连重放）。

技术方案要点：

- **流式链路**：后端 `openai_client` 新增异步流式调用（httpx `AsyncClient.stream`，解析 `data:` 分块中的 `content` / `reasoning_content` 增量）；FastAPI `StreamingResponse` 以 `text/event-stream` 下发 `reasoning_delta` / `content_delta` / `done` / `error` 事件。
- **后台生成**：每次生成注册为进程内任务（内存注册表 + `asyncio` 任务），SSE 端点是"订阅者"而非生成载体——前端断开、切换会话、离开页面都不影响生成；重新订阅先重放已有缓冲再继续实时推送（FR-022 / FR-021）。
- **持久化**：回复行在生成开始前落库（status=generating 占位），完成/停止/失败时一次性更新最终内容与状态，避免逐 delta 写库。
- **前端**：`stores/chat.ts` 管理会话/消息/生成态；`fetch` + `ReadableStream` 手动解析 SSE（POST 不能用 `EventSource`）；Markdown 用 `markdown-it` 渲染、`dompurify` 清洗。

## Technical Context

**Language/Version**: Python 3.12（backend，uv 管理）；TypeScript + Vue 3.5（frontend，npm 管理）

**Primary Dependencies**: FastAPI、SQLAlchemy 2.x、Alembic、httpx（含异步流式，已有依赖）、Pydantic；前端 Vue Router、Pinia、ant-design-vue、sass；**新增**：`markdown-it` + `dompurify`（前端运行时，FR-013 Markdown 渲染与 XSS 清洗）、`@types/markdown-it`（dev）

**Storage**: SQLite（唯一数据库，`backend/app.db`；新增 conversations / messages 两表，Alembic 迁移 + `sql/migrations/` 存档）

**Testing**: 后端 pytest（+ httpx TestClient，假流注入测试生成与停止）；前端 Vitest（SSE 解析器、store 状态流转、Markdown 清洗渲染）

**Target Platform**: 本地单用户 Web 工作台（现代桌面浏览器；开发环境 Vite 代理 `/api` → `127.0.0.1:8218`，代理透明转发 SSE 流）

**Project Type**: web-application（前后端分离，`frontend/` + `backend/`）

**Performance Goals**: 模型每个增量到达后 ≤50ms 内转发为 SSE 事件；会话列表为摘要查询、百级会话 <1s；输入发送到"正在思考"反馈为本地即时（消息保存一个 RTT）

**Constraints**: API Key 仅存在于后端调用链路（FR-010/FR-025）；同一会话生成期间互斥（禁止重复发送/切换 Agent，FR-020）；生成任务仅存进程内存，服务重启未完成任务如实显示为未完成（记录于 research R4）；不做上下文压缩（FR-018）

**Scale/Scope**: 单用户本地使用；2 张新表、8 个 API 端点、1 个页面 + 4~5 个聊天组件、1 个 Pinia store；纯前端展示不含权限与多租户

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 原则 | 检查项 | 结论 |
|------|--------|------|
| I. Spec-First | spec.md 已完成并通过质量清单；文档全部中文 | ✅ 通过 |
| II. SSOT | data-model.md 为两新表主定义 → ORM 对齐；contracts/chat-api.md 为接口主定义 → `schemas/chat.py` → `frontend/src/api/chat.ts` 三层对齐；UI 复用 tokens.scss 既有变量不新增 | ✅ 通过 |
| III. Contract-First | contracts/ 先于实现产出（本计划 Phase 1 即产出）；路径统一 `/api` 前缀，经 Vite 代理 | ✅ 通过 |
| IV. Verify Before Ship | quickstart.md 定义端到端验证；交付门禁沿用 AGENTS.md §9（pytest / pyright / build / vitest） | ✅ 通过 |
| V. Simplicity | 不引入消息队列/Redis/WebSocket 库——进程内注册表满足单用户后台生成；新依赖仅 markdown-it + dompurify（FR-013 直接消费方）；不预建会话删除、上下文压缩（明确范围外） | ✅ 通过 |
| VI. Feedback Loop | 发现规范与实现不符时回写 data-model / contracts 再改代码 | ✅ 通过 |
| 固定技术栈 | 未引入 React/Django 等；后端无新依赖；前端新增 Markdown 渲染库属功能必需（清单外"等价替代框架"不含展示类小库，且宪法 YAGNI 允许有明确需求的依赖） | ✅ 通过 |
| uv / npm 工作流 | 后端命令一律 `uv run`；前端经 npm scripts | ✅ 通过 |
| 数据库约束 | 两新表走 Alembic 迁移 + `sql/migrations/008-chat-conversations.sql` 存档；Session 经依赖注入 | ✅ 通过 |
| 目录结构 | 后端 api/ services/ schemas/ models/ 各归其位；前端 api/ stores/ components/chat/ views/ 分层 | ✅ 通过 |
| `0user chat/` 只读 | 仅读取需求文档，不写入 | ✅ 通过 |

## Project Structure

### Documentation (this feature)

```text
specs/008-chat-conversations/
├── plan.md              # 本文件
├── research.md          # Phase 0：技术决策（流式协议、后台生成、Markdown 选型等）
├── data-model.md        # Phase 1：conversations / messages 主定义 + 状态机
├── quickstart.md        # Phase 1：端到端验证指南
├── contracts/
│   └── chat-api.md      # Phase 1：REST + SSE 事件契约（唯一主定义）
└── tasks.md             # Phase 2 产出（/speckit-tasks，本命令不创建）
```

### Source Code (repository root)

```text
backend/
├── app/
│   ├── api/
│   │   └── chat.py                     # [新增] /api/conversations 路由（薄路由层）
│   ├── core/
│   │   └── config.py                   # [修改] 新增聊天相关常量（流超时等）
│   ├── models/
│   │   ├── __init__.py                 # [修改] 新增 ConversationEntry / MessageEntry
│   ├── schemas/
│   │   └── chat.py                     # [新增] 会话/消息/SSE 事件 Pydantic 契约实现
│   ├── services/
│   │   ├── chat_service.py             # [新增] 会话与消息业务（上下文构造、标题截取、seq 分配）
│   │   ├── generation_registry.py      # [新增] 进程内生成任务注册表（订阅/重放/停止）
│   │   └── openai_client.py            # [修改] 新增异步流式调用 stream_chat_completion
│   └── main.py                         # [修改] 注册 chat 路由
├── migrations/versions/
│   └── <rev>_add_conversations_and_messages_tables.py   # [新增] Alembic 迁移
├── tests/
│   ├── conftest.py                     # [修改] 新增 seed_agent / seed_conversation 夹具
│   ├── test_chat_api.py                # [新增] 会话与消息 REST 契约测试
│   └── test_chat_stream.py             # [新增] 流式事件、停止、异常分类测试
└── pyproject.toml                      # [不变] 无新增依赖

frontend/
├── src/
│   ├── api/
│   │   └── chat.ts                     # [新增] 会话/消息接口 + SSE 流解析封装
│   ├── components/chat/
│   │   ├── ConversationSidebar.vue     # [新增] 左侧会话列表 + 新建按钮
│   │   ├── ChatMessages.vue            # [新增] 消息区（滚动、自动到底）
│   │   ├── MessageBubble.vue           # [新增] 单条消息（Markdown 渲染、复制、重新生成）
│   │   └── ChatComposer.vue            # [新增] 输入区（发送/停止、Agent 选择、@ 唤起）
│   ├── stores/
│   │   └── chat.ts                     # [新增] 会话/消息/生成状态（Pinia）
│   ├── views/
│   │   └── ChatView.vue                # [重写] 占位页 → 聊天页布局容器
│   └── package.json                    # [修改] + markdown-it、dompurify、@types/markdown-it
└── tests（同目录 __tests__/）
    ├── chat-store.spec.ts              # [新增]
    └── sse-parse.spec.ts               # [新增]

sql/migrations/
└── 008-chat-conversations.sql          # [新增] 建表 SQL 存档（与 Alembic 对应）
```

**Structure Decision**: 沿用既有 web-application 双目录结构（Option 2），后端保持 api / services / schemas / models 分层，前端保持 api / stores / components / views 分层；聊天专属组件独立放 `components/chat/`，路由复用 `MODULES` 元数据中已注册的 `chat` 模块（现 ChatView 占位页原地重写，不改路由表）。

## Complexity Tracking

> 无宪法违例，无需记录。
