# Research: 用户工作空间与文件系统权限（014）

> Phase 0 输出。每个决策：结论 + 理由 + 已评估替代方案。全部基于代码库实读
（runtime.py / tools.py / ask_user.py / tool_executor.py / file_tool.py / shell_tool.py /
chat_service.py / models / config / AGENTS.md）。

## R1. Workspace 存储位置与形态

**Decision**: `conversations` 表新增 3 个可空列：`workspace_path`（String 500）、
`workspace_source`（String 20：`system` / `user_selected`）、`workspace_selected_at`
（DateTime 可空）。全空 = 未选择工作空间（授权范围仅系统目录）。`runs` 表新增
`workspace_path`（String 500 可空）记录运行时快照。

**Rationale**: spec 五「如果项目已有 Session 数据结构，请在现有结构上扩展」——本项目
Session 即 `ConversationEntry`（聊天会话），在其上扩展即最小侵入；3 列平铺优于 JSON 列
（可查询、可校验、与项目其他表风格一致）。`runs.workspace_path` 同时服务 US4-3
（Trace 反映启动时工作空间）与 FR-032 的映射落点。

**Alternatives**:
- 新建 `session_workspaces` 表：多一张表 + join，无查询收益（1:1 关系）→ 弃
- JSON metadata 列：项目无先例，SQLite JSON 查询弱 → 弃
- 内存 only：违反 FR-003 持久化要求 → 弃

## R2. 权限检查的接入点

**Decision**: 收敛在 `agent_runtime/tools.py` 的 `run_tool` 内，新增 builtin 工具的
**权限检查阶段**（在目录查名/取消检查之后、分发执行之前）：`file_read_write` 提取
`path`，`shell` 提取 `cwd`（新增参数）与命令中显式出现的绝对/相对路径参数；构造
`RunPermissionContext` 后调 `PermissionManager.check()`。ALLOW → 原有分发；ASK_USER →
走 013 挂起机制等用户答复；DENY → 结构化失败（`denied`）。

**Rationale**: `run_tool` 是运行内所有工具调用的唯一入口（tools.py 已有目录查名、
取消检查、分发三阶段），在此插入权限阶段即 Invariant 2「权限判断只能来自
PermissionManager、不能散落在 Tool 中」的最小实现。file_tool 内部的
`_resolve_within_root` 白名单检查移除（职责上移），避免双头判定。

**Alternatives**:
- 各工具实现内自查：违反 Invariant 2，两工具重复逻辑 → 弃
- tool_executor.execute 内查：这是同步直调入口（调试/评测），无 Session 运行上下文
  （无会话/挂起机制）；直调场景保持系统目录白名单（file_tool 保留系统目录回退）→ 采用
  「运行内查三值、直调查系统目录」的双层方案
- 装饰器/AOP：项目无先例，隐式行为 → 弃

## R3. PathResolver 的规范化算法

**Decision**: 纯 `pathlib` + `os.path` 方案：
① 输入字符串 `os.path.expanduser` 后，若非绝对路径则以**运行上下文的基准目录**
（file: 系统授权目录；shell: cwd 参数或系统授权目录）拼接；② `Path.resolve()`
（Python 3.12 在 Windows 上解析符号链接/junction，非严格模式不要求路径存在——
新文件场景可用）；③ Windows `str` 比较前 `os.path.normcase` 统一大小写与分隔符；
④ 包含判断：`resolved == root or root in resolved.parents`（目录树包含，非前缀）。

**Rationale**: spec 十三/十四/十五要求 canonical + 目录树判断 + Symlink 穿透，
`Path.resolve()` 是标准库对这三者的直接实现；`normcase` 处理 Windows 大小写
（NTFS 不敏感）。`is_relative_to` 在大小写上不做归一（Windows 下 `D:\A` vs `d:\a`
会误判），故用 normcase 后的字符串比较。

**Alternatives**:
- 字符串前缀 `startswith`：spec 明令禁止（D:\project vs D:\project2 误判）→ 弃
- 第三方 path 库：零新增依赖约束 → 弃
- resolve(strict=True)：新文件/待创建路径会抛错，需额外祖先回退 → 用非严格 resolve
  （Python 3.12 行为已满足：对不存在尾部不做展开但保留其后的规范化）

**Symlink 边界说明**: `Path.resolve()` 穿透符号链接依赖文件系统语义；对「链接本身
不存在」的中间段按普通目录名处理（与 POSIX readlink 行为一致）。测试用
`tmp_path` + `os.symlink`/Windows junction 覆盖可创建场景，跳过无权限平台
（`pytest.skip`），如实记录而非假装测试。

## R4. Temporary Grant 作用域与形态

**Decision**: 运行期 dataclass `TemporaryGrant(path, scope="current_run", created_at)`，
存放于 `RunPermissionContext.grants`（该上下文挂在本次运行的 ToolContext 上，随
RunContext 生灭）。用户允许后 grant 以**规范化后的请求路径**入列（最小权限：授权
文件本身；若被拒对象是目录列举类操作则授权该目录）。AgentRun 结束即随上下文销毁，
无任何落盘；下一次运行重新判定（spec 十九/二十二/二十三）。

**Rationale**: 作用域对象就是 RunContext 的生命周期，天然满足「不跨消息/不永久」；
落盘反而要加失效清理逻辑（YAGNI）。授权粒度取请求路径本身而非其所在目录树，
符合 spec 二十三最小权限。

