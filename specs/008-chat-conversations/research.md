# Research: 聊天功能（第八阶段）

**Date**: 2026-09-14 | **Feature**: `008-chat-conversations`

本功能没有遗留 NEEDS CLARIFICATION（spec 质量清单已确认）；本文记录实现层面的关键技术决策（Decision / Rationale / Alternatives），作为 tasks 与 implement 阶段的依据。

## R1 流式传输协议：SSE（fetch POST + 手动解析）

**Decision**: 后端用 FastAPI `StreamingResponse`（`text/event-stream`）下发 SSE 事件；前端用 `fetch`（POST 请求体）+ `ReadableStream` + `TextDecoder` 手动解析 SSE 帧。生成任务与 SSE 订阅解耦（见 R4）。

**Rationale**:
- 单向服务器推送场景，SSE 比 WebSocket 简单（无握手/心跳协议栈、经 Vite `http-proxy` 透明转发、天然兼容未来反向代理）。
- 浏览器原生 `EventSource` 只支持 GET，无法携带消息体，故用 fetch 手动解析——这也是 OpenAI 官方 SDK 流式模式的做法，解析逻辑约 40 行。
- 事件格式沿用 SSE 标准：`event: <类型>\ndata: <JSON>\n\n`，空闲期发 SSE 注释行 `: ping`（15s）防代理/浏览器空闲断连。

**Alternatives considered**:
- WebSocket：全双工能力本阶段用不到（无中途插话需求），引入连接生命周期管理与额外依赖，违反 Simplicity。
- 轮询：无法满足"随模型输出流式追加"（FR-012），延迟与请求量都不可接受。
- NDJSON（无 event 行）：可行但调试工具支持弱于 SSE，且放弃 SSE 语义没有换来任何简化。

## R2 思考过程的获取与深度思考参数映射

**Decision**:
- 流式增量解析同时读取 `choices[0].delta.content` 与 `choices[0].delta.reasoning_content`（OpenAI 兼容生态对推理模型的通用扩展字段，本项目对接的 GLM 系中转站返回该字段）；`reasoning_content` 归入思考过程事件，`content` 归入正文事件。无思考输出的模型自然只有 `content`，前端思考区隐藏——**不强依赖模型支持思考**。
- 深度思考参数映射：Agent 的 `enable_deep_thinking && thinking_level != 'off'` → 请求体附加 `"thinking": {"type": "enabled"}`；否则 `"thinking": {"type": "disabled"}`（GLM 系原生参数，中转站透传）。服务端不识别该字段时通常忽略，不影响普通请求；若个别服务端报 400，按既有错误分类提示，不做自动重试。
- 思考过程只展示不进上下文：后续请求的 `messages` 数组中历史消息只含 `content`，`reasoning_content` 不回传模型。

**Rationale**: 保持调用层与"OpenAI Chat Completions 兼容"这个既有约定（002 阶段 research R3）兼容；思考字段缺失时优雅降级为普通对话。

**Alternatives considered**:
- 引入推理参数 `reasoning_effort`（OpenAI o 系风格）：与本项目实际对接的 GLM 中转不匹配。
- 把思考内容拼进正文用 `<think>` 标记解析：格式脆弱、Markdown 渲染易串，且持久化层需要二次拆分。

## R3 上下文构造与超限判定

**Decision**:
- 上下文 = `[system?]` + 会话内按 `seq` 升序的**有效**消息：`role=user` 全部纳入 + `role=assistant` 且 `status=completed` 的（`incomplete` / `generating` 不纳入，FR-017/FR-023）；每条消息只含 `content`。本次用户消息已先落库，自然位于末尾且仅出现一次（FR-016）。
- system 消息取会话当前 Agent 的 `system_prompt`；为空则不放 system。Agent 切换后新请求用新 Agent 的 prompt + 同一会话历史（FR-019）。
- 超限判定用字符级启发式估算：`estimated_tokens ≈ ceil(total_chars × 0.6)`（中文为主场景的保守下限），`estimated_tokens + max_output_tokens > model.context_length` 时拒绝发送，返回 `422` + 固定文案（含"缩短输入或新建会话"指引，FR-018）。服务商侧仍返回上下文超限错误（400）时，错误分类归入 `context_overflow` 并在流内 `error` 事件提示——双保险，估算只是前置拦截。

