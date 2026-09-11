# Tasks: Skills 与 MCP 管理（第四阶段）

**Input**: Design documents from `/specs/004-skills-mcp-management/`

**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/skills-api.md ✅, contracts/mcp-api.md ✅, quickstart.md ✅

**Tests**: 按 AGENTS.md §9 质量门禁与宪法 IV（验证驱动），测试任务为必做项（含 MCP 真 stdio 集成测试）。

**Organization**: 按用户故事分组（US1–US7 对应 spec.md）：US1–US3 Skills 核心（P1）、US4 ZIP 导入（P2）、US5 MCP 配置（P1）、US6+US7 MCP 测试与启停（P1+P2）。新增依赖仅两个：`mcp`（MCP 协议客户端）与 `python-multipart`（ZIP 上传），均在 Foundational 落地。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行（不同文件、无依赖）
- **[Story]**: 归属用户故事（US-ALL = 跨故事共享）

## Path Conventions

Web app 双项目：`backend/`（uv）+ `frontend/`（npm）。后端命令一律在 `backend/` 内 `uv run`；前端命令在 `frontend/` 内执行（Windows 注意 AGENTS.md §5 的 Node 22 PATH 切换）。

---

## Phase 1: Setup（共享基础设施）

- [x] T001 [US-ALL] 核对根目录 `.gitignore` 已覆盖 `backend/workspace/`（Skills 目录 `workspace/skills/` 是其子目录，无需新增规则）；若缺失则补上

**Checkpoint**: 忽略规则就绪。

---

## Phase 2: Foundational（阻塞性前置，全部故事依赖）

**⚠️ CRITICAL**: 本阶段完成前不得开始任何用户故事实现。

- [x] T002 [US-ALL] 在 `backend/` 执行 `uv add mcp` 与 `uv add python-multipart`（运行必需依赖，research R3/R7），`uv sync` 后确认 `uv.lock` 更新
- [x] T003 [US-ALL] `backend/app/core/config.py` 新增三个设置项：`skills_dir`（默认 `./workspace/skills`）、`mcp_test_timeout_seconds`（默认 `30`）、`skill_import_max_bytes`（默认 `10485760`），对齐 [contracts/skills-api.md](contracts/skills-api.md) §7 与 [contracts/mcp-api.md](contracts/mcp-api.md) §8
- [x] T004 [US-ALL] `backend/app/models/__init__.py` 追加 `SkillEntry`（skills 表：`id` / `dir_name` 唯一索引 / `enabled` DEFAULT 1 / `created_at` / `updated_at`）与 `McpServerEntry`（mcp_servers 表：`id` / `name` 唯一索引 / `description` / `server_type` / `command` / `command_args`(JSON) / `env_secret_ref` FK / `url` / `headers_secret_ref` FK / `enabled` / `last_test_status` / `last_test_message` / `last_test_tool_count` / `last_test_at` / `tools_json` / `created_at` / `updated_at`），字段类型与约束和 [data-model.md](data-model.md) 逐列一致
- [x] T005 [US-ALL] 在 `backend/` 执行 `uv run alembic revision --autogenerate -m "add skills and mcp_servers tables"` → 检查脚本（无播种数据）→ `uv run alembic upgrade head`；对应 SQL 存档到 `sql/migrations/`
- [x] T006 [P] [US-ALL] 创建 `backend/app/schemas/skill.py`：按 [contracts/skills-api.md](contracts/skills-api.md) §3 实现 `SkillItem` / `SkillDetail` / `SkillUpdateRequest`（name 1–100、description ≤500、instruction ≤200000）/ `SkillToggleRequest` / `SkillRefreshResult` / `SkillImportResult`（deleted 响应复用 002 `DeleteResponse` 形态则直接新建同构模型）
- [x] T007 [P] [US-ALL] 创建 `backend/app/schemas/mcp.py`：按 [contracts/mcp-api.md](contracts/mcp-api.md) §2 实现 `McpServerItem` / `McpServerDetail` / `McpServerUpsertRequest`（含 stdio/http 字段互斥的 model_validator、env/headers 三态 `dict[str, str | None]`、url 格式校验）/ `McpToggleRequest` / `McpToolInfo` / `McpToolParam` / `McpTestResult`，以及 `TestStatus` / `TestCategory` / `ServerType` Literal 枚举
- [x] T008 [US-ALL] `backend/tests/conftest.py` 扩展两个夹具：`skills_dir`（`tmp_path/skills` 子目录并 monkeypatch `settings.skills_dir`，不触碰真实 `backend/workspace/skills/`）与 `mcp_test_timeout`（monkeypatch `settings.mcp_test_timeout_seconds` 为小值如 5，缩短集成测试时长）

