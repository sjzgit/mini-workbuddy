"""评测服务子包（specs/012-agent-evaluation）。

架构约束（Invariants 1/2）：评测是 Agent Runtime 的消费者——
Agent 执行只经 `app.services.agent_runtime.execute_run`，
评测自身不实现第二套 Agent Loop / Tool Calling / Context 构建。
"""

# 异常类从各子模块导出；run_service 相关异常由调用方直接从子模块导入
# （避免循环导入：runner ← __init__ ← run_service）。
from app.services.evaluation.dataset_service import (
    DatasetCaseNotFoundError,
    DatasetNotFoundError,
    DatasetValidationError,
    ImportValidationError,
)
from app.services.evaluation.task_service import (
    TaskNotFoundError,
    TaskValidationError,
)

__all__ = [
    "DatasetCaseNotFoundError",
    "DatasetNotFoundError",
    "DatasetValidationError",
    "ImportValidationError",
    "TaskNotFoundError",
]
