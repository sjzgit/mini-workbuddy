# Research: 上下文压缩与运行记录可观测（011）

> 本文件解决 spec 与 Plan 阶段遗留的全部待定项。每项给出决策、理由与备选方案。

## R1. Token 估算算法（spec FR-024）

**Decision**: 复用 008 已有估算口径，抽出为共享模块 `backend/app/services/agent_runtime/compression.py` 中的 `estimate_text_tokens(text) -> int` 与 `estimate_messages_tokens(messages) -> int`：
- 单条文本：`ceil(len(text) * CONTEXT_CHAR_TOKEN_RATIO)`，系数 `0.6`（主定义 `schemas/chat.py`，沿用不复制）；
- 每条消息额外 +4 token 结构开销（沿用 `chat_service._CONTEXT_MSG_OVERHEAD`，迁移到共享模块后 chat_service 引用之）；
- 估算范围（FR-022）：系统提示词 + Skill 目录 XML + 工具定义 JSON（`json.dumps` 后估）+ 会话摘要 + 历史消息 + 本轮新增消息与工具结果；
- 页面与事件中展示估算值时一律带"≈"或"（估算）"标注；接口返回的实际 usage 不与估算混用（字段分离：`usage` vs `estimated_tokens`）。

**Rationale**: 项目无 OpenAI 官方 SDK、模型为 GLM 系（无适配 tokenizer），引入 tiktoken 属新依赖且对目标模型失准；008 的前置容量检查已用该系数运行一个阶段，口径连续。
**Alternatives**: tiktoken（新依赖+模型不匹配，弃）；让模型自己报 token（请求前无法获得，弃）。

## R2. 输出预留与安全余量（spec FR-023）

**Decision**:
- 输出预留 = `models.max_output_tokens`（已有字段）；为空时取 `compact_default_output_reserve_tokens`（默认 **4096**）；
- 安全余量 = `context_length × compact_safety_margin_ratio`（默认 **10%**）；
- 可用输入容量 `available_input = context_length − output_reserve − ceil(context_length × 0.10)`；
- 全部为 `core/config.py` 配置项，有默认值。

**Rationale**: max_output_tokens 本就是"为回答预留的空间"的模型级定义；10% 余量覆盖估算误差（字符比法的偏差量级）；两者相加在小窗口模型下也不会吃掉全部输入空间。
**Alternatives**: 固定 8K 预留（小窗口模型吃满，弃）；余量可按 Agent 配置（YAGNI，全局默认足够）。

## R3. Agent 压缩配置字段与校验（spec FR-025/026）

**Decision**: `agents` 表新增 4 列（详细定义见 data-model.md §2），Pydantic 校验边界：

| 字段 | 默认 | 校验范围 |
|------|------|----------|
| auto_compact | true | bool |
| compact_trigger_ratio | 0.80 | 0.50 ≤ r ≤ 0.95 |
| compact_keep_recent_rounds | 5 | 1 ≤ n ≤ 50 整数 |
| compact_summary_target_tokens | 1000 | 100 ≤ n ≤ 8000 整数 |

摘要目标长度在压缩执行时被 `min(配置值, available_input // 2)` 二次限制（FR-026，小窗口模型保护）；表单提供说明文案（contracts/agent-compression-config.md）。
**Rationale**: 上限 0.95 防止阈值贴近 1.0 导致压缩后立刻再触发；target 上限 8000 覆盖大窗口场景、下限 100 保证摘要可用性。
**Alternatives**: 全局配置而非 Agent 级（文档明确要求 Agent 级，弃）。

## R4. 压缩状态与边界的存储（spec FR-033/034）

**Decision**: 新表 `conversation_compactions`（详见 data-model.md §3）：每会话一行（unique conversation_id），`summary_text` + `boundary_seq` 同行同事务更新——单行 UPDATE 天然保证"摘要与边界一致更新"，失败即整体回滚保留上一份有效摘要。
- `boundary_seq` = 已压缩覆盖的最后一条 messages.seq；无摘要时 boundary_seq=0、summary_text=''；
- 聊天组装历史时：`seq > boundary_seq` 的 user + completed assistant 消息进入 history，摘要由 Runtime 注入为上下文首条 user 消息（role=user，会话背景，FR-031）；
- `conversations` 删除时级联删除该行（FK ondelete CASCADE，与 011 澄清决定一致）。

**Alternatives**: 摘要/边界分两表（需两表事务，一致性弱，弃）；摘要存文件（违反"数据必须入库"宪法约束，弃）。

## R5. 压缩触发点、范围与摘要请求（spec FR-022/028/032/036~038）

