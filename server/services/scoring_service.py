"""
ScoringService — backward-compat shim (sys.modules alias)

实际实现已迁移至 server/lib/prompt_scoring_lib/service.py（W0 ADR-005，2026-05-28）。

迁移路径：
- 旧：from services.scoring_service import ScoringService, invoke_score_turn_compat
- 新：from lib.prompt_scoring_lib import ScoringService, invoke_score_turn_compat
"""
import sys as _sys
from lib.prompt_scoring_lib import service as _real_module

_sys.modules[__name__] = _real_module