**Checkpoint**: 依赖、配置、数据层、契约 Schema、测试夹具就绪 → 用户故事可开始。

---

## Phase 3: US1 + US2 + US3（P1，Skills 列表/刷新/编辑/启停/删除）🎯 MVP

**Goal**: Skills 管理页面完整闭环——文件为本的列表与手动刷新、编辑写回文件、启停持久化、删除确认。
**Independent Test**: quickstart.md 场景 A（手动创建→刷新→编辑→启停→删除）+ 场景 C（空状态与不合规目录）。

### 实现任务

- [x] T009 [US1] 创建 `backend/app/services/skill_files.py`（纯文件层，无 DB）：frontmatter 解析（`---` 逐行 `key: value`，仅 name/description，宽松读）/ 规范重写（严格写，UTF-8 `\n`）/ 合规判定（`skill.md` 存在且非空）/ 目录扫描（合规目录清单 + 不合规 skipped 清单）/ 单文件读（`read_skill` → name/description/instruction + mtime）/ 单文件写（`write_skill`）/ 目录删除；目录根 `settings.skills_dir`，首次访问自动创建
- [x] T010 [US1] 后端测试 `backend/tests/test_skill_files.py`：frontmatter 解析（标准两键 / 无 frontmatter 兜底 / 未知键忽略 / description 含冒号）/ 合规判定（缺失、空文件、正文非空三态）/ 扫描（合规 + skipped 同时返回、目录名合法字符集校验）/ 规范重写幂等（写后读一致）
- [x] T011 [US1/US2/US3] 创建 `backend/app/services/skill_service.py`：`list_skills`（扫描 ⨝ DB enabled，`updated_at` 倒序，行缺失视为启用并补行——幂等同步）/ `refresh`（新目录补行默认启用、消失目录清行、返回 items + skipped）/ `get_skill` / `update_skill`（写文件 + 刷新 DB `updated_at`）/ `set_enabled` / `delete_skill`（删目录 + 删行，目录占用等系统错误 → `SkillOperationError` 人话信息）
- [x] T012 [US1/US2/US3] 创建 `backend/app/api/skills.py`：按契约挂 6 个端点（`GET /api/skills`、`GET /api/skills/{dir_name}` 404"Skill 不存在"、`PUT /api/skills/{dir_name}`、`PUT /api/skills/{dir_name}/enabled`、`DELETE /api/skills/{dir_name}` 400 人话错误、`POST /api/skills/refresh`）；`app/main.py` 注册路由
- [x] T013 [US1/US2/US3] 后端测试 `backend/tests/test_skills_api.py`：列表字段完整与倒序 / 空目录返回 `[]` / 刷新发现手动新建目录（无需重启）与 skipped 提示 / 刷新清消失行 / 编辑保存后读回一致且 `updated_at` 刷新 / 启停后刷新页面数据保持（重启语义由持久化断言覆盖）/ 删除确认后目录与行均消失、取消分支文件未动 / 未知 dir_name 404 / body 非法 422
- [x] T014 [P] [US1/US2/US3] 前端 `frontend/src/api/skills.ts`：按契约派生 `SkillItem` / `SkillDetail` / `SkillUpdatePayload` / `SkillRefreshResult` 类型与接口调用（含 `FormData` 上传预留，null 不混用 undefined）
- [x] T015 [P] [US1/US2/US3] 前端 `frontend/src/stores/skills.ts`：Pinia store（列表 / 加载态 / 错误态 / `refreshing` / 刷新动作返回 skipped / 启停 / 删除 / 编辑保存后重拉）
- [x] T016 [US2] 前端 `frontend/src/components/skills/SkillEditDrawer.vue`：编辑抽屉——名称 input / 用途说明 input / 详细指令 `a-textarea`（autosize ≥ 16 行，适合长 Markdown；旁注"支持 Markdown，供 Agent 阅读"）；保存经 store 写回并提示成功
- [x] T017 [US1/US2/US3] 前端 `frontend/src/views/SkillsView.vue` 替换占位页：页头右侧「导入 ZIP」（Upload，beforeUpload 拦截手动提交——本任务先占位禁用，Phase 4 启用）与「刷新」按钮（loading）；Table（名称 / 说明 / 启用 Switch+`Modal.confirm` / 更新时间 / 操作列：编辑、删除+确认）；空状态 Empty；刷新 skipped 用 `message.warning` 提示；样式全引用 tokens.scss 变量
- [x] T018 [US1/US2/US3] 前端 Vitest：`frontend/src/stores/__tests__/skills.spec.ts`（加载 / 空态 / 刷新 skipped 态 / 启停与错误态）

