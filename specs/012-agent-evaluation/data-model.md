# Data Model: Agent 评测系统（specs/012-agent-evaluation）

> 数据模型主定义（宪法 II SSOT）：本文件 → `backend/app/models/__init__.py`。实现侧字段类型 MUST 与本文档一致，变更先改本文档再落 Alembic 迁移。所有时间字段沿用项目口径：naive UTC、去微秒。

## 1. 实体关系总览

```text
evaluation_datasets 1 ──── N evaluation_cases
evaluation_tasks（持有三份 JSON 快照，引用 agent_id / dataset_id）
evaluation_runs N ──── 1 evaluation_tasks
evaluation_case_runs N ──── 1 evaluation_runs
evaluation_case_runs N ──── 1 evaluation_cases（按 dataset_case_id 追溯）
evaluation_case_runs ──agent_run_id──▶ runs（AgentRun，业务引用不建外键）
```

## 2. 表定义

### 2.1 evaluation_datasets — 评测数据集

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | Integer | PK, autoincrement | |
| name | String(100) | NOT NULL | 数据集名称 |
| description | String(500) | NOT NULL, default '' | 描述 |
| created_at | DateTime | NOT NULL | |
| updated_at | DateTime | NOT NULL | |

索引：无附加（列表按 updated_at 倒序，量级小）。

### 2.2 evaluation_cases — 评测用例

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | Integer | PK, autoincrement | |
| dataset_id | Integer | FK→evaluation_datasets.id ON DELETE CASCADE, NOT NULL | |
| user_question | Text | NOT NULL | 用户问题（必填，非空白） |
| expected_answer | Text | NULL | 参考答案（可空） |
| scoring_criteria | Text | NULL | 评分标准（可空） |
| created_at | DateTime | NOT NULL | |
| updated_at | DateTime | NOT NULL | |

索引：`ix_evaluation_cases_dataset (dataset_id)`。

### 2.3 evaluation_tasks — 评测任务（评测定义）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | Integer | PK, autoincrement | |
| name | String(100) | NOT NULL | 任务名 |
| agent_id | Integer | NOT NULL | 业务引用（不建 DB 外键，项目先例） |
| dataset_id | Integer | NOT NULL | 业务引用 |
| evaluator_type | String(30) | NOT NULL | `llm_judge` \| `exact_match`（contracts 唯一主定义） |
| evaluator_config | JSON | NOT NULL | 评分器原始配置（model_model_id/temperature/max_tokens/prompt_template） |
| pass_threshold | Integer | NOT NULL | 通过阈值 0–100（默认 80） |
| agent_snapshot | JSON | NOT NULL | Agent 快照（§3.1），创建时固化，永不更新 |
| dataset_snapshot | JSON | NOT NULL | 数据集快照（§3.2），创建时固化，永不更新 |
| evaluator_snapshot | JSON | NOT NULL | 评分器快照（§3.3），创建时固化，永不更新 |
| status | String(20) | NOT NULL, default 'pending' | 任务状态机（§4.1） |
| created_at / updated_at | DateTime | NOT NULL | |

索引：`ix_evaluation_tasks_dataset (dataset_id)`。

### 2.4 evaluation_runs — 评测运行（一次实际执行）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | Integer | PK, autoincrement | |
| task_id | Integer | FK→evaluation_tasks.id ON DELETE CASCADE, NOT NULL | |
| run_id | String(64) | NOT NULL | 评测运行业务标识（uuid4 hex，区别于 AgentRun run_id） |
| status | String(20) | NOT NULL, default 'pending' | 运行状态机（§4.2） |
| started_at | DateTime | NULL | |
| finished_at | DateTime | NULL | |
| interrupted_at | DateTime | NULL | 重启恢复标记时间 |
| interrupted_reason | String(500) | NULL | 重启恢复原因 |
| total_cases | Integer | NOT NULL, default 0 | 快照 Case 总数 |
| completed_cases | Integer | NOT NULL, default 0 | 已到终态的 Case 数 |
| passed_cases / failed_cases | Integer | NOT NULL, default 0 | 仅有效评分口径 |
| execution_failed_cases | Integer | NOT NULL, default 0 | 执行失败数 |
| judge_failed_cases | Integer | NOT NULL, default 0 | 评分失败数 |
| cancelled_cases | Integer | NOT NULL, default 0 | 已取消 Case 数 |
| average_score | Integer | NULL | 平均分（仅有效评分；无有效评分 = NULL，禁止 0） |
| pass_rate | Integer | NULL | 通过率 0–100（分母 = 有效评分 CaseRun；无有效评分 = NULL） |
| total_duration_ms | Integer | NULL | |
| total_tokens | Integer | NULL | 全部 CaseRun token 之和 |
| created_at | DateTime | NOT NULL | |
| updated_at | DateTime | NOT NULL | |

