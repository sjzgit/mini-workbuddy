# Research: Skills 与 MCP 管理（第四阶段）

**Date**: 2026-09-10 | **Status**: Complete

本阶段技术决策记录。每项含：Decision（结论）、Rationale（理由）、Alternatives（被否方案）。
本文解决 spec Assumptions 留给 Plan 阶段的全部待决项：Skill 目录内文件组织、合规判定标准、
测试超时上限、掩码形式、workspace 位置。无 NEEDS CLARIFICATION 遗留。

---

## R1 Skill 以文件为本：内容不入库，状态入库（FR-002/003/011/013）

**Decision**: 双层职责划分：

- **Skill 内容的事实源是文件**：`backend/workspace/skills/<dir_name>/skill.md`——单文件承载
  名称（frontmatter `name:`）、用途说明（frontmatter `description:`）、详细指令（frontmatter
  之后的 Markdown 正文）。文件格式主定义见 [contracts/skills-api.md](contracts/skills-api.md) §2。
  spec 需求明确"用户可在该目录下手动创建 Skill、刷新后无需重启即被发现"——文件必须是本体，
  入库反而制造第二事实源（手动改动文件后 DB 与文件漂移）。
- **SQLite `skills` 表只持久化用户状态**：`dir_name`（唯一键）+ `enabled`（默认启用）+ 时间戳。
  刷新动作执行"目录 ↔ DB 行"同步：新合规目录补行（默认启用）、已删除目录清行、不合规目录
  跳过并计入 skipped 列表提示（FR-005）。列表展示的名称/说明/更新时间实时从文件读取（更新时间
  取文件 mtime），DB 只出 enabled。
- **合规判定**（spec Assumption 移交项）：目录内存在 `skill.md` 且非空 → 合规；`name` 缺失取
  目录名兜底、`description` 缺失为空串——手动创建者无需了解 frontmatter 也能被列出；`skill.md`
  缺失或空文件 → 不合规，跳过并提示。该口径同时用于刷新跳过与 ZIP 导入校验（同一函数）。

**Rationale**: "文件为本 + 状态入库"让"删库即空列表"（003 的空状态语义）与"删文件即 Skill 消失"
天然一致；frontmatter+正文是业界 Skill 分发的通用格式（Claude Skills 等），ZIP 导入的外部包
无需转换即可使用。

**Alternatives**:

- *内容全部入库（文件仅作导入通道）*：手动改文件后页面不反映，FR-003"重新扫描目录更新列表"
  退化为空话，违反 SSOT，否决。
- *meta.json + instruction.md 双文件*：格式自创、与业界 Skill 包格式不兼容，导入前需转换，否决。
- *启用状态存文件（frontmatter 加 enabled 键）*：停用是用户状态而非内容，写文件会产生与外部
  工具（git）的噪声 diff，且"文件为本"语义被污染，否决。

---

## R2 skill.md 文件格式与编辑回写（FR-010/011）

**Decision**: 文件结构（主定义 [contracts/skills-api.md](contracts/skills-api.md) §2）：

```markdown
---
name: 会议纪要整理
description: 把口述或草稿整理成结构化会议纪要
---
（此后为详细指令正文，Markdown，供 Agent 阅读）
```

- 解析器手写（`skill_files.py`）：识别首行 `---`、逐行 `key: value` 直到闭合 `---`，仅消费
  `name`/`description` 两键（其余键原样保留？否——**编辑保存时 frontmatter 只重写这两个键**，
  未知键丢弃，避免"页面上看不见却影响行为"的暗字段）；无 frontmatter 的文件视为正文全为指令、
  name 取目录名（宽松读取，严格写入：保存后文件必然是规范格式）。
- 编辑保存 = 整文件重写（frontmatter 由 name/description 生成 + 原正文），UTF-8、`\n` 换行。
  保存后刷新 DB 行 `updated_at` 并即时返回最新列表项。
- 编辑读取：`GET /api/skills/{dir_name}` 返回 name/description/instruction 三字段（契约 §3）。

**Rationale**: 三区域编辑页（名称/用途说明/详细指令）与文件三部分一一对应，写回规则无歧义；
"宽松读、严格写"让手动创建的粗糙文件可被列出，一经页面编辑即被规范化，渐进对齐格式。

**Alternatives**: *引入 PyYAML 解析 frontmatter*：两键解析不需要完整 YAML 依赖，且 YAML 报错
信息对非技术用户不友好，否决；*三个独立文件*：目录内容翻倍、部分写入有撕裂风险，否决。

---

## R3 MCP 协议客户端：官方 SDK（FR-018/025~028）

**Decision**: `uv add mcp`（官方 MCP Python SDK）。测试连接流程（`services/mcp_client.py`，async）：

