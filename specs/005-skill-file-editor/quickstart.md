# Quickstart: Skill 目录浏览与文件在线编辑（第五阶段）

**Date**: 2026-09-11 | 端到端验证指南。前置契约：[contracts/skill-files-api.md](contracts/skill-files-api.md)；数据模型：[data-model.md](data-model.md)（零迁移）。

## 前置准备

```bash
# 后端（backend/ 内；无新依赖、无迁移，直接启动）
uv run uvicorn app.main:app --reload --port 8218

# 前端（frontend/ 内，新终端）
cd ../frontend && npm run dev
```

需要先有至少一个 Skill（可在 `backend/workspace/skills/` 下手工建目录含 `skill.md`，或用 004 的导入功能）。

## 验证场景

### A. 详情大对话框与基础信息（US1）

1. Skills 列表点击「编辑」→ 打开**大对话框**（非右侧抽屉）：上方为基础信息区（名称/描述可编辑、启用开关、目录名称与更新时间只读），下方为左树右编辑区工作区。
2. 修改名称与描述 → 点击「保存基础信息」→ 用文本编辑器打开 `skill.md` 核对 frontmatter 已更新；列表中名称、说明、更新时间同步刷新（SC-001）。
3. 在对话框内切换启用开关 → 列表状态同步。

### B. 目录树浏览（US2）

1. 在该 Skill 目录下手工构造多级结构，例如：

   ```
   workspace/skills/demo/
   ├── skill.md
   ├── scripts/
   │   └── run.py
   └── notes.txt
   ```

2. 对话框内点击树的「刷新」→ 左侧树形与磁盘结构一致（目录在前、字典序，SC-002）。
3. 点击 `scripts/run.py` → 右侧显示其路径与内容；点击 `scripts/` 目录 → 仅展开/收起，不进编辑区。
4. 空子目录展示为无子节点的目录节点；只有 `skill.md` 时树不空白、不报错。

### C. 文件在线编辑（US3）

1. 点击 `notes.txt` → 修改内容 → 「保存」→ 提示成功；用文本编辑器核对磁盘内容一致（SC-003）。
2. 关闭对话框重新打开 → 再次点击该文件 → 内容为已保存版本（文件为本，无缓存漂移）。
3. 点击 `skill.md` 编辑正文（不动 frontmatter）→ 保存 → 列表更新时间刷新、名称说明不变（FR-012）。
4. 将 `skill.md` 的 frontmatter 名称改掉并保存 → 列表名称同步变化（文件为本的兜底链路）。
5. 清空文件内容保存 → 合法（文件变空文件）。

### D. 不可编辑文件（SC-005）

1. 复制一个二进制文件（如任意 `.png`）进该 Skill 目录 → 刷新树 → 点击它 → 明确提示「不是可编辑的文本文件」，右侧无乱码内容。
2. 构造 >1MB 的文本文件（如 `big.txt`）→ 点击 → 明确提示超过大小上限、不可编辑。

### E. 路径安全（SC-004，可用接口直接验证）

```bash
# 以下请求应全部被拒绝（400），且 Skill 目录外无任何文件被读/写：
curl "http://127.0.0.1:8218/api/skills/demo/file?path=../secret.txt"
curl "http://127.0.0.1:8218/api/skills/demo/file?path=%2Fetc%2Fhosts"        # /etc/hosts
curl -X PUT http://127.0.0.1:8218/api/skills/demo/file \
  -H "Content-Type: application/json" \
  -d '{"path": "..\\evil.txt", "content": "boom"}'
```

- 三类形态（`..`、绝对路径、盘符/反斜杠）均返回 400「非法的文件路径」；核对上级目录无 `secret.txt`/`evil.txt` 落盘。
- 不存在的文件：`path=no-such.txt` → 404「文件不存在」。

## 自动化门禁（交付前必须全绿，AGENTS.md §9）

```bash
# backend/ 内
uv run pytest && uv run pyright
# frontend/ 内
npm run build && npm run test:unit
```
