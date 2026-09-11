# Research: MCP 表单 JSON 导入与类型命名修正（第六阶段）

**Date**: 2026-09-11 | **Status**: Complete

三项增量决策。无 NEEDS CLARIFICATION 遗留。

---

## R1 保存无反应缺陷根因（US1，FR-006）

**Decision**: `McpServerFormModal.vue` 修复两处关联缺失：

1. `<Form>` 缺 `:model="form"` 绑定——ant-design-vue 的 `validate()`/`validateFields` 需要从
   `model` 读取数据，缺失即抛 `model is required for validateFields to work` 且校验静默失败。
2. 带校验规则的 `FormItem` 缺 `name` 属性——规则无处挂靠，字段级错误提示无法渲染到对应控件旁。

修复后 `handleSubmit` 中 `formRef.value?.validate()` 正常走通：校验通过 → 提交；失败 → antd
自动在对应 `FormItem` 下方渲染 `message`（既有规则文案："请输入名称"等），无需手工处理错误分支。

同时为"保存基础信息/保存文件"之外的表单校验铺平：url 规则项补 `name: 'url'` 使非法 url 提示落到字段旁（spec US1 验收 3）。

**Rationale**: 用户报错信息直指根因；两处是同一类"声明式校验的绑定缺失"，一起修复并在验收里以
警告零出现（SC-001）锁死回归。

**Alternatives**: *绕开 Form 校验、handleSubmit 手写 if 判断*：失去字段级提示与 antd 统一交互，
且掩盖根因，否决。

---

## R2 类型命名口径（US2，FR-001/002）

**Decision**: 展示文案统一为 **"stdio"**（小写原文）：表单 RadioButton"本机启动"→"stdio"，
列表类型 Tag"本机"→"stdio"；"远程 HTTP"保持不变。`server_type` 取值（`"stdio"`）与后端枚举不动。

> 用户输入写作 `stadio`，但 JSON 参考示例为 `"transport": "stdio"`、后端枚举亦为 `stdio`——
> 按 `stdio` 笔误处理（spec Assumptions 已记录）；文案采用与传输协议一致的原文 `stdio`。

**Rationale**: 与业界 MCP 配置（用户给的 JSON 即 `transport: "stdio"`）术语对齐，US3 导入填充后
认知零冲突；纯文案替换零风险。

**Alternatives**: *保留"本机启动"在括号里（"stdio（本机启动）"）*：JSON 里没有这个概念，加长
文案无增益；*"stadio" 原样上屏*：拼写错误进入产品文案，否决。

---

## R3 JSON 导入：纯函数解析契约（US3，FR-004/005）

**Decision**: 新增 `components/mcp/jsonImport.ts`：

```ts
parseMcpJson(text: string): ParseResult
// ParseResult = { ok: true, form: {name?, description?, command?, args?, env?} }
//              | { ok: false, reason: string }   // 人话原因
```

解析规则（主定义 [contracts/json-import.md](contracts/json-import.md)）：

1. 空输入 / `JSON.parse` 失败 → `JSON 格式不合法…`；解析结果非普通对象 → `JSON 需为对象`。
2. `transport` 存在且 !== `"stdio"` → `仅支持 stdio…`。
3. 字段映射：`name`/`description`/`command` 为字符串时采用；`args` 为字符串数组时采用（保序）；
   `env` 为"值均为字符串的对象"时采用（空串键跳过）；`enabled` 与未知字段忽略。
4. **先整体校验后产出**：任何字段类型不符 → `ok:false` 且不返回 `form`——调用方零部分填充（SC-003）。
5. 至少一个可识别字段都没有 → `未找到可导入的字段…`。
6. 组件侧：解析成功把 `form` 写回 `reactive` 表单（`args`/`env` 转动态行数组），提示成功；
   失败 `message.warning(reason)`，表单不动。

**Rationale**: 纯函数使 SC-002/SC-003 的每个分支（完整/部分字段/非法 JSON/非 stdio/类型错）
都能以 Vitest 表驱动锁定，组件层只剩"写入表单"这一个副作用；"整体校验后产出"让零部分填充成为
结构性保证而非小心约定的产物。

**Alternatives**: *解析逻辑内联在组件里*：不可单测、分支藏进 UI 代码；*后端新增解析接口*：纯
前端能力无后端消费方（宪法 V），且引入网络往返不值得；*逐字段容错（能填多少填多少）*：部分填充
让使用者难判断哪些生效了，违反 SC-003，否决。

---

## 结论

R1 定位并修复缺陷根因（`:model` + `name` 绑定），R2 统一术语为 `stdio`，R3 以纯函数 + 契约
落地 JSON 导入。零后端、零迁移、零依赖。contracts/quickstart 据此展开。
