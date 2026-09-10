# Research: 工具管理（第三阶段）

**Date**: 2026-09-10 | **Status**: Complete

本阶段技术决策记录。每项含：Decision（结论）、Rationale（理由）、Alternatives（被否方案）。
本文解决 spec 留给 Plan 阶段的全部待决项（授权目录、默认时区、超时/截断数值等），无 NEEDS CLARIFICATION 遗留。

---

## R1 工具元数据与启停状态的职责划分（FR-001~008）

**Decision**: 代码注册表 + 数据库状态表，各管一事：

- **工具元数据**（名称、用途说明、参数说明、适用场景、输入要求、使用限制、是否内置）主定义在 [contracts/tool-definitions.md](contracts/tool-definitions.md)，实现载体为后端代码注册表 `services/tool_registry.py`——工具的说明文本与参数校验必须与工具的可执行实现同源演化，放进数据库会制造第二事实源。
- **启停状态**持久化在 SQLite `tools` 表（`name` 唯一键 + `enabled`），满足宪法"数据必须入库"与 FR-008。
- **播种**：Alembic 迁移建表时插入三条内置工具行（`current_time` / `shell` / `file_read_write`，默认启用）。另提供幂等的 `tool_service.ensure_seeded(session)` 作为测试与运维引导入口（表清空后可手动恢复，正常运行不自动调用，保证"数据被清空 → 空状态"可复现）。

**Rationale**:

1. spec Edge Case 明确要求"工具数据被清空时展示空状态"——以 DB 行作为工具的注册事实，清空即空列表，语义自洽；若列表永远由代码注册表渲染则该场景永不可达。
2. 执行入口的"工具是否存在"查注册表，"是否启用"查 DB——存在性与元数据属系统能力（随代码版本发布），启停属用户状态（随数据持久化），两者生命周期不同。
3. 说明文本若入库，每次措辞修订都要写数据迁移；留在契约+注册表，代码版本即文档版本。

**Alternatives**:

- *全部字段入库（元数据 + 状态）*：说明文本被复制进 DB，违反 SSOT（宪法 II），否决。
- *DB 只存启停覆盖行、无行=启用*：清空数据后页面仍显示三个工具，"空状态"不可复现，与 spec Edge Case 冲突，否决。
- *启动时（lifespan）自动播种*：测试中 TestClient 的 lifespan 使用真实 engine 而夹具覆盖的是内存库，播种对测试不可见导致用例不稳定；且"清空数据后自动复活"让空状态不可测，否决。

---

## R2 对外标识符：工具 name 作为主键（FR-005/009）

**Decision**: HTTP 路径与执行入口统一用注册表键 `name`（`current_time` / `shell` / `file_read_write`）作为工具标识：`GET /api/tools/{name}`、`PUT /api/tools/{name}/enabled`、`execute(name, params)`；DB `id` 仅作内部主键不出现在契约中。

**Rationale**: 内置工具是固定系统组件而非用户创建的记录，name 是稳定且对模型有意义的自然键（Agent Loop 调用时传的就是它）；002 的模型用自增 id 是因为那是用户自建行。执行入口"按名称查注册表"与"按名称查启停"用同一个键，杜绝 id↔name 映射层。

**Alternatives**: *数字 id 对外*：需要一次 id→注册表键换算，且对后续 Agent Loop 无意义，否决。

---

## R3 危险命令拦截机制（FR-016，安全核心）

**Decision**: 执行层"规范化 + 规则表"黑名单拦截，纯函数模块 `services/danger_rules.py` 承载：

1. **规范化**：小写化、连续空白折叠（保留 `|` `;` `&&` 等结构符），供规则匹配。
2. **规则表**：六类规则（类别枚举与拒绝文案主定义在 [contracts/tool-definitions.md](contracts/tool-definitions.md)），每条规则 = 正则模式 + 结构化条件（"危险目标 token"与"危险动作 token"同时命中才拦，避免误伤）：

