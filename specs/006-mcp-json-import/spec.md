# Feature Specification: MCP 表单 JSON 导入与类型命名修正（第六阶段）

**Feature Branch**: `006-mcp-json-import`

**Created**: 2026-09-11

**Status**: Draft

**Input**: User description: "MCP管理的新增中增加json导入：1. 将MCP-类型中的`本机启动`名称改为`stadio`；2. 当选择`stadio`时增加`json导入`方式（textarea 输入 JSON + `解析json` 按钮导入到对应字段）；3. JSON 格式参考（name/description/transport/enabled/command/args/env）；4. BUG：MCP Server 弹窗点击保存无反应，报错 `[ant-design-vue: Form] model is required for validateFields to work.`"

> 说明：`stadio` 按 `stdio` 笔误处理——JSON 参考示例中 `"transport": "stdio"` 与后端既有枚举均为 `stdio`（宪法 Assumptions 记录该判定，若确需 "stadio" 字样请退回澄清）。
> 本特性为 004 MCP 管理的迭代增强：两项表单交互改进 + 一个前端 BUG 修复，**零后端改动**。

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 修复保存按钮无反应 (Priority: P1)

使用者在 MCP 管理页打开新增/编辑 Server 弹窗，填写合法表单后点击保存，表单正常提交（新增出现列表/编辑刷新列表），不再无反应；校验不通过时，对应字段旁出现错误提示而非静默失败。

**Why this priority**: 这是当前功能缺陷——保存链路完全不可用，JSON 导入（US2）填好字段后同样依赖保存链路生效，必须最先修复。

**Independent Test**: 打开新增弹窗 → 填写合法 stdio 配置 → 点击保存 → 列表出现新 Server；故意留空名称点击保存 → 名称字段旁出现"请输入名称"提示且不提交；编辑既有 Server 改名保存 → 列表同步。

**Acceptance Scenarios**:

1. **Given** 新增弹窗中已填写合法的本机启动（stdio）配置， **When** 点击保存， **Then** 提交成功、弹窗关闭、列表出现该 Server。
2. **Given** 新增弹窗中名称为空， **When** 点击保存， **Then** 不提交，名称字段旁显示校验错误提示。
3. **Given** 编辑弹窗中 url 格式非法（如 `not-a-url`）， **When** 点击保存， **Then** 不提交，url 字段旁显示格式错误提示。
4. **Given** 任一次合法保存， **Then** 控制台不出现 `model is required for validateFields to work` 警告。

---

### User Story 2 - 类型命名修正 (Priority: P1)

新增/编辑表单中的类型选项"本机启动"更名为"stdio"（与业界 MCP 配置的 `transport: stdio` 术语一致），列表页的类型标签同步显示为"stdio"（远程 HTTP 选项文案不变）。改名仅影响展示文案，`server_type` 取值与后端枚举不变。

**Why this priority**: 与 US2 的 JSON 导入直接相关——导入的 JSON 使用 `transport: "stdio"` 术语，界面术语与之对齐后才不产生认知冲突；且改动成本极低。

**Independent Test**: 打开新增弹窗核对类型选项为"stdio / 远程 HTTP"；新增一个 stdio Server 后核对列表标签显示"stdio"。

**Acceptance Scenarios**:

1. **Given** 使用者打开新增/编辑弹窗， **When** 查看类型选项， **Then** 显示"stdio"与"远程 HTTP"两项，不含"本机启动"字样。
2. **Given** 列表中存在 stdio 类型 Server， **When** 查看类型标签， **Then** 显示"stdio"。
3. **Given** 改名前后， **When** 新增/编辑/测试连接， **Then** 行为与改名前完全一致（仅文案变化）。

---

### User Story 3 - stdio 表单的 JSON 导入 (Priority: P1)

表单选择 stdio 类型时，展示"JSON 导入"区域：一个多行文本框与"解析 JSON"按钮。使用者粘贴形如下例的 JSON 后点击按钮，系统解析并把内容填入表单对应字段（名称、描述、启动命令、启动参数、环境变量），随后可继续人工调整并保存。

```json
{
  "name": "filesystem",
  "description": "filesystem",
  "transport": "stdio",
  "enabled": true,
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-filesystem"],
  "env": {}
}
```

解析失败（JSON 非法、`transport` 不是 `stdio`、`args`/`env` 字段类型不符等）时明确提示原因，表单保持原状不被部分填充。`enabled` 字段不参与导入（启用状态由界面开关管理）。导入为覆盖语义：解析成功即用 JSON 值覆盖表单当前对应字段。

**Why this priority**: 本特性的核心增值——使用者可直接粘贴 MCP Server 使用说明里给出的标准配置片段，免于逐字段手工誊抄；依赖 US1 的保存链路与 US2 的术语对齐。

**Independent Test**: 打开新增弹窗选 stdio → 粘贴示例 JSON → 点击"解析 JSON"→ 核对名称/描述/命令/参数/环境变量五个区域被正确填充；分别粘贴非法 JSON、`transport: "http"` 的 JSON、`args` 为字符串的 JSON，核对三者均提示明确原因且表单未被改动；解析后点保存核对链路通畅。

**Acceptance Scenarios**:

