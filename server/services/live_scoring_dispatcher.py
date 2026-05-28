"""
LiveScoringDispatcher — backward-compat shim (sys.modules alias)

实际实现已迁移至 server/lib/prompt_scoring_lib/dispatcher.py（W0 ADR-005，2026-05-28）。

迁移路径：
- 旧：from services.live_scoring_dispatcher import LiveScoringDispatcher, LiveScoringJob
- 新：from lib.prompt_scoring_lib import LiveScoringDispatcher, LiveScoringJob
"""
import sys as _sys
from lib.prompt_scoring_lib import dispatcher as _real_module

_sys.modules[__name__] = _real_module