**Rationale**: 不引入 tokenizer 依赖（tiktoken 对 GLM 词表也不准）；字符系数估算法虽粗，但作为"明显超限才拦"的前置防线足够，误放行由服务商 400 兜底。

**Alternatives considered**: tiktoken / transformers tokenizer：新增依赖且与实际模型词表不符，估算精度假象；完全不前置拦截：用户要等一整轮失败才得到反馈，体验差。

## R4 后台继续生成：进程内生成注册表 + 订阅重放

**Decision**:
- `POST .../messages` 只负责"落库用户消息 + 创建 generating 占位回复行 + 启动生成任务"，立即返回 201（含 `reply_message_id`）；**生成不在 SSE 请求生命周期内**。
- `generation_registry`（进程内存）持有每个生成任务：`asyncio.Task`、状态（running / completed / failed / stopped）、思考与正文缓冲、订阅者队列。SSE 端点 `GET .../messages/{id}/stream` 是纯订阅者：先重放缓冲、再实时跟随；`done` 后订阅立即收到终态事件。
- 前端离开页面/切换会话**不中断 fetch**——订阅由 Pinia store（全局单例）持有，组件卸载不清理；"停止生成"是唯一主动断开路径（`POST .../stop` → `asyncio.Task.cancel()` + 关闭上游 httpx 流）。
- 进程重启后注册表清空：`status=generating` 的孤儿回复行在下次被订阅（或加载会话）时识别为"任务不存在"，标记 `incomplete` 并提示"生成中断"。已生成内容因未逐 delta 落库而丢失——如实显示未完成，符合 FR-023/FR-024"未完成回复显示真实状态"。

**Rationale**: FR-022 要求切换会话/离开页面后台继续生成，这从根本上排除了"SSE 请求即生成"的简单模型；单用户本地工作台场景下进程内注册表已覆盖全部需求，无需任务队列。

**Alternatives considered**:
- SSE 请求即生成、断开即取消：直接违反 FR-022。
- WebSocket 双向通道 + 服务端会话恢复：能力过剩，复杂度高。
- 逐 delta 写库：SQLite 写放大 + 频繁行锁，收益仅为崩溃时多保留部分文本，不符合 Simplicity。

## R5 停止生成的取消机制

**Decision**: 停止 = `asyncio.Task.cancel()` + 上游 `AsyncClient.stream` 上下文退出（httpx 流随之关闭，服务端连接中断即"尽可能终止模型请求"）。任务内部捕获 `CancelledError` 与 `httpx.HTTPError`：已生成缓冲 > 0 → 回复行更新为 `incomplete`（保留部分正文）；缓冲为空 → 回复行删除（不创建空白回复，FR-024）。同时清注册表、广播 `done`（stopped=true）给订阅者。

**Rationale**: asyncio 协作式取消最直接；不承诺模型服务商侧立即停止计费（spec Assumptions 已声明"尽力而为"）。

**Alternatives considered**: 协作式检查点（每 delta 检查 stop 标志）：实现等价但响应延迟高；线程 + 事件：与既有异步链路割裂。

## R6 Markdown 渲染与 XSS 防护

**Decision**: 新增 `markdown-it`（渲染）+ `dompurify`（清洗），封装为 `frontend/src/utils/markdown.ts` 单一入口（启用 linkify、代码块围栏；禁用原始 HTML → `html: false`，再经 DOMPurify 二次清洗）；消息气泡内用 `v-html` 渲染清洗后结果。代码块不做语法高亮（等宽字体 Fira Code 展示，YAGNI）。