1. **Given** 类型选择 stdio， **When** 查看表单， **Then** 存在 JSON 导入区域（多行文本框 + "解析 JSON"按钮）；选择"远程 HTTP"时该区域不展示。
2. **Given** 文本框中粘贴了字段完整的合法 JSON， **When** 点击"解析 JSON"， **Then** 名称、描述、启动命令、启动参数（含顺序）、环境变量被正确填入表单。
3. **Given** JSON 只包含部分字段（如仅 name 与 command）， **When** 解析， **Then** 仅这些字段被填充，其余表单字段保持原值。
4. **Given** 文本框为空或不是合法 JSON， **When** 点击"解析 JSON"， **Then** 提示"JSON 格式不合法"类原因，表单零改动。
5. **Given** JSON 中 `transport` 为 `"http"` 或其他非 `stdio` 值， **When** 解析， **Then** 提示该导入区域仅支持 stdio 配置，表单零改动。
6. **Given** JSON 中 `args` 不是字符串数组（如字符串）或 `env` 值包含非字符串， **When** 解析， **Then** 提示对应字段类型问题，表单零改动。
7. **Given** JSON 中含未知多余字段（如 `icons`）， **When** 解析， **Then** 多余字段被忽略，不报错。

---

### Edge Cases

- 粘贴的 JSON 是数组或字符串（非对象）怎么办？—— 提示"JSON 需为对象"，表单零改动。
- JSON 中 `name` 超过 100 字符怎么办？—— 照常填入，由保存时的既有字段校验拦截（导入不做长度预检，只做类型解析）。
- `env` 的键为空字符串怎么办？—— 解析时跳过该键。
- `args` 含非字符串元素怎么办？—— 提示"启动参数必须为字符串数组"，表单零改动。
- 编辑既有 Server 时使用 JSON 导入怎么办？—— 与新增一致：解析成功覆盖表单字段（掩码占位不受影响——env 键被覆盖为新值，留空仍表示保留原值）。
- 导入后未保存就关闭弹窗怎么办？—— 表单状态丢弃，无持久化影响（与手工填写一致）。
- 环境变量值包含密钥怎么办？—— 粘贴内容仅存在于表单，保存后走既有掩码与密钥库链路，无新增暴露面。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 新增/编辑弹窗的类型选项文案 MUST 由"本机启动"改为"stdio"（"远程 HTTP"不变）；列表页 stdio 类型的标签 MUST 同步显示"stdio"。
- **FR-002**: 改名 MUST 仅影响展示文案：`server_type` 取值、后端枚举、既有行为不变。
- **FR-003**: 类型选择 stdio 时，表单 MUST 提供 JSON 导入区域（多行文本框 + "解析 JSON"按钮）；选择"远程 HTTP"时 MUST NOT 展示。
- **FR-004**: 点击"解析 JSON" MUST 按契约（[contracts/json-import.md](contracts/json-import.md)）解析文本：成功时将 `name`/`description`/`command`/`args`/`env` 填入对应表单字段（覆盖语义，`args` 保序）；`transport` 字段仅接受 `"stdio"`；`enabled` 与未知字段忽略。
- **FR-005**: 解析失败（空输入、非法 JSON、非对象、`transport` 非 stdio、`args` 非字符串数组、`env` 值非字符串且无任何可识别字段等）MUST 给出明确人话原因，且表单 MUST 保持解析前的状态（零部分填充）。
- **FR-006**: 修复保存无反应缺陷：保存 MUST 正常提交合法表单；校验失败 MUST 在对应字段旁显示错误提示；MUST NOT 出现 `model is required for validateFields to work` 警告。
- **FR-007**: 页面配色、字号、布局与交互 MUST 与既有管理页面一致（引用设计令牌）。

### Key Entities

- **MCP JSON 导入格式（契约主定义，[contracts/json-import.md](contracts/json-import.md)）**: stdio 类型配置的对象表达——`name`/`description`/`transport`/`enabled`/`command`/`args`/`env`；仅前端消费，无后端接口变更。
- **表单校验绑定**: 弹窗表单与校验规则的显式关联（缺陷根因即关联缺失），修复后校验按字段生效。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 合法表单保存成功率 100%；校验失败 100% 在对应字段旁提示；`model is required` 警告出现次数为 0。
- **SC-002**: 合法 JSON（完整与部分字段两种）解析后字段填充正确率 100%，`args` 顺序保持；`enabled`/未知字段零误导入。
- **SC-003**: 非法 JSON、非 stdio `transport`、`args`/`env` 类型错误四类输入的拒绝率 100%，每次均有明确原因提示，表单零部分填充。
- **SC-004**: 全部界面文案中"本机启动"出现次数为 0（表单选项与列表标签均为"stdio"）。

## Assumptions

- `stadio` 为 `stdio` 笔误（JSON 示例与后端枚举均为 `stdio`）；如确需 "stadio" 字样需退回澄清。
- JSON 导入为纯前端能力：解析与填表在浏览器内完成，不新增后端接口（保存仍走既有 POST/PUT）。
- `enabled` 字段不参与导入：启用状态语义由界面开关与既有启停接口管理，避免导入隐式改变可用性。
- 导入是显式覆盖动作：不与表单当前值做合并或冲突确认；`env` 覆盖指键值被替换为新值，编辑态"留空保留原值"的三态语义不变。
- 解析仅做类型级校验（字符串/数组/对象），长度与格式校验仍由保存时的既有规则承担。
- 本特性零数据模型变更、零迁移、零新增依赖。
