# Research: Agent 管理（第七阶段）

**Date**: 2026-09-11 | **Feature**: [spec.md](./spec.md)

本文档解决 Phase 0 的全部技术未知项。技术栈已由宪法固定，无需选型研究；研究焦点是"在既有代码库模式上如何落地"。

## R1. Agent 与绑定的数据建模

**Decision**: 三张新表——`agents`（主配置）、`agent_bindings`（通表，`resource_type` 判别字段）、`agent_prompt_versions`（版本快照）。不建 agent_loop / 会话 / 运行记录表。

**Rationale**:
- 工具、Skills、MCP 绑定字段完全同构（仅引用对象不同），单表 + `resource_type`（`tool` / `skill` / `mcp`）+ `resource_id` 比 3 张表少 2/3 的迁移与 service 代码（宪法 V 简洁务实）。
- 绑定需要独立表而非 JSON 列：引用保护（US6）要求"反查哪个 Agent 引用了某资源"，SQL 查询比 JSON 遍历可靠且可加外键。
- 版本表独立：版本号只随提示词内容变化递增（FR-018~020），与主表更新解耦；`agent_id + version` 唯一。

**Alternatives considered**:
- 每资源一张绑定表（agent_tool_bindings × 3）：字段重复，反查要 UNION 三表，放弃。
- 绑定存 JSON 列在 agents 表上：无法外键约束，资源删除时反查脆弱，放弃。
- 提示词只存最新版 + 历史另存：两处状态易漂移，直接以"版本表为正文、主表冗余最新内容"落库，最新内容冗余在 `agents.system_prompt` 便于列表/详情直读。

## R2. 至多一个默认 Agent 的一致性

**Decision**: 复用模型管理的成熟模式——SQLite 部分唯一索引 `uq_agents_single_default`（`sqlite_where=text("is_default = 1")`），数据库层兜底；service 层"先取消旧默认，再设置新默认"并在同一事务内完成。

**Rationale**: 既有 `ModelEntry.uq_models_single_default`（specs/002 research R2）已验证该方案在 SQLite 下可靠；删除/切换全部走 service 事务，测试覆盖"至多一个默认"不变式。

**Alternatives considered**: 仅应用层保证（并发/异常路径可能双默认），放弃；触发器（SQLite 触发器难调试、迁移负担），放弃。

## R3. 删除默认 Agent 的"先选新默认"交互契约

**Decision**: 后端 `DELETE /api/agents/{id}?new_default_id=` 可选参数（与模型管理 `DELETE /api/models/{id}?new_default_id=` 同构）。删除默认 Agent 且还有其他 Agent 时：若 `new_default_id` 缺失，返回 `409` + `detail` 人话提示 + `requires_new_default: true`（响应体），并附剩余 Agent 简表；前端弹窗让用户选定后再带参重发。

**Rationale**: 保持与 002 阶段删除默认模型完全一致的 API 形态，前端交互模式可复用；409 语义为"业务状态冲突，需补充决策"。

**Alternatives considered**: 两个接口（先查可选项再删）：多一次往返，放弃；自动随机指定新默认：违反 FR-024（必须用户选择），放弃。

## R4. 资源引用保护接入点

**Decision**: 新建 `services/agent_references.py` 提供 `assert_not_referenced_by_agent(session, resource_type, resource_id, display_name)`，抛 `ReferencedByAgentError(agents=[...])`；在以下既有 service/API 链路的最前端接入：
- 模型删除：`model_service.delete_model`（先于既有默认切换规则，FR-029）
- Skill 删除：`skill_service.delete_skill`（先于删目录动作）
- MCP Server 删除：`mcp_service` 删除分支（先于清理 secrets 指针）

API 层统一映射 `ReferencedByAgentError → 409`，detail 形如 `「xxx」正被 Agent「A」「B」使用，请先在对应 Agent 中移除后重试`。内置工具本无删除接口，无需改动（FR-028）。

**Rationale**: 检查收敛在一个模块，三处复用；409 与 R3 一致；服务端执行满足 FR-027（绕过前端同样被拒）。

**Alternatives considered**: 前端禁用按钮 + 后端不查：违反 FR-027，放弃；数据库外键 RESTRICT：SQLite 外键默认关闭且无法给出"哪些 Agent 在用"的人话提示，仅作兜底外键仍保留。

## R5. 提示词版本生成规则