**Decision**:
1. **检查点**：Runtime 主循环每轮模型请求发起前（含轮数耗尽后的收尾请求前）估算一次；`estimated_input ≥ trigger_ratio × available_input` 即触发（auto_compact 关闭时跳过压缩逻辑）。
2. **消息组划分**：运行内上下文 `ctx.messages` 结构化为有序"组"：头部（system 字符串、Skill 目录、工具定义——不在 messages 内，单独估算）；摘要（单独一条 user 消息）；对话组序列——每组 = 一条 user 消息，或一条 assistant 消息及其后全部 tool 结果消息（运行内工具交互天然成组，满足 FR-036 配对要求）。每组带 `db_seq`（来自 history 注入的 seq；运行内新增组为 None）。
3. **保留与压缩**：从最早组开始划出待压缩集合，保留最近 `compact_keep_recent_rounds` 个完整对话轮 + 本次用户消息所在组 + 全部运行内新增组（db_seq=None）；待压缩集合全部文本交给当前运行使用的模型（同 base_url/model_identifier/api_key/temperature）生成摘要。
4. **摘要请求**：复用 `stream_chat_completion`（流式收集、`include_usage=True`，delta 不外发），`purpose="context_compression"`；独立超时 `compact_request_timeout_seconds`（默认 **60s**，覆盖 120s 读超时）；摘要提示词固定模板（任务清单式：用户目标/已确认事实/重要工具结果/明确限制/未完成事项），已有摘要作为"前版摘要"一并提交（FR-030）；目标长度写进提示词（约 N token，不保证等长）。
5. **分批**：单批输入上限 = `available_input // 2`；待压缩内容超限时按组切片多批（滚动合并），批数上限 `compact_max_batches`（默认 **4**），超出部分留给下次压缩（边界只推进到已处理组）。
6. **压缩后重估**（FR-037）：仍超限 → 按组从最早继续减少保留集合（先 DB 历史组、再运行内已完成组），记录实际保留数并写入 `compression_completed` 事件；仍不足则转 R6 备用处理。
7. **首次即超**（FR-039）：固定内容（system+skills+tools+摘要）+ 本次用户消息本身超 available_input → 不发请求，发 `error`（category=context_overflow）后以失败结束，结束原因说明"系统提示词/工具配置本身已超出容量"。
8. **次数限制**：单次运行压缩尝试上限 `compact_max_attempts_per_run`（默认 **2**），超限后只做备用裁剪不再请求摘要（防反复压缩无法结束）。
9. **写回**：摘要成功后单事务 upsert `conversation_compactions`（summary_text + boundary_seq=待压缩集合中最大 db_seq）；写回失败按摘要失败处理（不推进边界）。
10. **取消**（FR-042）：批次间与请求前检查 cancel 信号，取消后清理未完成请求（复用 008 超时/断连路径）。

**Rationale**: 与《9 上下文压缩.md》逐条对齐；运行内新增组不压缩保证"尚未完成的工具交互不被裁掉"（FR-036）；分批+次数上限保证摘要请求自身不超容量且可终止（FR-032）。
**Alternatives**: 后台线程压缩（增加并发复杂度，当前流程内压缩耗时可控，弃）；摘要用独立小模型（文档要求用当前运行模型，弃）。

## R6. 压缩失败与备用裁剪（spec FR-040/041）

**Decision**: 摘要请求超时/模型错误/空摘要/写回失败 → 发 `compression_failed` 事件，立即转备用裁剪：按 R5.2 的组为单位从最早丢弃（保持配对），尽量保留最近对话与本次用户消息；丢弃后重估，能装下则继续运行，仍不行则 `error`（context_overflow）结束。备用裁剪发 `compression_fallback` 事件（记录丢弃/保留组数与裁剪后估算值），**不更新边界、不写库、不影响历史**（只影响本次请求）。
**Rationale**: 备用路径与压缩共用组结构，实现与测试都只多一个分支。
**Alternatives**: 失败后重试摘要（已有次数上限兜底，首选取裁剪保证响应性）。

## R7. 运行记录持久化方案（spec FR-001~009、FR-043~045）