**Checkpoint**: 场景 A、C 人工验证通过 + `uv run pytest`、`npm run test:unit` 绿。

---

## Phase 4: US4（P2，Skill ZIP 导入）

**Goal**: ZIP 导入全链路——双重 ZIP 校验、路径逃逸拒绝、资源上限、结构判定、同名拒绝、原子落地。
**Independent Test**: quickstart.md 场景 B（合规 + 同名 + 逃逸 + 非 ZIP 四分支）。

### 实现任务

- [x] T019 [US4] `backend/app/services/skill_service.py` 追加 `import_zip(file) -> SkillItem`：文件名 `.zip` 后缀 + `PK\x03\x04` 魔数双校验 → 隔离临时目录解压（逐条目绝对路径/`..` 黑名单 + resolve 包含性 + 总大小 ≤ `settings.skill_import_max_bytes` + 条目数 ≤ 200）→ 结构判定（根 `skill.md` 取 ZIP 名 / 唯一顶层目录取目录名）→ 同名冲突拒绝 → 合规校验 → 目录移入 `skills_dir` → 刷新同步返回新项；任何失败清理临时目录且不触碰 `skills_dir`（契约 skills-api.md §5）
- [x] T020 [US4] 后端测试 `backend/tests/test_skill_files.py` 追加导入单测（或独立 `test_skill_import.py`）：标准 ZIP 成功 / 根布局与单目录布局两种形态 / 非 ZIP 魔数拒绝 / `../evil.txt` 逃逸拒绝且目标目录零改动 / 超大小上限拒绝 / 超条目数拒绝 / 结构不符拒绝 / 同名冲突拒绝且原目录内容未变
- [x] T021 [US4] `backend/app/api/skills.py` 追加 `POST /api/skills/import`（multipart `file` 字段）：400 人话失败原因、422 非 ZIP/超限；前端 `api/skills.ts` 启用 `importZip(file)` 与 `SkillsView.vue` 的「导入 ZIP」入口（上传成功后重拉列表 + `message.success`，失败 `message.error` 透出 detail）
- [x] T022 [US4] 前端 Vitest：`skills.spec.ts` 追加导入成功/失败分支（mock api 层）

**Checkpoint**: 场景 B 人工验证通过；pytest / Vitest 绿。

---

## Phase 5: US5（P1，MCP Server 配置管理）

