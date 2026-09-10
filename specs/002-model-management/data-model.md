# Data Model: 模型管理（第二阶段）

**Date**: 2026-09-10 | **Source of Truth**: 本文件是数据模型的主定义（宪法 II/III），实现侧 SQLAlchemy ORM（`backend/app/models/`）字段与类型 MUST 与本文一致，变更必须先改这里再落 Alembic 迁移。

## 实体关系

```text
models (业务配置表)                secrets_vault (密钥密文表，独立于业务数据)
┌──────────────────────┐          ┌────────────────────┐
│ id (PK)              │          │ id (PK)            │
│ secret_ref (FK, NULL)│───1:0..1─│ ciphertext         │
│ ...（见下）           │          │ updated_at         │
└──────────────────────┘          └────────────────────┘
                                   ▲
                                   └─ 解密钥匙：backend/secret.key（文件，不入库）
```

- 一个模型配置至多关联一条密钥记录（`secret_ref` 为 NULL 表示未配置密钥）。
- 删除模型时**同事务**删除对应 `secrets_vault` 行（FR-021）。
- 密钥从数据库读出密文后，经主密钥 Fernet 解密仅在后端内存中使用，任何出站响应只含 `api_key_configured`。

## 表：models

| 列 | 类型 | 约束 / 默认 | 说明 |
|----|------|------------|------|
| `id` | INTEGER | PK, 自增 | |
| `display_name` | VARCHAR(100) | NOT NULL | 显示名称（去除首尾空白后非空） |
| `model_identifier` | VARCHAR(200) | NOT NULL | 请求使用的模型标识（与服务商一致） |
| `base_url` | VARCHAR(500) | NOT NULL | 服务地址（API Base URL，存储末尾去斜杠的规范形式，见 research R3） |
| `secret_ref` | INTEGER | NULL, FK → secrets_vault.id | 未配置密钥时为 NULL |
| `context_length` | INTEGER | NOT NULL, > 0 | 上下文窗口（token） |
| `max_output_tokens` | INTEGER | NOT NULL, > 0 | 单次最大生成（token），且 ≤ context_length |
| `temperature` | NUMERIC(3,1) | NOT NULL, 0.0–2.0 | 建议默认 0.7 |
| `input_price` | NUMERIC(10,4) | NULL, ≥ 0 | 元 / 百万输入 token；NULL=未配置，0=免费 |
| `output_price` | NUMERIC(10,4) | NULL, ≥ 0 | 元 / 百万输出 token |
| `cached_input_price` | NUMERIC(10,4) | NULL, ≥ 0 | 元 / 百万缓存命中输入 token |
| `is_default` | BOOLEAN | NOT NULL, DEFAULT 0 | 部分唯一索引保证至多一条为 1 |
| `created_at` | DATETIME | NOT NULL, 当前时间(UTC) | |
| `updated_at` | DATETIME | NOT NULL, 每次更新刷新(UTC) | 列表"最后更新时间"来源 |

**索引**：

- `uq_models_single_default`：`CREATE UNIQUE INDEX ON models(is_default) WHERE is_default = 1`（部分唯一索引，research R2——数据库层保证默认唯一）
- `ix_models_updated_at`：普通索引，列表按更新时间排序

**校验规则（与 spec FR-007 对应，实现于 Pydantic Schema 层 + 服务层复核）**：

1. `display_name`、`model_identifier`、`base_url`、`context_length`、`max_output_tokens`、`temperature` 必填；三项价格可选。
2. `base_url` 必须是 `http://` 或 `https://` 开头的合法 URL，且路径不得以 `/chat/completions` 结尾（表单层拦截误填，见 Edge Cases）。
3. `context_length`、`max_output_tokens` 为正整数；`max_output_tokens ≤ context_length`。
4. `temperature ∈ [0, 2]`。
5. 价格 `≥ 0`；NULL 与 0 语义不同（未配置 vs 免费），存储与响应均保留区别。

## 表：secrets_vault

| 列 | 类型 | 约束 | 说明 |
|----|------|------|------|
| `id` | INTEGER | PK, 自增 | 被 models.secret_ref 引用 |
| `ciphertext` | VARCHAR(512) | NOT NULL | Fernet 加密后的 API Key（token 化密文，永不存明文） |
| `created_at` | DATETIME | NOT NULL | |
| `updated_at` | DATETIME | NOT NULL | 替换密钥时刷新 |

**约束**：本表只有后端 `core/secret_vault.py` 一个访问入口（写入/替换/读取/删除），业务代码不得绕过；`models` 表与任何 API 响应不含密文与明文。

## 主密钥（文件，非表）

- 路径：`backend/secret.key`（`app.core.config.Settings.secret_vault_path` 可覆盖）。
- 首次访问不存在时自动生成 Fernet key 并写入（`0600`）。
- `.gitignore` 追加 `backend/secret.key` 与 `backend/app.db`（后者开发库不入库）。

## 状态与生命周期

```text
[无模型] --保存第1个(自动 is_default=1)--> [模型A(默认)]
[模型A(默认), 模型B] --设B为默认--> [模型A, 模型B(默认)]   （同事务翻转，索引保证无中间态双默认）
[模型A(默认), 模型B] --删除A(new_default=B)--> [模型B(默认)]
[模型A(默认)] --删除A(最后一个)--> [无模型, 无密钥残留]      （清空默认与密钥）
```

- 新增模型时若表中无任何 `is_default=1`，则该模型设为默认（覆盖"保存第一个模型"与"删除最后一个后又新增"两种到达路径）。
- 编辑不触碰 `is_default` 与 `secret_ref`（除非填写了新密钥）。

## 与 spec 需求的映射

| spec 需求 | 数据层落点 |
|-----------|-----------|
| FR-001/022 列表字段与持久化 | models 全列 + SQLite 持久化 |
| FR-007 校验 | 上方校验规则 1–5 |
| FR-009~012 密钥保护 | secrets_vault 独立表 + secret.key + 单一访问入口 + `api_key_configured` 派生列 |
| FR-017/018/019/021 默认一致性 | 部分唯一索引 + 事务编排 + 删除时清理 secret_ref/secrets_vault |
| 价格未填/为 0 区分（FR-007/US2-场景4） | NUMERIC NULL vs 0 |
