# Tool Definitions: 工具管理（第三阶段）

**Date**: 2026-09-10 | **Source of Truth**: 本文件是三类内置工具的标识、参数定义、说明文本、统一执行结果结构与错误码的**主定义**（宪法 II/III）。实现侧（后端注册表 `services/tool_registry.py`、危险规则 `services/danger_rules.py`、前端详情展示）MUST 与本文一致，变更先改这里。

## 1. 工具标识（注册表键）

| name | display_name | 一句话用途 |
|------|--------------|-----------|
| `current_time` | 当前时间 | 查询指定时区的当前日期和时间 |
| `shell` | Shell 命令 | 执行系统命令并返回输出与执行状态 |
| `file_read_write` | 文件读写 | 在授权目录内读取、创建和修改文本文件 |

## 2. 参数定义（Pydantic 模型主定义）

### current_time

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `timezone` | string | 否 | IANA 时区名称，如 `Asia/Shanghai`、`America/New_York`、`Etc/UTC`。**避免使用 CST 等含义不明确的缩写**（IANA 名称严格校验，缩写无法识别）。省略时使用系统默认时区 |

### shell

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `command` | string | 是 | 要执行的命令（≤ 10000 字符）。用于查看系统信息、搜索文件、运行脚本、执行测试等。危险命令（递归删除系统目录、格式化磁盘、修改关键系统权限、关闭安全防护、读取并外传密钥、直接执行远程下载的脚本）会在执行前被拦截 |

### file_read_write

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `action` | string（enum: `read` / `write`） | 是 | `read` 读取文件内容；`write` 创建或覆盖写入文件 |
| `path` | string | 是 | 相对授权目录的文件路径（相对路径形式）。以 `/` 或盘符开头的绝对路径、以及解析后落在授权目录之外的路径会被拒绝 |
| `content` | string | 是（仅 write） | 要写入的文本内容（UTF-8 文本，≤ 1MB）。`write` 时允许空字符串（创建空文件）；文件不存在则创建（含父目录），已存在则覆盖；`read` 时忽略此参数 |

## 3. 工具说明文本（详情页与模型可见说明）

### current_time

- **适用场景**：需要知道当前日期、时间或某地本地时间时使用，例如日程判断、时间计算、日志确认。
- **输入要求**：时区必须是 IANA 时区名称；未提供时返回系统默认时区的时间。
- **使用限制**：不适用 CST、GMT+8 等缩写或偏移写法；无法识别的时区将返回错误。

### shell

- **适用场景**：查看系统信息、搜索文件、运行脚本、执行测试等本地命令行操作。
- **输入要求**：一条完整的命令字符串；执行超时上限 60 秒，输出超过 20000 字符将被截断并标注。
- **使用限制**：以下六类危险命令会在执行前被拦截并拒绝：递归删除根目录或系统目录、格式化磁盘、修改关键系统权限、关闭安全防护、读取并外传密钥、未经检查直接执行远程下载的脚本。

### file_read_write

- **适用场景**：读取、创建或修改授权目录内的文本文件（笔记、配置、代码、脚本等）。
- **输入要求**：路径为相对授权目录的相对路径；内容为 UTF-8 文本，单文件上限 1MB。
- **使用限制**：仅能访问授权目录内（路径解析后不得逃逸）；本阶段仅支持文本文件；写入采用覆盖语义，无删除文件能力。

## 4. 统一执行结果（ToolExecutionResult）

执行入口 `tool_executor.execute(name, params)` 的**唯一返回结构**（HTTP 与未来 Agent Loop 共用）：

| 字段 | 类型 | 说明 |
|------|------|------|
| `success` | boolean | 执行是否成功（含"命令执行完成但退出码非 0"= false） |
| `error_code` | string \| null | 失败时的错误码（下表）；成功为 null |
| `message` | string | 人话结果/错误信息（可包含拒绝原因、排查指引）；不含堆栈与内部路径 |
| `output` | string \| null | 成功时的输出内容（时间字符串 / 命令输出 / 文件内容）；截断时含截断标记 |
| `extra` | object \| null | 附加信息：`timezone`（时间工具实际时区）、`exit_code`（命令退出码）、`truncated`（是否截断）、`blocked_category`（危险命令类别）、`path`（实际写入的绝对路径）等；成功无附加信息时为 `{}` |

## 5. 错误码（枚举唯一主定义，实现侧只消费）

### 入口层（执行前三查 + 兜底，FR-010/012）

| error_code | message 模板（前端/模型直接可读） |
|------------|----------------------------------|
| `tool_not_found` | 工具不存在或未注册：{name} |
| `tool_disabled` | 工具已停用：{display_name}。可在工具管理页启用 |
| `invalid_params` | 参数不符合要求：{字段与原因，逐项列出} |
| `execution_error` | 工具执行出错：{人话原因} |

### 工具层（各工具实现抛出）

| error_code | 归属工具 | message 模板 |
|------------|----------|--------------|
| `unknown_timezone` | current_time | 无法识别时区"{timezone}"。请使用 IANA 时区名称，如 Asia/Shanghai、America/New_York、Etc/UTC，避免 CST 等缩写 |
| `dangerous_command_blocked` | shell | 已拒绝执行危险命令（{blocked_category 的人话类别}）：{该类别的简要原因}。如确需相关操作请拆分为安全步骤后手动执行 |
| `command_timeout` | shell | 命令执行超过 {timeout_seconds} 秒已被终止。请缩小命令范围或拆分执行 |
| `path_outside_root` | file_read_write | 路径超出授权目录：{path}。仅允许访问授权目录内的相对路径 |
| `file_not_found` | file_read_write | 文件不存在：{path} |
| `file_too_large` | file_read_write | 文件超过 {file_max_bytes} 字节上限：{path} |
| `file_not_text` | file_read_write | 文件不是可读的 UTF-8 文本：{path}。本阶段仅支持文本文件 |

### 危险命令类别（blocked_category 取值）

`recursive_delete_system`（递归删除根/系统目录）、`format_disk`（格式化磁盘）、`modify_system_permissions`（修改关键系统权限）、`disable_security`（关闭安全防护）、`secret_exfiltration`（读取并外传密钥）、`remote_script_execution`（直接执行远程下载脚本）

拦截规则表（正则 + 结构化 token 条件）见 [../research.md](../research.md) R3；规则命中即拦截，**不依赖工具说明对模型的约束**（FR-016）。

## 6. 配置常量（进 `core/config.py`，环境变量可覆盖）

| 常量 | 默认值 | 消费方 |
|------|--------|--------|
| `default_timezone` | `Asia/Shanghai` | current_time 未指定时区 |
| `authorized_dir` | `./workspace` | file_read_write 授权目录 |
| `shell_timeout_seconds` | `60` | shell 执行超时 |
| `shell_output_max_chars` | `20000` | shell 输出截断 |
| `file_max_bytes` | `1048576` | file_read_write 单文件上限 |