**Goal**: MCP Server 的 CRUD、掩码展示、三态保留协议、持久化；列表含测试结果列与工具数量入口。
**Independent Test**: quickstart.md 场景 D（两类 Server 新增 → 掩码核对 → 保留原值 → 重启保留）。

### 实现任务

- [x] T023 [US5] 创建 `backend/app/services/mcp_service.py`（本任务先做配置部分，测试部分 Phase 6 追加）：`list_servers` / `get_server`（含 `env_masked`/`headers_masked` 掩码字典与 `tools` 快照解析）/ `create_server`（同名 → `McpNameConflictError`；env/headers JSON 序列化经 `secret_vault.store_secret` 加密）/ `update_server`（三态合并：null 保留、字符串替换、键缺席删除；改后删除消失键的孤儿密文）/ `delete_server`（删行 + `secret_vault.delete_secret` 两份）/ `set_enabled`；服务层异常 `McpNotFoundError` / `McpNameConflictError` / `McpBusyError`；**任何返回不含明文**（FR-023）
- [x] T024 [US5] 创建 `backend/app/api/mcp.py`：按契约挂 6 个端点（`GET /api/mcp/servers`、`GET /api/mcp/servers/{id}`、`POST /api/mcp/servers` 201、`PUT /api/mcp/servers/{id}`、`DELETE /api/mcp/servers/{id}`、`PUT /api/mcp/servers/{id}/enabled`；`POST …/test` Phase 6 追加）；404"MCP Server 不存在"、同名 400、忙 400；`app/main.py` 注册路由
- [x] T025 [US5] 后端测试 `backend/tests/test_mcp_api.py`：stdio/http 两类创建字段校验（互斥 422：stdio 带 url、http 带 command 等）/ 同名 400 / 列表与详情字段完整（未测试 NULL → 前端"未测试"口径）/ **掩码断言**（详情响应 `env_masked` 为 `••••••`，全响应文本搜索不到明文 env 值，SC-005）/ 三态合并（null 保留、字符串替换、键缺席删除——重启读回验证）/ 编辑与删除后 `secrets_vault` 行数变化断言 / 404 / 测试快照列初始 NULL
- [x] T026 [P] [US5] 前端 `frontend/src/api/mcp.ts`：按契约派生全部类型（`McpServerItem` / `McpServerDetail` / `McpServerUpsertPayload`（env/headers 为 `Record<string, string | null>`）/ `McpTestResult` / `McpToolInfo` / `McpToolParam` / `TestStatus` / `TestCategory`）与接口调用
- [x] T027 [P] [US5] 前端 `frontend/src/stores/mcp.ts`：Pinia store（列表 / 加载 / 错误 / `testingId` 单一进行中标识 / 变更后重拉）
- [x] T028 [US5] 前端 `frontend/src/components/mcp/McpServerFormModal.vue`：新增/编辑复用——类型 RadioGroup 切换 stdio（命令 / 参数动态行列表保序可增删移 / 环境变量键值动态行，值留空 = 保留原值，placeholder 提示）与 http（url / Header 键值动态行）两组字段；顶部常驻 `Alert` 字段说明与填写示例（契约 §4 文案）；表单校验（必填、url 格式、互斥由类型切换天然保证）；编辑时 env/headers 值输入框一律留空（显示掩码键名 + "已配置"标记），提交未修改键为 null
- [x] T029 [US5] 前端 `frontend/src/views/McpView.vue` 替换占位页：页头「新增」按钮；Table（名称 / 说明 / 类型 Tag 本机·远程 / 测试结果列按 status 着色（未测试灰 / 成功绿 / 失败红 / 配置已变更橙） / 工具数量列（有数量可点击 → 预留弹窗 Phase 6、无数量"未知"） / 启用 Switch+确认 / 操作列：测试（Phase 6 启用）、编辑、删除+确认）；空状态 Empty
- [x] T030 [US5] 前端 Vitest：`frontend/src/stores/__tests__/mcp.spec.ts`（加载 / 空态 / 错误态）+ 表单纯函数测试（参数列表与键值行的增删移操作，若抽为可复用函数）

