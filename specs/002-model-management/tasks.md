# Tasks: 模型管理（第二阶段）

**Input**: Design documents from `/specs/002-model-management/`

**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/api-contract.md ✅

**Tests**: 按 AGENTS.md §9 质量门禁与宪法 IV（验证驱动），测试任务为必做项。

**Organization**: 按用户故事分组（US1–US5 对应 spec.md），每个故事可独立实现与验证。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行（不同文件、无依赖）
- **[Story]**: 归属用户故事

## Path Conventions

Web app 双项目：`backend/`（uv）+ `frontend/`（npm）。后端命令一律在 `backend/` 内 `uv run`；前端命令在 `frontend/` 内执行（Windows 注意 AGENTS.md §5 的 Node 22 PATH 切换）。

---

## Phase 1: Setup（共享基础设施）

- [x] T001 [US-ALL] `backend/` 内 `uv add cryptography`；确认 `pyproject.toml` 与 `uv.lock` 同步更新
- [x] T002 [US-ALL] 更新根目录 `.gitignore`：追加 `backend/secret.key` 与 `backend/app.db`（若无）

**Checkpoint**: 依赖与忽略规则就绪。

---

## Phase 2: Foundational（阻塞性前置，全部故事依赖）

**⚠️ CRITICAL**: 本阶段完成前不得开始任何用户故事实现。

- [x] T003 [US-ALL] 创建 `backend/app/models/__init__.py`：按 [data-model.md](data-model.md) 定义 `ModelEntry`（models 表）与 `SecretVaultEntry`（secrets_vault 表）ORM，含部分唯一索引 `uq_models_single_default` 与 `ix_models_updated_at`；字段类型/约束与主定义逐列一致
- [x] T004 [US-ALL] 在 `backend/` 执行 `uv run alembic revision --autogenerate -m "add models and secrets_vault tables"`，检查迁移脚本（确认含部分唯一索引）→ `uv run alembic upgrade head`；对应 SQL 存档到 `sql/migrations/`
- [x] T005 [US-ALL] 创建 `backend/app/core/secret_vault.py`：主密钥自动生成（首访时写 `backend/secret.key`，`0600`）+ Fernet 加密/解密/删除接口；`app/core/config.py` 新增 `secret_vault_path` 设置项；这是 secrets_vault 表的唯一访问入口
- [x] T006 [US-ALL] 创建 `backend/app/schemas/model.py`：按 [contracts/api-contract.md](contracts/api-contract.md) 实现 `ModelItem` / `ModelDetail` / `ModelUpsertRequest`（含全部字段校验规则 1–5）/ `TestConnectionResult` / `TestErrorCategory`；响应模型永不含密钥字段（只有 `api_key_configured`）
- [x] T007 [P] [US-ALL] `backend/tests/conftest.py` 扩展：隔离的临时 SQLite 测试库 + 临时 `secret.key` 目录夹具（不触碰开发 `app.db` 与真实主密钥）

**Checkpoint**: 数据层、密钥库、契约 Schema、测试夹具就绪 → 用户故事可开始。

---

## Phase 3: US1 + US2 + US3（P1，核心 CRUD 与密钥保护）🎯 MVP

**Goal**: 模型列表、空状态、新增/编辑表单校验、密钥全链路保护。
**Independent Test**: quickstart.md 场景 1–4。

### 实现任务

- [x] T008 [US1/US2/US3] 创建 `backend/app/services/model_service.py`：列表（更新时间倒序）/ 详情 / 新增（首个自动默认 + 密钥加密入库）/ 编辑（空密钥保留原值）/ 删除（含 new_default_id 事务编排与密钥清理）/ 设默认（同事务翻转）；所有写操作单事务，默认唯一性依赖部分唯一索引兜底
- [x] T009 [US1/US2/US3] 创建 `backend/app/api/models.py`：按契约挂 7 个接口（GET 列表 / GET 详情 / POST / PUT / DELETE?new_default_id / POST default / POST test-connection 占位）；`app/main.py` 注册路由
- [x] T010 [US1] 后端测试 `backend/tests/test_models_api.py`：契约测试覆盖 7 接口（含 404/400/422 路径、空表 `[]`、响应无密钥正文断言）
- [x] T011 [US2/US3] 后端测试 `backend/tests/test_model_service.py`：业务规则（首个自动默认、切换默认事务、删除默认强制 new_default_id、删除清理密钥、编辑留空保留密钥、五类校验规则、价格 null vs 0）
- [x] T012 [P] [US1/US2] 前端 `frontend/src/api/models.ts`：按契约派生 TS 类型与 7 个接口调用（null 不混用 undefined）
- [x] T013 [P] [US1/US2] 前端 `frontend/src/stores/models.ts`：Pinia store（列表/加载态/错误态/刷新动作）
- [x] T014 [US1] 前端 `frontend/src/views/ModelsView.vue`：替换占位页——a-table 列表（8 列信息 + 操作列）+ 空状态 Empty + 添加入口；样式全引用 tokens.scss 变量，字号按 AGENTS.md §8
- [x] T015 [US2] 前端 `frontend/src/components/models/ModelFormModal.vue`：新增/编辑弹窗表单——每字段填写说明、建议值标注（上下文 8192 / 输出 4096 / 温度 0.7，标注"建议值，以服务商说明为准"）、服务地址 /v1 示例与 chat/completions 拦截提示、编辑时密钥框空 + "已配置，留空则保留原密钥"、a-form 自定义校验规则与字段旁错误
- [x] T016 [US3] 前端 Vitest：`stores/__tests__/models.spec.ts`（加载/空态/错误态）与表单校验核心逻辑测试（跨字段规则 max_output ≤ context、价格 null/0）