**Rationale**: 模型输出属不可信输入，`v-html` 必须两层防护（不解析原始 HTML + 白名单清洗）；markdown-it 类型支持完善（@types/markdown-it），dompurify 3.x 自带类型。两项均有大量当前消费方（每条消息渲染）。

**Alternatives considered**:
- `marked`：更小但历史 XSS 修复记录较多、类型需另配；无决定性优势。
- 自研受限渲染器：长尾 Markdown 语法覆盖不可控。
- 语法高亮（shiki/highlight.js）：spec 未要求，纯增重。

## R7 会话标题截取规则

**Decision**: 第一条用户消息保存成功后，取其去除首尾空白的前 20 个字符作为标题（截断时补省略号 `…`）；控制字符与换行折叠为空格。常量 `TITLE_MAX_CHARS = 20` 主定义在契约（contracts/chat-api.md），后端 `schemas/chat.py` 与前端类型文件只消费。更新入口仅在"标题仍为默认值『新会话』时"的首条用户消息路径，此后不再改标题（FR-007）。

**Rationale**: spec Assumptions 已定 20 字符；纯前端截取会把"标题事实"分裂到客户端，由后端在保存用户消息的同一事务内截取并更新会话，保证列表接口返回值一致。

**Alternatives considered**: 模型生成标题：spec 明确禁止（FR-007）；前端截取：SSOT 分裂。

## R8 重新生成语义：原地重置

**Decision**: `POST .../regenerate` 作用于最后一条 agent 回复：同事务内将其 `content`/`reasoning_content` 清空、`status` 重置为 `generating`（seq 不变，保持会话内位置），然后走与普通生成相同的任务启动与订阅流程。旧回复内容被覆盖，不再保留历史版本。

**Rationale**: spec Assumptions 已定"替换"；原地重置保证 `(conversation_id, seq)` 唯一性不被破坏，且上下文构造逻辑无需感知"重新生成"这一特殊状态。

**Alternatives considered**: 软删除旧行 + 追加新行：seq 唯一约束需让位逻辑复杂化，且"会话中间插入新回复"会产生歧义；前端本地替换：持久化事实分裂。

## R9 测试策略：假流注入

**Decision**:
- `openai_client.stream_chat_completion` 设计为可 monkeypatch 的模块级 async 生成器（产出 `ContentDelta` / `ReasoningDelta` 数据类）；后端测试用受控假流覆盖：正常多增量、首字即失败（401/400/超时）、流中途断开、空内容、思考与正文交错。
- SSE 断言用 TestClient 的 stream 模式逐帧解析；停止测试通过"假流阻塞在可控事件上 → 调 stop → 断言 incomplete 状态与事件序列"实现。
- 前端 Vitest 覆盖：SSE 帧解析器（分片边界、多事件、注释行）、chat store（上下文/状态流转/缓冲累积/错误终态）、MessageBubble 清洗渲染（script 注入被剥离）。

**Rationale**: 真实模型调用不可在 CI/本地测试中依赖；假流让异常分支可精确复现（现有 002 阶段 test_connection 测试同思路）。

**Alternatives considered**: 起本地 mock SSE 服务：更重，收益不高于 monkeypatch；只测前端解析器：后端事件契约（contracts）是唯一主定义，必须有契约测试锁住。

## R10 端口、代理与并发假设

**Decision**: 生成注册表假设**单进程**运行（start_dev.py 单 uvicorn worker）——多 worker 部署下 SSE 订阅可能路由到无该任务的进程，本阶段明确不支持并在本文记录；SQLite 单写者与单用户场景匹配。Vite 代理 `/api` 已存在，SSE 透传无需改配置（http-proxy 默认流式转发，`: ping` 心跳兜底空闲断连）。

**Rationale**: 本地工作台形态（宪法：紧凑工作台）；为多 worker 引入粘性路由/进程间总线远超当前需求。

**Alternatives considered**: 预留 Redis pub/sub：违反 YAGNI；数据库轮询替代注册表：延迟与写入成本高，且"逐 delta 落库"已否决。
