# mini-workbuddy

紧凑的 AI 工作台：聊天、Agent / 模型 / 工具 / MCP / Skills 管理、运行记录与 Agent 评测。
当前已交付：**第一阶段（工程初始化）**、**第二阶段（模型管理）** 与 **第三阶段（工具管理）**——"模型管理"可登记兼容 OpenAI Chat Completions 接口的模型（密钥本地加密保存）；"工具管理"提供三类内置工具（当前时间 / Shell 命令 / 文件读写）的启停管理与统一执行入口（危险命令在执行层拦截，文件操作限制在授权目录内）。

## 环境要求

| 工具 | 版本 |
|------|------|
| Node.js | ≥ 22.18（本机 nvm 目录：`%APPDATA%\nvm\v22.20.0`） |
| npm | ≥ 10 |
| uv | ≥ 0.11（Python 3.12 由 uv 管理，无需单独安装） |

## 快速启动

```bash
# 1. 后端：安装依赖并执行数据库迁移（backend/ 目录）
cd backend
uv sync
uv run alembic upgrade head

# 2. 启动后端（backend/ 目录，端口读自 backend/app/core/config.py）
uv run python start_dev.py
# 若提示端口被占用（上次异常退出留下的孤儿进程），用 --reset 清理后启动：
uv run python start_dev.py --reset

# 3. 前端：安装依赖并启动（frontend/ 目录，另开一个终端）
cd ../frontend
npm install
npm run dev
```

打开前端开发地址（默认 <http://localhost:5173>）：默认进入聊天页，左侧可切换 8 个模块。
后端健康检查：<http://127.0.0.1:8218/api/health>（返回 `{"status":"ok"}`）。

> 前端在开发环境始终请求相对路径 `/api`，由 Vite 代理转发到后端（`frontend/vite.config.ts`）。

### 密钥安全说明（模型管理）

- 模型的 API Key 以 **Fernet 加密**保存在数据库独立表中，加密用的主密钥位于 `backend/secret.key`
- 该文件在**首次保存带密钥的模型时自动生成**，已加入 `.gitignore`，不会进入版本库
- **请备份 `backend/secret.key`**：丢失后已保存的密钥将无法解密（删除模型重新添加即可恢复使用）
- 所有接口响应只返回"密钥是否已配置"，任何页面、日志都不会显示密钥正文

### 工具管理安全说明（第三阶段）

- **授权目录**：文件读写工具只能访问 `backend/workspace/`（首次使用自动创建，已加入 `.gitignore`）；可用环境变量 `AUTHORIZED_DIR` 覆盖
- **危险命令拦截**：Shell 工具在执行层拦截六类危险命令（递归删除系统目录、格式化磁盘、修改关键系统权限、关闭安全防护、读取并外传密钥、直接执行远程下载的脚本），拦截先于实际执行
- **执行上限**：命令超时 60 秒（`SHELL_TIMEOUT_SECONDS`）、输出截断 20000 字符（`SHELL_OUTPUT_MAX_CHARS`）、单文件 1MB（`FILE_MAX_BYTES`）、默认时区 `Asia/Shanghai`（`DEFAULT_TIMEZONE`）

### Windows + nvm 提示

若默认 Node 版本低于 22，前端命令这样执行：

```bash
cmd /c "set PATH=%APPDATA%\nvm\v22.20.0;%PATH% && npm install && npm run dev"
```

## 目录一览

```text
0user chat/    用户私人目录（不入仓库工作流）
frontend/      前端（Vue 3 + TS + Vite + Pinia + Ant Design Vue）
backend/       后端（FastAPI + SQLAlchemy + Alembic + SQLite，uv 管理）
specs/         spec-kit 规范文档（spec / plan / tasks 等）
sql/           SQL 存档（与 Alembic 迁移对应）
AGENTS.md      开发规范单一事实来源（技术栈、命令、检查清单）
```

## 测试与检查

每次修改后需要运行的检查（详见 [AGENTS.md](AGENTS.md) §9）：

```bash
# 后端（backend/ 内）
uv run pytest
uv run pyright

# 前端（frontend/ 内）
npm run build
npm run test:unit
```