**Checkpoint**: 场景 1–4 人工验证通过 + 后端测试绿。

---

## Phase 4: US4（P1，默认模型与删除）

**Goal**: 默认模型全生命周期一致性与删除流程。
**Independent Test**: quickstart.md 场景 5。

- [x] T017 [US4] 后端删除/设默认接口收尾（若 T008/T009 已含则核验）：`DELETE` 校验 new_default_id 语义（默认模型 + 存在其他模型时必填且存在）；409/400 错误文案与契约一致
- [x] T018 [US4] 后端测试补充：删除序列全流程（删普通 → 删默认带 new_default → 删最后一个清空默认与密钥）+ 任意操作后默认 ≤ 1 的不变量断言
- [x] T019 [US4] 前端 `frontend/src/components/models/DeleteModelModal.vue`：普通删除确认弹窗；删除默认模型且有余量时先弹"选择新默认"再执行；完成后刷新列表
- [x] T020 [US4] 列表页接入"设为默认"操作（当前非默认行可点，loading 防抖）

**Checkpoint**: 场景 5 验证通过。

---

## Phase 5: US5（P2，测试连接）

**Goal**: 真实请求调用与五类错误分类提示。
**Independent Test**: quickstart.md 场景 6。

- [x] T021 [US5] 创建 `backend/app/services/openai_client.py`：R3 地址规范化（去尾斜杠、末段非 v1 补 /v1）+ `POST {base}/chat/completions`（30s 超时、max_tokens=min(64, 配置值)）+ 响应解析出回复文本；异常/状态码原样上抛给分类层
- [x] T022 [US5] `model_service.py` 增加测试连接编排：调用 openai_client → 按 R4 分类表映射 category + 契约 message 模板（透传信息前过滤密钥）→ `TestConnectionResult`（成功含 200 字符内回复摘录）
- [x] T023 [US5] `api/models.py` 补 `POST /{id}/test-connection`
- [x] T024 [US5] 后端测试：mock httpx 五类失败场景 + 成功场景的分类断言 + message 不含密钥断言
- [x] T025 [US5] 前端列表页接入测试连接：行内/弹窗展示"正在测试"（按钮禁用防重复）→ 成功 Alert + 回复摘录 / 失败分类提示与排查建议

**Checkpoint**: 场景 6 验证通过。

---

## Phase 6: 收尾与交付门禁

- [x] T026 [P] [US-ALL] `README.md` 补充：secret.key 自动生成说明与备份提示（不含 pip 步骤）
- [x] T027 [US-ALL] 人工走查 quickstart.md 全部场景（自动化已覆盖等价断言；真实服务的连接测试场景 6 留待用户按 quickstart.md 操作验证）
- [x] T028 [US-ALL] 交付门禁四连（AGENTS.md §9）：`uv run pytest`（47 通过）+ `uv run pyright`（0 错误）+ `npm run build`（零错误）+ `npm run test:unit`（31 通过）全绿；UI 改动人工核对 §8 设计令牌条目
- [ ] T029 [US-ALL] 运行 `/speckit-analyze` 跨文档一致性分析并处理发现项（待用户发起）

---

## Dependencies & Execution Order

- **Phase 1 → 2 顺序执行**；T007 可与 T003–T006 并行（不同文件）
- **Phase 3 内**：T008 → T009 → (T010, T011)；T012/T013 可与后端并行 [P]；T014 依赖 T012/T013；T015 依赖 T014（同页面挂载）
- **Phase 4 依赖 Phase 3**（列表与表单存在才有删除/默认交互）
- **Phase 5 依赖 Phase 2**（openai_client 只依赖数据层，可与 Phase 4 并行）
- **Phase 6 最后**，T029 在 T028 全绿后执行

## Notes

- 每完成一个任务勾选对应复选框（实现阶段由 /speckit-implement 维护）
- 提交粒度：每个 Phase 或逻辑分组一次提交（仓库启用 git 后）
- 实现中发现规范问题 → 先回写 `data-model.md` / `contracts/api-contract.md` 再同步代码（宪法 VI）
