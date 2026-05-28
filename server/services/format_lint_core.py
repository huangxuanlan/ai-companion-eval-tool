"""
Format Lint Core - backward-compat shim (sys.modules alias)

实际实现已迁移至 server/lib/format_lint_lib/core.py (W0 ADR-005).
本次 cd7f186+2 hotfix (2026-05-29) 补齐 D2 抽取遗漏:

修复前: 本文件与 lib/format_lint_lib/core.py 是两份分叉真实代码,
  - services 版 EMOJI_RE 含 U+2700-U+27BF (误判 ❶❷ 序号符为 Emoji)
  - lib 版 EMOJI_RE 已修复 (排除 U+2776-U+2793 序号符区间)
  - 所有调用方 import services.format_lint_core, lib 版变成死代码

修复后: 本文件改为 sys.modules alias shim, 所有访问透明指向 lib 真实代码,
        消除代码分叉, 统一行为, 100% 向后兼容 import / monkeypatch.

迁移路径:
- 旧: from services.format_lint_core import detect_format_leakage, bridge_history, ...
- 新: from lib.format_lint_lib import detect_format_leakage, bridge_history, ...
"""
import sys as _sys
from lib.format_lint_lib import core as _real_module

# 把本模块对象整个替换为 lib 模块, monkeypatch 真的作用到 lib 生产代码
_sys.modules[__name__] = _real_module
