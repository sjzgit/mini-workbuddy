# Quickstart: MCP 表单 JSON 导入与类型命名修正（第六阶段）

**Date**: 2026-09-11 | 端到端验证指南。前置契约：[contracts/json-import.md](contracts/json-import.md)；数据模型：[data-model.md](data-model.md)（零迁移）。

## 前置准备

```bash
# 后端（backend/ 内；零改动，直接启动）
uv run uvicorn app.main:app --reload --port 8218

# 前端（frontend/ 内，新终端）
cd ../frontend && npm run dev
```

## 验证场景

### A. 保存按钮修复（US1，SC-001）

1. 打开「MCP 管理」→「新增 Server」→ 选 stdio，填名称 `save-fix-demo`、启动命令 `npx` → 点击保存 → **提交成功**、弹窗关闭、列表出现该 Server（此前点击无反应）。
2. 再开新增弹窗 → 名称留空直接保存 → **不提交**，名称字段旁出现"请输入名称"。
3. 开发者控制台全程无 `[ant-design-vue: Form] model is required` 警告。
4. 编辑任一 http 型 Server → 把 url 改成 `not-a-url` 保存 → 不提交，url 字段旁显示格式错误。
5. 编辑 `save-fix-demo` 改描述保存 → 列表同步。

### B. 类型命名（US2，SC-004）

1. 新增/编辑弹窗类型选项显示 **"stdio"** 与 **"远程 HTTP"**（无"本机启动"字样）。
2. 列表中 `save-fix-demo` 的类型标签显示 **"stdio"**。
3. 新增、编辑、测试连接行为与改名前一致（仅文案变化）。

### C. JSON 导入（US3，SC-002/SC-003）

1. 新增弹窗选 stdio → 出现 JSON 导入区（textarea + "解析 JSON"）；切到"远程 HTTP"→ 导入区消失。
2. 粘贴完整示例 JSON（见契约 §1）→ 点击"解析 JSON" → 名称/描述/命令/参数（两项、顺序一致）/环境变量全部正确填充；继续点保存 → 链路通畅、列表出现新 Server。
3. 粘贴仅含 `{"name": "partial", "command": "uvx"}` 的 JSON → 仅这两个字段被填充，其余保持原值。
4. 粘贴 `{ "name": "x", "command": 123 }` → 提示字段类型问题，**表单零改动**（此前填的内容未被部分覆盖）。
5. 粘贴非法 JSON（如缺引号 `{name: 1}`）→ 提示"JSON 格式不合法"。
6. 粘贴 `transport: "http"` 的 JSON → 提示仅支持 stdio，表单零改动。
7. JSON 含未知字段（`"icons": []`）→ 正常导入不报错；`enabled: false` → 不影响任何状态。

### 自动化门禁（交付前必须全绿，AGENTS.md §9）

```bash
# backend/ 内（零改动，复跑确认无回归）
uv run pytest && uv run pyright
# frontend/ 内
npm run build && npm run test:unit   # 含 jsonImport.spec.ts 解析契约表驱动测试
```
