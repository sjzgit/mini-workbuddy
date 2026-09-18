# Quickstart: 用户工作空间与文件系统权限（014）端到端验证

> 前置：后端 `backend/` 内 `uv sync` 已执行、`uv run alembic upgrade head` 已到 head；
> 前端 `frontend/` 内 `npm install` 已执行。启动：后端 `uv run python start_dev.py`，
> 前端 `npm run dev`。

## 1. 自动化验证（交付门禁）

```bash
# backend/ 内
uv run pytest                                   # 全部测试（含新增 test_path_resolver /
                                                # test_permission / test_workspace_service /
                                                # test_workspace_api / test_workspace_runtime）
uv run pyright                                  # 类型检查无错误

# frontend/ 内
npm run build                                   # 零错误
npm run test:unit                               # Vitest 全部通过
```

## 2. 手动验证场景（按 spec 用户故事）

### 场景 A：选择工作空间（US1）

1. 打开聊天页，任选/新建会话 → 输入区底部出现「📁 未选择工作空间」
2. 点击 → 输入一个真实目录（如 `D:\projects\demo`，先手动创建）→ 确认
3. 期望：入口显示 `📁 D:\projects\demo`；刷新页面后仍显示（持久化）
4. 输入不存在的路径 `D:\no-such-dir` → 期望报错「工作空间路径不存在」，原值保留
5. 点击「清除」→ 回到「未选择工作空间」

### 场景 B：工作空间内直接执行（US2）

1. 会话工作空间设为 `D:\projects\demo`，目录内放一个 `hello.txt`
2. 对话让 Agent：「读取 hello.txt 的内容」
3. 期望：`file_read_write` 卡片直接 success，无任何询问弹窗
4. 让 Agent 执行 shell：「运行 `dir`（或 `ls`）」
5. 期望：命令输出即 `D:\projects\demo` 的目录列表（cwd 生效），无询问

### 场景 C：工作空间外触发确认（US3）

1. 工作空间 `D:\projects\demo`；外部准备 `D:\projects\other\note.txt`
2. 对话让 Agent：「读取 D:\projects\other\note.txt」
3. 期望：输入区上方出现 Ask User 面板，问题含目标路径，选项「允许本次访问 / 拒绝」
4. 选「允许本次访问」→ 期望：文件内容正常读出，运行继续
5. 新消息再次让 Agent 读同一文件 → 期望：**再次**弹出询问（临时授权不跨运行）
6. 重做步骤 3，选「拒绝」→ 期望：工具卡片显示失败（用户拒绝），Agent 正常继续回复

### 场景 D：运行中切换不影响进行中的运行（US4）

1. 工作空间 A，让 Agent 执行一个较慢的任务（如 shell `timeout`/`sleep` 后读文件）
2. 任务执行中把工作空间切换为 B
3. 期望：进行中的任务全程按 A 判定并正常完成；下一条消息按 B 判定
4. 打开该运行的记录页 → 运行详情可见其 `workspace_path` = A

### 场景 E：保护路径不可绕过（US3-5 / Invariant 8）

1. 让 Agent 读取 `C:\Windows\win.ini`
2. 期望：工具卡片直接失败（system_protected_path），**不出现**询问面板

## 3. API 冒烟（可选，curl）

```bash
# 设置（先真实创建目录）
curl -X PUT http://127.0.0.1:8218/api/conversations/1/workspace \
  -H "Content-Type: application/json" -d "{\"path\": \"D:\\\\projects\\\\demo\"}"
# 查询
curl http://127.0.0.1:8218/api/conversations/1/workspace
# 清除
curl -X DELETE http://127.0.0.1:8218/api/conversations/1/workspace
```

期望：PUT/DELETE 返回 `ConversationWorkspaceOut`；无效路径 400 + 人话 detail；
不存在会话 404。
