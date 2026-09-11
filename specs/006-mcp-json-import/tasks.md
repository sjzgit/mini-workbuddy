# Tasks: MCP 表单 JSON 导入与类型命名修正（第六阶段）

**Input**: Design documents from `/specs/006-mcp-json-import/`

**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/json-import.md ✅, quickstart.md ✅

**Tests**: 按 AGENTS.md §9 质量门禁与宪法 IV（验证驱动），测试任务为必做项。

**Organization**: 三个用户故事均 P1。US1（保存修复）是 US3 的前置（导入填好字段后靠保存链路生效），US2（命名）与 US3 的解析纯函数无耦合可并行。**零后端改动、零迁移、零新增依赖。**

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行（不同文件、无依赖）
- **[Story]**: 归属用户故事

## Path Conventions

前端改动集中在 `frontend/`（npm）；后端命令仅在交付门禁复跑时使用（`backend/` 内 `uv run`）。前端命令注意 AGENTS.md §5 的 Node 22 PATH 切换。

---

## Phase 1: Setup（共享基础设施）

- [x] T001 核对 `frontend/src/components/mcp/McpServerFormModal.vue` 当前实现，确认 BUG 现象（`<Form>` 无 `:model`、校验型 `FormItem` 无 `name`、`handleSubmit` 中 `validate()` 静默失败路径）——只读核对，作为修复基线

**Checkpoint**: 基线确认；无依赖/迁移任务。

---

## Phase 2: US1（P1，修复保存无反应）🎯 MVP

**Goal**: 保存链路恢复——合法表单正常提交，校验失败落到字段旁。
**Independent Test**: quickstart.md 场景 A（合法保存出现列表 / 空名称字段旁提示 / 控制台零警告 / url 非法提示）。

### 实现任务

- [x] T002 [US1] 修复 `frontend/src/components/mcp/McpServerFormModal.vue`：①`<Form>` 补 `:model="form"` 绑定（research R1 根因 1）；②带校验规则的 `FormItem` 补 `name` 属性——名称项 `name="name"`、url 项 `name="url"`（根因 2，使"请输入名称"/"url 格式不合法"提示渲染到字段旁）；③`handleSubmit` 保持 `formRef.value?.validate().catch(() => false)` 模式并确认 `valid === false` 时不提交；④核对 radio 类型切换/动态行渲染不受 `:model` 引入影响（form 为 reactive，直接引用即可）
- [ ] T003 [US1] 手动回归验证（开发环境）：quickstart 场景 A 的 5 步全部通过；确认 `model is required` 警告零出现；确认编辑既有 Server（含掩码 env 保留语义）不受影响

**Checkpoint**: 场景 A 全绿后 US3/US2 才可开始（保存链路是导入的前置）。

---

## Phase 3: US2 + US3（P1，类型命名 + JSON 导入）

> US2 纯文案与 US3 纯函数互不耦合，可并行推进；US3 的组件接线依赖 US1 已完成。

**Goal**: 术语对齐（stdio）+ stdio 表单 JSON 导入区（解析契约落地，失败零部分填充）。
**Independent Test**: quickstart.md 场景 B（命名）+ 场景 C（导入七步）。

### 实现任务

- [x] T004 [P] [US3] 创建 `frontend/src/components/mcp/jsonImport.ts`：实现 `parseMcpJson(text): ParseResult` 纯函数——按 [contracts/json-import.md](contracts/json-import.md) §3 顺序（空输入 → JSON.parse → 非对象 → transport 校验 → 五字段类型校验 → 无可识别字段 → 产出 form）；错误文案与契约 §2/§3 逐字一致；导出 `McpJsonImportForm` / `ParseResult` 类型（null 不混用 undefined）
- [x] T005 [P] [US3] 创建 `frontend/src/components/mcp/__tests__/jsonImport.spec.ts`：Vitest 表驱动锁定契约全部分支——完整示例 JSON 五字段填充且 args 保序 / 部分字段仅填出现的 / `enabled:true` 与未知字段（`icons`）忽略 / 空输入、非法 JSON、数组输入、`transport:"http"`、`command:123`、`args:"x"`、`args:[1]`、`env:{k:1}`、零可识别字段九类失败各自 reason 断言 / 空 env 键跳过（SC-002/SC-003）
- [x] T006 [US2] 修改 `frontend/src/components/mcp/McpServerFormModal.vue`：类型 RadioButton 文案"本机启动"→"stdio"（value 不变仍为 `stdio`）；"远程 HTTP"保持；同步检查组件内其他"本机启动"字样（字段指引文案等）一并替换
- [x] T007 [P] [US2] 修改 `frontend/src/views/McpView.vue`：列表类型标签映射 `typeLabel` 的 `stdio: '本机'` → `stdio: 'stdio'`；确认 http 标签"远程"不变
- [x] T008 [US3] 修改 `frontend/src/components/mcp/McpServerFormModal.vue` 接入导入区：stdio 分支（类型 RadioGroup 下方）渲染折叠面板或独立小节——`Textarea`（placeholder 给出契约 §1 示例精简版）+ "解析 JSON"按钮；点击 → `parseMcpJson`：`ok:true` 时将 `name`/`description`/`command` 写回 reactive 表单、`args` 转 `form.args` 字符串数组、`env` 转 KvRow 行数组（`keep:false` 即视为新值），`message.success("已导入 N 个字段")`；`ok:false` 时 `message.warning(reason)` 且表单零改动；http 分支不渲染该区（FR-003~005）

**Checkpoint**: 场景 B、C 人工走查通过；Vitest 绿。

---

## Phase 4: Polish & 交付门禁

- [x] T009 全量门禁（AGENTS.md §9）：`frontend` 内 `npm run build` 零错误 + `npm run test:unit` 全绿（含 jsonImport.spec.ts）；`backend` 内 `uv run pytest` 全绿 + `uv run pyright` 无错误（零改动复跑确认无回归）；修复所有失败项
- [ ] T010 按 [quickstart.md](quickstart.md) 场景 A–C 完成人工端到端验证并记录结果
- [ ] T011 运行 `/speckit-analyze` 跨文档一致性分析并处理发现项（待下一命令执行）

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup（T001）**: 无依赖
- **US1（T002–T003）**: 依赖 T001；**阻塞 US3 组件接线（T008）**——导入填好字段后靠保存链路生效
- **US3 纯函数线（T004–T005）与 US2（T006–T007）**: 无耦合，T001 后即可并行开始
- **Phase 4**: 依赖全部故事完成

### Parallel Opportunities

- T004+T005（纯函数 + 测试）∥ T006/T007（两处文案）∥ T002（组件修复）在 T001 后三者文件互不冲突可并行；仅 T008 必须等 T002 完成
- T007 与 T006 是不同文件，可并行

---

## Notes

- [P] 任务 = 不同文件、无依赖
- 错误文案是契约的一部分（json-import.md §2/§3）：实现与测试共用同一文案，改文案先改契约
- `enabled` 不导入是 spec Assumption 的显式决策，测试须有"忽略"断言防回归
- 修复 `:model` 后注意编辑态掩码 env 的 `keep` 语义不受表单绑定影响（值仍以行数组独立维护）
- 每个任务或逻辑组一次提交（仓库已启用 git）
