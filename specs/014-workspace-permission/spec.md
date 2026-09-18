# Feature Specification: 用户工作空间与文件系统权限

**Feature Branch**: `014-workspace-permission`

**Created**: 2026-09-18

**Status**: Draft

**Input**: User description: "允许用户在 Chat Session 中选择当前 Workspace，并让 `file_read_write` / `shell` 工具基于统一的 Workspace Permission 机制访问文件系统"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 为 Session 选择工作空间（Priority: P1）

用户在 Chat 输入区域为当前 Session 选择一个目录作为工作空间（例如 `D:\projects\my-project`）。选择成功后，界面上显示当前工作空间路径，后续该 Session 的 Agent 操作即可以此目录作为授权访问范围之一。用户也可以随时清除当前工作空间，恢复为仅默认系统工作空间。

**Why this priority**: 这是整个功能的核心入口。没有"选择工作空间"这一步，后续所有基于工作空间的权限控制都无从谈起。它本身就是一个可独立交付的最小价值单元。

**Independent Test**: 在 Chat 输入区域选择一个目录 → 界面显示该目录为当前工作空间 → 再次进入该 Session 时工作空间仍然保留；点击清除后工作空间显示为空（未选择）。

**Acceptance Scenarios**:

1. **Given** 用户打开一个 Chat Session, **When** 用户在输入区域选择一个存在的目录作为工作空间, **Then** 界面显示当前工作空间为该目录，且提示信息表明选择成功
2. **Given** 用户已为 Session 设置了工作空间, **When** 用户刷新页面或重新打开该 Session, **Then** 当前工作空间仍然显示为之前选择的目录（工作空间随 Session 持久化）
3. **Given** 用户已为 Session 设置了工作空间, **When** 用户选择"清除当前工作空间", **Then** 界面显示未选择工作空间，后续 Agent 操作仅默认系统工作空间可用
4. **Given** 用户尝试设置一个不存在或不是目录的路径, **When** 用户提交该路径, **Then** 系统拒绝设置并提示路径无效，Session 保持原工作空间不变

---

### User Story 2 - 工作空间内的文件与 Shell 操作自动放行（Priority: P1）

Agent 在用户已设置工作空间的 Session 中使用 `file_read_write` 或 `shell` 工具访问工作空间内（含系统工作空间）的路径时，操作直接执行，不需要用户额外确认。

**Why this priority**: 这是工作空间存在的核心价值——让 Agent 的文件操作获得顺畅的授权体验。如果工作空间内的操作仍需逐次确认，功能就失去了意义。

**Independent Test**: 为 Session 设置工作空间 → 让 Agent 读取/写入工作空间内文件 → 操作直接成功，不出现确认请求。

**Acceptance Scenarios**:

1. **Given** Session 的系统工作空间为 `D:\mini-agent-data` 且 Session 工作空间为 `D:\projects\my-project`, **When** Agent 读取 `D:\projects\my-project\src\main.py`, **Then** 操作直接执行成功，无需用户确认
2. **Given** 同上, **When** Agent 写入/创建/删除/重命名/移动/复制/列出工作空间内文件（工具支持的每种操作）, **Then** 操作均直接执行成功
3. **Given** 同上, **When** Agent 以工作空间作为 cwd 执行 shell 命令, **Then** 命令直接执行成功
4. **Given** 用户未为 Session 选择任何工作空间, **When** Agent 访问系统工作空间内路径, **Then** 操作直接执行成功
5. **Given** 用户将 Session 工作空间从 A 切换为 B, **When** 用户发送下一条消息, **Then** Agent 使用 B 作为授权范围（消息 A 期间的结果不受影响）

---

### User Story 3 - 工作空间外路径触发用户确认（Priority: P1）

Agent 尝试访问工作空间之外（系统工作空间和 Session 工作空间均不覆盖）的路径时，系统不直接执行也不直接拒绝，而是向用户发起确认请求。用户允许则本次执行临时获得该路径的访问授权；用户拒绝则本次操作失败，Agent 继续运行并知晓被拒绝。

**Why this priority**: 这是权限模型的核心安全交互，与 Story 2 共同构成完整的权限闭环。它与 Story 2 一起界定"什么能直接做、什么要问人"。

**Independent Test**: 让 Agent 访问工作空间外路径 → 出现确认请求 → 允许后操作成功且仅本次运行有效；拒绝后操作失败但运行不中断。

**Acceptance Scenarios**:

