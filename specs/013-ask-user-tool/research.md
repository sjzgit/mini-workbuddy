# Research: Ask User 询问工具（第十三阶段）

**Date**: 2026-09-18 | **Status**: Complete

每项含 Decision / Rationale / Alternatives。spec 留给 Plan 的待决项（等待上限、无人值守判定、回答文本格式）全部解决。

---

## R1 等待机制：进程内挂起注册表 + asyncio.Event（核心）

**Decision**: 新模块 `services/agent_runtime/ask_user.py`，进程内注册表 `{call_id: PendingAsk}`，PendingAsk = `{answered: asyncio.Event, selected: list[str], text: str, cancelled: bool}`。runtime 工具分支 `run_tool` 中对 `ref == "ask_user"` 走专用异步分支 `_run_ask_user`：

1. 注册表校验参数（`AskUserParams`）
2. 发 `ask_user` 事件（结构化负载进 SSE 缓冲，弹窗与刷新恢复的数据源）
3. `asyncio.wait` 三路竞争：`answered.wait()` / `ctx.cancel.wait()` / `asyncio.timeout(settings.ask_user_timeout_seconds)`
4. 组装 `ToolCallOutcome`：回答 → success；取消 → cancelled；超时 → error（结构化文案交还模型）；finally 清理注册表

回答提交：新端点 POST `/api/conversations/{cid}/messages/{mid}/ask-answers` 按 call_id 查注册表 → 写入答案 → 置位 event → 唤醒挂起的运行。

**Rationale**: 复用 run_tool 既有的"永不抛异常、结构化 outcome"哲学；`asyncio.wait` 单点覆盖"回答/取消/超时"三退出路径；GenerationTask 事件缓冲天然让刷新后的订阅重放 `ask_user` 事件 → 弹窗自动重现（spec FR-012 免费满足）。取消复用既有 `ctx.cancel`（停止按钮置位），无需新通道。

**Alternatives**:
- *把回答持久化到 DB，轮询读取*：多一张表 + 轮询延迟，单进程内存事件已足够（先例 generation_registry），否决。
- *工具执行器 tool_executor.execute 内实现等待*：tool_executor 是同步统一入口且无 emitter/取消上下文，挂起语义只属于运行内；tool_executor 对 ask_user 返回"仅在 Agent 运行中可用"（执行层拒绝，见 R6）。
- *复用 tool_call_started 事件承载问题（前端解析 params JSON）*：弹窗需要强类型字段（options 数组、multi_select 布尔），解析参数 JSON 脆弱且语义混淆；专用事件更清晰。

---

## R2 无人值守判定：RunRequest.reply_message_id is None

**Decision**: `_run_ask_user` 执行时检查 `ctx.run_request.reply_message_id is None` → 立即返回 `ToolCallOutcome(success=False, error_code="ask_user_unavailable", message="当前为自动运行（无聊天界面），没有用户可以回答；请基于已有信息继续或调整方案")`，不注册等待、不发事件。

**Rationale**: RunRequest 契约（009 §6）明确评测直调场景 conversation_id / reply_message_id 皆空——这是既有契约给出的"有无交互界面在场"判定，零新增概念；评测 runner 与未来其他直调方自动覆盖。失败文案按 spec Assumptions 要求让模型能自行调整。

**Alternatives**: *从工具目录中摘除（评测运行不暴露该工具）*：模型得到 tool_not_found 无法理解原因；spec FR-014 要求"返回明确失败结果"而非"工具不存在"，否决。

---

## R3 事件契约与转发链路

**Decision**: 新事件 `ask_user`（EVENT_ASK_USER），负载 `AskUserData{round, call_id, question, options: list[str], multi_select: bool}`。链路三处接线：

1. **chat 桥接**（chat_service._run_generation）：加入原样转发白名单（与 tool_call_* 同分支，经 `_SSE_STRIP_KEYS` 剥离无透传字段——本事件无透传字段）
2. **RunRecorder**：`ask_user` 按结构性事件 `_insert_event` 落 run_events（运行记录时间线可回放；result 经既有 tool_call_completed 的 tool_result payload 完整保存，FR-016 免费满足）
3. **前端**：api/chat.ts StreamEvent 联合 + dispatchFrame case + chat store `pendingAsk` 槽位（按会话隔离，`tool_call_completed`/终态时清除）

