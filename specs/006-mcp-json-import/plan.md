# Implementation Plan: MCP 表单 JSON 导入与类型命名修正（第六阶段）

**Branch**: `006-mcp-json-import` | **Date**: 2026-09-11 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/006-mcp-json-import/spec.md`

## Summary

三项纯前端改动（零后端、零迁移、零新依赖）：① 修复保存无反应缺陷——`McpServerFormModal.vue` 的 `Form` 缺 `:model` 绑定且校验型 `FormItem` 缺 `name` 属性，`validate()` 静默失败导致 `handleSubmit` 直接 return（用户报错 `model is required for validateFields to work` 的根因）；② 类型选项文案"本机启动"→"stdio"（列表 Tag 同步），`server_type` 枚举不变；③ stdio 表单新增 JSON 导入区（textarea + "解析 JSON"按钮），解析逻辑抽为纯函数模块 `jsonImport.ts`（可独立 Vitest 测试），按 [contracts/json-import.md](contracts/json-import.md) 契约填充 `name`/`description`/`command`/`args`/`env` 五个字段，失败给出明确原因且表单零改动。

## Technical Context

**Language/Version**: TypeScript + Vue 3（前端，Node 22）；后端无改动

**Primary Dependencies**: **零新增**。复用 ant-design-vue（Modal/Form/FormItem/Input/Textarea/RadioGroup）、既有设计令牌。

**Storage**: 无变更

**Testing**: 前端 Vitest（`jsonImport.ts` 纯函数全覆盖 + api 封装既有测试保持）；后端无改动（既有 260 用例保持全绿）

**Target Platform**: 本地单机部署，经 Vite 代理联调

**Performance Goals**: 解析 JSON < 10ms（Kb 级文本）；无并发指标

**Constraints**:

- 保存链路修复后：合法表单 100% 提交、校验失败定位字段、`model is required` 警告零出现（SC-001）
- 解析失败表单零部分填充（SC-003）
- 全部界面文案"本机启动"出现 0 次（SC-004）
- `server_type` 取值、后端接口、密钥掩码链路不变

**Scale/Scope**: 2 个前端文件修改 + 2 个新文件（`jsonImport.ts` + 其测试）；无后端文件

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 宪法原则 | 检查项 | 结论 |
|---------|--------|------|
| I. Spec-First | 基于 `spec.md`（2026-09-11 清单 16/16，无 NEEDS CLARIFICATION；`stadio` 按 `stdio` 笔误处理并记录） | ✅ 通过 |
| II. SSOT | JSON 导入格式主定义 → `contracts/json-import.md`（前端消费）；类型文案唯一出处为组件常量；无数据模型变更 | ✅ 通过 |
| III. Contract-First | 解析契约先于编码产出；`jsonImport.ts` 的 ParseResult 与契约逐字段对齐 | ✅ 通过 |
| IV. Verify Before Ship | 交付前四项门禁全绿（后端零改动须复跑确认无回归） | ✅ 通过 |
| V. Simplicity | 纯前端小改动；解析逻辑为纯函数无副作用；`enabled` 忽略不造多余状态 | ✅ 通过 |
| VI. Feedback Loop | 发现规范问题回写契约再同步代码 | ✅ 通过 |
| 固定技术栈 | 无任何选型变化 | ✅ 通过 |
| uv 工作流 | 无新依赖 | ✅ 通过 |
| 数据库约束 | 无 Schema 变更 | ✅ 通过 |
| 前后端联调 | 无新接口；保存走既有 POST/PUT 相对路径 | ✅ 通过 |
| 目录结构 | 新文件归 `frontend/src/components/mcp/`（与表单组件同目录，参照 models/formRules.ts 先例） | ✅ 通过 |
| UI 设计约束 | 复用 antd 组件与 tokens.scss 变量 | ✅ 通过 |
| 质量门禁 | 四项检查排入交付清单 | ✅ 通过 |

**Phase 1 设计后复检**：[research.md](research.md)（R1–R3）已解决全部待决项；[contracts/json-import.md](contracts/json-import.md) 与 spec FR-004/005 一致；无新增违规。**Gate 结论：通过，无需 Complexity Tracking 例外。**

## Project Structure

### Documentation (this feature)

```text
specs/006-mcp-json-import/
├── plan.md                      # 本文件
├── research.md                  # Phase 0：三项决策（BUG 根因/命名口径/解析契约）
├── data-model.md                # Phase 1：零数据模型变更声明
├── quickstart.md                # Phase 1：端到端验证指南
├── contracts/
│   └── json-import.md           # Phase 1：JSON 导入格式主定义（前端消费契约）
└── tasks.md                     # Phase 2（/speckit-tasks）
```

### Source Code (repository root)

```text
frontend/src/
├── components/mcp/
│   ├── McpServerFormModal.vue   # 修改：①Form 绑 :model + 校验型 FormItem 加 name（BUG 修复）
│   │                            #       ②类型文案"本机启动"→"stdio"
│   │                            #       ③stdio 分支新增 JSON 导入区（textarea + 解析按钮）
│   └── jsonImport.ts            # 新增：parseMcpJson(text) 纯函数（契约实现，含 ParseResult 类型）
│   └── __tests__/
│       └── jsonImport.spec.ts   # 新增：解析契约全覆盖（合法/部分字段/非法 JSON/transport/类型错）
└── views/
    └── McpView.vue              # 修改：列表类型标签 stdio → "stdio"（原"本机"）
```

**Structure Decision**: 解析逻辑独立为纯函数模块（与 models/formRules.ts 同一先例），组件只做 UI 编排——保证 SC-003 的"失败零部分填充"可被纯函数级测试锁死；视图层只动两处文案。

## Complexity Tracking

> 无 Constitution Check 违规，无需填写。
