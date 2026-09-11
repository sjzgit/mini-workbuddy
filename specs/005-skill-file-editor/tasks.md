# Tasks: Skill 目录浏览与文件在线编辑（第五阶段）

**Input**: Design documents from `/specs/005-skill-file-editor/`

**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/skill-files-api.md ✅, quickstart.md ✅

**Tests**: 按 AGENTS.md §9 质量门禁与宪法 IV（验证驱动），测试任务为必做项。

**Organization**: 三个用户故事均 P1 且共用同一批后端基础（文件层三函数 + 三端点），故 Foundational 承载文件层与端点，US1–US3 分别落契约测试与前端组件分区。**零新增依赖、零迁移、零表变更。**

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行（不同文件、无依赖）
- **[Story]**: 归属用户故事（US-ALL = 跨故事共享）

## Path Conventions

Web app 双项目：`backend/`（uv）+ `frontend/`（npm）。后端命令一律在 `backend/` 内 `uv run`；前端命令在 `frontend/` 内执行（Windows 注意 AGENTS.md §5 的 Node 22 PATH 切换）。

---

## Phase 1: Setup（共享基础设施）

- [x] T001 核对根目录 `.gitignore` 已覆盖 `backend/workspace/`（本特性无新增运行时目录；若缺失则补上）

**Checkpoint**: 忽略规则就绪；无依赖安装与迁移任务（零新增依赖、零表变更）。

---

## Phase 2: Foundational（阻塞性前置，全部故事依赖）

**⚠️ CRITICAL**: 本阶段完成前不得开始任何用户故事实现。

- [x] T002 [US-ALL] `backend/app/services/skill_files.py` 追加纯文件函数：`_resolve_skill_file(dir_path, rel_path)`（黑名单：`..`/绝对路径/盘符/空串 + `(dir/rel).resolve().is_relative_to(dir.resolve())` 包含性双重校验，非法抛 `InvalidSkillFilePath`；与 004 ZIP 导入同算法，契约 skill-files-api.md §4）；`list_tree(dir_path)`（递归目录树 → `SkillFileNode` 嵌套结构：目录在前、同类型字典序、文件 children=[]）；`read_text_file(dir_path, rel_path)`（字节数 > `settings.file_max_bytes` → `too_large`；UTF-8 严格解码失败 → `not_text`；返回 `SkillFileData(path/editable/reason/content/size)`，不可编辑时 content 恒 None）；`write_text_file(dir_path, rel_path, content)`（UTF-8 覆盖写 + 写前编码后字节数上限校验；目标必须已存在）
- [x] T003 [US-ALL] `backend/app/schemas/skill.py` 追加：`SkillFileNode`（name/path/type/children 递归）、`SkillFileContent`（path/editable/reason/content/size）、`SkillFileWriteRequest`（path + content，content 允许空串）、`SkillFileSavedResponse`（saved/path）——逐字段对齐 [contracts/skill-files-api.md](contracts/skill-files-api.md) §2
- [x] T004 [US-ALL] `backend/app/services/skill_service.py` 追加编排层：`get_tree(session, dir_name)`（Skill 存在性校验 → `_find` → list_tree）；`read_file(session, dir_name, rel_path)`（路径非法 → `SkillInvalidPathError`、文件不存在 → `SkillFileNotFoundError`）；`write_file(session, dir_name, rel_path, content)`（同上校验 + 写回；目标为 `skill.md` 时刷新 DB 行 `updated_at` 并返回最新 `SkillItem`——FR-012）；`SkillInvalidPathError` / `SkillFileNotFoundError` / `SkillFileTooLargeError` 异常定义
- [x] T005 [US-ALL] `backend/app/api/skills.py` 追加 3 端点：`GET /api/skills/{dir_name}/tree`（200 `SkillFileNode[]`；Skill 404"Skill 不存在"）；`GET /api/skills/{dir_name}/file?path=`（200 `SkillFileContent`——editable=false 是正常查询结果；路径非法 400"非法的文件路径"；文件 404"文件不存在"）；`PUT /api/skills/{dir_name}/file`（200 `SkillFileSavedResponse`；超上限 422 人话提示；错误语义同读）；**路由顺序**：`/refresh`、`/import` 静态段必须保持在前，`/{dir_name}` 动态段在后（避免遮蔽）

**Checkpoint**: 文件层、Schema、服务编排、三端点就绪；`uv run pytest` 既有 240 用例仍绿。

---

## Phase 3: US1 + US2 + US3（P1，详情对话框 + 目录树 + 文件编辑）

> 三个故事共享同一组件（对话框三区）与同一批端点，按分区拆任务；每个故事可独立验证（对应 quickstart 场景 A/B/C/D/E）。

**Goal**: 大对话框详情（基础信息独立保存）+ 左树右编辑区（浏览 + 在线编辑写回）。
**Independent Test**: quickstart.md 场景 A（基础信息）、B（目录树）、C（编辑保存）、D（不可编辑）、E（路径安全）。

### 实现任务

