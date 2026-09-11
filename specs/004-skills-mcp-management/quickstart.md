# Quickstart: Skills 与 MCP 管理（第四阶段）

**Date**: 2026-09-10 | 端到端验证指南。前置契约：[contracts/skills-api.md](contracts/skills-api.md)、[contracts/mcp-api.md](contracts/mcp-api.md)；数据模型：[data-model.md](data-model.md)。

## 前置准备

```bash
# 1. 依赖与迁移（backend/ 内）
cd backend
uv sync                                   # 含新增依赖 mcp、python-multipart
uv run alembic upgrade head               # 建 skills、mcp_servers 两表

# 2. 启动后端（backend/ 内，保持运行）
uv run uvicorn app.main:app --reload --port 8218

# 3. 启动前端（frontend/ 内，新终端）
cd ../frontend
npm install
npm run dev                               # /api 代理到 127.0.0.1:8218 附近（vite.config.ts）
```

## 验证场景

### A. Skills：手动创建 → 刷新 → 编辑 → 启停 → 删除

1. 手动创建 Skill（模拟用户直接操作目录）：

   ```
   backend/workspace/skills/meeting-notes/skill.md
   ---
   name: 会议纪要整理
   description: 把口述草稿整理成结构化纪要
   ---
   # 指令正文（Markdown）
   ```

2. 打开前端「Skills 管理」页 → 点击**刷新** → 列表出现 `meeting-notes`（名称/说明/启用/更新时间正确），**无需重启服务**（FR-003，SC-001）。
3. 点击**编辑** → 抽屉三区域（名称/用途说明/详细指令）有值；修改说明与指令正文 → 保存 → 列表更新时间刷新；用文本编辑器打开 `skill.md` 核对内容与页面一致（FR-011，SC-002）。
4. 关闭开关并确认停用 → 状态为停用；刷新页面、重启后端后仍为停用，且磁盘文件仍在（FR-012/013，SC-004）。
5. 删除并确认 → 列表消失，`workspace/skills/meeting-notes/` 目录已被删除；取消删除分支核对文件未动（FR-014）。

### B. Skills：ZIP 导入（成功 + 三类失败）

1. 准备合规 ZIP（内含 `skill.md` 的目录打包为 `demo-skill.zip`）→ 页面**导入 ZIP** → 成功出现在列表且默认启用（FR-006，SC-003）。
2. 再次导入同名 `demo-skill.zip` → 拒绝并提示同名冲突，原目录内容未变（FR-008）。
3. 导入内含 `../evil.txt` 条目的 ZIP → 拒绝并提示不安全路径；核对 `workspace/skills/` 无任何新文件、上级目录无 `evil.txt`（FR-009，路径逃逸 100% 拒绝）。
4. 导入非 ZIP 文件（改名的 .txt）→ 拒绝并提示非有效压缩包（FR-007）。

### C. Skills：空状态与不合规目录

1. 清空（或首次未建）`workspace/skills/` → 页面显示空状态，无报错（FR-004）。
2. 在目录下创建只有空 `skill.md` 的目录 `bad-skill/` → 刷新 → 列表不含它且出现警告提示（FR-005）；删除 `bad-skill` 后刷新，警告消失。

### D. MCP：新增两类 Server（掩码 + 持久化）

1. 「MCP 管理」页 → **新增** → 选「本机启动」：名称 `fs-demo`、启动命令 `npx`、参数逐行 `-y` / `@modelcontextprotocol/server-everything`（或任一本机可用的 MCP Server 包）；环境变量加 `API_TOKEN=secret-value-1234` → 保存。
2. 列表显示：名称/说明/类型「本机」/「未测试」/工具数量「未知」（FR-015）。
3. **编辑**该 Server：环境变量值输入框为空且 placeholder 提示留空保留 → 直接保存 → 再测试仍能用原值（FR-024，掩码未被保存为实际值）；任何页面/响应中看不到 `secret-value-1234` 明文，只有 `••••••`（FR-023，SC-005）。
4. 新增「远程 HTTP」型 Server：url `http://127.0.0.1:9999/mcp` + 一个自定义 Header → 保存成功（FR-018/019）。
5. 重启后端 → 两类配置与启用状态保留（SC-004）。

### E. MCP：测试连接（成功 / 无工具 / 失败分类 / 并发锁）

1. 对 `fs-demo` 点**测试连接** → 按钮进入 loading；完成后展示工具数量，点击数量弹窗展示工具列表（名称/用途/参数类型/是否必填）（FR-027，SC-008）；测试结束后系统无残留的 `npx`/node 子进程（任务管理器或 `tasklist` 核对，SC-007）。
2. 对一个能启动但不提供工具的 Server 测试 → 显示「连接成功，未发现工具」（FR-027）。
3. 构造失败场景并核对提示分类（FR-028，SC-006）：

   | 场景 | 构造 | 期望分类 |
   |------|------|---------|
   | 命令不存在 | 启动命令填 `definitely-not-a-cmd` | 启动命令不存在 |
   | 启动即退出 | 启动命令填 `cmd` 参数 `/c exit 1`（Windows） | 启动失败或提前退出 |
   | 超时 | 启动命令填一个挂起不响应 MCP 协议的程序（如 `cmd` 参数 `/c pause`） | 超时（约 30s） |
   | 协议不兼容 | 启动一个 stdout 输出非 MCP 内容的程序（如 `cmd /c echo hello`） | 协议不兼容 或 启动失败（按 SDK 实际语义） |
   | 连接失败 | http 型 url 指向未监听端口 | 连接失败 |
4. 任一失败测试的提示与诊断信息中搜索 `secret-value-1234` → 零命中（脱敏，SC-005）。
5. 对同一 Server 快速连点测试 → 第二次被拒（「正在测试中」）；测试中编辑/删除也被拒（FR-030，Edge Case）。

### F. MCP：启停与「配置已变更」

1. 停用 `fs-demo` → 测试连接仍可执行且成功后状态仍为停用（FR-033）。
2. 对已测试成功的 `fs-demo` 修改启动参数并保存 → 测试结果列变为「配置已变更，待重新测试」（FR-034，SC-009）；重新测试成功后恢复成功状态。
3. 删除任一 Server（确认）→ 列表移除；sqlite 中对应 `secrets_vault` 密文行已清理（可用 `sqlite3 backend/app.db` 核对，或信任接口行为：编辑已删除 id 返回 404）。

## 自动化门禁（交付前必须全绿，AGENTS.md §9）

```bash
# backend/ 内
uv run pytest          # 全部通过（含 MCP 真 stdio 集成测试）
uv run pyright         # 无错误

# frontend/ 内
npm run build          # 零错误（含 type-check）
npm run test:unit      # 全部通过
```
