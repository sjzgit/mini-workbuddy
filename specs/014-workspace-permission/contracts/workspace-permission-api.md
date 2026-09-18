# Contract: Workspace & Permission API（014 主定义）

> 本文件是工作空间 API、权限事件与错误码的**唯一主定义**。
> `backend/app/schemas/`（Pydantic）与 `frontend/src/api/chat.ts`（TypeScript）MUST 与本文件
> 逐字段对齐；变更先改本文件。风格沿袭 specs/008 chat-api.md 与 specs/013 ask-user-api.md。

## 1. Workspace API

前缀：`/api/conversations`（与既有会话路由同前缀；开发环境 Vite 代理 `/api`）。

### 1.1 GET /api/conversations/{conversation_id}/workspace

查询当前会话的工作空间。

**200 响应**（`ConversationWorkspaceOut`）：

```json
{
  "workspace_path": "D:\\projects\\my-project",
  "workspace_source": "user_selected",
  "workspace_selected_at": "2026-09-18T02:00:00"
}
```

未选择时三字段均为 `null`。`workspace_selected_at` 为 naive UTC ISO 字符串（项目口径）。

**404**：会话不存在 → `{"detail": "会话不存在"}`。

### 1.2 PUT /api/conversations/{conversation_id}/workspace

设置（或更换）当前会话的工作空间。**生成中（busy）允许调用**——设置只影响后续
AgentRun（运行快照语义，spec 二十八）。

**请求体**（`WorkspaceSetRequest`）：

```json
{ "path": "D:\\projects\\my-project" }
```

- `path`：必填，去首尾空白后 1–500 字符；必须是**绝对路径**

**200 响应**：`ConversationWorkspaceOut`（设置成功后的状态）。

**错误**：

| 状态 | 场景 | detail |
|------|------|--------|
| 404 | 会话不存在 | 会话不存在 |
| 400 | 路径是相对路径 | 请提供绝对路径（如 D:\projects\demo） |
| 400 | 路径不存在 | 工作空间路径不存在：{path} |
| 400 | 不是目录 | 工作空间路径不是目录：{path} |
| 400 | 命中系统保护路径 | 该路径为系统保护路径，不允许设为工作空间：{path} |
| 400 | 无法规范化解析 | 工作空间路径无法解析：{path} |

### 1.3 DELETE /api/conversations/{conversation_id}/workspace

清除当前会话的工作空间（三列置 NULL）。幂等：未设置时同样返回成功。

**200 响应**：`ConversationWorkspaceOut`（三字段 `null`）。

**404**：会话不存在。

### 1.4 ConversationSummary 增补

既有会话摘要（列表/新建/切换响应）增补字段：

```json
{ "workspace_path": "D:\\projects\\my-project" }   // null = 未选择
```

前端输入区入口据此渲染，无需额外请求。

## 2. SSE 事件

### 2.1 permission_checked（新事件）

**触发**：运行内每次 `file_read_write` / `shell` 权限判定后（含 allow，审计要求）。
**转发**：chat_service 桥接白名单；Recorder 落 `run_events`（结构性事件）。
**前端**：类型加入联合；本期聊天页不消费（前向兼容），运行记录时间线可读。

```json
{
  "run_id": "…", "seq": 5, "round": 1, "call_id": "t1a2b3c4d",
  "decision": "allow",
  "tool_name": "file_read_write",
  "path": "D:\\projects\\my-project\\src\\main.py",
  "reason": "路径在会话工作空间内"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| decision | `"allow" \| "ask_user" \| "deny"` | 三值决策（禁止布尔） |
| tool_name | string | 注册表名 |
| path | string | 规范化后的目标路径 |
| reason | string | 人话原因（不含文件内容/密钥） |

### 2.2 run_started 增补

```json
{ "workspace_path": "D:\\projects\\my-project" }   // null = 本次运行未选择工作空间
```

### 2.3 ask_user 复用（权限确认）

权限确认**不新增事件**：复用 013 `ask_user` 事件 + AskUserPanel + ask-answers 端点。
权限确认场景的负载特征：

```json
{
  "event": "ask_user",
  "data": {
    "call_id": "t1a2b3c4d",
    "question": "Agent 请求访问会话工作空间之外的路径：D:\\projects\\other\\a.txt（原因：路径在工作空间外）。是否允许本次运行访问？",
    "options": ["允许本次访问", "拒绝"],
    "multi_select": false
  }
}
```

回答语义：选中「允许本次访问」→ 临时授权（仅当前 AgentRun）并继续执行原工具调用；
选中「拒绝」/ 超时 / 取消 → 本次工具调用失败（见 §3 错误码），运行继续。

## 3. 工具错误码增补（ToolErrorCode 主定义增补）

| 错误码 | 场景 | 交还模型文案示例 |
|--------|------|------------------|
| `system_protected_path` | 目标命中系统保护路径（DENY，不可确认绕过） | `[system_protected_path] 路径位于系统保护目录，禁止访问：D:\Windows\a.txt` |
| `permission_denied_by_user` | 权限确认被拒绝/超时/取消 | `[permission_denied_by_user] 用户拒绝了本次路径访问授权：D:\projects\other\a.txt` |
| `path_resolution_failed` | 路径规范化解析失败 | `[path_resolution_failed] 路径无法解析：…` |
| `permission_check_failed` | 权限检查内部错误（按失败处理，不放行） | `[permission_check_failed] 权限检查失败，操作未执行` |
| `ask_user_unavailable` | 无人值守（评测直调）遇 ASK_USER | 同 013 文案（无用户可回答，请基于已有信息继续） |

既有 `path_outside_root` 保留：tool_executor 同步直调场景的系统目录白名单。

## 4. 工具参数契约变更（003 契约的增量）

### 4.1 file_read_write

- `path` 语义扩展：**相对路径**（相对系统授权目录，原语义不变）或**绝对路径**
  （进入统一权限判定：系统工作空间 ∪ 会话工作空间 ∪ 临时授权）
- 操作集合不变（read / write）；删除/移动等仍不支持（spec 三十五不做扩面）

### 4.2 shell

- 新增可选参数 `cwd`（string）：命令执行基准目录；缺省 = 会话工作空间（未选择则
  系统授权目录）。cwd 与命令文本中可明确解析的路径参数均经统一权限判定
- **安全边界声明（契约级）**：本检查为应用层路径检查，**不等同 OS 级沙箱**；命令
  执行体的间接访问（如脚本内部读外部文件）不在检查范围。未来经 ExecutionBackend
  （Docker/OS Sandbox）替换执行底座时本契约不变

## 5. 配置

| 环境变量 | 默认 | 说明 |
|----------|------|------|
| `PROTECTED_PATHS` | `""` | 追加系统保护路径，`os.pathsep` 分隔（Windows `;`）；与内置默认集合并 |

## 6. 权限判定规则（规范性）

1. 目标路径先规范化：expanduser → 相对路径按工具基准目录拼接 → `resolve()` →
   `normcase`（Windows 大小写/分隔符归一）
2. 判定顺序：**保护集 DENY** → 系统工作空间 ALLOW → 会话工作空间 ALLOW →
   临时授权 ALLOW → 其余 ASK_USER
3. 包含判断为目录树语义（`resolved == root or root in resolved.parents`），
   禁止字符串前缀比较
4. 临时授权仅当前 AgentRun 内有效；不落盘；不随会话持久化；不放大授权范围