**Decision**:
1. **落点**：`execute_run` 内部创建 `RunRecorder`（`agent_runtime/recorder.py`），包装事件迭代器——聊天与后续评测共用同一记录入口（FR-005），Runtime 对外接口不变。Recorder 使用独立 `SessionLocal` 短会话，不阻塞事件转发（结构性事件逐条 INSERT，SQLite 单用户量级可接受）。
2. **三张新表**：`runs`（一行一运行，快照+聚合指标）、`run_events`（结构性事件，unique(run_id, seq) 幂等）、`run_payloads`（详细载荷，大字段完整保存）。字段详见 data-model.md §4~6。
3. **持久化范围**：9 种既有事件中的结构性 7 种 + 011 新增 4 种压缩事件；`reasoning_delta`/`content_delta` **不落库**（011 澄清决定），但 Recorder 消费它们用于计算 `first_output_ms`（首个非空 `content_delta`）。
4. **落库前清洗**：`run_completed.data` 剥离 `content_text`/`reasoning_text`（正文单一事实来源在 messages 表）；工具事件剥离 010 的 `params`/`result` 展示字段（完整文本进 payload 表，事件只留摘要）；载荷写入前经 `services/sanitize.py` 脱敏。
5. **指标口径**（FR-014，由事件流推导、增量写入 runs 行）：
   - `model_call_count` = `model_request_started` 次数（含失败与压缩请求——压缩请求 purpose 可区分但计入总数，用途在事件中标记，FR-045）；
   - `tool_call_count` = `tool_call_completed` 且 status ∈ {success, error, cancelled}（denied=校验拒绝不计入已执行，但事件保留可查）；
   - Token 用量 = 各 `model_request_completed.usage` 与压缩请求 usage 的 `merge_add`（任一未知则该维未知，禁止填 0）；
   - `total_duration_ms` = finished_at − started_at；
   - `first_output_ms` = 首个非空 content_delta 距 run 开始的毫秒数；无正文输出为 NULL。
6. **状态映射**（契约主定义）：`completed→succeeded`、`max_rounds→partial`、`error→failed`、`cancelled→cancelled`；end_reason 保存 Runtime 人话原因；error_summary 保存脱敏错误摘要。
7. **中断恢复**（FR-007）：应用启动时（lifespan）将所有 `status='running'` 的 runs 批量置为 `failed`，end_reason="运行中断：服务在运行期间重启"；与 008 既有"孤儿 generating 消息惰性标记"并存。
8. **级联删除**：runs/run_events/run_payloads/conversation_compactions 均经 FK ondelete CASCADE 随会话删除（011 澄清决定）。
9. **事件幂等**（FR-008）：`run_events` 唯一约束 (run_id, seq)，重复投递 INSERT 跳过；指标在 runs 行上做增量更新且以终态事件为最终一致（重复 run_completed 不重复累计）。

**Alternatives**: Recorder 放桥接层（评测需重复接线，弃）；事件落库改批量缓冲（崩溃时丢事件，与"中断可定位"目标冲突，弃）。

## R8. 浏览器断开 → 后台运行 → 自动续播（spec FR-006，011 澄清决定）

**Decision**:
1. `chat_service.build_message_stream` 的 finally 分支**不再**因客户端断开触发 `cancel_event`（删除 009 §7"连接断开→取消"行为）；生成任务继续执行，终态照常落库并广播（无订阅者时广播为空操作）。
2. 自动续播复用既有机制，零新增接口：`GenerationTask.buffer` 在无订阅者期间持续累积全部事件；前端 `loadMessages()` 已实现"发现 `status==='generating'` 消息即重建 SSE 订阅"，订阅端点按 008 语义先重放 buffer 再实时跟随——断开期间的增量重放后即可实时续播。
3. 用户主动"停止生成"仍走 `/stop`（显式取消，语义不变）；会话互斥（生成中 409）不变——后台运行期间同会话不可发送新消息。
4. 聊天页在生成中气泡区显示既有"运行中"状态；后台完成后重新进入会话即见最终回答（已完成消息正常渲染）。

**Rationale**: 澄清决定选了"自动续播"；现有 buffer+重放+重订阅设计天然支持，只需删除断开取消一行行为，改动最小。
**Alternatives**: 新增"查询运行状态"专用接口（既有消息状态已足够，YAGNI）。

## R9. 运行记录 REST API 与页面（spec FR-010~018）

**Decision**（契约主定义 `contracts/runs-api.md`）：
- `GET /api/runs`（status/agent_id/conversation_id 筛选 + page/page_size 分页，返回快照摘要 + total）——COUNT + SELECT 两条查询，恒定查询次数（SC-003）；所有展示字段来自 runs 行快照，**无逐行关联查询**（agent/model 名称是快照列）。
- `GET /api/runs/{run_id}` 详情 = 摘要 + 结构性事件列表（run_events，安全字段）。
- `GET /api/runs/{run_id}/payloads` 载荷元数据列表；`GET /api/runs/{run_id}/payloads/{payload_id}` 按需读取单条载荷全文（独立受控入口，FR-018/021）。
- `GET /api/conversations/{conversation_id}/runs` 会话维度最近运行（聊天页入口）。
- 页面：`RunsView.vue`（a-table + 状态 Select + Agent Select + 后端分页，仿 ModelsView 范式）；`RunDetailDrawer.vue` 行点击打开（仿 ToolDetailDrawer 范式），时间线组件 `RunTimeline.vue` 按事件类型渲染步骤（模型/工具/压缩/错误），模型步骤与工具步骤的"查看完整载荷"展开时才请求 payload 接口。

