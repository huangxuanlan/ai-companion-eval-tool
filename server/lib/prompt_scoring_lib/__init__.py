"""
prompt_scoring_lib — 6 维打分管道 + 实时打分调度

抽自 services/scoring_service.py + services/live_scoring_dispatcher.py（W0 ADR-005 / 3 人天）

公开 API：
- ScoringService — 打分管道主类（复用 score_excel.py 核心函数）
- invoke_score_turn_compat — 异步打分单轮兼容入口
- LiveScoringDispatcher — 全局 live scoring 调度器（serializes per conversation + global pool limit + dedup）
- LiveScoringJob — dispatcher 任务 dataclass
- PIPELINE_SCRIPTS — pipeline 脚本目录常量

依赖：
- model_adapter_lib（已抽，ADR-005）
- prompt_template_lib（已抽，ADR-005）
- services.task_control（保留在 services/，不抽）
- database 模块

共享对象：长文 / 短文 / 桥接（覆盖所有打分调用路径）
"""

from .service import (
    PIPELINE_SCRIPTS,
    ScoringService,
    invoke_score_turn_compat,
)
from .dispatcher import (
    LiveScoringDispatcher,
    LiveScoringJob,
)

__all__ = [
    "PIPELINE_SCRIPTS",
    "ScoringService",
    "invoke_score_turn_compat",
    "LiveScoringDispatcher",
    "LiveScoringJob",
]