- [x] T006 [P] [US1] 后端测试 `backend/tests/test_skills_api.py` 追加 US1 相关断言：基础信息沿用既有编辑端点（frontmatter 同步已在 004 覆盖），补充树/文件端点与编辑端点的联动——保存 skill.md 后 `GET /api/skills` 列表 `updated_at` 刷新且名称说明随 frontmatter 变化（FR-012，SC-001 后半）
- [x] T007 [US2] 后端测试 `backend/tests/test_skill_files.py` 追加树与读取单测：多级嵌套树结构（目录在前字典序、文件 children=[]）、空目录返回 `[]`、只含 skill.md 的最小树、UTF-8 文本读取、非 UTF-8（写入 `b"\xff\xfe\x00"` 二进制）→ `not_text` 且 content=None、>1MB（monkeypatch `file_max_bytes` 缩小）→ `too_large` 且 content=None（SC-005）
- [x] T008 [US3] 后端测试 `backend/tests/test_skill_files.py` 追加写回单测：正常覆盖写读回一致、空内容清空文件合法、写后字节数超上限拒绝、目标不存在拒绝
- [x] T009 [US2/US3] 后端契约测试 `backend/tests/test_skills_api.py` 追加三端点 HTTP 测试：树端点结构（200 `[]` 空态 / 节点字段完整）；文件读端点（200 editable=true 含内容 / 200 editable=false reason / 400 非法路径 / 404 文件不存在 / 404 Skill 不存在）；文件写端点（200 saved / 422 超上限 / 400 非法路径 / 404）；**路径逃逸专项**（SC-004）：`../secret.txt`、`/etc/hosts`（URL 编码）、`..\\evil.txt`、`C:/Windows/system32` 四形态读与写全部 400，且 Skill 目录外零落盘（写前写后比对上级目录内容）
- [x] T010 [P] [US1/US2/US3] 前端 `frontend/src/api/skills.ts` 追加类型与调用：`SkillFileNode` / `SkillFileContent` / `SkillFileWritePayload` / `SkillFileSavedResponse`（从契约派生，null 不混用 undefined）+ `tree(dirName)` / `readFile(dirName, path)` / `writeFile(dirName, path, content)`（readFile 的 path 需 `encodeURIComponent` 传 query）
- [x] T011 [US1/US2/US3] 前端新组件 `frontend/src/components/skills/SkillDetailModal.vue` 替换 `SkillEditDrawer.vue`（删除旧文件）：**上区**基础信息 Form（名称/描述可编辑 + 「保存基础信息」按钮 → 调既有 `skillsApi.update`；启用 `Switch` → 调 `setEnabled` 即时生效并通知列表；目录名称/更新时间只读文本）；**下区**左 `Tree`（`treeData` 由 `skillsApi.tree` 加载，目录展开/收起、文件选中进入编辑区、顶部刷新按钮）+ 右侧编辑区（`Textarea` 等宽字体可滚动 + 「保存文件」按钮 → `skillsApi.writeFile`；`editable=false` 时显示原因提示并禁用编辑区）；Modal 宽 960 / 高约 80vh / footer 自绘关闭按钮；样式全引用 tokens.scss 变量（FR-013）
- [x] T012 [US1] `frontend/src/views/SkillsView.vue` 切换编辑入口：`openEdit` 打开 `SkillDetailModal`（移除 SkillEditDrawer 引用）；对话框保存基础信息后以返回 `SkillItem` 就地刷新列表行（复用 `store.replaceItem`）；启停事件冒泡刷新列表行
- [x] T013 [P] [US1/US2/US3] 前端 Vitest：`frontend/src/stores/__tests__/skills.spec.ts` 或新组件纯函数测试——树加载态与文件读写 api 封装（mock fetch 层，含 path 编码断言）；可编辑/不可编辑分支渲染逻辑（若抽为纯函数）

**Checkpoint**: quickstart 场景 A–E 人工走查通过；pytest / Vitest 绿。

---

## Phase 4: Polish & 交付门禁（跨故事）

- [ ] T014 按 [quickstart.md](quickstart.md) 场景 A–E 完成人工端到端验证并记录结果（自动化测试已覆盖同等断言；人工走查留待使用者按指南执行）
- [x] T015 全量门禁（AGENTS.md §9）：`backend` 内 `uv run pytest` 全绿 + `uv run pyright` 无错误；`frontend` 内 `npm run build` 零错误 + `npm run test:unit` 全绿；修复所有失败项
- [ ] T016 运行 `/speckit-analyze` 跨文档一致性分析并处理发现项（待下一命令执行）

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup（Phase 1）**: 无依赖
- **Foundational（Phase 2）**: T002 → T003/T004（Schema 可与文件层并行起草，服务层依赖两者）→ T005；**阻塞全部用户故事**
- **Phase 3**: 依赖 Foundational；后端测试（T006–T009）可与前端（T010–T013）并行推进
- **Phase 4**: 依赖全部故事完成

### Within Each Phase

- 文件层（T002）先行单测再接服务层（T004）与路由（T005）——与 004 相同的"纯函数层 → 编排层 → HTTP 层"推进
- 前端 api（T010）→ 组件（T011）→ 页面接线（T012）

### Parallel Opportunities

- T006/T007/T008/T009（不同测试文件或追加区段互不冲突）可并行
- T010（前端 api）与后端测试并行；T013 与 T012 并行
- 后端线（T002–T009）与前端线（T010–T013）在契约冻结后完全并行

---

## Notes

- [P] 任务 = 不同文件、无依赖
- 路径逃逸测试是本特性安全核心（SC-004）：读与写两侧、四类非法形态全覆盖
- `editable=false` 是 200 正常响应而非错误——前端按 reason 渲染提示，禁用编辑区
- 保存 skill.md 与保存其他文件的行为差异（FR-012）必须有独立断言
- 每个任务或逻辑组一次提交（仓库启用 git 后）
