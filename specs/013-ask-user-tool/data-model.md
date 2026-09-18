# Data Model: Ask User 询问工具（第十三阶段）

**Date**: 2026-09-18 | **Source of Truth**: 本文件是数据模型的主定义（宪法 II/III）。本特性**无新表**——数据面仅一行种子数据与一张进程内注册表。

## 1. 数据库变更：tools 表补一行种子

| 表 | 变更 | 说明 |
|----|------|------|
| `tools` | INSERT 一行：`name='ask_user'`, `enabled=1` | 迁移用 `WHERE NOT EXISTS` 幂等写入；与 003 播种三行同构 |

无 Schema 变更、无 Alembic 表结构操作（仅数据迁移）；`sql/migrations/013-ask-user-tool.sql` 存档。启停/绑定复用 `tools.enabled` 与 `agent_bindings`（resource_type='tool'），零新列。

## 2. 进程内挂起注册表（非持久化）

`services/agent_runtime/ask_user.py` 模块级注册表（先例：generation_registry）：

```text
PendingAsk（一次等待中的询问）
┌──────────────────────────────────┐
│ answered: asyncio.Event          │  回答/取消/超时任一路径置位唤醒
│ selected: list[str]              │  选中的选项（选择顺序）
│ text: str                        │  手动输入文本（开放式/其他）
│ cancelled: bool                  │  等待中运行被取消（非有效回答）
└──────────────────────────────────┘
键：call_id（tool 调用标识，'t' 前缀随机，碰撞概率可忽略）
```

- 写入方：runtime `_run_ask_user`（注册后等待）；`answer` 端点（写入答案并置位）
- 生命周期：注册 → 答复/取消/超时任一 → 读取 → finally 移除；运行结束不残留（兜底 finally）
- 单进程假设与 generation_registry 相同（宪法既定单实例部署）

## 3. 事件负载（契约 §2 的数据面）

`ask_user` 事件 data（公共字段 run_id/seq 之外）：

| 字段 | 类型 | 说明 |
|------|------|------|
| `round` | int | 所在运行轮次 |
| `call_id` | string | 工具调用标识（回答端点按此定位） |
| `question` | string | 问题文本 |
| `options` | list[string] | 选项列表；空 = 开放式 |
| `multi_select` | boolean | 是否多选（仅选项式有意义） |

## 4. 状态机

```text
[模型调用 ask_user]
  ├─ reply_message_id=None（评测直调）──► 立即失败结果 ask_user_unavailable（不注册）
  ├─ 参数非法 ──► invalid_params（denied）
  └─ 注册 PendingAsk + 发 ask_user 事件 ──► 等待中（运行暂停推进）
        ├─ POST ask-answers（有效回答）──► success：回答文本交还模型，弹窗关
        ├─ cancel 置位（用户停止）──► cancelled：无回答交还，运行取消终态
        └─ 超时（300s 可配）──► error：结构化超时文案交还模型，运行继续
```

## 5. 与 spec 需求映射

| spec 需求 | 数据面落点 |
|-----------|-----------|
| FR-001~003 治理 | tools 种子行 + 既有 enabled/agent_bindings 复用 |
| FR-004/012 弹窗与恢复 | ask_user 事件（GenerationTask 缓冲重放） |
| FR-009/010 回答与暂停 | PendingAsk 注册表 + asyncio.wait |
| FR-011 取消 | ctx.cancel（既有停止通道）+ cancelled 标记 |
| FR-013 上限 | settings.ask_user_timeout_seconds |
| FR-014 无人值守 | reply_message_id 判定（R2） |
| FR-016 记录 | ask_user 落 run_events + tool_result payload（既有） |
