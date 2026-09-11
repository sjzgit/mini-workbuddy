# AGENTS.md — mini-workbuddy 开发规范（单一事实来源）

> 本文件是项目开发约定的**唯一主定义**。后续开发约定变化时**只更新这一个文件**，禁止让相同规则散落在各任务说明中。所有 Agent 与开发者在动手前必须先读本文件。
>
> 最高准则见 `.specify/memory/constitution.md`（宪法）；本文件是宪法的运行时细化。冲突时宪法优先。

## 1. 项目名称

**mini-workbuddy** —— 紧凑的 AI 工作台（聊天 + Agent/模型/工具/MCP/Skills 管理 + 运行记录 + 评测）。

## 2. 固定技术栈（不可替换）

### 前端（frontend/）

| 项 | 选型 |
|----|------|
| 框架 | Vue 3（Composition API，`<script setup>`）+ TypeScript |
| 构建 | Vite |
| 路由 | Vue Router（history 模式，路由表集中在 `src/router/index.ts`） |
| 状态 | Pinia（全局状态必须走 Store，禁止跨组件直传复杂状态对象） |
| 样式 | sass + 全局 CSS 变量（设计令牌） |
| UI 库 | Ant Design Vue（ant-design-vue，优先复用其组件） |
| 依赖管理 | npm |
| 测试 | Vitest（+ @vue/test-utils） |
| 字体 | @fontsource/dm-sans、@fontsource/outfit、@fontsource/fira-code（自托管） |

### 后端（backend/）

| 项 | 选型 |
|----|------|
| 语言 | Python 3.12（版本以 `backend/pyproject.toml` 声明为准） |
| 框架 | FastAPI |
| 校验 | Pydantic + pydantic-settings（API 契约与配置的主定义） |
| ORM | SQLAlchemy 2.x |
| 迁移 | Alembic |
| 数据库 | **SQLite（本项目唯一数据库，禁止 JSON 文件替代）** |
| 依赖管理 | **uv（强制，见 §4）** |
| 测试 | pytest（+ httpx TestClient） |
| 类型检查 | pyright（配置：根目录 `pyrightconfig.json`） |

### 禁止引入

- React、Next.js、Nuxt、Django、Flask
- pip 直接管理后端依赖
- 技术栈清单之外的框架/等价替代库（换 UI 库、换 ORM 等视为违反宪法）
- 新增依赖须有明确当前需求（YAGNI）

## 3. 目录结构

```text
mini-workbuddy/
├── 0user chat/            # 用户私人目录，Agent 禁止写入/修改
├── frontend/              # 前端（npm）
│   └── src/
│       ├── api/           # 请求封装（request.ts）+ 各接口模块
│       ├── components/    # 通用组件
│       ├── layouts/       # 布局组件（WorkbenchLayout）
│       ├── router/        # 路由表
│       ├── stores/        # Pinia store
│       ├── styles/        # tokens.scss（设计令牌主定义）+ main.scss
│       ├── views/         # 页面组件
│       ├── App.vue
│       └── main.ts
├── backend/               # 后端（uv）
│   ├── app/
│   │   ├── api/           # 路由层（只做 HTTP 编排）
│   │   ├── core/          # 配置、数据库连接等横切设施
│   │   ├── schemas/       # Pydantic 模型（API 契约实现）
│   │   ├── services/      # 业务逻辑层（有业务后再建）
│   │   └── models/        # ORM 模型（有业务后再建）
│   ├── migrations/        # Alembic 环境
│   ├── tests/             # pytest
│   ├── workspace/         # 文件读写工具授权目录 + Skills 目录（运行时生成，不入库）
│   ├── pyproject.toml
│   └── uv.lock
├── specs/                 # spec-kit 规范文档
├── sql/                   # SQL 存档（增量脚本放 sql/migrations/）
├── AGENTS.md              # 本文件（开发规范 SSOT）
└── README.md              # 项目简介与快速启动
```

分层规则（MUST）：

- 前端：页面、路由、状态、请求封装、通用组件、样式**分目录放置**，不得混写
- 后端：应用入口（`app/main.py`）、路由（`api/`）、业务逻辑（`services/`）、数据访问（`models/` + SQLAlchemy）、数据校验（`schemas/`）各归其位
- **不预建没有消费方的空目录/空文件**；无业务内容的模块只保留一个占位页面

## 4. uv 工作流（后端强制）

所有后端命令在 `backend/` 目录执行：

| 操作 | 命令 |
|------|------|
| 添加依赖 | `uv add <package>` |
| 安装依赖 | `uv sync` |
| 运行任意命令 | `uv run <cmd>`（uvicorn / alembic / pytest / pyright 一律如此） |

- **禁止** 直接使用 pip（含 README 等文档中不得出现 pip 步骤）
- `pyproject.toml` 与 `uv.lock` 必须同时提交且保持一致

## 5. 常用命令

