# Quickstart: 统一 Agent Runtime（009）验证指南

> 端到端验证本阶段成果。前置：后端（`backend/`，uv）与前端（`frontend/`，npm）可按 AGENTS.md §8 启动。

## 前置准备

1. 数据库已迁移：`cd backend && uv run alembic upgrade head`。
2. 至少一个可用模型（模型管理页配置并测试通过）。
3. 三个 Agent：
   - **直答 Agent**：不绑定任何工具/Skill/MCP。
   - **工具 Agent**：绑定 `current_time`（或 `shell`），max_rounds 默认 10。
   - **Skill Agent**：绑定一个已启用的 Skill（如说明为"如何查询系统信息"的目录），max_rounds 设为 2（用于轮数收尾验证）。
4. （可选，MCP 并发验证）一个 stdio 型 MCP Server 已配置、测试通过并启用。

## 启动

```bash
# 后端（backend/）
uv run python start_dev.py
# 前端（frontend/）
npm run dev
```

## 验证场景

### S1 直答链路经 Runtime（US1）

1. 聊天页选**直答 Agent**，发送"你好"。
2. 期望：流式回复正常，正文完整；后端日志出现 `[runtime]` 行：run_id、模型请求开始/结束、run_completed（status=completed）。
3. F12 Network → stream 响应：事件顺序 `run_started → model_request_started → (reasoning_delta|content_delta)* → model_request_completed → run_completed`，seq 严格递增，`run_completed` 恰一次且 `usage` 非 0 或 null（不出现假 0）。

### S2 工具循环与正文保留（US2）

1. 选**工具 Agent**，发送"现在几点了？请先说说你的打算再调用工具"。
2. 期望：先出现正文片段，随后"正在调用工具：current_time"提示，工具完成后继续输出最终回答。
3. 期望：工具调用前后正文全部按序保留，无覆盖/清空；事件含 `tool_call_started`（params_summary ≤200 字符）与 `tool_call_completed`（status=success，call_id 与 started 相同）。

### S3 Skill 按需加载（US3）

1. 选**Skill Agent**，发送符合该 Skill 用途的任务。
2. 期望：事件中出现 `tool_call_started`（tool_name=load_skill, tool_type=skill）→ `tool_call_completed`（status=success），模型随后按指令继续调用绑定工具或给出回答。
3. 反例：把 Skill 停用后重新运行 → 模型工具列表无 load_skill（日志确认目录为空）；直接伪造调用（或等模型尝试）→ 得到 `skill_not_found`/`skill_disabled` 类明确错误，运行不崩溃。

### S4 权限拒绝（US4）

1. 用**直答 Agent**（无工具）请求模型调用工具的输入（如诱导性 prompt），或观察日志中伪造的 tool_calls。
2. 期望：拒绝执行、错误交还模型、运行正常收尾；日志有 denied 记录。

### S5 轮数收尾（US7 决策 B）

1. **Skill Agent** max_rounds=2，发送需要多步工具的任务。
2. 期望：两轮后不再执行工具，出现一次收尾模型请求（round=max_rounds+1），最终有基于已有信息的回答；`run_completed.status=max_rounds`，消息落库为 completed。

### S6 取消与清理（US5）

1. 工具 Agent 生成中点击"停止"。
2. 期望：输出 1~3 秒内停止；`run_completed.status=cancelled, stopped=true`；有正文则消息落库 incomplete。
3. 关闭浏览器标签页（或断网）→ 期望后端日志触发取消并按取消路径收尾。

### S7 并发隔离（FR-039~043）

1. 两个浏览器窗口分别选不同 Agent 同时发送（不同会话）。
2. 期望：两个运行并行推进，输出互不串扰；日志中两套 run_id 的事件交错但各自 seq 独立递增。
3. 同一会话：窗口 A 发送后，窗口 B 对同一会话发送 → B 收到 409"会话正在生成中"。
4. 同一 MCP Server 被两个 Agent 同时调用 → 两个运行各自调用成功，结果不混淆（日志两套 call_id）。

### S8 事件契约与日志脱敏（US6）

1. 抽查任一含工具调用的运行日志与事件：无完整 Skill 指令正文、无未截断工具结果（>200 字符必被截断）、无 API Key。
2. `model_request_completed.usage` 各项：接口返回则非 0 整数，未返回则 null，绝无 0。

## 自动化检查（交付门禁，AGENTS.md §9）

```bash
cd backend  && uv run pytest && uv run pyright
cd frontend && npm run build && npm run test:unit
```

全绿方可交付。后端测试覆盖：事件顺序与配对、直答/工具循环/Skill 加载、轮数收尾、拒绝链、取消清理（假 MCP 连接）、并发会话互斥。
