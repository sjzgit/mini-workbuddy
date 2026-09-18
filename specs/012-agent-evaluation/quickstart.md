# Quickstart: Agent 评测系统端到端验证（specs/012-agent-evaluation）

> **验证状态（2026-09-17 实现完成时）**：
> - `uv run pytest`（全量 452 项）✅ 全绿；`uv run pyright` ✅ 0 错误
> - `npm run build` ✅ 零错误；`npm run test:unit`（141 项）✅ 全绿
> - 端到端链路（§2 的自动化等价）：`PYTHONIOENCODING=utf-8 uv run python tests/e2e_manual_check.py` ✅ 10/10 通过
>   （覆盖：数据集创建/导入/非法拒绝 → 任务快照固化与改名不变 → 评测执行/失败隔离/聚合 → Case 明细 → 重试保留历史 → 取消 → 重启恢复 → 导出）
> - 真实 LLM 全链路（含 AgentRun 轨迹下钻抽屉）待用户按 §2 步骤在开发环境人工走查

> 实现完成后的验证指南。前置：后端依赖已 `uv sync`；测试/构建命令见 `AGENTS.md §5/§9`。

## 1. 自动化验证

```bash
# 后端（backend/ 内）
uv run alembic upgrade head        # 应用评测表迁移
uv run pytest tests/test_evaluation_dataset.py \
             tests/test_evaluation_task.py \
             tests/test_evaluation_runner.py \
             tests/test_evaluation_evaluator.py \
             tests/test_evaluation_recovery.py -v
uv run pyright

# 前端（frontend/ 内，Windows 先切换 node 22，见 AGENTS.md §5）
npm run build
npm run test:unit
```

预期：pytest 全绿（覆盖数据集校验/快照固化/失败隔离/评分重试/聚合口径/重启恢复/重试保留历史）；前端构建零错误、Vitest 全绿。

## 2. 手工端到端链路（spec SC-001）

1. 启动后端：`uv run python start_dev.py`（backend/）；前端：`npm run dev`（frontend/）
2. 打开「Agent 评测」页 → **数据集** Tab：创建数据集「客服评测集」，录入或导入 ≥5 个 Case（可用下方示例 JSON）
3. **任务** Tab：创建评测任务——选择已有 Agent、上述数据集、评分器 `llm_judge`（选一个已配置模型）或 `exact_match`，通过阈值 80 → 确认详情可见三类快照
4. 发起评测 → **运行** Tab：观察进度推进（总数/已完成/通过/失败）
5. 打开运行详情：核对汇总指标（平均分/通过率/Token/时长/工具调用）；打开某 Case 明细：核对问题/参考答案/实际回答/分数/理由/行为指标
6. 点击 Case 明细的「查看 Agent 运行」→ 跳转运行记录页并打开对应 AgentRun 抽屉（消息、工具调用、载荷）
7. 控制验证：运行中点「暂停」→ 当前 Case 完成后停止；「恢复」→ 继续；「取消」→ 运行终止
8. 重试验证：对失败 Case 点「重试」→ 出现 attempt=2 的新 CaseRun，原记录保留
9. 恢复验证：运行进行中重启后端 → 运行状态变为「已中断」，无残留「运行中」

## 3. 示例导入 JSON

```json
{
  "name": "客服评测集",
  "description": "客服 Agent 基础评测",
  "cases": [
    {
      "user_question": "如何申请退款？",
      "expected_answer": "在订单详情页点击申请退款，填写原因后提交，1-3 个工作日到账。",
      "scoring_criteria": "回答必须包含退款入口位置与到账时间"
    },
    {
      "user_question": "1+1 等于几？只回答数字。",
      "expected_answer": "2",
      "scoring_criteria": null
    }
  ]
}
```

## 4. 可复现性抽查（SC-004）

创建任务后：修改被测 Agent 的系统提示词、编辑数据集 Case 文本 → 重新查看任务详情与历史运行：快照内容与历史评测分数/Case 文本保持不变；再次发起运行时数据集按快照 Case 执行。
