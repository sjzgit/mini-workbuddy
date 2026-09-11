# Implementation Plan: Skill 目录浏览与文件在线编辑（第五阶段）

**Branch**: `005-skill-file-editor` | **Date**: 2026-09-11 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/005-skill-file-editor/spec.md`

> 说明：本特性是 004 Skills 管理的迭代增强。仓库尚未启用 git，Branch 字段沿用 feature 目录名（与前几阶段一致）。

## Summary

将 Skills 详情从右侧抽屉升级为大对话框（上：基础信息区——名称/描述可编辑并单独保存、启用状态可切换、目录名与更新时间只读；下：左侧 Skill 目录树 + 右侧 textarea 在线编辑区）。后端在 004 的文件层（`skill_files.py`）上新增三个纯文件能力：目录树扫描（含子目录层级）、单文件读取（UTF-8 + 大小上限校验，不可编辑时给明原因）、单文件写回；服务层经既有 `skill_files` 的目录名/路径校验与 ZIP 导入同款的**包含性校验**杜绝路径逃逸（读取与保存同等拦截）；HTTP 层新增 3 个端点挂到既有 `/api/skills` 前缀。前端以 `SkillDetailModal.vue` 替换 `SkillEditDrawer.vue`（ant-design-vue Modal 宽幅 + Tree + Textarea），api/store 类型随契约扩展。**零新增依赖、零数据模型变更、零迁移**——skills 表与既有配置（`file_max_bytes` 等）全部复用。

## Technical Context

**Language/Version**: Python 3.12（后端，uv 管理）/ TypeScript + Vue 3（前端，Node 22）

**Primary Dependencies**: **零新增**。后端复用 FastAPI、Pydantic、SQLAlchemy、pathlib/zipfile 同代的标准库能力；前端复用 ant-design-vue（Modal/Tree/Textarea/Switch）、Pinia、既有设计令牌。

**Storage**: **无数据模型变更**——skills 表结构与 `workspace/skills/` 文件约定不变；文件树与文件内容实时读磁盘（文件为本，research R1@004 延续）。

**Testing**: 后端 pytest（契约测试 + 路径逃逸/编码/上限单测）；前端 Vitest（store 与纯函数）

**Target Platform**: 本地单机部署（Windows 开发机），前后端经 Vite 代理联调

**Performance Goals**: 目录树与单文件加载 < 500ms（本地磁盘 IO，量级为单 Skill 目录内文件）；无并发指标

**Constraints**:

- 路径逃逸 100% 拒绝：读取与保存同等校验（`..`、绝对路径、盘符形态），SC-004
- 非 UTF-8 与超 1MB 文件 100% 明确提示不可编辑、零乱码（SC-005）
- 保存 skill.md 后列表信息与更新时间同步刷新（FR-012）；保存其他文件不动列表
- 编辑语义为"页面为准直接覆盖"（spec Assumption），无冲突检测
- UI 引用 tokens.scss 设计令牌，与既有管理页一致（FR-013）

**Scale/Scope**: 后端 3 个新端点 + 文件层 3 个新函数；前端 1 个组件重构（抽屉 → 对话框）+ api/store 扩展；测试新增约 20 个用例

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 宪法原则 | 检查项 | 结论 |
|---------|--------|------|
| I. Spec-First | 本 plan 基于 `spec.md`（2026-09-11 质量检查清单 16/16 通过，无 NEEDS CLARIFICATION；用户跳过 specify 命令，spec 由本次按其输入补齐并记录） | ✅ 通过 |
| II. SSOT | 文件树/文件内容契约 → `contracts/skill-files-api.md`；文件层实现消费既有 `skill_files.py`（同一文件读写入口的扩展）；配置常量复用 `file_max_bytes`（不新建第二处定义）；UI 令牌 → `tokens.scss`；无数据模型变更故 data-model 仅作"无变更"声明 | ✅ 通过 |
| III. Contract-First | 契约先于编码产出；`schemas/skill.py` 扩展与契约逐字段对齐；前端类型从契约派生；路径沿用 `/api/skills` 经 Vite 代理 | ✅ 通过 |
| IV. Verify Before Ship | 交付前 `uv run pytest`、`uv run pyright`、`npm run build`、`npm run test:unit` 全绿 | ✅ 通过（流程排入交付门禁） |
| V. Simplicity | 零新增依赖、零迁移、无新表；不做新建/删除/上传文件（spec 明确出边界，YAGNI）；树不做轮询只做手动刷新 | ✅ 通过 |
| VI. Feedback Loop | 实现中发现规范问题回写契约再同步代码 | ✅ 通过 |
| 固定技术栈 | 无任何选型变化 | ✅ 通过 |
| uv 工作流 | 无新依赖；命令一律 `uv run` | ✅ 通过 |
| 数据库约束 | 无 Schema 变更（skills 表沿用）；文件为本的内容不入库（004 既定架构） | ✅ 通过 |
| 前后端联调 | 前端只请求相对路径 `/api`（复用 `request.ts`） | ✅ 通过 |
| 目录结构 | 后端扩展 services/skill_files.py + skill_service.py + api/skills.py（各归其位）；前端组件重构放 components/skills/ | ✅ 通过 |
| UI 设计约束 | Modal/Tree/Textarea/Switch 复用 antd；引用 tokens.scss 变量；字号符合规格 | ✅ 通过 |
| 质量门禁 | 四项检查命令排入交付清单 | ✅ 通过 |

**Phase 1 设计后复检**：[research.md](research.md)（R1–R4）已解决全部待决项；[contracts/skill-files-api.md](contracts/skill-files-api.md) 与 004 [skills-api.md](../004-skills-mcp-management/contracts/skills-api.md) 同口径（路径安全、UTF-8、上限）；无新增违规。**Gate 结论：通过，无需 Complexity Tracking 例外。**

## Project Structure

### Documentation (this feature)

```text
specs/005-skill-file-editor/
├── plan.md                      # 本文件（/speckit-plan 输出）
├── research.md                  # Phase 0 输出：四项技术决策（端点形态/路径安全/不可编辑语义/前端形态）
├── data-model.md                # Phase 1 输出：无数据模型变更声明 + 文件节点/内容结构
├── quickstart.md                # Phase 1 输出：端到端验证指南
├── contracts/
│   └── skill-files-api.md       # Phase 1 输出：目录树/文件读/文件写三端点契约（主定义）
└── tasks.md                     # Phase 2 输出（/speckit-tasks）
```

### Source Code (repository root)

```text
backend/
├── app/
│   ├── api/
│   │   └── skills.py            # 追加 3 端点：GET /tree、GET /file、PUT /file
│   ├── schemas/
│   │   └── skill.py             # 追加 SkillFileNode/SkillFileTree/SkillFileContent/
│   │                            #   SkillFileWriteRequest（契约实现）
│   ├── services/
│   │   ├── skill_files.py       # 追加 list_tree/read_text_file/write_text_file
│   │   │                        #   （纯文件层：包含性校验 + 编码/上限判定）
│   │   └── skill_service.py     # 追加 get_tree/read_file/write_file 编排
│   │                            #   （含 skill.md 保存后同步 DB 行）
│   └── main.py                  # 无变更（路由已在 004 注册）
└── tests/
    ├── test_skill_files.py      # 追加：树扫描/读/写单测 + 越界/编码/上限拒绝
    └── test_skills_api.py       # 追加：三端点契约测试（含 SC-004/SC-005 断言）

frontend/src/
├── api/
│   └── skills.ts                # 追加树/读/写类型与调用（从契约派生）
├── stores/
│   └── skills.ts                # 追加树缓存与文件内容状态（按需）
├── views/
│   └── SkillsView.vue           # 编辑入口从抽屉切换为详情对话框
└── components/
    └── skills/
        └── SkillDetailModal.vue # 新组件：大对话框（基础信息区 + 左树右编辑区）
                                  #   （替换 SkillEditDrawer.vue，后者删除）
```

**Structure Decision**: 沿用 004 既定分层——文件能力全部落在 `skill_files.py`（纯文件、可独立单测），服务层只做编排与 DB 同步，路由层薄；前端以单组件 `SkillDetailModal.vue` 承载三区布局（基础信息表单 + Tree + Textarea），替换并删除 `SkillEditDrawer.vue`，避免两套详情形态并存。

## Complexity Tracking

> 无 Constitution Check 违规，无需填写。