**Rationale**: 011 已确立"新事件 = Schema 常量 + 桥接白名单 + Recorder 分支"三件套模式，照章办事；前端 store 槽位制（RunDisplayState）已按会话隔离，弹窗状态挂槽位即可支持"切走再切回弹窗仍在"。

**Alternatives**: *前端从 tool_call_started 的 params 解析*：见 R1 否决理由。

---

## R4 回答文本格式（交还模型的 result_for_model）

**Decision**（契约主定义，含示例）：

- 开放式：输入文本本身（strip 后）
- 选项式：选中选项按顺序以"、"连接（如 `方案A、方案C`）
- 选中"其他"：输入文本作为回答；若同时选中普通选项与"其他"：`选项A、选项B；其他：自定义文本`
- 多选与单选格式一致（多选天然多项连接）

**Rationale**: 全中文场景用"、"连接最贴近模型阅读习惯；"其他"带前缀标注让模型能区分候选与自由输入；格式确定性强、可测试。

**Alternatives**: *JSON 结构化交还*：对模型可读性差且多数模型对纯文本工具结果响应更好；*逐行列表*：短选项场景浪费 token。

---

## R5 参数校验与边界（AskUserParams）

**Decision**: `question: str`（strip 后 1–2000 字符，必填）；`options: list[str] | None`（≤10 项，每项 strip 后 1–200 字符，空列表按 None 处理 → 开放式）；`multi_select: bool = False`（options 为空时忽略）。空选项列表、未指定 multi_select 默认单选，均与 spec Edge Cases 一致。

**Rationale**: 与注册表既有参数模型（ConfigDict extra="forbid"）同构；上限防模型生成超长弹窗；"strip 后 1–200"直接杜绝全空白选项。

---

## R6 tool_executor 对 ask_user 的行为

**Decision**: `tool_executor._dispatch` 中 ask_user 不接入 handler 映射，落入"尚未接入"路径——改造为显式分支：返回 `ToolExecutionResult(success=False, error_code="execution_error", message="ask_user 仅能在 Agent 运行（聊天/评测经 Runtime）中由模型调用，不支持直接执行")`。

**Rationale**: tool_executor 是同步统一入口（003 契约），挂起等待是运行内语义（R1）；显式人话拒绝避免误导调试者。Runtime 的 run_tool 不经 tool_executor 执行 ask_user（专用分支），两者不冲突。

---

## R7 播种与配置

**Decision**:

- 新迁移 `add ask_user tool seed`：`INSERT INTO tools (name, enabled, ...) SELECT ... WHERE NOT EXISTS`（幂等，防重复种子）；SQL 存档 `sql/migrations/013-ask-user-tool.sql`
- config.py 新增 `ask_user_timeout_seconds: int = 300`（5 分钟；FR-013 的"可在系统配置中调整"落点）

**Rationale**: 幂等 WHERE NOT EXISTS 保证重复 upgrade 安全；300 秒覆盖"用户离开片刻"场景又不至于会话长时间占用（可环境变量覆盖）。

---

## R8 前端弹窗组件与状态

**Decision**: 新组件 `components/chat/AskUserModal.vue`（ant-design-vue Modal，:closable=false :mask-closable=false :keyboard=false——回答是必答阻塞项，唯一出路是回答或点停止）：

- 开放式：问题 + textarea，strip 非空才可提交
- 选项式单选：Radio.Group + 末尾固定"其他，我手动输入"；选其他 → 下方 textarea
- 选项式多选：Checkbox.Group，同上追加
- 提交按钮 loading 防重复（FR-017）；失败提示且弹窗不关
- store：`RunDisplayState.pendingAsk: {callId, question, options, multiSelect} | null`；`ask_user` 事件置位；`tool_call_completed`（该 call_id）与 `finalizeRun` 清位

**Rationale**: 必答阻塞语义下禁用意外关闭路径，防止用户误触丢问；状态放槽位与既有 run 展示状态同生命周期；防重复提交走既有过 debounce/loading 模式。

**Alternatives**: *可关闭弹窗 + 聊天流内卡片重新打开*：交互绕弯，首版从简；*Drawer 而非 Modal*：需求明确"弹窗"，Modal 贴合。

---

## 结论

spec 待决项全部解决：**R1 挂起注册表 + 三路 asyncio.wait**、**R2 reply_message_id 判无人值守** 为架构核心；等待上限 300s（R7）、回答文本格式（R4）均已定值并进契约。零新增第三方依赖。
