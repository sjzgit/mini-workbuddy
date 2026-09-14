# Quickstart: Agent 管理（第七阶段）验收指南

**Date**: 2026-09-11 | **Feature**: [spec.md](./spec.md) | **Contract**: [contracts/agents-api.md](./contracts/agents-api.md)

自动化检查见 tasks.md 对应任务；本指南是人工端到端验收路径。

## 前置条件

```powershell
# 后端（uv 强制）
cd backend
uv sync
uv run alembic upgrade head      # 应用 007 迁移（三张新表）
uv run uvicorn app.main:app --reload

# 前端（另开终端）
cd frontend
npm install
npm run dev
```

数据库文件 `backend/app.db`；迁移回滚 `uv run alembic downgrade -1`。

## 验收场景

### A. 空状态与无模型引导

1. 清空 Agent（首次使用即为空）→ 打开 Agent 管理页 → **预期**：空状态卡片 + 新建入口。
2. 若模型管理为空 → 点新建 → **预期**：模型区显示"先添加模型"提示与跳转模型管理入口；填写其余字段后发布被 422 拦截（模型必选）。
3. 跳转模型管理添加一个模型 → 返回新建 → **预期**：默认选中该默认模型。

### B. 新建与列表（US1/US2）

4. 新建 Agent"写作助手"：说明留空、保留默认提示词模板、选默认模型、勾选 1 个工具 + 2 个 Skills + 0 个 MCP、轮数默认 10 → 发布 → **预期**：201 成功回列表，卡片出现且带默认标识；卡片显示模型名称与标识、工具 1 / Skills 2 / MCP 0、提示词模板条目（1 条，无 +N）。
5. 再建"翻译助手"绑定 5 项能力 → **预期**：卡片条目最多 3 项 + `+2`；两卡片均有，第一张仍为默认。

### C. 编辑与提示词版本（US3）

6. 打开"写作助手"详情 → **预期**：全屏 dialog 三列；提示词版本选择器显示 v1。
7. 只改名称保存 → **预期**：版本仍为 v1（FR-019）。
8. 修改提示词内容保存 → **预期**：版本变 v2；切回 v1 可查看原文并可基于它编辑；不改动内容直接保存 → 不产生 v3。
9. 仅改工具绑定/轮数保存 → 版本不变。

### D. 默认与删除流程（US4）

10. 设"翻译助手"为默认 → **预期**：旧默认自动取消，至多一个默认标识。
11. 删除普通 Agent → 出现确认框 → 取消不删、确认删除。
12. 删除当前默认 Agent（还有其他 Agent）→ **预期**：409 流程——弹窗要求先选新默认，选定后完成删除与切换；中途取消则不删。
13. 删除最后一个 Agent → 确认 → **预期**：回空状态，默认清除（`cleared_default: true`）。

### E. 停用绑定保持（US5）

14. 建 Agent 绑定某工具 → 工具管理停用该工具 → 打开 Agent 编辑 → **预期**：绑定仍在、标记"已停用，不可用"；不移除直接保存 → 绑定保留，卡片计数含该绑定；恢复启用后标记消失。

### F. 引用删除保护（US6）

15. Agent 引用某模型 / Skill / MCP 后，分别在对应管理页删除 → **预期**：删除被拒，提示列出引用它的 Agent 名称。
16. （开发者）直接 `DELETE /api/models/{id}` 绕过前端 → **预期**：409 同样被拒（服务端检查）。
17. 在 Agent 中移除引用（或删除该 Agent）→ 再次删除资源 → **预期**：成功。
18. 删除默认模型且被 Agent 引用 → **预期**：409 引用保护生效，不触发默认模型切换。

### G. 持久化

19. 刷新页面 / `Ctrl+C` 重启后端再启动 → **预期**：Agent 列表、绑定、版本、默认状态完整保留。

## 自动化检查（交付门禁）

```powershell
cd backend  ; uv run pytest          # 全部通过（含 tests/test_agents_api.py、tests/test_agent_references.py）
cd frontend ; npm run build          # 无错误
cd frontend ; npx vitest run         # 全部通过
```
