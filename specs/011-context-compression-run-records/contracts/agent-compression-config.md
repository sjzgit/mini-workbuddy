# Contract: Agent 压缩配置（011）

**Date**: 2026-09-15

本文件是 Agent 压缩配置四字段的**唯一主定义**（对 007 Agent API 契约的增补）。后端 `backend/app/schemas/agents.py` 与前端 `frontend/src/api/agents.ts` MUST 与本文逐字段对齐；数据列定义见 [data-model.md](../data-model.md) §2。

## 字段定义

| 字段 | 类型 | 默认 | 校验 | 说明 |
|------|------|------|------|------|
| `auto_compact` | boolean | `true` | — | 自动压缩开关；关闭后不调用模型生成摘要（FR-027） |
| `compact_trigger_ratio` | number | `0.8` | `0.5 ≤ r ≤ 0.95` | 触发比例：估算输入达到可用输入容量的该比例时触发压缩 |
| `compact_keep_recent_rounds` | integer | `5` | `1 ≤ n ≤ 50` | 保留最近完整对话轮数（每轮 = 用户消息 + 回答 + 相关工具交互） |
| `compact_summary_target_tokens` | integer | `1000` | `100 ≤ n ≤ 8000` | 摘要生成目标长度（软目标，不保证精确等长；执行时受可用容量二次限制） |

常量主定义（`schemas/agents.py`，前端 `api/agents.ts` 镜像）：

```text
AUTO_COMPACT_DEFAULT            = true
COMPACT_TRIGGER_RATIO_DEFAULT   = 0.8
COMPACT_TRIGGER_RATIO_MIN/MAX   = 0.5 / 0.95
COMPACT_KEEP_ROUNDS_DEFAULT     = 5
COMPACT_KEEP_ROUNDS_MIN/MAX     = 1 / 50
COMPACT_SUMMARY_TARGET_DEFAULT  = 1000
COMPACT_SUMMARY_TARGET_MIN/MAX  = 100 / 8000
```

## API 变更

- `POST /api/agents`、`PUT /api/agents/{id}` 请求体增上述 4 字段（全部可选，缺省用默认值；显式传非法值 422）。
- `GET /api/agents/{id}` 响应增上述 4 字段；`GET /api/agents`（列表/卡片）**不变**——压缩配置属编辑态参数，列表卡片不展示（2026-09-16 分析 F1 修订）。
- 其余 007 契约端点与语义不变。

校验失败示例：`422 {"detail": "触发比例需在 0.5 ~ 0.95 之间"}`（人话，指明字段与合法范围）。

## Agent 管理页展示要求（FR-025"清晰说明"）

四个字段放入 Agent 编辑弹窗"Agent 编排"区新增的"上下文压缩"分组，控件与说明文案：

| 字段 | 控件 | 说明文案（辅助文字） |
|------|------|----------------------|
| 自动压缩 | Switch | 会话接近模型上下文容量时，自动把较早对话整理为摘要 |
| 触发比例 | InputNumber（step 0.05，min 0.5，max 0.95） | 估算输入达到可用容量的该比例时触发压缩 |
| 保留最近对话轮数 | InputNumber（整数，1~50） | 压缩时完整保留最近 N 轮对话（含工具交互） |
| 摘要目标长度 | InputNumber（整数，100~8000，单位 Token） | 生成摘要的目标长度（估算值，不保证精确等长）；小窗口模型下会自动受限 |

校验错误就地展示（沿用现有 maxRounds 的 validator 模式）。

## 运行时消费

- Runtime 在运行启动加载 Agent 配置时一并读取四字段；`auto_compact=false` 时跳过全部压缩逻辑（不发起摘要请求，FR-027）。
- 关闭压缩且输入超容量：发送时 422（沿用 008 `CONTEXT_OVERFLOW_DETAIL`，文案增补"开启自动压缩"指引）；运行中每轮检查失败则 `error(context_overflow)` 结束运行。