**Alternatives**:
- 会话级 grant 表 + 过期时间：超出 MVP 范围（spec 三十五）→ 弃
- 内存全局 dict（进程级）：跨运行泄漏风险，直接违反 FR-023 → 弃

## R5. ASK_USER 复用方式

**Decision**: 完整复用 013 机制：`run_tool` 权限阶段判定 ASK_USER 后，调用
`ask_registry.register(call_id)` 注册挂起，`ToolCallRecord.ask` 置位 → runtime 主循环
现有 ask 分支发 `ask_user` 事件（问题文案 = 权限请求描述 + 路径 + 原因，选项 =
["允许本次访问", "拒绝"]，单选）→ `await_ask_user` 三路等待 → 回答后按选项文本
映射：允许 → 创建 TemporaryGrant 并继续执行原工具调用；拒绝/超时 → 结构化失败
（`permission_denied_by_user`），运行继续。

**Rationale**: spec 二十一明令复用；013 的注册表、回答端点、SSE 事件、前端
AskUserPanel 全部零改造可用。与 013 唯一的语义差异是「回答后的去向」：
ask_user 工具的答案交还模型作工具结果，权限确认的答案驱动 grant/拒绝——在
run_tool 内部消化，主循环无感知。

**Alternatives**:
- 新建确认通道/事件：平行机制，违反复用要求 → 弃
- 前端专用权限弹窗：多一条 SSE 事件 + 组件，收益为零（问题+选项已可表达）→ 弃

## R6. 系统保护路径策略

**Decision**: 默认保护集（Windows：`C:\Windows`、`C:\Program Files`、`C:\Program Files (x86)`、
`C:\ProgramData`；跨平台：用户 `.ssh`、`.aws`、`.gnupg` 目录）；`settings.protected_paths`
（字符串，`os.pathsep` 分隔）允许追加。判定在 ASK_USER 之前：规范化后命中保护集 →
DENY（`system_protected_path`），即使工作空间包含它也 DENY（保护集优先级最高）。
追加项同样不可被确认绕过。

**Rationale**: spec 十六要求「结合当前运行平台、策略可配置、不要硬编码巨大黑名单」。
默认集取 Windows 系统目录 + 常见凭据目录（与 danger_rules 密钥源口径呼应），
配置追加提供扩展能力。保护集判定先于授权并集，保证 Invariant 8。

**Alternatives**:
- 空默认集全靠配置：开箱即不安全 → 弃
- 巨大硬编码黑名单：spec 明确反对 → 弃
- 正则/通配符匹配：路径匹配语义复杂易错，用目录树包含即可 → 弃

## R7. Workspace API 形态

**Decision**: 遵循项目现有 REST 风格（chat.py 先例）：
`GET/PUT/DELETE /api/conversations/{conversation_id}/workspace`。PUT 体
`{"path": "..."}`；响应统一 `ConversationWorkspaceOut {workspace_path,
workspace_source, workspace_selected_at}`。校验失败 400/422、会话不存在 404。
busy（生成中）**允许**设置——快照语义保证正在运行的 AgentRun 不受影响
（这正是 spec 二十八的验收场景）。

**Rationale**: chat_service/api 已有会话域路由前缀与异常映射，直接挂同一路由文件；
spec 九「如果当前项目 API 风格是 REST，请遵循现有架构」成立。

**Alternatives**:
- 独立 `/api/workspaces` 资源：工作空间是会话的 1:1 属性，拆出去徒增端点 → 弃
- PUT 语义用 PATCH：项目现有更新均为 PUT → 弃

## R8. AgentRun 快照机制

**Decision**: `run_agent_loop` 配置加载阶段（现有独立 DB 短会话内）读取会话工作空间，
写入 `RunContext.workspace_path`（运行期不可变）；`RunPermissionContext` 由该快照 +
系统目录 + 空 grants 构造，挂在 ToolContext。运行中工作空间 API 修改 DB，不影响
已构造的上下文。快照同时进 `run_started` 事件（`workspace_path` 字段）与
`runs.workspace_path` 列。

**Rationale**: spec 二十八「AgentRun 开始时 snapshot」；现有主循环 ① 阶段已有一次
DB 读取会话/Agent 配置，顺路读取零额外成本；RunContext dataclass 本就是快照载体
（agent/model 配置同模式）。

**Alternatives**:
- 每次权限检查时读 DB：运行中切换会污染进行中的运行，违反 Invariant 6 → 弃
- 前端传工作空间：信任边界错误（客户端不可授权）→ 弃

## R9. 错误码体系

**Decision**: 复用 `schemas/tool.py` 的 `ToolErrorCode` 枚举，新增 5 个：
`system_protected_path`、`permission_denied_by_user`、`permission_check_failed`、
`path_resolution_failed`、`ask_user_unavailable`。保留既有 `path_outside_root`
（直调场景）。Workspace API 校验错误用契约 detail 文案（工作空间不存在 /
不是目录 / 无法解析），HTTP 400/404/422 沿用 chat.py 既有映射。

**Rationale**: spec 三十「复用现有体系」优先；ToolErrorCode 是工具执行错误码唯一
主定义的实现载体，新码进枚举即全链路（事件/记录/前端）自动携带。

**Alternatives**:
- 新建 PermissionErrorCode 平行枚举：双体系，违反 SSOT → 弃
- 布尔 + message：spec 明令禁止三值压成布尔 → 弃