```text
connect_and_list(config)                      # 总超时 asyncio.wait_for(settings.mcp_test_timeout_seconds)
├─ stdio: StdioServerParameters(command, args=list, env=最小安全环境+用户env)
│        async with stdio_client(params) as (r, w) → 子进程由 SDK 启动、退出时终止（零残留，FR-031）
├─ http:  streamablehttp_client(url, headers) → 连接复用自定义 Header
├─ async with ClientSession(r, w): await session.initialize()   # 协议初始化握手
├─ tools = await session.list_tools()          # 仅发现，绝不调用 call_tool（FR-026）
└─ 返回 McpToolInfo[]（name/description/inputSchema 解析为参数表）
```

命令与参数以独立字段直传 SDK（argv 数组形态），**不存在 Shell 拼接路径**（FR-021 由 SDK 传输
机制结构性保证）。stdio 子进程环境用 SDK 的 `get_default_environment()`（最小安全环境：仅
HOME/PATH 等）叠加用户 env——既避免泄漏本机全量环境变量，又保证可执行文件可被找到。

**Rationale**: MCP 的 Streamable HTTP 传输含 SSE 流、会话管理、协议版本协商，手写协议栈的
风险与维护成本远超收益；SDK 是 MCP 官方实现，协议兼容性（FR-028"协议版本不兼容"检测）由其
异常语义直接给出。async 服务挂到 FastAPI async 路由，无额外事件循环管理。

**Alternatives**:

- *手写 JSON-RPC over stdio*：stdio 侧勉强可行，但 HTTP 侧的 SSE/会话/重试不可行，两传输形态
  行为不一致，否决。
- *仅支持 stdio，HTTP 推迟*：FR-018 明确要求两类都支持，否决。

---

## R4 测试连接失败六分类与脱敏（FR-028/029，契约主定义见 mcp-api.md §5）

**Decision**: `mcp_client.py` 把 SDK/系统异常映射为错误分类枚举：

| 分类 | 判定依据 | 人话提示要点 |
|------|---------|--------------|
| `command_not_found` 启动命令不存在 | stdio 启动抛 `FileNotFoundError` | 检查命令名是否已安装、PATH 可达 |
| `process_failed` 启动失败或提前退出 | 进程非零退出 / 流过早关闭（`EOFError`、`ClosedResourceError`、`BrokenResourceError`） | 程序自身崩溃或参数不完整 |
| `timeout` 连接或读取超时 | `asyncio.TimeoutError`（总超时 30s，`settings.mcp_test_timeout_seconds` 可覆盖） | 启动慢或 Server 无响应 |
| `protocol_incompatible` 协议版本或响应格式不兼容 | SDK `McpError` 且含版本/初始化语义 | Server 与本系统协议版本不匹配 |
| `server_error` Server 主动返回错误 | SDK `McpError`（Server 端 JSON-RPC error） | 原样转述 Server 错误信息（脱敏后） |
| `connection_failed` 连接失败 | httpx `ConnectError`/`OSError`（HTTP 类） | 地址不可达、端口错误 |
| `unknown` 未知错误 | `Exception` 兜底 | 未知错误 + **脱敏诊断信息**（stderr/异常摘要，截断 500 字符） |

**脱敏**（`_sanitize` 纯函数）：用该 Server 配置中的 env 值与 Header 值（非空、长度 ≥ 4）对诊断
文本做全量替换为 `******`；诊断信息不包含完整命令行回显。该函数独立单测（test_mcp_client.py）。

**Rationale**: 分类依据全部来自异常类型判别（可单测），不靠字符串猜测；六类与 spec FR-028 列举
一一对应，`unknown` 兜底满足 FR-029"无法确定原因时明确提示 + 脱敏诊断"。

**Alternatives**: *按错误文本关键词分类*：随 SDK 措辞变化而脆断，否决；*不区分失败原因统一
提示*：直接违反 FR-028，否决。

---

## R5 敏感值加密复用密钥库；掩码与"保留原值"协议（FR-023/024）

**Decision**:

- **存储**：`mcp_servers` 表持两个指针列 `env_secret_ref` / `headers_secret_ref` → 既有
  `secrets_vault` 表（Fernet，[secret_vault.py](../../../backend/app/core/secret_vault.py)）。
  密文明文分别是 `JSON.stringify(env_dict)` 与 `JSON.stringify(headers_dict)`——整体一条密文，
  增删键不产生多条散密文。复用 `store_secret`/`load_secret`/`delete_secret`/`has_secret` 四个
  既有函数，零新增加密代码。
- **对外掩码**：详情接口返回 `env_masked: {key: "••••••"}`、`headers_masked: {key: "••••••"}`，
  以及 `has_env`/`has_headers` 布尔。**任何接口响应不含明文**；测试结果、日志、诊断信息经 R4
  `_sanitize` 脱敏。
