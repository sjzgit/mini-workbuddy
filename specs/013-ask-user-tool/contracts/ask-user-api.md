# Contract: Ask User 询问工具（第十三阶段）

**Date**: 2026-09-18 | **范围**: ask_user 工具定义、ask_user 事件、回答端点、交还模型的结果文本格式。本文件是四者的**主定义**（宪法 II/III），实现侧 MUST 与本文逐字段对齐，变更先改这里。

继承既有约定：工具治理见 [specs/003-tool-management/contracts/tool-definitions.md](../../003-tool-management/contracts/tool-definitions.md)；事件公共字段与转发见 [specs/009-agent-runtime/contracts/agent-runtime-api.md](../../009-agent-runtime/contracts/agent-runtime-api.md)。

## 1. 工具定义（注册表）

| 项 | 值 |
|----|-----|
| name | `ask_user` |
| display_name | `询问用户` |
| purpose | 向用户发起询问并等待回答；需要用户补充关键信息或在候选项间抉择时使用 |
| 工具类型 | builtin（纳入 003 治理：可启停、经 Agent 绑定后进入模型目录） |

**参数 JSON Schema**（Pydantic `AskUserParams`，extra="forbid"）：

| 参数 | 类型 | 必填 | 校验 | 说明 |
|------|------|------|------|------|
| `question` | string | 是 | strip 后 1–2000 字符 | 询问的问题文本 |
| `options` | list[string] | 否 | ≤10 项，每项 strip 后 1–200 字符；缺省/空 = 开放式 | 候选项；提供即为选项式 |
| `multi_select` | boolean | 否 | 缺省 false | 仅选项式有意义；true = 多选 |

**工具说明三节文本**（进注册表，工具管理页详情展示）：

- 适用场景：缺少完成任务所需的关键信息、需要在多个候选方案间由用户抉择、需要用户确认下一步方向时。
- 输入要求：question 为面向用户的完整问题；需要用户在候选项中选择时提供 options（2–10 个短选项），并用 multi_select 指明单选还是多选；仅提问不提供选项即开放回答。
- 使用限制：每轮运行不要重复询问同一问题；一次只问一个 waited 问题；自动运行（评测）场景无法获得回答，会收到"无用户可回答"的失败结果。

## 2. ask_user 事件（SSE）

```text
event: ask_user
data: { run_id, seq, round, call_id,
        question: string, options: string[], multi_select: boolean }
```

- 产出时机：`tool_call_started` 之后、等待回答之前；等待期间不再产出任何事件（FR-010 暂停）。
- 前端消费：按 `call_id` 关联弹窗；重连/刷新时随缓冲重放再次收到（弹窗恢复）。
- 回答端点成功后，运行继续：既有 `tool_call_completed`（status=success，result=回答文本）随之产出，前端据此关闭弹窗。

## 3. 回答端点

`POST /api/conversations/{conversation_id}/messages/{message_id}/ask-answers`

**请求体** `AskAnswerRequest`：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `call_id` | string | 是 | 询问事件的 call_id |
| `selected` | list[string] | 否 | 选中的选项文本（选择顺序）；开放式为空 |
| `text` | string \| null | 否 | 手动输入文本（开放式回答 / 选中"其他"时的输入） |

**响应** `200 {"resolved": true}`；错误：

| 状态 | 场景 | detail |
|------|------|--------|
| 404 | 会话/消息不存在 | 既有文案 |
| 404 | call_id 无对应等待中的询问（已答/已超时/不存在） | `没有等待回答的询问，可能已超时或已完成` |
| 422 | 回答整体为空（selected 空 且 text strip 后空） | `回答不能为空` |
| 409 | 消息对应的生成已结束（终态后到达的迟到回答） | `生成已结束，回答未被接受` |

- 幂等性：同一 call_id 的第二次提交得到 404（首次已消费）。
- 空回答校验与前端拦截双层（前端禁用提交按钮为主，服务端 422 兜底，FR-008）。

## 4. 交还模型的结果文本（result_for_model 格式主定义）

| 场景 | 文本 |
|------|------|
| 开放式 | 输入文本本身 |
| 选项式（单/多选） | 选中项按顺序以"、"连接，如 `方案A、方案C` |
| 选中"其他" | 输入文本本身 |
| 选中普通选项 + "其他" | `选项A、选项B；其他：自定义文本` |

超时/取消/无人值守交还模型的失败文本：

| error_code | 文本 |
|------------|------|
| `ask_user_timeout` | `用户未在 {N} 秒内回答本次询问。请基于已有信息继续，或调整方案后再询问` |
| `cancelled` | 复用既有取消文案（运行已取消，工具未执行） |
| `ask_user_unavailable` | `当前为自动运行（无聊天界面），没有用户可以回答；请基于已有信息继续或调整方案` |

## 5. tool_executor 直调行为

`tool_executor.execute("ask_user", ...)` → `success=false, error_code="execution_error"`，message：`ask_user 仅能在 Agent 运行中由模型调用，不支持直接执行`（挂起等待是运行内语义，见 research R6）。

## 6. 配置常量

| 常量 | 默认 | 说明 |
|------|------|------|
| `ask_user_timeout_seconds` | `300` | 等待回答上限（秒），环境变量可覆盖 |
