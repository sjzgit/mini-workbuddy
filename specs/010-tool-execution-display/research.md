# Research: 工具执行过程展示（010）

> 本文档记录 Plan 阶段的技术决策。所有 NEEDS CLARIFICATION 均已解决（Clarify 会话 2026-09-15 已确认持久化排除、切换会话保持流连接、历史不还原卡片）。

## R1: 完整输入/结果如何到达前端（US3 展开详情）

**Decision**: 事件流直接携带完整内容——`tool_call_started` 增补 `params` 字段、`tool_call_completed` 增补 `result` 字段（完整文本），后端在事件产出前按字符上限截断并追加截断标记；前端安全渲染（纯文本）+ 二级展示上限。

**Rationale**: 本阶段无持久化（Q1 已确认），SSE 事件流是唯一数据通道；`ToolCallRecord` 已持有完整 `result_for_model` 与原始参数文本 `raw_text`，仅是没放进事件。新增"按需详情拉取接口"需要后端内存缓存运行产物 + 新端点，违反 Simplicity。009 FR-037/038"展示事件仅含脱敏摘要"的约束由本契约增补修订：**日志仍只用摘要（FR-037 日志部分不变），模型上下文不变（FR-038 不变）**，仅展示事件增补完整字段；安全边界由"不展示堆栈（异常已转人话）、二进制不展开正文、双端展示上限、纯文本渲染"保障。

**Alternatives considered**:
- 按需详情接口（展开时 GET）：无持久化时后端无处可查，需引入运行产物缓存层，复杂度高，否决。
- 仅展示摘要：削弱 US3 核心价值（看懂 Agent 具体做了什么），否决。

## R2: 截断与展示上限的数值

**Decision**:
- 后端事件字段上限（`app/core/config.py` 新增配置）：`runtime_tool_params_max_chars = 4000`、`runtime_tool_result_max_chars = 16000`。超出截断并在文末追加 `\n…[已截断，完整内容共 N 字符]`。
- 前端详情展开上限：单字段最多渲染 20000 字符，超出提示"未展示全部（共 N 字符）"。
- 二进制启发式（前端）：内容含 NUL 字符或不可打印字符占比 > 30% → 不渲染正文，只显示"二进制内容（约 N KB）"。

**Rationale**: 4000/16000 字符覆盖绝大多数工具 I/O（SC-004 的 1MB 文本场景由后端截断兜底，SSE 单帧不超 ~48KB）；上限可配置，测试可覆盖。

**Alternatives considered**: 前端全量渲染 + 虚拟滚动——引入第三方虚拟列表库违反 YAGNI/技术栈清单；后端截断更可靠（网络与 DOM 双重保护）。

## R3: 工具易读名称与 MCP Server 名称来源

**Decision**:
- 内置工具：`tool_registry.get(name).display_name`（已有："当前时间"/"Shell 命令"/"文件读写"）。
- MCP 工具：易读名 = MCP 原工具名（`ToolCatalogEntry.ref`），并附带 `server_name = McpServerEntry.name`（执行时经 session 查询一次）。
- Skill 加载：固定显示名"加载 Skill"。

**Rationale**: 三个来源均已存在，无需新表或新配置；内部暴露名（`mcp__github__create_issue`）保留在 `tool_name` 字段用于关联与排障，卡片标题用易读名（FR-003）。

## R4: 生成中切换会话的"无缝续播"实现（Q2 确认行为）

**Decision**: 前端 store 从"全局单份生成状态"重构为"按会话的运行展示槽"：
- `runStates: Record<conversationId, RunDisplayState>`（segments、phase、generatingReplyId、错误等），切换会话不销毁；
- `activeStreams: Set<replyMessageId>` 登记活跃订阅，`loadMessages` 重订阅前先查该集合，已有活跃流则不再新建（避免双连接双倍事件）；
- `openStream` 回调闭包捕获 `(cid, mid)`，事件路由写入对应会话的槽，而非全局变量。

后端无需改动：SSE 连接在 SPA 内切换会话时保持（008 FR-022/009 桥接注释已明确"SPA 内切换会话不断流"）；`GenerationTask.buffer` + `subscribe()` 重放机制保证晚到订阅者完整重建状态。

