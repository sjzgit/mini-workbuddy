# Quickstart: 项目初始化（第一阶段）

**Feature**: 001-project-init | **Date**: 2026-09-10

端到端验证脚本：证明工程骨架真实可用（依赖安装 → 迁移 → 双端启动 → 页面与接口可达 → 检查全绿）。

## 前置条件

- Node.js ≥ 20（含 npm）
- uv（Python 包管理器）
- 现代桌面浏览器

## 1. 安装依赖

```bash
# 后端（backend/ 内，全程 uv，禁止 pip）
cd backend
uv sync

# 前端（frontend/ 内）
cd ../frontend
npm install
```

## 2. 数据库迁移

```bash
# backend/ 内
uv run alembic upgrade head
```

**预期**：命令成功退出；生成 `backend/app.db`；再次执行不报错（幂等，SC-006）。

## 3. 启动服务

```bash
# 后端（backend/ 内）
uv run uvicorn app.main:app --reload --port 8000

# 前端（frontend/ 内，另开终端）
npm run dev
```

**预期**：后端监听 8000；前端开发服务器启动（默认 5173），控制台无代理报错。

## 4. 验证场景

### V1 健康检查（后端 + 数据库）

```bash
curl http://127.0.0.1:8000/api/health
```

**预期**：`200`，返回 `{"status":"ok"}`（契约见 [contracts/api-contract.md](contracts/api-contract.md)）。

### V2 前端页面与代理链路

浏览器打开前端开发地址，依次验证：

1. 默认落在**聊天**页（`/chat`）
2. 左侧 8 个菜单依次点击，地址与页面正确切换（`/chat` `/agents` `/models` `/tools` `/mcp` `/skills` `/runs` `/evaluations`）
3. 对全部 8 个地址逐一按 F5 刷新，均渲染对应模块页，无空白页（SC-002）
4. 每个占位页显示：页面标题 + 一句说明 + "本模块将在后续阶段开发" + 当前阶段先完成什么；无虚构统计/对话/列表
5. 手输一个不存在的地址（如 `/xyz`）→ 显示 NotFound 兜底页，不白屏

### V3 布局与响应式

1. 桌面宽度：整页占满高度、无横向滚动；侧栏固定 188px；顶部显示 mini-workbuddy 与圆形字母标记
2. 拖窄浏览器至 < 900px：菜单收起为抽屉，可打开全部 8 个入口，主内容不被遮挡
3. 拖至约 360px：仍无整页横向滚动（SC-005）

### V4 字体回退

浏览器开发者工具屏蔽网络字体（或断网加载字体资源）后刷新：页面回退系统字体，功能与布局正常（SC-004 相关）。

### V5 视觉抽查

检查任意页面样式：颜色均引用全局 CSS 变量（`frontend/src/styles/tokens.scss`）；无蓝紫渐变/霓虹光效/大面积纯黑/高饱和荧光色；卡片为白底浅边框；无 32px 以上标题。

## 5. 质量门禁（交付前必须全绿）

```bash
# 后端（backend/ 内）
uv run pytest
uv run pyright        # 如全局不可用：uvx pyright（以根目录 pyrightconfig.json 为准）

# 前端（frontend/ 内）
npm run build
npm run test          # Vitest（若脚手架生成的是 npm run test:unit，以 AGENTS.md 命令清单为准）
```

**预期**：四项全部通过、零错误（SC-003）。

## 6. 工程整洁检查

- 除文档声明保留者外，无空文件/空目录（特别是：后端无提前搭建的 `models/`、`services/` 等空目录，SC-007 / FR-007）
- `backend/pyproject.toml` 与 `uv.lock` 存在且一致；README 无任何 pip 步骤
- `AGENTS.md` 含 FR-019 列举的全部条目