- **编辑"保留 or 替换"协议**（契约 §4）：提交体 `env: dict[str, str | null]`、
  `headers: dict[str, str | null]`——值为 `null` = 保留该键原值；值为字符串 = 替换/新增；
  键缺席 = 删除该键。前端编辑页值输入框显示占位提示"已配置：留空保留原值"，空值提交 null，
  **掩码永远不会被当作实际值保存**（掩码只出现在只读展示层，不进表单值）。
- `secrets_vault.ciphertext` 列为 `String(512)`——SQLite 不强制 VARCHAR 长度上限，长密文可存；
  在 data-model.md 注明该语义，不改 002 既有模型。

**Rationale**: 002 已确立"密钥库 + secret_ref 指针 + 留空保留"的成熟模式，本阶段是同模式在
多键值对场景的推广；`str | null` 三态协议让"保留/替换/删除"三个动作在契约层显式无歧义。

**Alternatives**:

- *每键一条密文（dict of secret_ref）*：关系建模复杂化（需第三张表），整体 JSON 密文已满足
  "整存整取、永不部分展示"的访问模式，否决。
- *掩码值提交后后端识别掩码串跳过*：用户真想存 `"••••••"` 字面量时产生歧义，`null` 三态无此
  问题，否决。
- *headers 不加密*：`Authorization: Bearer …` 与 env 密钥同等敏感（需求虽只点名 env，但按同一
  安全底线对称处理），否决。

---

## R6 测试结果快照与"配置已变更"（FR-015/016/034）

**Decision**: `mcp_servers` 表持久化最近一次测试快照四列：`last_test_status`（NULL=未测试 /
`success` / `failed` / `config_changed`）、`last_test_message`（人话提示，已脱敏）、
`last_test_tool_count`、`last_test_at`；另有 `tools_json` 文本列（成功测试时序列化的
`McpToolInfo[]`，快照语义整体覆写）。列表页"测试结果"列按 status 渲染（未测试/成功 N 个工具/
失败原因/配置已变更，待重新测试），工具数量点击弹窗读 `tools_json`（经详情接口获取，列表接口
不带全量工具减负载）。

- **触发 `config_changed`**：编辑保存时比较 command/command_args/env/url/headers 五项实际值
  （env/headers 解密后按 dict 相等比较）——任一变化且存在旧测试结果 → `last_test_status =
  'config_changed'`（message 固定"配置已变更，待重新测试"，保留旧 tool_count 与 tools_json：
  它们仍是"最近一次成功测试"的事实记录，spec 仅要求标记测试结果失效）。
- **失败也留痕**：测试失败同样更新四列（status=failed + 分类提示），"最近一次测试结果"如实
  反映。
- **并发控制**：`mcp_service` 模块级 `dict[int, asyncio.Lock]`；测试开始前 `lock.locked()`
  检查 + 获取失败即返回 400"该 Server 正在测试中"（同一 Server 至多一次，FR-030）；删除/编辑
  时锁被占用 → 400"正在测试中，请稍后再试"。锁常驻不清理（数量 = 曾测试的 Server 数，内存
  占用可忽略；进程重启自然清零）。

**Rationale**: 快照落库满足"重启后仍可见"（FR-022/SC-004）与工具弹窗离线可看；`config_changed`
按"值是否真变"判定而非"是否走过编辑表单"，避免无谓失效。

**Alternatives**:

- *工具列表单独建表 `mcp_tools`*：快照语义（整体覆写、无单条查询、无跨 Server 聚合）用 JSON
  列已完备，第三张表属过度建模（宪法 V），否决。
- *内存缓存测试结果*：重启即丢，违反 SC-004，否决。

---

## R7 ZIP 导入安全与结构校验（FR-006~009）

**Decision**（规则主定义 [contracts/skills-api.md](contracts/skills-api.md) §5）：

1. **上传**：`POST /api/skills/import`，multipart `file` 字段，仅接受 `.zip`（文件名后缀 +
   ZIP 魔数 `PK\x03\x04` 双重校验）。
2. **安全解压**：Python 3.12 标准库 `zipfile`；每个条目先做 `Path(entry).is_absolute()` 与
   `..` 片段检查，解压目标统一收敛到 `tmp_path/<skill_dir>/` 内再 `resolve()` 验证包含性——
   双重校验（黑名单 + 包含性），**任何条目越界即整体失败**，无部分落盘（FR-009）。
3. **资源上限**：解压总字节数 ≤ 10MB（`settings.skill_import_max_bytes`）、条目数 ≤ 200、
   单条目解压前累加校验——抑制 zip bomb。