索引：`uq_evaluation_runs_run_id (run_id)` unique；`ix_evaluation_runs_task (task_id)`；`ix_evaluation_runs_status (status)`。

计数口径：completed_cases = passed + failed + execution_failed + judge_failed（cancelled 不计入完成）；`average_score` / `pass_rate` 仅统计每 Case 最新非取消 CaseRun 中状态为 PASSED/FAILED 的记录（D9/D10）。

### 2.5 evaluation_case_runs — 用例运行

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | Integer | PK, autoincrement | |
| evaluation_run_id | Integer | FK→evaluation_runs.id ON DELETE CASCADE, NOT NULL | |
| dataset_case_id | Integer | NOT NULL | 业务引用（快照 Case 无独立表；见 §3.2） |
| status | String(20) | NOT NULL, default 'pending' | CaseRun 状态机（§4.3） |
| agent_run_id | String(64) | NULL | AgentRun 的 run_id（业务引用，D2）；下钻 GET /api/runs/{id} |
| score | Integer | NULL | 0–100；仅 PASSED/FAILED 有值 |
| reason | Text | NULL | 评分理由或失败说明 |
| evaluator_type | String(30) | NULL | 实际使用的评分器 |
| evaluator_metadata | JSON | NULL | 评分器元数据（重试次数、原始输出非法类型等） |
| duration_ms | Integer | NULL | Agent 执行耗时 |
| input_tokens / output_tokens / total_tokens | Integer | NULL | 来自 run_completed.usage_total（未知保持 NULL，不填零） |
| tool_call_count / model_call_count / iteration_count | Integer | NULL | 行为指标（来自 AgentRun 汇总） |
| error_type | String(30) | NULL | 执行/评分错误分类 |
| error_message | String(2000) | NULL | 脱敏错误信息 |
| attempt | Integer | NOT NULL, default 1 | 同一 Case 的第几次尝试（重试 +1） |
| started_at / finished_at | DateTime | NULL | |

索引：`ix_evaluation_case_runs_run (evaluation_run_id)`；`ix_evaluation_case_runs_case (dataset_case_id)`；`ix_evaluation_case_runs_agent_run (agent_run_id)`。

dataset_case_id 语义：创建 EvaluationRun 时按 `dataset_snapshot.cases` 展开逐 Case 建 PENDING CaseRun；`dataset_case_id` 存快照 Case 的原始 `case_id`（创建快照时 = evaluation_cases.id）。数据集被删后历史运行仍可读快照内容。

## 3. JSON 快照结构

### 3.1 agent_snapshot

```json
{
  "agent_id": 1, "name": "客服助手", "description": "…",
  "system_prompt": "…",
  "model": {"model_id": 1, "display_name": "…", "model_identifier": "…",
             "base_url": "…", "temperature": 0.7, "max_output_tokens": 4096,
             "enable_deep_thinking": false, "thinking_level": "off"},
  "max_rounds": 10,
  "skills": [{"id": "demo-skill", "name": "演示技能", "description": "…"}],
  "tools": [{"name": "current_time", "description": "…", "parameters": {}}],
  "mcp_servers": [{"id": 1, "name": "files-mcp", "tools": ["read_file"]}],
  "runtime": {"auto_compact": true, "compact_trigger_ratio": 0.8,
               "compact_keep_recent_rounds": 5, "compact_summary_target_tokens": 1000}
}
```