**Checkpoint**: 场景 D 人工验证通过；pytest / Vitest 绿。

---

## Phase 6: US6 + US7（P1+P2，MCP 测试连接与启停/结果有效性）

**Goal**: 真实测试连接（启动/连接 → initialize → list_tools → 清理零残留）、失败六分类、脱敏诊断、并发锁；启停独立性、`config_changed` 标记。
**Independent Test**: quickstart.md 场景 E（成功 / 无工具 / 六类失败 / 并发锁 / 脱敏）+ 场景 F（停用可测、config_changed）。

### 实现任务

- [x] T031 [US6] 创建 `backend/tests/fake_mcp_server.py`：内嵌 FastMCP 假 Server 脚本（`python fake_mcp_server.py --tools 2` 注册两个带参数说明的工具；`--tools 0` 无工具模式），供 stdio 集成测试真实走启动→initialize→list_tools 链路
- [x] T032 [US6] 创建 `backend/app/services/mcp_client.py`（async、无 DB）：`connect_and_list(config) -> list[McpToolInfo]`——stdio（`StdioServerParameters` + `get_default_environment()` 叠加用户 env）与 http（`streamablehttp_client(url, headers)`）两传输形态 → `ClientSession.initialize()` → `list_tools()` → inputSchema 解析为参数表；总超时 `asyncio.wait_for(settings.mcp_test_timeout_seconds)`；异常映射六分类（契约 mcp-api.md §5）+ `_sanitize` 脱敏纯函数（env/header 值长度 ≥4 全量替换 `******`、摘要 ≤500 字符）；`config_to_transport` 只透出连接所需字段
- [x] T033 [US6] 后端测试 `backend/tests/test_mcp_client.py`：`_sanitize` 单测（含密文值替换、短值不误伤、空配置） / 错误分类单测（注入各类异常 → category 断言）/ inputSchema 解析（required、type 缺省 any、description 缺省空）
- [x] T034 [US6/US7] `backend/app/services/mcp_service.py` 追加测试编排：模块级 `dict[int, asyncio.Lock]`；`test_server(session, id)` async——锁占用检查（重复测试 / 测试中编辑删除 → `McpBusyError`）→ 取配置（env/headers 解密）→ `connect_and_list` → 成功写快照四列 + tools_json（`tool_count=0` 时 message"连接成功，未发现工具"）/ 失败写 status=failed + 分类 message；不改 `enabled`（FR-033）；`update_server` 追加 `config_changed` 判定（五项值实际变化且存在旧结果 → status='config_changed'，保留旧 tool_count/tools_json，FR-034）
- [x] T035 [US6/US7] `backend/app/api/mcp.py` 追加 `POST /api/mcp/servers/{id}/test`（async 路由）→ `McpTestResult`；`api/mcp.py` 与 `mcp_service.py` 的忙拒绝统一 400
- [x] T036 [US6/US7] 后端集成测试 `backend/tests/test_mcp_test_connection.py`：真 stdio 假 Server 成功（tools=2：名称/用途/参数类型/必填齐全，SC-008）/ 无工具成功（message"连接成功，未发现工具"）/ 命令不存在（`command_not_found`）/ 启动即退出（`process_failed`）/ 超时（假 Server 挂起 + 缩短 timeout → `timeout`）/ http 连接失败（未监听端口 → `connection_failed`）/ 协议不兼容（stdout 输出非 MCP 内容 → 按实际 SDK 语义归类，断言 ∈ {protocol_incompatible, process_failed}）/ 测试后进程零残留（psutil 不可用则以子进程对象退出断言 + SDK 上下文退出保证）/ 同 Server 并发测试第二次 400（McpBusyError）/ 停用状态可测试且成功后 enabled 不变（FR-033）/ 修改启动参数后 `config_changed` 且重新测试成功后恢复（SC-009）
- [x] T037 [US6] 前端 `frontend/src/components/mcp/McpToolsModal.vue`：工具列表弹窗——每工具名称 / 用途 / 参数表（名称 / 类型 / 必填 / 说明），可滚动
- [x] T038 [US6/US7] 前端 `McpView.vue` 接通测试交互：「测试」按钮点击 → `testingId` 该行 loading 且禁用测试/编辑/删除（FR-030、Edge Case"删除入口测试中不可用"）→ 完成后以返回 `item` 替换行 + `message` 结果提示（成功含工具数量；失败透出分类 message）；工具数量点击打开 `McpToolsModal`（详情接口拉 tools）
- [x] T039 [US6/US7] 前端 Vitest：`mcp.spec.ts` 追加测试连接状态流转（testingId 置位/复位、结果行替换、失败错误态）