**Rationale**: 这是最贴合现有架构的路径——后端重放能力已存在；前端旧流继续接收事件并路由到各自槽位，切回即见最新状态，零取消副作用。前端 abort 旧连接的方案会触发服务端 `GeneratorExit → cancel_event.set()`（build_message_stream 兜底取消），违背 Q2 结论，否决。

**Alternatives considered**: 前端 abort + 后端区分断开来源——后端无法可靠区分"页面关闭"与"订阅转移"，需加显式协议信号，复杂度不值；切走即取消（009 现状语义）——被 Q2 明确否决。

## R5: "状态未知"与"已取消"终态的判定（FR-020/021）

**Decision**: 全部在前端判定，后端契约不变：
1. 流异常断开（`openStream` 抛错）且未收到 `run_completed` → 该会话槽内所有 `running` 卡片标 `unknown`（后端可能仍在跑但结果无法确认）。
2. `run_completed(status=cancelled, stopped=true)` 到达时残留 `running` 卡片 → `cancelled`。
3. `run_completed(status=error)` 或桥接兜底终态到达时残留 `running` 卡片 → `unknown`。
4. `tool_call_completed(status)` 正常映射：success→成功、error/denied→失败、cancelled→已取消。

**Rationale**: Runtime 顺序保证工具同步执行完才发 completed 事件，正常路径不会出现"终态后仍有 running 卡片"；1/3 是防御性兜底，确保任何路径不违反"不得停留正在执行、不得误标成功"（FR-022）。`unknown` 是纯前端展示态（后端自己也无法确认），不进事件契约。

## R6: 展开/收起与滚动位置保持（FR-019）

**Decision**: 容器级统一补偿——`ChatMessages.vue` watch 滚动容器 `scrollHeight` 变化：当用户处于上滚状态（`userScrolledUp`）时，`scrollTop += newHeight - oldHeight`，使视口锚定内容不随高度变化漂移；该机制同时覆盖卡片展开/收起、长内容展开、图片加载等所有高度突变场景。自动跟随逻辑保留现有"距底 80px 内跟随"。

**Rationale**: 逐组件补偿需要在每处展开点发事件并计算几何，易漏；容器级 watch 是单点通用解。"回到最新消息"按钮：`userScrolledUp === true` 时悬浮显示，点击滚到底部并恢复跟随（FR-018）。

**Alternatives considered**: CSS `overflow-anchor`——浏览器支持不一且与手动跟随逻辑叠加后行为难测，否决。

## R7: 结构化内容的格式化展示（FR-010）

**Decision**: 前端展示层按内容形态分级渲染，不新增依赖：
- 参数：尝试 `JSON.parse` → 成功则 `JSON.stringify(parsed, null, 2)` 以等宽字体 pre 展示（格式化缩进）；失败则按纯文本展示。
- 结果：默认纯文本（`white-space: pre-wrap`）；若整体是合法 JSON 对象/数组则同样格式化缩进。
- 渲染一律走 Vue 文本插值（`{{ }}`），不使用 `v-html`（FR-015 不可信文本不执行）。

**Rationale**: Vue 插值天然转义；JSON 格式化是唯一"结构化"形态（工具参数必为 JSON；MCP/内置结果多数为纯文本），无需 Markdown/代码高亮依赖。

## R8: 摘要生成（FR-014）

**Decision**: 卡片收起态摘要直接取事件既有字段——运行中显示 `params_summary`（截断 ≤200 字符的参数摘要），完成后显示 `result_summary`（≤200 字符结果摘要）；失败显示失败人话信息（`result` 首段 / `result_summary`）。不调用模型。

**Rationale**: 009 事件已携带两个摘要字段，零新增成本即满足"优先从工具返回的状态和内容中提取"。

## R9: 后端测试与前端测试策略

**Decision**:
- 后端 pytest：契约级断言新字段（params/result/display_name/server_name 存在性与截断行为、超限追加截断标记、取消路径仍发 completed(cancelled)）；沿用 `tests/test_agent_runtime*.py` 夹具风格。
- 前端 Vitest：store 事件路由（多会话槽隔离、活跃订阅去重、续播）、终态映射（unknown/cancelled 兜底）、卡片组件渲染（状态文字+图标、截断标注、二进制提示、JSON 缩进、纯文本转义防注入）；沿用现有 `__tests__` 风格。