| 类别 | 拦截目标（示例形态，非穷尽） |
|------|------------------------------|
| `recursive_delete_system` 递归删除根/系统目录 | `rm`+`-r`+`-f` 组合且目标是 `/`、`/*`、`/etc`、`/usr`、`/bin`、`C:\`、`C:\Windows`、`%SystemRoot%` 等；`rd /s /q`、`del /f /s /q`、`Remove-Item -Recurse -Force` 指向系统目录 |
| `format_disk` 格式化磁盘 | `format x:`、`mkfs.*`、`diskpart /s`、`Format-Volume` |
| `modify_system_permissions` 修改关键系统权限 | `chmod/chown/icacls/cacls/takeown/attrib` 且目标是根或系统目录（`chmod -R 777 /`、`icacls C:\Windows ...`） |
| `disable_security` 关闭安全防护 | `net stop/sc config` 针对 `windefend`、`wscsvc`、`mpssvc`、`firewalld`；`ufw disable`；`Set-MpPreference -Disable*`；`systemctl stop/disable` 防火墙类服务 |
| `secret_exfiltration` 读取并外传密钥 | 命中密钥源（`.ssh`、`id_rsa`、`.aws/credentials`、`.env`、`secret.key`、`.gnupg`）**且**同时命中外传通道（`curl`/`wget`/`nc`/`scp`/`Invoke-WebRequest`/`iwr` 上传形态） |
| `remote_script_execution` 直接执行远程下载脚本 | `curl/wget/irm/iwr ... | sh/bash/zsh/pwsh/powershell`；`bash <(curl ...)`；`iex (irm ...)`；`iex (New-Object Net.WebClient).DownloadString(...)` |

3. 命中即在执行前返回 `dangerous_command_blocked` 结果（含类别专属人话原因），**不执行**；未命中才进入 subprocess。
4. 横向兜底：执行超时（R4）、输出截断、文件工具授权目录（R5）——与 spec Assumptions"已知危险模式 + 横向限制"一致。

**Rationale**: 白名单会废掉 Shell 工具的通用性（spec 列举的用途——查看系统信息、搜索文件、运行脚本、执行测试——无法穷举枚举）；沙箱（容器/虚拟机）远超单机工具的复杂度预算；AST 级解析在 cmd/PowerShell/bash 跨语法场景不可靠。正则 + 结构化 token 的规则表可测试（每类规则有独立单测）、可扩展（规则是数据）。误拦截代价（返回明确拒绝原因，可换写法）远小于漏拦截代价（本机破坏），宁严勿松。

**Alternatives**:

- *命令白名单*：`pytest`、`dir` 之外的命令全拒——与工具用途根本冲突，否决。
- *容器沙箱*：引入 Docker 依赖与运维成本，违反 Simplicity/YAGNI，否决。
- *仅靠提示词约束模型*：被 spec 明文禁止（FR-016"拦截 MUST NOT 依赖工具说明对模型的约束"），否决。

---

## R4 Shell 执行参数（FR-015/017）

**Decision**:

- 执行：`subprocess.run(command, shell=True, capture_output=True, timeout=...)`（Windows 走 cmd.exe，跨平台形态一致）。
- **超时 60s**：`settings.shell_timeout_seconds`，超时杀进程返回 `command_timeout`。
- **输出截断 20000 字符**：`settings.shell_output_max_chars`，stdout+stderr 合并后截断，尾部追加截断标记且 `extra.truncated = true`。
- **编码**：按 UTF-8 优先、失败回退系统区域编码解码（`errors="replace"`），兼容中文 Windows 控制台输出。
- **命令长度上限 10000 字符**（参数校验层拦截）。
- 退出码非 0 = 正常业务结果（`success=false` + 输出 + `extra.exit_code`），不算系统错误（Edge Cases 约定）。

**Rationale**: 60s 覆盖"运行脚本/执行测试"的常见时长又保证入口不会无限占用；20000 字符约 5k token，是模型可消费的输出量级；数值进 settings（环境变量可覆盖），未来调整不改代码。

**Alternatives**: *asyncio 子进程*：当前执行入口是同步服务函数，引入 async 收益为零；*10s 超时*：跑一次 pytest 都不够，误伤正常用途。

---

## R5 文件读写工具约束（FR-018~020）

**Decision**:

- **授权目录**：`settings.authorized_dir`，默认 `./workspace`（相对 backend 运行目录，与 `app.db`、`secret.key` 同一约定），首次使用自动创建，`backend/workspace/` 加入 `.gitignore`。
- **路径校验**：`target = (root / path).resolve()` 后必须 `target.is_relative_to(root.resolve())`，否则 `path_outside_root`——统一拦截绝对路径、盘符路径与 `..` 穿越后的逃逸（绝对路径拼接后即自身，天然落在 root 外）。
- **编码**：读写均为 UTF-8 文本；非 UTF-8 内容返回人话错误（本阶段不支持二进制，spec Assumption）。
- **大小上限**：单文件 1MB（`settings.file_max_bytes`），读前检查、写前按内容字节数检查，超限 `file_too_large`。
- **处理规则**（写入参数说明，FR-019）：读取时文件不存在 → `file_not_found`；写入时父目录不存在自动创建、同名文件**覆盖写**；写入空字符串合法（创建空文件）。
- **参数形态**：单工具三参数 `action`（`read`|`write`，必填）、`path`（必填）、`content`（write 时必填，可为空串）。

**Rationale**: resolve + is_relative_to 是 Python 3.12 标准库给出的规范包含性判断，不手写字符串前缀比较（会被 `..`、符号链接、大小写绕过）；覆盖写是"修改文件"最可预期的语义，规则写进参数说明即满足 FR-019"处理规则明确"。

**Alternatives**: *追加写模式*：模型无法预期结果且与"修改"语义弱相关；*拆成 read_file / write_file 两个工具*：spec 将其定义为一个"文件读写工具"，拆分无增益；*字符串前缀检查*：可被 `a/../../x` 绕过，不安全。

---

## R6 统一执行入口形态（FR-009~012）

**Decision**: 入口是**后端进程内服务函数** `tool_executor.execute(name, params) -> ToolExecutionResult`：

```text
execute(name, params)
  ├─ 1 注册表查 name            → 未命中：tool_not_found
  ├─ 2 DB 查 enabled            → 停用：tool_disabled（无行=迁移未播种/被清空，视为未注册 → tool_not_found 语义）
  ├─ 3 注册表 Pydantic 模型校验参数 → 失败：invalid_params（指明字段与原因）
  ├─ 4 分发到工具实现            → 实现抛 ToolExecutionError(code, message)：原样包装
  └─ 5 全链路 try/except Exception 兜底 → execution_error，永不向上抛异常（FR-012）
