"""
PromptService — backward-compat shim (sys.modules alias)

实际实现已迁移至 server/lib/prompt_template_lib/service.py（W0 ADR-005，2026-05-28）。

迁移路径：
- 旧：from services.prompt_service import PromptService
- 新：from lib.prompt_template_lib import PromptService
"""
import sys as _sys
from lib.prompt_template_lib import service as _real_module

_sys.modules[__name__] = _real_module
