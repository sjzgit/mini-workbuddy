# Data Model: 用户工作空间与文件系统权限（014）

> 主定义。ORM（`backend/app/models/__init__.py`）与 Alembic 迁移 MUST 与本文件一致；
> 变更先改本文件。

## 1. 持久化变更

### 1.1 conversations 表增补（Session Workspace）

| 列 | 类型 | 约束 | 说明 |
|----|------|------|------|
| workspace_path | String(500) | nullable | 用户选择的 Session Workspace 规范化绝对路径；NULL = 未选择 |
| workspace_source | String(20) | nullable | `system`（回落展示用）/ `user_selected`；仅 workspace_path 非空时有意义 |
| workspace_selected_at | DateTime | nullable | 最近一次设置时间（naive UTC，models._utcnow 口径） |

语义：三列全 NULL = 未选择工作空间。清除 = 三列置 NULL（单事务）。

### 1.2 runs 表增补（运行时快照）

| 列 | 类型 | 约束 | 说明 |
|----|------|------|------|
| workspace_path | String(500) | nullable | 本次运行启动时快照的会话工作空间；NULL = 启动时未选择 |

写入时机：`run_started` 事件落库时（RunRecorder）；运行期不可变（Invariant 6）。

### 1.3 迁移

- Alembic：`backend/migrations/versions/` 新增一个 revision（加列，幂等 downgrade）
- SQL 存档：`sql/migrations/014-workspace-permission.sql`

## 2. 运行期结构（不落盘）

### 2.1 RunPermissionContext（一次运行的权限上下文）

```text
RunPermissionContext
├── system_root: str          # 规范化后的系统授权目录（settings.authorized_dir resolve）
├── session_root: str | None  # 规范化后的会话工作空间快照（None = 未选择）
├── protected: list[str]      # 规范化后的保护路径集（默认集 + settings.protected_paths）
└── grants: list[TemporaryGrant]  # 本运行内用户允许产生的临时授权（初始空）
```

生命周期：run_agent_loop ① 阶段构造（快照），随 RunContext.aclose 销毁。

### 2.2 TemporaryGrant

```text
TemporaryGrant
├── path: str        # 规范化后的授权路径（文件本身或目录）
├── scope: str       # 恒 "current_run"（预留未来 run/message 细分）
└── created_at: datetime
```

判定扩展：`grants` 命中 = 规范化请求路径 == grant.path，或 grant.path 是请求路径的
目录祖先（授权目录时覆盖其子树）。随运行销毁，零持久化（Invariant 5）。

## 3. 权限判定状态机（PermissionManager.check）

```text
请求路径（工具参数提取）
    ↓ PathResolver.resolve（expanduser → 基准目录拼接 → resolve() → normcase）
规范化路径 resolution_failed? ── 是 → DENY(path_resolution_failed)
    ↓
命中保护集? ── 是 → DENY(system_protected_path)   【最高优先级，不可确认绕过】
    ↓
== system_root 或在其子树内? ── 是 → ALLOW
    ↓
session_root 非空且（== 或在其子树内）? ── 是 → ALLOW
    ↓
grants 命中? ── 是 → ALLOW（临时授权）
    ↓
否则 → ASK_USER（"路径在工作空间外"）
```

决策结构 `PermissionDecision(decision, path, reason)`：decision ∈
`allow / ask_user / deny`；reason 为人话文案 + 错误码（deny 时），供事件与工具失败文本。

## 4. Ask User 权限确认流（复用 013）

```text
run_tool 权限阶段
    ↓ check() == ask_user
ask_registry.register(call_id)          # 013 注册表
record.ask = AskPendingInfo(question=权限请求文案, options=["允许本次访问", "拒绝"], ...)
    ↓ （主循环现有 ask 分支）
SSE ask_user 事件 → 前端 AskUserPanel
    ↓ 回答（POST ask-answers，013 端点零改造）
"允许本次访问" → grants.append(TemporaryGrant(resolved_path)) → 继续执行原工具调用
"拒绝" / 超时 / 取消 → ToolCallOutcome(success=False, error_code=permission_denied_by_user)
```

与 013 ask_user 工具的差异：仅"回答后的去向"（grant/失败 vs 答案文本交还），
注册/事件/等待/端点/前端零改造。

## 5. 事件增补

### 5.1 permission_checked（新结构性事件，落 run_events）

```json
{
  "run_id": "…", "seq": 5, "round": 1, "call_id": "t1a2b3c4d",
  "decision": "allow | ask_user | deny",
  "tool_name": "file_read_write",
  "path": "D:\\projects\\my-project\\src\\main.py",
  "reason": "路径在会话工作空间内"
}
```

- 载荷模型：`schemas/agent_runtime.PermissionCheckedData`
- 时机：每次 file_read_write / shell 权限判定后、执行前发一条（含 ALLOW——审计要求
  可追溯每次判定，SC-008）
- 边界：只含路径与决策，**不含文件内容**（FR-033）

### 5.2 run_started 增补

| 字段 | 类型 | 说明 |
|------|------|------|
| workspace_path | str \| null | 运行快照的会话工作空间（None = 未选择） |

## 6. API 契约（详见 contracts/workspace-permission-api.md）

- `GET /api/conversations/{id}/workspace` → `ConversationWorkspaceOut | null 语义`
- `PUT /api/conversations/{id}/workspace` ← `{"path": "…"}`（校验存在/是目录/可解析）
- `DELETE /api/conversations/{id}/workspace`
- `ConversationSummary` 增补 `workspace_path: string | null`（列表/摘要携带，前端入口渲染用）

## 7. 配置增补（core/config.py）

| 项 | 默认 | 说明 |
|----|------|------|
| protected_paths | `""` | 追加保护路径，`os.pathsep`（Windows `;`）分隔；空 = 仅默认集 |

默认保护集（代码常量，Windows + 跨平台凭据目录）：`C:\Windows`、`C:\Program Files`、
`C:\Program Files (x86)`、`C:\ProgramData`、`~/.ssh`、`~/.aws`、`~/.gnupg`。
