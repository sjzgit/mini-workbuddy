# Quickstart: 聊天功能（第八阶段）

**Date**: 2026-09-14 | **Feature**: `008-chat-conversations`

端到端验证指南。自动化检查（门禁）先行，再按场景手动验证。字段与事件语义以 [contracts/chat-api.md](contracts/chat-api.md) 为准，表结构以 [data-model.md](data-model.md) 为准。

## 前置条件

1. 系统中已有一个**真实可用**的模型配置（模型管理页，连接测试通过——需真实 base_url 与 API Key，本项目当前对接 OpenAI 兼容中转）。
2. 至少一个 Agent（Agent 管理页），绑定上述模型；首个 Agent 已自动成为默认 Agent。
3. 建议再建第二个 Agent（不同系统提示词，如"用文言文回答"）用于验证切换 Agent。

## 启动

```bash
# 后端（backend/ 内）
uv run alembic upgrade head        # 应用 008 迁移（conversations / messages 两表）
uv run python start_dev.py         # 端口 8218

# 前端（frontend/ 内，Windows + nvm 先切 node 22，见 AGENTS.md §5）
cmd /c "set PATH=%APPDATA%\nvm\v22.20.0;%PATH% && npm run dev"
```

打开 `http://localhost:5173`（Vite），侧边导航进入「聊天」。

## 自动化门禁（交付前必须全绿）

```bash
# 后端（backend/ 内）
uv run pytest            # 含 test_chat_api.py / test_chat_stream.py
uv run pyright

# 前端（frontend/ 内）
npm run build
npm run test:unit        # 含 sse-parse / chat-store / MessageBubble 清洗渲染
```

## 手动验证场景（对应 spec 用户故事）

### A. 发起对话与流式回复（US1）

1. 进入聊天页 → 底部确认默认选中「默认 Agent」→ 输入"用一句话介绍你自己" → Enter。
2. 期望：输入框立即清空；消息靠右出现；随后"正在思考"（或直接"正在生成"）；回答随生成逐步追加；开启深度思考的 Agent 可见思考过程分区；完成后回复左侧显示 Agent 名称。
3. 点击回复上的「复制」→ 剪贴板为正文 Markdown 源文本。
4. 「重新生成」仅出现在最后一条 Agent 回复上；点击后原回复位置重新流式生成并被替换。
5. 消息含 Markdown：让模型输出代码块/表格/列表，确认渲染正确且无脚本注入（正文含 `<script>alert(1)</script>` 时不执行）。

### B. 持久化与恢复（US2）

1. 新建会话 → 发送第一句较长消息 → 左侧标题变为消息前缀截断（含 `…`）。
2. 刷新页面 → 会话列表仍在（按最后更新时间倒序）→ 点击会话 → 记录完整显示且自动滚动到底部。
3. 关闭浏览器重开 → 继续追问，模型理解上文。
4. 生成期间注意左侧列表：当前会话置顶，仅点开其他会话查看不改变其排序。

### C. 多轮与切换 Agent（US3）

1. 同会话连续追问 3 轮（"我刚才问了什么？"），确认模型带上下文。
2. 底部切换为第二个 Agent（或 `@` 唤起选择）→ 再发送 → 回复体现新 Agent 提示词风格，且回复顶部 Agent 名称变为新 Agent。
3. 在 Agent 管理页删除会话当前选中的 Agent → 回到聊天页 → 历史可查看，发送被要求先重选 Agent；旧回复的 Agent 名称显示不变。

### D. 停止与后台继续（US4）

1. 发送一个会生成长文的请求 → 生成中确认发送按钮变为「停止」→ 点击停止 → 输出立即停止，已生成部分保留并显示未完成标识。
2. 再次发起长文生成 → 切到其他会话 / 离开聊天页逛模型管理页 → 约 20s 后回到原会话 → 回复已完整生成（后台未中断）。
3. 生成中尝试再次发送 / 切换 Agent：被阻止；生成结束后恢复。

### E. 异常路径（US5）

1. 将会话 Agent 的模型密钥改错（模型管理页）→ 发送消息 → 独立错误提示"认证失败…"；用户消息仍在，聊天记录无错误文本气泡。
2. 恢复密钥；断网（或改错 base_url）→ 发送 → "服务地址不可访问"提示；恢复网络后可继续正常对话。
3. 刷新页面时恰有生成中回复 → 重进会话后该消息显示生成中并继续追加（订阅重放）；若期间后端曾重启 → 该消息如实显示"生成中断"（未完成）。
4. 后端控制台确认：每次请求打印第三方 API 调用日志（模型、增量进度），且任何日志/前端响应中无 API Key。

## 验收对照

全部场景通过 + 自动化门禁全绿 → 对照 [spec.md](spec.md) Success Criteria（SC-001~SC-007）逐条确认后，本功能方可视为交付。