```

结果结构 `ToolExecutionResult`（主定义 [contracts/tool-definitions.md](contracts/tool-definitions.md)）：`success / error_code / message / output / extra`。**本阶段不暴露 HTTP 执行端点**：前端页面只做展示与启停，无 UI 消费方；Agent Loop 是未来的进程内调用方；契约测试与 quickstart 直接调用服务函数验证。

**Rationale**: spec 说"后续 Agent Loop 调用任何本地工具都要经过这里"——Agent Loop 是后端代码，进程内函数就是它的自然入口；为无消费方的场景预建 HTTP 端点违反宪法 V（Simplicity，"不提前搭建没有消费方的后端目录、抽象层"）。结果结构与错误码先在契约层定死，未来 Agent Loop 或调试端点直接复用。

**Alternatives**: *暴露 `POST /api/tools/execute`*：无 UI 消费方，属预建，否决（后续阶段有真实消费方时再加）；*入口做 FastAPI 依赖*：把执行入口绑死在请求生命周期上，Agent Loop 复用困难。

---

## R7 当前时间工具与默认时区（FR-013/014）

**Decision**: 用标准库 `zoneinfo.ZoneInfo(tz)` 解析时区；默认时区 `settings.default_timezone = "Asia/Shanghai"`（可用环境变量覆盖）。`CST`、拼错的名称均不是合法 IANA key，`ZoneInfo` 直接抛 `ZoneInfoNotFoundError` → 映射为 `unknown_timezone` 错误，文案给出 IANA 示例（契约主定义）。成功输出形如 `2026-09-10 14:30:05` 的本地时间字符串，`extra.timezone` 注明实际使用时区（含默认回退场景，US5 场景 1"标明所用时区"）。

**Rationale**: Python 3.12 标准库 `zoneinfo` 在 Windows 上依赖显式安装的 `tzdata` 包（实现时验证发现其并不在既有依赖树中，已按本条预案 `uv add tzdata` 落地）；拒绝模糊缩写不需要专门逻辑，IANA 严格性天然满足 FR-014。

**Alternatives**: *pytz*：第三方且 API 反直觉，标准库已覆盖；*UTC 单一时区*：直接违反 FR-013。

---

## R8 前端列表与详情形态（FR-001~003/021）

**Decision**: 替换 `ToolsView.vue` 占位页：

- **列表**：ant-design-vue `Table`，列 = 显示名称、工具标识（name）、用途说明、参数概要、启用状态（`Switch` + 确认弹层）、系统内置（`Tag`）；空数据用 `Empty` 空状态。
- **详情**：`Drawer`（右侧抽屉）承载——分节展示 用途说明 / 参数表（名称、类型、必填、含义）/ 适用场景 / 输入要求 / 使用限制。spec 的"详情页"以抽屉页面形态承载，不新增路由。
- **启停**：切换前 `Modal.confirm` 确认（spec US2"操作需确认后生效"），成功后列表状态即时刷新。
- 样式全部引用 `tokens.scss` 设计令牌，无删除/编辑入口（FR-007 的界面不提供）。

**Rationale**: 与 002 已确立的"Table + Modal/Drawer + 设计令牌"管理页范式一致（FR-021）；详情内容为多节只读文本，抽屉比整页路由轻，比 Modal 更适合纵向长内容。

**Alternatives**: *独立路由详情页*：多两条路由与页面文件，只读内容不值一页，否决；*Modal 详情*：纵向长内容（参数表 + 三段说明）体验差。

---

## R9 配置集中与运行时目录（宪法"配置集中"）

**Decision**: `core/config.py` 新增五个设置项（均可环境变量覆盖）：

| 设置项 | 默认值 | 用途 |
|--------|--------|------|
| `default_timezone` | `Asia/Shanghai` | 时间工具未指定时区时使用 |
| `authorized_dir` | `./workspace` | 文件工具授权目录（相对 backend 运行目录） |
| `shell_timeout_seconds` | `60` | 命令执行超时 |
| `shell_output_max_chars` | `20000` | 输出截断上限 |
| `file_max_bytes` | `1048576`（1MB） | 单文件读写上限 |

`.gitignore` 追加 `backend/workspace/`（运行时用户数据）。AGENTS.md §3 目录树同步补该目录一行（实现阶段完成，随 tasks 交付）。

**Rationale**: 数值类约束全部收敛到唯一配置入口（宪法 II），调整阈值不动代码；workspace 与 app.db 同为运行时产物，不入库。

---

## 结论

spec 留给 Plan 的全部待决项已解决：**R1 注册表+状态表职责划分**、**R3 危险命令规则表**、**R6 进程内统一入口** 为本阶段架构核心；授权目录（`./workspace`）、默认时区（`Asia/Shanghai`）、超时（60s）、截断（20000 字符）、文件上限（1MB）均有明确取值并进配置。data-model 与 contracts 据此展开。
