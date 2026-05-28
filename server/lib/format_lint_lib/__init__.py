"""
format_lint_lib — 格式 lint 与跨模式历史桥接

抽自 services/format_lint_core.py（W0 ADR-005 / 1.5 人天）

公开 API：
- calc_ngram_overlap(prev, curr, n=4) — 4-gram 重叠率（桥接 PRD §10.3.1）
- count_cjk_chars(text) — 中文字符数（CJK 字数检测）
- count_paren_pairs(text) — 全角圆括号配对数
- detect_format_leakage(text, target_mode) — 5 维硬约束（桥接 PRD §10.3.2）
- bridge_history(full_history, target_mode, max_turns) — 三明治异质隔离

共享对象：桥接（主用）+ 长文 / 短文（可选）+ 3 个 verify_*.py 脚本
"""

from .core import (
    EMOJI_RE,
    TEMPLATE_LEAK_PATTERNS,
    bridge_history,
    calc_ngram_overlap,
    count_cjk_chars,
    count_paren_pairs,
    detect_format_leakage,
)

__all__ = [
    "EMOJI_RE",
    "TEMPLATE_LEAK_PATTERNS",
    "bridge_history",
    "calc_ngram_overlap",
    "count_cjk_chars",
    "count_paren_pairs",
    "detect_format_leakage",
]
