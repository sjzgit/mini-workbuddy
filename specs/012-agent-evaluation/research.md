# Research: Agent 评测系统（specs/012-agent-evaluation）

> 本 feature 无 NEEDS CLARIFICATION 未决项（spec 质量检查 0 标记）。以下研究针对"现有代码如何支撑 spec"逐项决策，全部结论已核对源码。

## D1：Agent 执行入口 —— 复用 `execute_run`，评测零第二套循环

**Decision**: 评测通过 `app/services/agent_runtime.execute_run(RunRequest)` 执行每个 Case（FR-009 / Invariant 1/2）。

**Rationale**: 源码核实（`agent_runtime/__init__.py:63`）：
- `RunRequest.conversation_id=None, reply_message_id=None` 的评测直调场景 011 已显式支持（`RunRequest` docstring；`runtime.py` 中压缩逻辑在 `conversation_id is None` 时跳过）
- `execute_run` 内部驱动 `RunRecorder` 自动持久化 runs/run_events/run_payloads 三表 —— AgentRun 记录零成本获得（FR-011）
- `user_message` 传 Case 的 `user_question`，`history=[]`（每 Case 独立上下文，FR-010 / Invariant 3）
- 终态判定：`RunCompletedData.status in ("completed", "max_rounds")` 且 `content_text` 非空 → 评分；`status in ("error", "cancelled")` → EXECUTION_FAILED

**Alternatives considered**: 评测自建 Agent Loop（spec 明令禁止）；直接调 `stream_chat_completion`（绕过工具循环/Recorder，禁止）。

## D2：CaseRun ↔ AgentRun 关联 —— 直接持有 `run_id`

**Decision**: CaseRun 新增 `agent_run_id` 字段存 `run_id`（String(64)，非外键）。

**Rationale**: 现有 `RunEntry.run_id` 是 unique 索引；`RunRequest(run_id=...)` 可外部指定，评测在启动 Case 前生成 uuid 并先创建 PENDING CaseRun。前端下钻直接复用 `GET /api/runs/{run_id}` 与 `RunDetailDrawer.vue`（FR-030，不建第二套轨迹查看器）。项目先例：`runs.conversation_id` 同样为业务引用不建 DB 外键。

**Alternatives considered**: 外键关联（`runs.run_id` unique 可做，但项目惯例是应用层引用 + 删除保护，保持一致）。

## D3：评测时 Agent 配置的执行语义 —— 快照用于记录与呈现，执行读取当前库（⚠ spec 已回写修正）

**Decision**: Phase 11 不基于快照重建 Agent 执行；评测执行时从当前库读取 Agent/模型/绑定配置（`run_agent_loop` 现有行为），快照仅作为"评测时刻配置的权威记录"持久化与展示。Agent 在评测期间被删除 → 执行失败（EXECUTION_FAILED，失败隔离，不阻塞）。

**Rationale**: 用户需求文档明确"优先复用现有架构，不允许为了 Evaluation 重复实现"。Runtime 从库实时加载配置（`run_agent_loop` ①段）；若按快照重建执行，需在 Runtime 增加快照加载分支 —— 侵入 9 个阶段的稳定链路，违背"最小必要重构"。可复现性边界：数据集与评分器（评测子系统完全自持的两类输入）按快照执行；Agent 执行环境与聊天共享、按当时库内状态执行。

**回写记录**: 原 spec 表述"按创建时的快照执行与呈现，内容不变"过强，已修正 spec（US2 验收场景 2、FR-006）为"快照固化与呈现 + Agent 删除转执行失败"，并在 Assumptions 注明此边界。遵循宪法 VI（先改主定义再实现）。

**Alternatives considered**: 基于快照重建 Agent 执行上下文（侵入 Runtime，否决）；仅存 agent_id 不存快照（违背可追溯性要求，否决）。

## D4：三类快照的存储形态 —— 三列 JSON

**Decision**: `evaluation_tasks` 表三列：`agent_snapshot` JSON、`dataset_snapshot` JSON、`evaluator_snapshot` JSON，创建时一次性固化，之后永不更新。

**Rationale**: SQLite 单实例、快照只写不改、无跨表事务需求；JSON 列与 `McpServerEntry.tools_json` 先例一致。快照结构（data-model.md §3）：
- Agent 快照：id/name/description/system_prompt/model（display_name/model_identifier/base_url/temperature/max_output_tokens/enable_deep_thinking/thinking_level）/max_rounds/skills[]/tools[]/mcp_servers[]/compact 配置
- 数据集快照：dataset_id/name/description/cases[]（case 原文四字段）
- 评分器快照：type/model_model_id/temperature/max_tokens/prompt_template/pass_threshold/config