**Checkpoint**: 场景 E、F 人工验证通过；pytest（含真 stdio 集成）/ Vitest 绿。

---

## Phase 7: Polish & 交付门禁（跨故事）

- [x] T040 [US-ALL] `AGENTS.md` §3 目录树 `workspace/` 行注释更新为「文件读写工具授权目录 + Skills 目录（运行时生成，不入库）」（宪法 VI 回写，一行变更）
- [ ] T041 [US-ALL] 按 [quickstart.md](quickstart.md) 场景 A–F 完成人工端到端验证并记录结果（自动化测试已全覆盖对应断言；人工走查留待使用者按指南执行）
- [x] T042 [US-ALL] 全量门禁（AGENTS.md §9）：`backend` 内 `uv run pytest` 全绿 + `uv run pyright` 无错误；`frontend` 内 `npm run build` 零错误 + `npm run test:unit` 全绿；修复所有失败项
- [ ] T043 [US-ALL] 运行 `/speckit-analyze` 跨文档一致性分析并处理发现项（待下一命令执行）

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup（Phase 1）**: 无依赖，立即开始
- **Foundational（Phase 2）**: 依赖 T001；**阻塞全部用户故事**（T002 依赖安装最先，T004 模型 → T005 迁移 → T006/T007 Schema 可并行）
- **Phase 3（Skills 核心）**: 依赖 Foundational；skill_files → skill_service → api → 前端串行推进，前端 T014/T015 可与后端并行
- **Phase 4（ZIP 导入）**: 依赖 Phase 3（复用 skill_service 与页面骨架）
- **Phase 5（MCP 配置）**: 依赖 Foundational，与 Phase 3/4 无耦合（可并行推进）
- **Phase 6（MCP 测试）**: 依赖 Phase 5（复用 mcp_service 与页面）；T032 依赖 T031（假 Server 供集成测试）
- **Phase 7（Polish）**: 依赖全部故事完成

### Within Each Phase

- 文件层（skill_files）/ SDK 层（mcp_client）先行单测，再接服务层与路由
- 服务层 → 路由层 → 前端 api → store → 组件/页面
- 每阶段结束跑一次既有门禁命令，失败即修

### Parallel Opportunities

- T006 / T007（两份 Schema）、T014+T015 / T026+T027（前端 api+store 成对）、T009（skill_files）与 T031（假 Server）等不同文件任务可并行
- Phase 3/4（Skills 线）与 Phase 5/6（MCP 线）两条线互相独立

---

## Notes

- [P] 任务 = 不同文件、无依赖
- 后端新命令一律 `uv run`；前端命令注意 Node 22 PATH（AGENTS.md §5）
- 敏感值断言贯穿 MCP 全部测试：任何响应体文本 `assert 明文 not in body`（SC-005）
- 每个任务或逻辑组一次提交（仓库启用 git 后）
- 停在任何 Checkpoint 验证当前故事独立可用后再前进
