# Contract: 工具过程展示事件增补与前端展示行为（010）

> 本契约分两部分：§1 是对 `specs/009-agent-runtime/contracts/agent-runtime-api.md`（事件契约主定义）的**增补修订清单**——主定义文件已同步更新并标注"010 增补"，此处为 diff 视图，两处冲突时以 009 契约文件为准；§2 是前端展示行为契约（本阶段新增的页面行为约束）。
> 字段命名 snake_case；代码落点：`backend/app/schemas/agent_runtime.py` → 前端 `frontend/src/api/chat.ts` 类型派生，三层对齐。

## 1. 对 009 事件契约的增补（diff）

### 1.1 `tool_call_started`（ToolCallStartedData）增补字段

```
params:        str          # 完整参数 JSON 文本；超 runtime_tool_params_max_chars(默认4000) 字符截断，
                            # 文末追加 "\n…[已截断，完整内容共 N 字符]"
display_name:  str          # 易读名称：builtin=tool_registry.display_name；mcp=原工具名(entry.ref)；
                            # skill="加载 Skill"
server_name:   str | None   # MCP Server 显示名；仅 tool_type="mcp" 时非空，其余 None
```

### 1.2 `tool_call_completed`（ToolCallCompletedData）增补字段

```
result:        str          # 完整结果文本：成功=result_for_model；失败/拒绝=人话失败信息
                            # （[错误码] + 说明，无异常堆栈）；超 runtime_tool_result_max_chars
                            # (默认16000) 字符截断，标记格式同 params
display_name:  str          # 同 1.1
server_name:   str | None   # 同 1.1
```

### 1.3 不变量（继承 009 + 本阶段澄清）

- 事件仍按 `seq` 升序产出；`run_completed` 之后不再有任何事件。
- **日志约束不变**：后台日志仍只记录 `params_summary` / `result_summary` 与元数据，禁止记录 `params` / `result` 全文（修订 009 FR-037 时保留日志部分）。
- **模型上下文不变**：交还模型的工具结果文本与 `result` 字段同源（`result_for_model`），不因展示需求改变上下文内容（009 FR-038 不变）。
- `params` / `result` 按不可信文本对待：前端禁止 `v-html`/innerHTML 渲染，仅纯文本插值（FR-015）。
- 新配置项：`runtime_tool_params_max_chars=4000`、`runtime_tool_result_max_chars=16000`（`app/core/config.py`）。

## 2. 前端展示行为契约

### 2.1 卡片状态机与文案（FR-020/021/022/027）

| 状态 | 触发 | 文案 | 视觉标识 |
|------|------|------|----------|
| `running` | `tool_call_started` | 正在执行 | 旋转 loading 图标 + 主色 |
| `success` | completed `status=success` | 成功 · {耗时} | ✓ 图标 + `--success` |
| `error` / `denied` | completed `status=error/denied` | 失败 · {耗时} | ✕ 图标 + `--danger` |
| `cancelled` | completed `status=cancelled`，或 `run_completed(stopped=true)` 时残留 running | 已取消 | ⏹ 图标 + `--text-tertiary` |
| `unknown` | 流断开无终态 / `run_completed(status=error)` 时残留 running | 状态未知 | ？图标 + `--warning` |

耗时展示：`duration_ms`，≥1000ms 显示秒（如 `2.3 秒`），否则毫秒（如 `450 毫秒`）。

### 2.2 卡片标题规则（FR-003）

- builtin：`{display_name}`（如"当前时间"）
- mcp：`{server_name} · {display_name}`（如"GitHub · create_issue"）
- skill：`加载 Skill`
- `tool_name`（内部暴露名）不作为标题，仅展开详情内以次要文字展示（排障用途）。

### 2.3 卡片内容分区（FR-004/005/010~014）

- **收起态**：状态徽标 + 标题 + 摘要一行（运行中 = `params_summary`；完成 = `result_summary`；均单行省略）+ 耗时（完成后）。
- **展开态**：`输入参数` 与 `执行结果` 两个分区，可独立折叠；渲染规则：
  - 合法 JSON（对象/数组）→ `JSON.stringify(_, null, 2)` 等宽缩进展示；
  - 其他文本 → 纯文本 `pre-wrap` 展示（保留换行）；
  - 含 NUL 或不可打印字符占比 > 30% → 不渲染正文，显示"二进制内容（约 N KB），类型未知"；
  - 单字段渲染上限 20000 字符，超出截断并提示"未展示全部（共 N 字符）"；
  - 后端截断标记 `…[已截断，完整内容共 N 字符]` 原样展示（文字标注已截断，FR-011）。
- 失败卡片展开态：`执行结果` 分区显示人话失败信息；MUST NOT 出现异常堆栈（`Traceback`、`File "..."` 等由后端保证不产生）。

### 2.4 运行展示槽与订阅（FR-023 / Clarify Q2）

- store 按会话维护 `RunDisplayState`（segments/phase/generatingReplyId），切换会话不销毁；
- 活跃订阅按 `replyMessageId` 登记（`activeStreams`），`loadMessages` 重订阅前先查集合，已有活跃流不重复订阅；
- 流事件经闭包路由至对应会话槽位，与当前查看的会话无关（后台会话的事件静默入库槽位）；
- 刷新页面：槽位清空，不还原历史卡片（FR-024/025）；后端因连接断开取消运行后，消息状态经既有 008 规则展示。

### 2.5 滚动与交互（FR-016~019）

- 生成中距底 ≤80px 视为"在底部附近"，新内容自动跟随；
- 用户上滚离开底部 → 暂停跟随，显示"回到最新消息"悬浮按钮；点击滚至底部并恢复跟随；手动滚回底部同样恢复；
- 容器 watch `scrollHeight` 突变：上滚状态下 `scrollTop += 高度增量`，保持阅读位置（覆盖卡片展开/收起、长内容展开）。

### 2.6 样式约束（FR-026 + 宪法 UI 约束）

- 全部颜色/字号/圆角引用 `frontend/src/styles/tokens.scss` CSS 变量；禁止硬编码色值与脱离规格字号；
- 卡片复用气泡视觉语言（白底 + `--border` 边框 + 10px 圆角），展开交互与 `msg-reasoning` 的 details 折叠一致。
