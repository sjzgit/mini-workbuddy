# Quickstart: 上下文压缩与运行记录可观测（011）验证指南

> 本文件是端到端验证清单。实现细节见 [plan.md](./plan.md) 与 [tasks.md](./tasks.md)；契约见 [contracts/](./contracts/)；数据模型见 [data-model.md](./data-model.md)。

## 前置准备

```bash
# 后端（backend/ 内）
uv sync
uv run alembic upgrade head          # 应用本次迁移（runs/run_events/run_payloads/conversation_compactions + agents 4 列）
uv run python start_dev.py           # 启动后端（默认 8218，见 config.dev_server_port）

# 前端（frontend/ 内，注意 AGENTS.md §5 的 node 版本切换提示）
npm install
npm run dev
```

准备数据：模型管理中配置一个小上下文模型（如 `context_length=4096`、`max_output_tokens=512`，便于触发压缩）；创建绑定该模型的 Agent，确认"上下文压缩"分组四项默认值（开启 / 0.8 / 5 / 1000）。

## 自动化检查（交付门禁）

```bash
# 后端（backend/ 内）
uv run pytest                 # 全部通过（含新增 test_run_records.py、test_context_compression.py）
uv run pyright                # 无错误

# 前端（frontend/ 内）
npm run build                 # 零错误
npm run test:unit             # 全部通过（含新增 runs store/api spec）
```

## 验证场景

### 场景 1：运行记录持久化与生命周期（US1，契约 runs-api.md）

1. 聊天页发送一条消息 → 完成后执行：
   `curl http://127.0.0.1:8218/api/runs?page=1&page_size=20`
   → 第一条为本运行：`status="succeeded"`、`agent_name`/`model_name` 为快照、`model_call_count≥1`、`total_duration_ms>0`。
2. 生成中点击"停止" → 该 run `status="cancelled"`，end_reason 为取消人话；有正文则消息 incomplete 保留。
3. 构造模型失败（临时改错 base_url）→ run `status="failed"`，`error_summary` 有人话摘要，消息正文不含错误文本。
4. 运行中重启后端 → 启动后查列表：该 run `status="failed"` 且 end_reason 含"运行中断"。
5. 数据库删除某会话（或调既有删除入口）→ `runs`/`run_events`/`run_payloads`/`conversation_compactions` 对应行消失（级联）。

### 场景 2：列表指标与恒定查询（US2，SC-003/SC-005）

1. 列表页（`/runs`）按开始时间倒序展示；状态筛选与 Agent 筛选生效；翻页正常。
2. 断言查询次数（后端测试已覆盖）：同分页条件下 10 行与 50 行均为 2 条 SQL（COUNT + SELECT）。
3. 令模型不返回 usage → 列表 Token 列显示"未知"而非 0；无正文输出的 run 首个输出耗时显示"无正文输出"。
4. 修改 Agent 名称后刷新列表 → 历史行仍显示旧名（快照）。

### 场景 3：运行详情与时间线（US3）

1. 列表行点击打开详情抽屉：时间线含 run_started、模型请求（配对 call_id）、工具步骤（内置与 MCP 分别显示名称/Server 名）、最终回答、run_completed。
2. 工具步骤显示输入/结果**摘要**；"查看完整载荷"展开时才请求 `GET /api/runs/{run_id}/payloads/{id}`，内容为脱敏后全文。
3. 检查任一载荷与事件：无 `sk-` 密钥、无 Authorization、无用户设备绝对路径（workspace 路径显示为 `${workspace}`）。

### 场景 4：上下文自动压缩（US4）

1. 用小上下文模型连续对话直至触发（观察聊天流无异常，前端可忽略压缩事件）。
2. 详情时间线出现 `compression_started`（trigger_reason="threshold"、估算前后值）→ `compression_completed`（kept_rounds、boundary_seq、duration_ms）+ 一条 `purpose="context_compression"` 的模型请求（已计入 model_call_count）。
3. 查库 `conversation_compactions`：summary_text 非空、boundary_seq>0；聊天记录原文完整无删改。
4. 继续对话再次触发 → 摘要为增量更新（前版摘要进入新摘要请求），boundary_seq 单调推进。
5. 聊天页刷新 → 自动续播：生成中的会话恢复流式展示直至完成；后台完成的会话直接显示最终回答。

### 场景 5：压缩配置与关闭行为（US5）

1. Agent 编辑页"上下文压缩"分组：四项默认值与说明文案正确；非法值（如触发比例 0.3）保存被拦截并提示。
2. 关闭自动压缩后构造超容量输入 → 发送被 422 拦截，提示"缩短内容 / 开启压缩 / 新建会话"；无摘要请求发出（详情无 compression 事件）。

### 场景 6：压缩失败与备用裁剪（US6）

1. 测试态令摘要请求失败（mock 层脚本异常/超时）→ 详情出现 `compression_failed` + `compression_fallback`（dropped/kept 组数），本次对话仍成功返回；`conversation_compactions` 边界未变。
2. 压缩过程中点击停止 → run 以 cancelled 结束，压缩请求终止，无残留。

## 验收对照

| Spec 标准 | 对应场景 |
|-----------|----------|
| SC-001 七类退出路径状态正确 | 场景 1 + 自动化测试 |
| SC-002 事件配对与去重 | 场景 3.1 + test_run_records |
| SC-003 恒定查询次数 | 场景 2.2 |
| SC-004 敏感信息脱敏 | 场景 3.3 |
| SC-005 指标一致 | 场景 2.3 + 对账测试 |
| SC-006 压缩触发/历史保留/增量更新 | 场景 4 |
| SC-007 失败转备用、边界不变 | 场景 6.1 |
| SC-008 关闭压缩明确提示 / 首发超限 | 场景 5.2 + 固定内容超限测试 |
| SC-009 压缩统计与事件字段 | 场景 4.2 |
| SC-010 聊天卡片与详情一致 | 场景 3.2 与聊天工具卡片对照 |