**Alternatives**: 详情独立路由页（需改元数据路由机制，抽屉是既有范式，弃）；列表前端全量拉取后切片（违背恒定查询次数意图，弃）。

## R10. 脱敏（spec FR-020/021）

**Decision**: 新建 `backend/app/services/sanitize.py`，提供 `sanitize_text(text) -> str` 与 `sanitize_messages(messages) -> list`：
- 密钥形态：`sk-...`、`Bearer ...`、`Authorization` 头、`api_key`/`secret`/`token` 赋值形态 → `***`；
- 环境变量整行赋值（`KEY=value` 形态且 KEY 全大写）→ 值打码；
- 用户设备绝对路径：workspace 目录前缀 → `${workspace}`；其他盘符路径（`X:\...`、`/home/...`、`C:\Users\...`）→ `${path}` 占位；
- 应用点：run_payloads.content 写入前、runs.error_summary、error 事件 message（幂等，事件本已脱敏的再过一遍无害）。

**Rationale**: 单点实现便于测试（SC-004 可自动断言）；正则覆盖当前已知敏感形态，工具输出/错误信息的间接泄露经统一出口拦截。
**Alternatives**: 各写入点自行脱敏（易漏，弃）。

## R11. 详细载荷完整保存（spec FR-021，011 澄清决定）

**Decision**: `run_payloads.content` 使用 SQLAlchemy `Text`（SQLite 动态类型，实际容量受限于 SQLITE_MAX_LENGTH ≈ 1GB），**不设应用层截断**；载荷类型：`model_input`（该次请求 messages 数组 JSON，脱敏后）、`model_output`（该次响应正文/思考/工具调用全文）、`tool_params` / `tool_result`（来自 ToolCallRecord.params_full/result_full 全量）、`compression_input` / `compression_output`。完整文本经事件 `data` 的 `*_full` 透传字段（桥接层 SSE 剥离，模式同 `run_completed.content_text` 先例）由 Recorder 接收落库，SSE 消费者不可见。
**Rationale**: 沿用 content_text 的"透传-剥离"既有模式，Runtime 契约不变式（SSE 无全文）保持。
**Alternatives**: 事件带截断文本 + 载荷另存（两套来源不一致，弃）。

## R12. 配置项汇总（core/config.py 新增）

| 配置 | 默认 | 对应 |
|------|------|------|
| compact_safety_margin_ratio | 0.10 | R2 |
| compact_default_output_reserve_tokens | 4096 | R2 |
| compact_request_timeout_seconds | 60 | R5.4 |
| compact_max_attempts_per_run | 2 | R5.8 |
| compact_max_batches | 4 | R5.5 |

## 测试策略（对齐 spec 测试与验证要求）

- **后端**（pytest，复用 FakeStream/runtime_db/chat_session_factory 夹具）：
  - `test_run_records.py`：七类退出路径的 runs 状态与 end_reason；事件配对与 (run_id,seq) 去重；列表 API 恒定查询次数（用事件计数断言 2 次）；详情/载荷按需加载；级联删除；启动中断恢复；敏感信息断言（payload/事件/错误摘要不含密钥形态与绝对路径）。
  - `test_context_compression.py`：阈值触发与压缩后容量回归；边界增量（第二次压缩只含新增组、摘要含前版）；分批与次数上限；失败四态（超时/异常/空摘要/写回失败）→ 备用裁剪且边界不变；auto_compact 关闭不发摘要请求；首次固定内容超限直接失败；取消信号终止压缩；压缩请求计入模型调用次数与 Token 且 purpose 正确；估算标注（事件含 estimated_* 字段）。
  - 扩展 `test_chat_stream.py`：订阅断开后任务继续、终态落库、重新订阅重放续播。
- **前端**（Vitest）：`stores/__tests__/runs.spec.ts`（列表/筛选/分页/详情/载荷加载）；`api/__tests__/runs.spec.ts` 可并入；`stores/__tests__/chat.spec.ts` 增断流后重连续播与 compression 事件忽略不崩溃；agents spec 增压缩字段提交断言。
- **质量门禁**：`uv run pytest`、`uv run pyright`、`npm run build`、`npm run test:unit` 全绿。