**Decision**: 保存时判定规则收敛在 `agent_service.save_agent`：
1. 新建 → 插入版本 1；
2. 编辑 → 比较 `payload.system_prompt` 与该 Agent 当前最新版本内容：
   - 不同 → 新版本号 = max(version) + 1，插入新行；相同 → 不动版本表；
3. 版本表永不 UPDATE / DELETE（只追加），主表 `system_prompt` 冗余最新内容。

**Rationale**: 与 FR-018~020 逐条对应；"以版本表为唯一历史真相，主表只是最新快照"避免两处历史逻辑。

**Alternatives considered**: 前端传 `version_bump` 标志由前端决定：信任边界错误，放弃；按修改时间+内容 hash 判定：内容直接比较已足够（SQLite 本地，无性能压力）。

## R6. 已停用能力的绑定表现

**Decision**: `agent_bindings` 不冗余 `enabled` 快照；停用状态在读取时实时 join 资源表计算：候选项列表只出启用的资源，已绑定资源 join 后 `enabled = false` 的在响应中标 `enabled: false`（前端标"已停用，不可用"），可手动移除、可随保存保留。绑定数量统计 = `COUNT(agent_bindings)` 不滤停用（FR-006/US5）。

**Rationale**: 不冗余就没有快照过期问题（资源恢复启用后自动恢复可用，无需迁移绑定数据）；统计口径规则简单直读。

**Alternatives considered**: 绑定时快照 enabled：需定义"资源恢复启用后绑定是否自动恢复"等衍生规则，复杂度更高，放弃。

## R7. 前端页面结构与既有模式对齐

**Decision**:
- `AgentsView.vue` 重写为卡片列表（ant-design-vue `a-card` 网格 + 空状态 `a-empty`），操作沿用既有视图的 message/modal 交互风格。
- 详情用 `a-modal` 全屏（`width: 100%` + 无边距）实现"全屏 dialog"，三列布局用 CSS grid（列宽约 `1fr 1fr 1fr`，提示词列铺满高度）。
- 能力多选用自绘卡片 + `a-checkbox`（`ResourceSelectCards.vue` 三类复用），而非 `a-select`——契约要求展示名称+用途说明的卡片形态（FR-013）。
- 新建与编辑共用 `AgentDetailDialog.vue`（受控打开，`mode: create | edit`）。
- Pinia `stores/agents.ts` 管列表与加载态；dialog 内部表单态组件自持（与既有 stores 边界一致）。

**Rationale**: McpView / ModelsView 已建立"视图直接调 store、样式引用 tokens 变量"的既定模式；全屏 modal 是 antd 支持良好的形态，无需新依赖。

**Alternatives considered**: 新路由页承载详情：用户要求 dialog 形态且列表上下文不丢失，放弃；`a-select` mode="multiple"：无法承载"卡片 + 用途说明 + 停用标记"，放弃。

## R8. 无模型引导

**Decision**: 打开新建 dialog 时拉取模型列表：为空则模型选择区渲染引导卡（"还没有可用模型，请先前往模型管理添加" + 跳转按钮 `router.push('/models')`），其余区域照常可填；保存校验（模型必选）由后端 422 兜底。

**Rationale**: FR-014 要求明确提示 + 入口；后端校验兜底符合"引用检查/校验在服务端"的一贯原则。

## R9. 测试策略

**Decision**:
- 后端 pytest：
  - `tests/test_agents_api.py`：契约级（列表/详情/新建/编辑/删除/设默认/校验 422/409 流），重点覆盖版本规则（FR-018~020）、默认唯一性、删除默认需 new_default_id 流程、绑定含停用资源的读取表现。
  - `tests/test_agent_references.py`：三资源删除保护（含"删除默认模型先查引用"顺序、绕过前端直发请求被拒）。
- 前端 Vitest：stores/agents（加载/保存动作）+ ResourceSelectCards（多选/停用标记渲染）组件测试。
- 手动验收走 quickstart.md。

**Rationale**: 与 002/003/004 阶段测试粒度一致，契约测试为主、组件测试轻量。

## R10. 契约字段命名与枚举

**Decision**: 常量主定义落在 `contracts/agents-api.md`：
- `resource_type`: `tool` | `skill` | `mcp`
- `max_rounds`: 正整数，默认 10，范围 1~100
- 卡片能力条目展示上限：3（纯前端展示规则，+N = 总绑定数 − 3）
- 错误响应遵循全局约定 `{"detail": "..."}`，业务冲突 409 / 校验失败 422 / 不存在 404

**Rationale**: 宪法 III 要求枚举先入 contracts，实现侧只消费。