（快照为记录与呈现用；执行语义见 research D3。Tools 目录含 exposed_name/description/parameters。）

### 3.2 dataset_snapshot

```json
{
  "dataset_id": 1, "name": "客服评测集", "description": "…",
  "cases": [{"case_id": 10, "user_question": "如何申请退款？",
              "expected_answer": "…", "scoring_criteria": "…"}]
}
```

### 3.3 evaluator_snapshot

```json
{
  "type": "llm_judge",
  "model_model_id": 1, "model_display_name": "GPT 测试模型",
  "temperature": 0.0, "max_tokens": 1024,
  "prompt_template": null,
  "pass_threshold": 80,
  "config": {}
}
```

`prompt_template` 为空时使用内置默认评分提示词（contracts/evaluation-api.md §judge-prompt）。

## 4. 状态机（契约唯一主定义：contracts/evaluation-api.md §enums）

### 4.1 EvaluationTask.status

```text
PENDING ──▶（不可直接执行，Run 才是执行载体；PENDING 表示从未发起过运行）
```

说明：Task 是定义不是执行（FR-005），status 仅保留 pending 单态占位（需求 §30 的状态机语义由 EvaluationRun 承载；Task 级 RUNNING/COMPLETED 即最近一次 Run 的状态，前端从 Run 推导，不冗余存储）。

### 4.2 EvaluationRun.status

```text
PENDING ──▶ RUNNING ──┬──▶ COMPLETED
                      ├──▶ CANCELLED
                      ├──▶ FAILED
PAUSED ──▶（resume）──▶ RUNNING
RUNNING/PAUSED ──（服务重启）──▶ INTERRUPTED
```

合法跳转表（其余一律拒绝，FR-023）：

| from | to |
|------|----|
| PENDING | RUNNING, CANCELLED |
| RUNNING | PAUSED, COMPLETED, CANCELLED, FAILED, INTERRUPTED |
| PAUSED | RUNNING, CANCELLED, INTERRUPTED |
| INTERRUPTED | RUNNING（重新发起，复用 Run 续跑 PENDING CaseRun） |

FAILED 定义：运行框架级异常（如快照展开失败）；Case 级失败不导致 Run FAILED。

### 4.3 CaseRun.status

```text
PENDING ──▶ RUNNING ──┬──▶ PASSED（score ≥ pass_threshold）
                      ├──▶ FAILED（有效评分 < threshold）
                      ├──▶ EXECUTION_FAILED
                      ├──▶ JUDGE_FAILED
                      └──▶ CANCELLED
PENDING ──▶ CANCELLED（取消/中断时未启动的 Case）
PENDING/RUNNING ──▶（服务重启）──▶ CANCELLED（error_type=interrupted）
```

## 5. 聚合口径（AggregateResult，FR-020/D10）

- 统计集合：每 dataset_case 取**最新一条非 CANCELLED** CaseRun（attempt 最大）
- 有效评分集：该集合中 status ∈ {PASSED, FAILED}
- `average_score` = 有效评分集 score 平均（四舍五入取整）；集合为空 → NULL
- `pass_rate` = 有效评分集中 PASSED 占比 ×100；集合为空 → NULL
- `execution_success_rate` = 集合中 status ∉ {EXECUTION_FAILED, CANCELLED} 占比
- `judge_success_rate` = 集合中 status ∉ {JUDGE_FAILED, EXECUTION_FAILED, CANCELLED} 占比
- `total_tokens` = 全部 CaseRun total_tokens 已知值之和（NULL 项跳过；全未知 → NULL）
- 平均耗时 = 集合 duration_ms 已知值平均

## 6. 与既有表的关系

- **runs（AgentRun）**：每 Case 执行由 RunRecorder 自动落一行；CaseRun.agent_run_id → runs.run_id（业务引用）。评测发起的 Run 其 `conversation_id=NULL`，运行记录列表天然可区分。
- **conversations / messages**：评测完全不写入（`RunRequest.conversation_id=None` 路径已支持）。
- **models / secrets_vault**：评分器经 `model_model_id` 实时解析模型配置与密钥（只读）。
- **agents / agent_bindings**：只读（快照来源与执行时配置读取）。