1. **Given** Session 工作空间为 `D:\projects\my-project`, **When** Agent 请求读取 `D:\projects\other-project\a.txt`, **Then** 系统向用户展示确认请求（包含待访问路径与原因）
2. **Given** 系统展示了路径访问确认请求, **When** 用户选择允许, **Then** 当前 AgentRun 中该路径的访问获得临时授权，操作继续执行成功
3. **Given** 系统展示了路径访问确认请求, **When** 用户选择拒绝, **Then** 该操作以失败结束（Agent 收到明确的拒绝信息），AgentRun 本身继续运行
4. **Given** 用户在消息 A 的 AgentRun 中允许过访问 `D:\projects\other-project`, **When** 用户发送消息 B 且 Agent 再次访问该路径, **Then** 系统再次发起确认（临时授权不延续到下一次运行）
5. **Given** Agent 请求访问的路径位于系统保护目录（即使其逻辑上可以通过确认请求放行）, **When** Agent 尝试访问, **Then** 操作直接被拒绝，不向用户发起确认请求

---

### User Story 4 - 运行中的 AgentRun 不受工作空间切换影响（Priority: P2）

用户在某个 AgentRun 正在执行时切换 Session 工作空间，正在运行的 AgentRun 仍按其启动时的工作空间执行，不会中途改变授权范围。工作空间的修改只影响后续的 AgentRun。

**Why this priority**: 这是保障状态一致性的重要行为约束，但不阻塞主流程——多数用户不会在运行中途切换工作空间。

**Independent Test**: 启动一个长时间运行的 Agent 任务 → 任务执行中切换工作空间 → 该任务的后续操作仍按启动时的工作空间判断权限。

**Acceptance Scenarios**:

1. **Given** AgentRun 1 在工作空间 A 下运行中, **When** 用户将 Session 工作空间切换为 B, **Then** AgentRun 1 后续的权限判断仍以 A（及系统工作空间）为准
2. **Given** 用户在 AgentRun 运行中切换了工作空间, **When** 用户发送下一条消息触发 AgentRun 2, **Then** AgentRun 2 以新工作空间 B 为准
3. **Given** AgentRun 1 运行期间用户切换工作空间, **When** 用户查看运行记录（Trace）, **Then** AgentRun 1 的记录反映其启动时使用的工作空间

---

### User Story 5 - 权限决策可追溯（Priority: P2）

用户（开发者）可以在运行记录（Trace / 事件时间线）中看到与文件系统权限相关的事件：工作空间的变更历史、每次路径访问的权限决策（放行/询问/拒绝）及原因，便于调试与审计。

**Why this priority**: 可观测性是生产级 Agent Runtime 的必要能力，但不阻塞核心链路，属于重要但非首日必须的增强。

**Independent Test**: 执行一系列带权限检查的操作后 → 打开该 Session 的运行记录 → 能看到工作空间变更事件与权限决策事件（含路径、决策、原因）。

**Acceptance Scenarios**:

1. **Given** 用户在 Session 中切换了工作空间, **When** 用户查看运行记录, **Then** 能看到工作空间变更事件（旧值、新值、来源、时间）
2. **Given** Agent 执行了若干文件/shell 操作, **When** 用户查看运行记录, **Then** 能看到权限检查记录（工具、路径、决策 ALLOW/ASK_USER/DENY、原因）
3. **Given** 系统发起了路径访问确认请求且用户做出了选择, **When** 用户查看运行记录, **Then** 能看到用户允许或拒绝的记录

---

### Edge Cases

