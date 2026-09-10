# Research: 模型管理（第二阶段）

**Date**: 2026-09-10 | **Status**: Complete

本阶段技术决策记录。每项含：Decision（结论）、Rationale（理由）、Alternatives（被否方案）。

---

## R1 本地密钥保存方式（FR-009，spec 留给 Plan 阶段的唯一决策）

**Decision**: 采用"主密钥文件 + Fernet 对称加密 + 独立密钥表"方案。

- 主密钥：首次启动时自动生成 32 字节 Fernet key，写入 `backend/secret.key`（权限 0600，`.gitignore` 排除，不入库）。
- 密文存储：加密后的 API Key 存入 SQLite 独立表 `secrets_vault`（字段仅 `id` / `ciphertext` / `updated_at`），与业务表 `models` 分离；`models` 表只存 `secret_ref` 外键，**永不含明文，也不含可逆的密钥材料**。
- 对外只读状态：所有查询路径只返回 `api_key_configured: bool`。

**Rationale**:

1. 满足 spec FR-009 全部约束——明文不落普通业务表、不落前端、不入版本库；`secret.key` 入 `.gitignore` 后库中只有密文。
2. SQLite 单文件本地库 + 一个本地密钥文件，与项目"单机本地部署"匹配，无外部服务依赖。
3. Fernet（cryptography 库）提供认证加密（AES-128-CBC + HMAC），防篡改、实现简单、Python 生态标准做法。
4. 独立 `secrets_vault` 表使"删除模型时清理密钥"成为一行删除，且未来其他模块（如 MCP 凭据）可复用同一密钥库。
5. SQLite 库文件本身泄露（如误提交）时，密文在无 `secret.key` 的情况下不可解。

**Alternatives**:

- *Windows 凭据管理器（keyring 库）*：系统级安全更强，但引入平台绑定 API 与新依赖行为差异（Linux/macOS 回退不一致），测试夹具复杂；本项目威胁模型是"防止明文误入库与误展示"，Fernet 方案已足够。
- *环境变量存密钥*：多模型多密钥无法表达，用户增删密钥需改环境文件，体验差。
- *明文存表 + 前端脱敏*：直接违反 FR-009，否决。
- *SQLCipher 全库加密*：需要替换 SQLAlchemy 驱动与编译依赖，超出当前需求（YAGNI），且违反"SQLite 唯一数据库"的既定连接方式。

---

## R2 默认模型一致性保障（FR-017/021）

**Decision**: 数据层部分唯一索引 + 服务层事务编排，两层共同保障。

- `models` 表增加 `is_default` 布尔列，建 **SQLite 部分唯一索引** `CREATE UNIQUE INDEX ... ON models(is_default) WHERE is_default = 1`——数据库层硬性保证"至多一个默认"。
- 切换/删除默认模型的操作在**单个事务**内完成（先设新默认或清空 → 再删旧），避免中间态可见。
- 删除默认模型前由服务层强制要求请求携带 `new_default_id`（还有其他模型时），事务内完成"设新 + 删旧"。

**Rationale**: spec SC-003 要求"任意时刻"一致性，仅靠应用层判断在异常路径（并发、崩溃）下不成立；部分唯一索引让数据库拒绝任何双默认状态，事务保证删除序列原子。

**Alternatives**:

- *单独的 default_model 指针表*：多一张表多一次 join，对"至多一条"的语义反而绕远；部分索引更直接。
- *仅服务层互斥判断*：不满足"任意时刻"硬保证，否决。

---

## R3 服务地址规范化与请求拼装（FR-006、Edge Cases）

**Decision**: 后端统一规范化：去除末尾斜杠 → 若末段不是 `/v1` 且地址不含路径段则按原样追加 `/v1` 逻辑由**调用器**处理——具体规则收敛为：

- 存储时：仅做末尾斜杠去除 + 转小写 host 部分，保存用户输入的规范形式。
- 调用时：`chat_url = normalize(base_url) + "/chat/completions"`；若 `normalize(base_url)` 末段不是 `v1`，则先补 `/v1` 再拼。

| 用户输入 | 实际请求 |
|---------|---------|
| `https://api.example.com/v1/` | `https://api.example.com/v1/chat/completions` |
| `https://api.example.com` | `https://api.example.com/v1/chat/completions` |
| `https://gateway.corp/llm/v1` | `https://gateway.corp/llm/v1/chat/completions` |
| `https://api.example.com/v1/chat/completions`（误填完整路径） | 保存时表单示例引导拦截；测试连接时该地址拼出 `…/chat/completions/chat/completions` → 返回 404，归类"服务地址不可访问"并提示核对 /v1 写法 |

