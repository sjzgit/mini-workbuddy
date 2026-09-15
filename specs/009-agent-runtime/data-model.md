# Data Model: 统一 Agent Runtime（009）

> 本阶段**不新增数据库表、不新增迁移**（spec FR-007）。数据模型 = 现有配置表的运行时视图 + 运行期内存实体。
> 既有表的主定义保持不变：models/skills/tools/mcp_servers/agents/agent_bindings/conversations/messages（见 002/003/004/007/008 各 data-model.md）。

## 1. 运行期内存实体（不持久化）

### 1.1 RunRequest（运行请求，Runtime 入参）

| 字段 | 类型 | 说明 |
|------|------|------|
| run_id | str | 唯一运行标识（uuid4） |
| agent_id | int | 所选 Agent（Runtime 据此加载配置） |
| user_message | str | 本次用户输入 |
| history | list[RunHistoryMessage] | 调用方传入的有效历史（role ∈ user/assistant，只含正文） |
| limits | RunLimits | 运行级能力限制（只能收窄） |
| cancel | asyncio.Event | 取消信号（外部置位） |

### 1.2 RunLimits（运行级能力限制，缺省 = 不收窄）

| 字段 | 类型 | 说明 |
|------|------|------|
| max_rounds | int \| None | 收窄最大轮数；None = 用 Agent 配置值。取 `min(agent.max_rounds, limits.max_rounds)` |
| allowed_tool_names | frozenset[str] \| None | 工具白名单（暴露名口径）；None = 不收窄。不在名单内的绑定工具不进目录、调用被拒 |
| disabled_skill_ids | frozenset[str] | 本次运行停用的 skill_id（dir_name）；目录与 load_skill 均排除 |

约束（FR-003）：limits 只能收窄——不在 Agent 已绑定且启用范围内的项一律无效，白名单合并结果仍以绑定∩启用为全集。

### 1.3 RunEvent（运行事件，Runtime 出参）

| 字段 | 类型 | 说明 |
|------|------|------|
| run_id | str | 所属运行 |
| seq | int | 运行内从 1 严格递增 |
| event | RunEventType | 事件类型（contracts/agent-runtime-api.md §2） |
| round | int \| None | 所属轮次（run_started 为 0） |
| call_id | str \| None | 模型请求/工具调用标识（开始/结束配对） |
| data | dict | 事件负载（按类型，契约 §3） |

### 1.4 RunResult（运行最终结果，随终态事件/返回值给出）

| 字段 | 类型 | 说明 |
|------|------|------|
| status | Literal[completed, max_rounds, error, cancelled] | 最终状态 |
| reason | str | 结束原因（人话，进日志与事件） |
| reasoning_text | str \| None | 思考过程全文（多轮按序拼接） |
| content_text | str | 回答正文全文（工具调用前后片段按序拼接） |
| error_category | StreamErrorCategory \| None | 失败类别（沿用 008 枚举） |
| usage_total | UsageInfo \| None | 全部模型请求用量之和；任何一项未知则该项为 None |

### 1.5 ToolCatalogEntry（运行内工具目录项）

| 字段 | 类型 | 说明 |
|------|------|------|
| exposed_name | str | 暴露给模型的名称（内置原名 / `mcp__server__tool` / `load_skill`） |
| tool_type | Literal[builtin, mcp, skill] | 工具类型 |
| description | str | 给模型的用途说明 |
| parameters | dict | JSON Schema（内置由 pydantic 模型导出；MCP 为 inputSchema；load_skill 固定） |
| ref | str \| int | 真实标识：内置=注册表 name；MCP=原始工具名；skill=dir_name |
| server_id | int \| None | MCP 所属 Server id |

命名规则（FR-022）：消毒 = 非 `[A-Za-z0-9_-]` 折叠为 `_`，总长 ≤ 64；冲突追加 `_2`、`_3`…；`load_skill` 为保留名。

### 1.6 McpRunConnection（每运行独享的 MCP 连接）

| 字段 | 类型 | 说明 |
|------|------|------|
| server_id | int | mcp_servers.id |
| stack | AsyncExitStack | 连接/子进程托管，运行结束 finally 关闭 |
| session | ClientSession | 已 initialize 的 MCP 会话 |
| tools | list[McpToolInfo] | list_tools 结果（含 inputSchema） |

生命周期：运行开始逐个连接（失败跳过并记日志，不阻断运行）；`finally` 统一关闭（FR-029）。并发运行各自独享实例，互不共享（FR-040/041）。

### 1.7 ToolCallRecord（一次工具调用，仅运行期）

| 字段 | 类型 | 说明 |
|------|------|------|
| call_id | str | 与开始/结束事件配对 |
| exposed_name / tool_type / ref | — | 来自目录项 |
| status | Literal[success, error, denied, cancelled] | 执行状态 |
| result_for_model | str | 完整结果（仅进模型上下文） |
| summary | str | 脱敏摘要（≤200 字符，进事件与日志） |
| duration_ms | int | 执行耗时 |
| started_at_seq / ended_at_seq | int | 事件序号 |

## 2. 状态机

### 2.1 运行状态（RunResult.status）

```
running ──模型不再请求工具──▶ completed
       ──达到有效轮数且仍请求工具，收尾作答完成──▶ max_rounds
       ──运行级错误（模型/工具执行链路不可恢复）──▶ error
       ──cancel 置位或任务被取消──▶ cancelled
```

终态唯一且 run_completed 事件恰一次（FR-035）。`max_rounds` 的收尾回答视为正常完成（消息落库 status=completed）。

### 2.2 聊天消息终态（沿用 008，桥接映射）

| RunResult.status | 有正文/思考 | 无任何正文 |
|------------------|------------|-----------|
| completed / max_rounds | completed | —（不可能：completed 必有正文） |
| error / cancelled | incomplete | 删除占位行 |

## 3. 既有表的运行时读取视图（只读，不改动）

- Agent 配置：`agents`（model_id、system_prompt、max_rounds、enable_deep_thinking、thinking_level）× `models`（连接参数、密钥引用）。
- 能力绑定：`agent_bindings` 按 agent_id 过滤 × `tools/skills/mcp_servers.enabled`（运行开始与工具执行前各校验一次）。
- 会话历史：`messages`（user 全部 + assistant 且 completed），由聊天层读取后经 `RunRequest.history` 传入。
- Skill 指令：`workspace/skills/{dir_name}/skill.md`（skill_files 唯一读写口）。

## 4. 配置项（backend/app/core/config.py 新增，全部有默认值）

| 配置 | 默认 | 说明 |
|------|------|------|
| runtime_skill_max_bytes | 65536 | load_skill 指令大小上限（超限报错不截断，FR-019） |
| runtime_mcp_connect_timeout_seconds | 30 | 运行内 MCP 连接+列工具超时 |
| runtime_tool_result_summary_chars | 200 | 工具结果/参数脱敏摘要截断长度 |