- Agent 请求路径为 `D:\project\src\..\secret.txt`（含 `..`）时如何处理？→ 系统先将路径规范化（canonicalize）为真实绝对路径再判断，`..` 不能用于绕过授权范围
- Agent 请求路径为 `D:\project`（授权根目录本身）时如何处理？→ 授权根目录本身视为可访问
- Agent 请求路径位于 `D:\project2`（与授权目录 `D:\project` 前缀相似但属于同级目录）时如何处理？→ 必须判定为工作空间之外，前缀相似不构成授权
- Workspace 内存在符号链接/链接目录指向工作空间外部（如 `D:\project\link → D:\secret`）时如何处理？→ 路径解析必须穿透符号链接，`D:\project\link\secret.txt` 不能因为字符串位于工作空间下就直接放行
- 用户输入相对路径（如 `.\src`）作为工作空间或请求路径时如何处理？→ 系统基于明确规则解析为绝对路径后再判断
- Windows 大小写不敏感与路径分隔符差异（`/` 与 `\`）如何处理？→ 判断时按平台语义进行等价处理，不因写法差异误判
- 用户请求的路径正好位于授权目录边界（如 `D:\project` 与 `D:\project\` 尾部分隔符差异）如何处理？→ 规范化后等价处理
- Agent 请求的路径当前不存在（如要创建的新文件）如何处理？→ 基于最近存在的祖先目录进行规范化解析后再判断
- Agent 尝试执行 shell 命令，命令中以字符串形式引用了未授权路径（如 `cat D:\secret\a.txt`）时如何处理？→ 系统对能明确解析出的 cwd 与文件路径参数进行权限检查；无法可靠解析的部分作为已记录的应用层限制，不声称完全隔离
- Agent 执行的 shell 命令间接访问了未授权资源（如脚本内部读取外部文件）时如何处理？→ 本期明确不承诺 OS 级隔离，作为已知边界记录，架构预留沙箱扩展点
- 权限检查过程中发生内部错误（如路径解析失败）时如何处理？→ 操作失败并返回明确的错误类别（而非笼统的"拒绝"），不因内部错误而放行
- 用户在确认请求出现时关闭页面/不响应时如何处理？→ 该 AgentRun 保持等待或超时失败，不自动放行

## Requirements *(mandatory)*

### Functional Requirements

**工作空间选择与持久化**

- **FR-001**: System MUST 允许用户在 Chat 输入区域为当前 Session 设置一个本地目录路径作为 Session Workspace
- **FR-002**: System MUST 校验用户设置的工作空间路径：路径存在、是目录、可规范化解析；校验失败时拒绝设置并返回明确的错误原因
- **FR-003**: System MUST 将 Session Workspace 随 Session 持久化，Session 重新打开后仍然生效
- **FR-004**: System MUST 支持修改和清除 Session Workspace；清除后该 Session 的授权范围回落为仅系统工作空间
- **FR-005**: System MUST 记录 Session Workspace 的来源（系统默认 / 用户选择）与设置时间
- **FR-006**: System MUST 保证 Session Workspace 属于 Session 作用域：同一 Agent 下不同 Session 可拥有互不相同的工作空间
- **FR-007**: System MUST 提供 Session Workspace 的查询、设置、清除能力（API 形式遵循项目现有 API 风格）

**权限模型**

- **FR-010**: System MUST 以"系统工作空间 + Session 工作空间 + 临时授权"的并集作为文件系统访问的授权范围
- **FR-011**: System MUST 提供集中式的权限判断，返回三值决策：ALLOW / ASK_USER / DENY，并附带决策原因；禁止仅返回布尔值
- **FR-012**: System MUST 将权限判断收敛到统一权限层，`file_read_write` 与 `shell` 工具 MUST 使用同一权限层；权限判断逻辑禁止散落在各工具内部各自实现
- **FR-013**: System MUST 在权限判断前对请求路径做规范化解析（解析 `..`、`.`、相对路径、重复分隔符、大小写、符号链接），再与规范化后的授权根目录做目录树包含判断；禁止使用简单字符串前缀比较
- **FR-014**: System MUST 对符号链接/链接目录做穿透解析，工作空间内的链接指向外部目标时，按解析后的真实目标路径判断权限
- **FR-015**: System MUST 维护系统保护路径策略：命中保护路径的访问一律 DENY，且不允许用户通过确认放行；保护路径列表 MUST 可通过系统配置扩展，而非硬编码于代码逻辑中
- **FR-016**: System MUST 为权限检查产生的决策保留原因说明（如"路径在工作空间外"、"命中系统保护路径"、"用户拒绝"），用于展示、Trace 与审计

**Ask User（路径确认）**

- **FR-020**: System MUST 在权限决策为 ASK_USER 时，暂停当前工具执行并向用户发起路径访问确认请求，请求中包含待访问路径与请求原因
- **FR-021**: System MUST 复用项目已有的 Ask User（human-in-the-loop）机制完成上述确认交互，不另建平行机制
- **FR-022**: System MUST 在用户允许时为当前 AgentRun 创建临时授权（Temporary Grant），使本次运行内对该路径的访问直接放行
- **FR-023**: System MUST 保证临时授权的作用域为当前 AgentRun：下一次用户消息触发的 AgentRun 不继承任何临时授权，必须重新检查
- **FR-024**: System MUST 保证临时授权遵循最小权限原则：授权范围限于被请求的具体路径（或其所在的具体目录），禁止因用户允许一次而放大到无关的上级目录
- **FR-025**: System MUST 保证临时授权不会永久修改 Session Workspace 或系统工作空间
- **FR-026**: System MUST 在用户拒绝时使本次工具操作以失败结束（带明确的"用户拒绝"原因），且 AgentRun 继续运行不中断
- **FR-027**: System MUST 保证权限判断由运行时/安全层执行，LLM（模型输出）不能决定或影响权限决策结果

**运行一致性**

- **FR-030**: System MUST 在 AgentRun 启动时快照当前生效的工作空间上下文，运行期间的权限判断使用该快照
- **FR-031**: System MUST 保证 Session Workspace 的修改不影响正在运行的 AgentRun，仅影响后续 AgentRun
- **FR-032**: System MUST 在已有事件/Trace 体系中记录工作空间变更事件（旧值、新值、来源、时间）
- **FR-033**: System MUST 在已有事件/Trace 体系中可追踪每次权限检查的关键信息（工具、路径、决策、原因），且不记录文件内容、密钥等敏感数据

**Shell 特殊约束**

- **FR-040**: System MUST 对 shell 命令中能明确解析出的 cwd 与文件路径参数执行统一权限检查
- **FR-041**: System MUST 在产品文档与运行说明中如实说明：当前 shell 保护为应用层检查，不构成 OS 级沙箱隔离；命令内部的间接访问不在检查范围内
- **FR-042**: System MUST 保留未来接入真正沙箱（容器/OS 级）的扩展点，当前不实现沙箱本身

**错误处理**

- **FR-050**: System MUST 区分权限与工作空间相关的错误类别（至少包括：工作空间不存在、工作空间无效、路径在工作空间外、命中系统保护路径、用户拒绝、权限检查内部失败、路径解析失败），错误信息对用户可理解
- **FR-051**: System MUST 在权限检查发生内部错误时按失败处理（不因内部错误放行），并返回明确的错误类别

### Key Entities *(include if feature involves data)*

- **Session Workspace**: 用户为某个 Chat Session 选择的工作空间。关键属性：路径、来源（系统默认 / 用户选择）、设置时间。属于 Session，而非 Agent；同一 Agent 下不同 Session 各自独立
- **System Workspace**: 系统配置指定的默认授权目录，所有 Session 默认可访问（本功能沿用现有系统配置，不改变其定义方式）
- **Temporary Grant**: 用户通过确认请求授予的临时访问授权。关键属性：路径、作用域（当前 AgentRun）、创建时间。随 AgentRun 结束而失效，不落盘持久化
- **Permission Decision**: 一次权限检查的结果记录。关键属性：决策（ALLOW / ASK_USER / DENY）、路径、工具、原因
- **Path Resolution**: 路径规范化过程。关键属性：原始输入、规范化结果。负责处理相对路径、`..`、符号链接、平台路径语义差异

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 用户可以在 30 秒内完成为 Session 选择工作空间的操作，且选择结果在重新打开 Session 后保持
- **SC-002**: 工作空间内的文件读写与 shell 操作 100% 免确认直接执行，不向用户弹出确认请求
- **SC-003**: 工作空间外的路径访问 100% 触发确认请求或被拒绝，零"未确认直接执行"的情况（安全抽查 100% 通过）
- **SC-004**: 路径绕过尝试（`..` 回溯、前缀相似目录、符号链接穿透、大小写/分隔符变体）100% 被正确判定，不因路径写法变体而放行
- **SC-005**: 临时授权 0 泄漏：用户允许后，下一次消息触发的 AgentRun 访问同一路径时 100% 重新发起确认
- **SC-006**: 运行中的 AgentRun 在工作空间切换后 100% 保持启动时的授权范围（通过运行记录验证）
- **SC-007**: 90% 以上的路径访问确认请求，用户无需额外帮助即可理解请求内容并做出选择（可理解的请求呈现）
- **SC-008**: 所有权限决策均可在运行记录中追溯（工具、路径、决策、原因齐全），追溯覆盖率 100%
- **SC-009**: 现有功能回归测试 100% 通过，新功能的自动化测试覆盖上述全部核心场景（工作空间管理、路径规范化、权限决策、临时授权、工具接入）

## Assumptions

- 本功能沿用项目现有的 Session 数据结构与持久化方式，在其上扩展工作空间信息，不新建平行存储
- 本功能沿用项目现有的 Ask User（human-in-the-loop）机制（见 specs/013-ask-user-tool），不新建平行确认通道
- 系统工作空间沿用现有系统配置（默认授权目录），本功能不改变其配置来源
- 用户只能选择真实存在的本地目录作为工作空间（MVP 不支持"尚不存在、将来创建"的目录）
- 本期产品形态为单机单用户工作台，无需多用户/多角色权限体系（RBAC/ACL 明确不在范围内）
- 本期不实现 OS/容器级沙箱；shell 的应用层检查是已知安全边界，需在文档与运行说明中如实说明
- 权限检查与路径解析均在后端运行时层实现（与现有工具执行链路一致），前端只负责工作空间的展示与设置入口
- Windows 为当前主要部署平台，路径规范化需覆盖 Windows 路径语义（大小写不敏感、盘符、分隔符），同时保持跨平台可移植性
- Trace/事件中记录路径与决策原因，但不记录文件内容与凭据类敏感数据