**Rationale**: 兼容主流 OpenAI 兼容服务两种常见地址形态；把规范化收敛在调用器一处（SSOT），前端只做格式提示不做地址改写。

**Alternatives**:

- *强制用户必须填到 /v1*：对网关型地址（路径含 /v1 之外前缀）不友好。
- *前端拼接 URL*：违反"后端统一一套调用逻辑"且难以测试，否决。

---

## R4 测试连接错误分类（FR-016）

**Decision**: 后端服务层按响应特征映射为五类 + 兜底，每类附人话提示与排查建议（文案主定义在 `contracts/api-contract.md`）：

| 分类 | 判定特征（httpx 异常 / HTTP 状态 / 响应体） |
|------|---------------------------------------------|
| `auth_error`（密钥错误） | 401/403 |
| `model_not_found`（模型标识错误） | 404 且响应体含 model 相关信息 |
| `unreachable`（服务地址不可访问） | 连接错误、DNS 失败、非 404 的 4xx/5xx 网关类状态（如 502/503） |
| `timeout`（请求超时） | httpx 超时异常（30s） |
| `bad_response`（返回格式异常） | 200 但 JSON 解析失败 / 缺少 choices 结构 |
| `unknown`（无法确定） | 以上均不匹配 |

**Rationale**: 五类与 spec FR-016 一一对应；`unknown` 兜底满足"无法确定原因时如实说明"。响应体中的服务商原始错误信息只作为分类依据，**透传前必须过滤密钥参数**（FR-011：提示文案不含密钥正文）。

**Alternatives**:

- *直接透传服务商错误 JSON*：可能包含请求头/参数回显，有泄露密钥风险且对用户不友好，否决。
- *只分"成功/失败"两类*：不满足 SC-005（五类中至少四类可明确分类），否决。

---

## R5 温度与数值字段校验（FR-007、Assumptions）

**Decision**: 温度范围 0–2（含边界，步进 0.1，建议值 0.7）——OpenAI Chat Completions 通用范围；上下文长度与最大输出长度为正整数，`max_output_tokens <= context_length`；三项价格 Decimal(10,4)、≥ 0、`None`（未配置）与 `0`（免费）区分存储。

**Rationale**: spec Assumptions 已确认按 OpenAI 通用范围处理；Decimal 避免浮点误差累积到后续计费。

**Alternatives**: *Float 价格*——精度问题留隐患，否决。

---

## R6 模型调用客户端（FR-013/023）

**Decision**: 服务层内建一个轻量 `openai_client`，直接用 `httpx` POST `{chat_url}`（R3 规则），带 30s 超时；请求体 `{model, messages:[{role:"user",content:"…"}], max_tokens: 小值, temperature}`，只此一套逻辑。

**Rationale**: 本阶段只需要"测试连接"一次真实调用；引入 openai 官方 SDK 会带入与其版本耦合的依赖树（YAGNI），而 httpx 已在依赖树中（测试组已用），直接实现 30 行内完成且完全可控（错误分类需要底层异常细节，SDK 反而屏蔽）。

**Alternatives**:

- *openai Python SDK*：抽象了错误细节，分类五类异常需要解包 SDK 异常链；且为单次调用引入完整 SDK 不符合 Simplicity，否决（后续聊天阶段用量上来再评估）。
- *aiohttp / requests*：技术栈外新依赖，否决。

---

## R7 前端表单与交互形态（FR-024）

**Decision**: 列表用 ant-design-vue `Table` + 空状态 `Empty`；新增/编辑用 `Modal` 内嵌表单（a-form 自定义校验规则）；删除确认用 `Modal.confirm` 变体（默认模型时弹选择新默认的 Modal）；测试连接用页面内联结果区（`Alert` + 回复摘录），进行中按钮 loading + 禁用。

**Rationale**: 与第一阶段已确立的"复用 antd 组件 + 设计令牌"一致；Modal 表单是管理页标准形态，不新增路由页面。

**Alternatives**: *独立路由的新增/编辑页面*：多两条路由与页面文件，对单表单 CRUD 过重，否决。

---

## 结论

所有 Technical Context 中的待决项已在本文档解决，无 NEEDS CLARIFICATION 遗留。关键决策：**R1 密钥库方案**、**R2 部分唯一索引** 为本阶段架构核心，data-model 与 contracts 据此展开。