### 后端（backend/ 内）

```bash
uv sync                                  # 安装依赖
uv run alembic upgrade head              # 执行数据库迁移
uv run uvicorn app.main:app --reload --port 8218   # 启动后端（开发）
uv run pytest                            # 运行测试
uv run pyright                           # 类型检查
```

### 前端（frontend/ 内）

```bash
npm install                # 安装依赖（frontend/.npmrc 已固定 legacy-peer-deps）
npm run dev                # 启动开发服务器（/api 代理到 127.0.0.1:8000）
npm run build              # 生产构建（type-check 前置）
npm run test:unit          # Vitest 单元测试（单次运行）
```

> Windows + nvm 提示：本机默认 node 18 不满足要求，运行前端命令前先切换：
> `cmd /c "set PATH=%APPDATA%\nvm\v22.20.0;%PATH% && <命令>"`

## 6. 数据库迁移方式

1. 修改 ORM 模型（`backend/app/models/`）
2. 在 `backend/` 执行：`uv run alembic revision --autogenerate -m "<说明>"`
3. 检查生成脚本 → `uv run alembic upgrade head`
4. 变更性 SQL 需同步存档到 `sql/migrations/`（与 Alembic 版本对应）

约定：

- 数据库文件 `backend/app.db`（开发默认，不入库；连接串经 `DATABASE_URL` 覆盖）
- 所有 Schema 变更必须走 Alembic；Session 经 FastAPI 依赖注入获取，禁止路由内自建 engine/session

## 7. 前后端联调

- 前端**始终请求相对路径 `/api`**（`frontend/src/api/request.ts` 统一加前缀）
- 开发环境由 Vite 代理转发（`frontend/vite.config.ts`：`/api → http://127.0.0.1:8000`）
- **禁止**在前端业务代码硬编码后端绝对地址
- API 契约主定义：feature spec 的 `contracts/` → `backend/app/schemas/`（Pydantic）→ 前端 `src/api/` 类型派生，三层 MUST 对齐

## 8. 配色与字号入口（UI 设计令牌）

**唯一主定义：`frontend/src/styles/tokens.scss`** —— 所有页面与组件 MUST 引用 CSS 变量，禁止页面内自写相近色或脱离规格的字号。

- 配色：暖色工作台（`--bg-*` 层级 / `--accent: #c2703a` 主色系 / `--text-*` 三级文本 / `--success` `--warning` `--danger` 语义色 / `--border*` 边框三级）
- 字体：`--font-body`（DM Sans）/ `--font-display`（Outfit，标题与产品名）/ `--font-mono`（Fira Code，代码日志）；网络字体不可用回退系统字体
- 字号规格：页面主标题 22px/650；卡片标题 16–17px/600；正文与表单 14px；按钮与菜单 13–13.5px；辅助说明 12–12.5px；代码 13px；正文行高 1.5；**禁止 32px 以上大标题**
- 禁止：蓝紫渐变、霓虹光效、大面积纯黑背景、高饱和荧光色；阴影仅用于弹窗与浮层；卡片以白底 + 浅边框区分
- 布局：整页占满高度无横向滚动；桌面侧栏固定 188px；<900px 收起为抽屉

## 9. 每次修改后的检查清单（交付前必须全绿）

```bash
# 后端（backend/ 内）
uv run pytest          # 全部通过
uv run pyright         # 无错误

# 前端（frontend/ 内）
npm run build          # 零错误
npm run test:unit      # 全部通过
```

涉及 UI 的改动额外人工核对 §8 全部条目（颜色引用变量、字号规格、无禁用视觉元素）。

## 10. 前后端开发规范

### 前端

- 组件一律 Composition API + `<script setup lang="ts">`
- 优先复用 ant-design-vue 组件；自定义样式只引用设计令牌变量
- 全局/跨组件状态放 Pinia store；组件内状态用 `ref`/`reactive`
- API 调用统一经 `src/api/` 封装模块，组件内不直接 `fetch`
- 路由懒加载（`() => import(...)`）；新页面在 `views/` 建组件并在 `router/index.ts` 注册
- 测试与被测文件同目录（`__tests__/`）或集中放置，新增核心逻辑须配套 Vitest

### 后端

- 路由层薄：参数校验（Pydantic）→ 调 service/数据访问 → 返回 schema
- 配置集中在 `app/core/config.py`（pydantic-settings），禁止散落硬编码
- 公共异常语义统一（如健康检查的 503 结构），错误信息不泄露内部细节
- 测试先行：契约测试以 feature spec 的 `contracts/` 为准；夹具在 `tests/conftest.py`
- 类型注解完整（pyright basic 通过）

### 通用

- 遵循 spec-kit 流程：spec → plan → tasks → implement；实现与规范不一致时先改规范（SSOT）再改代码
- `0user chat/` 目录禁止读写
- 提交粒度：每个任务或逻辑分组一次提交（仓库启用 git 后）