4. **结构判定**：复用 R1 合规函数——ZIP 根直接含 `skill.md` → Skill 目录名取 ZIP 文件名去
   后缀；ZIP 含唯一顶层目录且其中有 `skill.md` → 取该目录名；否则结构不符失败。
5. **同名冲突**：目标 `workspace/skills/<dir_name>` 已存在 → 拒绝，提示同名冲突（FR-008），
   已有目录零改动。
6. **落地**：校验全过 → 目录整体移入 `workspace/skills/` → 刷新同步（新行默认启用）→ 返回
   新 Skill 列表项。全程临时目录操作，失败自动清理。

**Rationale**: "先解到隔离临时目录 → 校验 → 原子移入"使失败路径不可能污染目标目录；上限值
（10MB/200 条）对单机 Skill 分发场景宽裕且能有效拦住解压攻击。

**Alternatives**:

- *流式解压到目标目录 + 失败回滚删除*：回滚逻辑复杂且失败窗口内文件已可见，否决。
- *支持多 Skill 打包（一个 ZIP 多个 Skill 目录）*：spec Assumption 明确"单个 ZIP 对应一个
  Skill"，否决。

---

## R8 前端形态与交互（FR-001/015/017/020/030/035）

**Decision**: 替换两个占位页，沿用 002/003 确立的"Table + Modal/Drawer + tokens.scss"范式：

- **SkillsView**：Table（名称、说明、启用 `Switch`+确认、更新时间、操作列：编辑/删除）；页头
  右侧"导入 ZIP"（antd `Upload`，`beforeUpload` 拦截手动提交）与"刷新"按钮（loading 态）；
  刷新返回的 skipped 目录以 `message.warning` 提示；编辑用右侧 `Drawer`（名称 input +
  说明 input + 详细指令 `Textarea` autosize 大区域，Markdown 说明文字）；删除 `Modal.confirm`。
- **McpView**：Table（名称、说明、类型 `Tag`（本机/远程）、测试结果（按 status 着色：成功绿/
  失败红/待重测橙/未测试灰）、工具数量（可点击打开 `McpToolsModal`：工具表含名称/用途/参数
  表）、启用 `Switch`+确认、操作列：测试/编辑/删除）；"新增"打开 `McpServerFormModal`：
  类型 `RadioGroup` 切换 stdio/http 两组字段；参数列表用动态行（每行一个 input，上下移动保序、
  可删除）；env/headers 用动态键值行（值 input 留空=保留原值，placeholder 提示）；顶部
  `Alert` 常驻字段说明与填写示例（"配置通常可从 MCP Server 的使用说明中获取，无需理解协议
  细节"）；测试按钮在该行测试中时 loading 并禁用编辑/删除/重复测试（FR-030、Edge Case）。
- 状态：`stores/skills.ts`、`stores/mcp.ts`（列表/loading/error + 变更后重拉；`mcp` store 额外
  持有 `testingId` 单一进行中标识）。api：`api/skills.ts`、`api/mcp.ts` 类型从契约派生。

**Rationale**: 两页信息密度不同（Skills 简单 / MCP 配置复杂），分别用 Drawer（长文本编辑）与
Modal（结构化表单）是 antd 既有惯例；工具数量弹窗符合 spec"点击弹窗展示"原文。

**Alternatives**: *Skills 编辑用整页路由*：三字段内容不值一个路由层级，否决；*MCP 表单拆
stdio/http 两个页面*：类型只是表单内一个切换维度，拆页反而割裂，否决。

---

## R9 配置集中（宪法 II，`core/config.py` 新增项）

**Decision**:

| 设置项 | 默认值 | 消费方 |
|--------|--------|--------|
| `skills_dir` | `./workspace/skills` | Skill 目录根（相对 backend 运行目录，与 `authorized_dir` 同约定） |
| `mcp_test_timeout_seconds` | `30` | 测试连接总超时 |
| `skill_import_max_bytes` | `10485760`（10MB） | ZIP 解压总大小上限 |

`.gitignore` 追加 `backend/workspace/`（已含 workspace 整目录则无需重复）。首次访问 `skills_dir`
自动创建（与 003 授权目录同策略）。

**Rationale**: 数值与路径约束收敛到唯一配置入口，环境变量可覆盖，调整不动代码（同 research
R9@003 的既有实践）。

---

## 结论

spec 留给 Plan 的全部待决项已解决：**R1 文件为本/状态入库**、**R3 官方 SDK**、**R4 六分类 +
脱敏**、**R5 密钥库复用 + null 三态保留协议** 为本阶段架构核心；Skill 目录根
（`./workspace/skills`）、合规口径（`skill.md` 存在且非空）、测试超时（30s）、掩码形式
（`••••••` 只读展示）、ZIP 上限（10MB/200 条）均有明确取值并进配置或契约。data-model 与
contracts 据此展开。
