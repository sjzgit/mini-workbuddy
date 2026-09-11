# Research: Skill 目录浏览与文件在线编辑（第五阶段）

**Date**: 2026-09-11 | **Status**: Complete

本阶段技术决策记录。本特性是 004 的迭代增强，架构基座（文件为本、密钥库、既有配置）全部沿用；
本文只记录增量决策。无 NEEDS CLARIFICATION 遗留。

---

## R1 端点形态：三个端点挂既有 `/api/skills` 前缀（FR-005/008/009）

**Decision**（契约主定义 [contracts/skill-files-api.md](contracts/skill-files-api.md)）：

| 端点 | 语义 |
|------|------|
| `GET /api/skills/{dir_name}/tree` | 目录树（`SkillFileNode` 递归结构，含目录与文件） |
| `GET /api/skills/{dir_name}/file?path=<相对路径>` | 读文件内容；不可编辑时返回 `editable=false` + 原因（非 JSON 错误，200 语义化响应） |
| `PUT /api/skills/{dir_name}/file` body `{path, content}` | 保存写回（UTF-8，覆盖语义） |

- 文件路径以 **Skill 目录内的相对路径**（POSIX 风格 `/` 分隔）为唯一标识——树返回什么路径，读写就收什么路径，无映射层。
- "不可编辑"（非 UTF-8、超上限）走 **200 + `editable=false` + `reason`** 而非 4xx：这是查询结果的一种正常形态（用户点了树上的二进制文件），不是请求错误；前端据此渲染提示。

**Rationale**: 三个端点与 004 的 Skill 资源是一对一的子资源关系（`/api/skills/{dir_name}/tree|file`），
独立资源前缀会割裂寻址；相对路径贯穿树/读/写，契约自洽。

**Alternatives**:

- *独立前缀 `/api/skill-files`*：资源归属模糊（哪个 Skill 的文件？），路径冗余，否决。
- *单端点 + action 参数*：三个动作的请求/响应结构差异大（树 vs 内容 vs 写回），拆开各自类型清晰，否决。

---

## R2 路径安全：黑名单 + 包含性双重校验（FR-007，SC-004）

**Decision**: `skill_files.py` 新增纯函数 `_resolve_skill_file(dir_path, rel_path) -> Path`：

1. **黑名单**：相对路径含 `..` 片段、以 `/`/`\` 开头（绝对路径）、含盘符（`X:`）→ 直接拒绝。
2. **包含性**：`(dir_path / rel_path).resolve()` 后必须 `is_relative_to(dir_path.resolve())`——
   与 004 ZIP 导入的 `_safe_target` 同一算法（research R7@004），符号链接等解析后逃逸同样被拦。
3. 读取与保存**共用同一函数**——无"只挡写不挡读"的不对称面。
4. 文件必须真实存在于该 Skill 目录内才可读写（不存在 → 404 语义）。

**Rationale**: 与 ZIP 导入同级的安全底线（spec Edge Case 明示）；双重校验互为备份，
黑名单给出精确人话错误，包含性兜底符号链接等解析层逃逸。

**Alternatives**: *仅包含性校验*：能拦但错误信息不精确（分不清"格式非法"与"越界"）；*仅黑名单*：
可被符号链接绕过；*复用 ZIP 的 `_safe_target`*：其锚点是临时根且含 ZIP 特定逻辑，抽出共享函数反而
耦合两条流程，各留一份约 10 行的对称实现更清晰（同一个契约口径、两处消费）。

---

## R3 不可编辑判定与大小上限（FR-010/011）

**Decision**:

- **读取**：`read_bytes` 后按 UTF-8 严格解码——`UnicodeDecodeError` → `editable=false, reason="not_text"`；
  字节数 > `settings.file_max_bytes`（1MB，复用 003 既有配置，**不新建设置项**）→ `editable=false, reason="too_large"`；
  两者都在**进入编辑区之前**判定，不返回内容，杜绝乱码。
- **保存**：内容按 UTF-8 编码写入；写入前校验编码后字节数 ≤ `file_max_bytes`（空内容合法）；
  目标是 skill.md 时触发 DB 行 `updated_at` 刷新并同步列表信息（FR-012——frontmatter 可能被改）。
- 保存路径若不存在（外部删除）→ 404 语义错误；不做自动新建（边界：只编辑现有文件）。

**Rationale**: "先判定、不返回内容"是零乱码的结构性保证；`file_max_bytes` 是 003 已确立的唯一
上限口径（宪法 II：不建第二处定义）。

**Alternatives**: *errors="replace" 宽松解码*：乱码进编辑区、保存即破坏文件，违反 SC-005，否决；
*新设置项 `skill_file_max_bytes`*：与 003 文件工具上限同一业务语义（单文本文件），两处配置必然漂移，否决。

---

## R4 前端形态：单组件大对话框（FR-001~004/013）

**Decision**: 新组件 `SkillDetailModal.vue` 替换 `SkillEditDrawer.vue`（后者删除）：

- **布局**：ant-design-vue `Modal`（宽约 960px、高约 80vh、`footer=null` 自绘底栏）；
  上区 = 基础信息 `Form`（名称/描述可编辑 + 保存按钮；启用 `Switch` 即时生效；目录名/更新时间只读文本）；
  下区 = 左 `Tree`（目录树，`loadData` 惰性可后续启用，首版整树一次加载）+ 右 `Textarea`（等宽字体、可滚动）+ 保存按钮。
- **交互细节**：切换文件前若有未保存修改以页面状态为准丢弃（第一版无脏检查提示，spec Assumption 覆盖写语义的自然延伸）；
  树提供手动刷新按钮；目录节点仅展开收起。
- 列表页编辑入口、对话框打开逻辑与 004 一致（`openEdit` 拉详情后打开）。

**Rationale**: 三区内容纵向 dense，大 Modal 比抽屉更适合"信息 + 双栏工作区"组合（004 research R8
选抽屉是因为只有三字段表单——形态随内容升级）；单组件替换避免新旧两套详情并存造成语义分裂。

**Alternatives**: *保留抽屉仅内嵌树*：抽屉宽度（≤640px 惯例）容不下双栏，否决；*独立路由详情页*：
模态工作流（改完关闭回列表）未被需求要求，多一层路由不值，否决。

---

## 结论

增量决策收敛为：**三个子资源端点 + 相对路径标识**（R1）、**黑名单+包含性双重路径防线**
（R2，与 ZIP 导入同口径）、**先判定不返内容的零乱码语义 + 复用 1MB 上限**（R3）、
**单组件大对话框替换抽屉**（R4）。零依赖、零迁移、零表变更。data-model 与 contracts 据此展开。