**Alternatives considered**: 快照独立表（`*_snapshots`）——增加两张表与 join，无查询收益，否决。

## D5：LLM 评分器的模型调用 —— 复用 `stream_chat_completion` 非流式消费

**Decision**: `LLMJudgeEvaluator` 经 `stream_chat_completion`（include_usage=True）调用评分模型，循环累积 ContentDelta 得全文，不向任何 SSE 透传（评分在服务端静默完成）。

**Rationale**: 项目唯一 LLM 封装入口；错误分类复用 `_STREAM_ERROR_MESSAGES` 语义。评分模型从 `evaluator_snapshot.model_model_id` 解析当前库中模型配置（含密钥 `secret_vault.load_secret`）——评分模型属于"评测子系统自持输入"，但密钥必须实时从库中解密；模型被删 → JUDGE_FAILED（不判 0 分）。评分提示词：System = 固定裁判角色 + 注入防护声明（FR-016）+ 输出 JSON 契约；User = 四输入（Question/Reference/Criteria/Actual）以分隔符包裹。temperature 用快照值、max_tokens 适度（默认 1024）。

**Alternatives considered**: 新建非流式 chat 函数——`stream_chat_completion` 已覆盖且评分无需非流式特化，否决。

## D6：Judge 输出校验与重试 —— 严格校验，恰好一次重试

