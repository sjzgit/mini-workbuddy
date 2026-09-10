# Quickstart: 模型管理（第二阶段）端到端验证

**Date**: 2026-09-10 | **Spec**: [spec.md](spec.md) | **契约**: [contracts/api-contract.md](contracts/api-contract.md)

本指南用于人工验证功能可用性。自动化测试见 `backend/tests/` 与 `frontend/src/**/__tests__/`。

## 前置条件

- Node 22（Windows + nvm 需先切版本，见 AGENTS.md §5 提示）与 uv 已安装
- 一个可用的 OpenAI Chat Completions 兼容服务地址、模型标识与 API Key（用于真实连接测试；无真实服务时场景 6 可用错误凭据验证失败路径）

## 启动

```bash
# 后端（backend/ 内）
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8218

# 前端（frontend/ 内，新终端）
npm install
npm run dev
```

浏览器打开 Vite 提示的地址，进入左侧菜单"模型管理"。

## 验证场景

### 场景 1：空状态（US1-2）

打开"模型管理"页 → 应显示空状态与"添加模型"入口，无报错。

### 场景 2：新增第一个模型并自动设为默认（US2 / US4-1）

1. 点击添加，填写合法配置（服务地址示例见表单提示；密钥填真实 Key）→ 保存。
2. 列表出现该模型，`默认` 标记为真，密钥列显示"已配置"。
3. 刷新页面 → 数据仍在（FR-022）。

### 场景 3：表单校验（US2-2/3/4）

逐项制造非法输入并保存：留空必填项、`base_url` 填 `https://x.com/v1/chat/completions`、`max_output_tokens > context_length`、`temperature = 3`、价格为 `-1` → 每次都应在**对应字段旁**看到原因且不保存。

### 场景 4：密钥保护（US3 / SC-002）

1. 打开浏览器开发者工具 Network，重新加载列表 → 检查 `GET /api/models` 响应：只有 `api_key_configured`，无密钥正文。
2. 编辑该模型：密钥输入框为空且有"已配置，留空则保留原密钥"提示；只改显示名称保存 → 再点"测试连接"仍成功（原密钥保留，FR-012）。
3. （可选）打开 `backend/app.db` 检查 `models` / `secrets_vault` 表：无明文 Key。

### 场景 5：默认模型切换与删除（US4）

1. 新增第二个模型 → 点"设为默认" → 新模型成为唯一默认，旧的取消。
2. 删除非默认模型 → 确认后删除，默认不变。
3. 删除默认模型（还有其他模型时）→ 弹出选择新默认，选择后完成删除与切换。
4. 删除最后一个模型 → 确认后页面回到空状态；重启后端后列表仍为空（默认设置已清除，SC-003/004）。

### 场景 6：测试连接成功与失败分类（US5 / SC-005）

1. 对配置正确的模型点"测试连接" → 显示"正在测试"（按钮禁用防重复点击）→ 成功显示"模型已连接"与一小段真实回复。
2. 复制该模型并分别改为：错误密钥 / 错误模型标识 / 不可达地址（如 `https://127.0.0.1:9/v1`）→ 各自得到对应分类提示与排查建议；任何失败提示不含堆栈与密钥。

## 自动化检查（交付门禁，AGENTS.md §9）

```bash
# 后端（backend/ 内）
uv run pytest
uv run pyright

# 前端（frontend/ 内）
npm run build
npm run test:unit
```

四项全绿 + 上述场景人工核对通过，方可视为交付完成。