**Decision**: 解析链：JSON 提取（容忍 ```json 围栏）→ Pydantic Schema（`score: int 0-100`，`reason: str min_length=1`）→ 非法则带"上次输出非法"反馈重试恰好 1 次 → 仍非法 JUDGE_FAILED。score 限定 int（float 但值等于整数时接受转 int；其余非法）。

**Rationale**: 用户需求 §22-24 逐项列举（NaN/Infinity/-10/150/"" 全非法）。`math.isfinite` 防御 JSON 解析出浮点；Pydantic `strict` 模式拒绝字符串数字 "85"。重试反馈不包含上次具体输出内容（避免把注入文本二次放大），只说明违规类型。

**Alternatives considered**: 无限重试（禁止）；重试时不带反馈（成功率更低，且需求允许）。

## D7：执行策略抽象与并发预留

**Decision**: `ExecutionStrategy` ABC（`execute(cases, worker)`，worker 为单 Case 协程函数）+ `SequentialExecutionStrategy` 顺序 await；`runner.py` 的编排逻辑（状态推进/评分/落库）全部在 worker 闭包内，策略只决定调度顺序。Phase 12+ 的 `ConcurrentExecutionStrategy` 用 `asyncio.Semaphore` + `gather` 实现即可，无需改核心。

**Rationale**: 用户需求 §15；接口签名与需求 §46 建议对齐（适配 async 生成器事件流——worker 内部自行消费 `execute_run` 事件流后返回结果对象）。

## D8：暂停/取消/恢复的执行模型

**Decision**:
- 每个评测运行一个后台 asyncio 任务（`asyncio.create_task`），进程内注册表 `dict[int, EvaluationRunControl]`（先例：`generation_registry.py`）
- **暂停**：置位 `pause_event`；worker 在 Case 边界检查（当前 Case 跑完，不启动下一个）→ run 状态 PAUSED；**恢复**：清除标志，从 PENDING CaseRun 继续（重跑 PENDING 的 CaseRun 行，幂等）
- **取消**：置位 `cancel_event` + 当前 Case 的 `RunRequest.cancel` 置位（Runtime 支持协作式取消，`runtime.py` 轮间检查）→ 当前 Case 标 CANCELLED，后续 PENDING CaseRun 全标 CANCELLED → run CANCELLED
- **重启恢复**：`main.py` lifespan 启动时扫描 `evaluation_runs.status in (RUNNING, PAUSED)` → INTERRUPTED + interrupted_at/reason；对应 PENDING/RUNNING CaseRun → CANCELLED（错误类型 interrupted）；注册表为空无需清理

**Rationale**: 与聊天生成任务模型同构（协作式取消 + 注册表）；"不伪造立即取消"符合需求 §33。暂停语义是"Case 边界软停"，恢复走 PENDING CaseRun 续跑，为未来 Resume 留扩展点（需求 §32）。

**Alternatives considered**: 线程池/进程池（无必要，全部 I/O 异步）；硬中断当前 Case（Runtime 不支持安全中断 LLM 流，否决）。

## D9：失败 Case 重试 —— 新建 CaseRun 行

**Decision**: `POST /runs/{id}/retry` 只接受失败态 CaseRun（EXECUTION_FAILED/JUDGE_FAILED/FAILED/CANCELLED），为其**新建**一条 CaseRun（同 evaluation_run/dataset_case，agent_run_id 新生成），原行不动；重试后的聚合在 run 汇总时按"每 Case 取最新非取消 CaseRun"口径重算。

**Rationale**: Invariant 12（历史不覆盖）；需求 §34 推荐 CaseRun #1 → Retry → CaseRun #2。幂等：重试只创建行，执行由统一 runner 消费 PENDING CaseRun。

**Alternatives considered**: 新建 EvaluationRun（需求允许但交互粒度粗；需求推荐 CaseRun 级，采用之）。

## D10：聚合口径 —— 失败绝不计 0 分

**Decision**: 汇总仅统计"最新非取消 CaseRun"；`average_score` / `pass_rate` / `judge_success_rate` 分母 = 有有效评分（PASSED/FAILED）的 CaseRun 数；`execution_success_rate` 分母 = 总数；执行失败/评分失败不计入分子分母（分数维度）。INACTIVE 数据（0 Case、全失败）时 average_score/pass_rate 返回 null 而非 0。

**Rationale**: 需求 §27/28 明确 (90+30)/2=60 而非 (90+0+30+0)/4=30；null 语义防止"全失败显示 0 分"误导。

## D11：评测 API 路径与风格

**Decision**: 按项目现有 REST 风格（`/api` 前缀、Pydantic 校验、异常→HTTP 映射）：
- `POST/GET /api/evaluation/datasets`，`GET/PUT/DELETE /api/evaluation/datasets/{id}`
- `POST /api/evaluation/datasets/{id}/cases`，`PUT/DELETE /api/evaluation/datasets/{id}/cases/{case_id}`
- `POST /api/evaluation/datasets/{id}/import`，`GET /api/evaluation/datasets/{id}/export`
- `POST/GET /api/evaluation/tasks`，`GET/DELETE /api/evaluation/tasks/{id}`
- `POST /api/evaluation/tasks/{id}/runs`，`GET /api/evaluation/runs`（列表）/ `GET /api/evaluation/runs/{id}`，`POST /api/evaluation/runs/{id}/pause|resume|cancel|retry`
- `GET /api/evaluation/runs/{id}/cases/{case_run_id}`（Case 明细）

**Rationale**: 需求 §36 给出参考路径并允许按项目风格调整（`/api` 前缀是宪法 III 硬约束）；暂停恢复补充了 `/resume`（需求 §33 要求 Start/Pause/Cancel/Retry 四操作 + spec FR-024 暂停语义需要可恢复）。

## D12：前端结构 —— 三 Tab + 复用 RunDetailDrawer

**Decision**: `EvaluationsView.vue` 改造为三 Tab 工作台（数据集/任务/运行），子组件拆分至 `components/evaluation/`；Case 明细的"查看 Agent 运行"通过路由跳转 `/runs?run_id=xxx`（RunsView 已支持按 run_id 打开详情抽屉，核实后如需微调则加 query 支持），复用 `RunDetailDrawer.vue`。

**Rationale**: FR-030 禁止第二套轨迹查看器；模块导航已注册 `evaluations` 路由与标题（modules.ts 无需改动）。

## D13：测试策略 —— 假流注入 + 内存库

**Decision**: 评测链路测试沿用 011 模式：monkeypatch `execute_run`（`services.evaluation.runner` 命名空间）注入假事件流（script 化 run_completed），评分器测试 monkeypatch `stream_chat_completion`；Service 层测试用内存 SQLite + TestClient。重启恢复测试直接调 `mark_interrupted_runs` 等价函数。

**Rationale**: `tests/test_agent_runtime_fixtures.py` 已有 `fake_runtime_stream` 先例；评测不需要真实 LLM。

## D14：迭代迁移策略

**Decision**: 迁移链追加一个 revision（down_revision = 当前 head `5f009f4ad657`），一次性建 5 张表；同步存档 `sql/migrations/012-agent-evaluation-evaluation-tables.sql`。

**Rationale**: 项目迁移惯例（每 feature 一个 revision）；测试库不走 Alembic（conftest `create_all`）。
