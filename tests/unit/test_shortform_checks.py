from __future__ import annotations

import pytest
from services.format_lint_core import (
    calc_ngram_overlap,
    detect_format_leakage,
    bridge_history,
)
from services.message_assembler import (
    SHORTFORM_HISTORY_PREFIX,
    SHORTFORM_HISTORY_SUFFIX,
    LONGFORM_HISTORY_PREFIX,
    LONGFORM_HISTORY_SUFFIX,
)


def test_calc_ngram_overlap():
    prev = "The quick brown fox jumps over the lazy dog."
    curr = "The quick brown fox jumps over the active dog."
    
    # 4-gram overlap test
    overlap = calc_ngram_overlap(prev, curr, n=4)
    assert overlap > 0.0
    
    # Empty inputs
    assert calc_ngram_overlap("", curr) == 0.0
    assert calc_ngram_overlap(prev, "") == 0.0


def test_detect_format_leakage_long():
    # 1. Valid longform (>=300 and <=500 CJK chars, >=3 parentheses pairs, no Emoji, no leak)
    # \u6211 is CJK character for "I/me"
    # \uff08 and \uff09 are full-width parentheses
    valid_cjk = "\u6211" * 350
    valid_parens = "\uff08\u6211\uff09" * 3
    text = valid_parens + valid_cjk
    
    issues = detect_format_leakage(text, target_mode="long")
    assert len(issues) == 0, f"Expected no issues, got: {issues}"
    
    # 2. Too short for longform
    short_text = "\uff08\u6211\uff09\u6211"
    issues = detect_format_leakage(short_text, target_mode="long")
    assert any("字数不足" in issue or "\u5b57\u6570\u4e0d\u8db3" in issue for issue in issues)
    assert any("圆括号不足" in issue or "\u5706\u62ec\u53f7\u4e0d\u8db3" in issue for issue in issues)
    
    # 3. Contains Emoji (\U0001F600 is smiley face)
    text_emoji = text + " \U0001F600"
    issues = detect_format_leakage(text_emoji, target_mode="long")
    assert any("Emoji" in issue for issue in issues)
    
    # 4. Contains template leak
    text_leak = text + " System Prompt"
    issues = detect_format_leakage(text_leak, target_mode="long")
    assert any("模板泄漏" in issue or "\u6a21\u677f\u6cc4\u6f0f" in issue for issue in issues)


def test_detect_format_leakage_short():
    # 1. Valid shortform (20-120 CJK chars, no **, no long parentheses pollution)
    text = "\u6211" * 50
    issues = detect_format_leakage(text, target_mode="short")
    assert len(issues) == 0
    
    # 2. Too long for shortform
    long_text = "\u6211" * 150
    issues = detect_format_leakage(long_text, target_mode="short")
    assert any("字数过多" in issue or "\u5b57\u6570\u8fc7\u591a" in issue for issue in issues)
    
    # 3. Contains bold markdown formatting
    bold_text = text + " **bold**"
    issues = detect_format_leakage(bold_text, target_mode="short")
    assert any("加粗" in issue or "\u52a0\u7c97" in issue for issue in issues)
    
    # 4. Too many parentheses (longform style) in shortform
    paren_text = "\uff08\u6211\uff09" * 4 + "\u6211" * 85
    issues = detect_format_leakage(paren_text, target_mode="short")
    assert any("疑似长文旁白括号污染" in issue or "\u7591\u4f3c\u957f\u6587\u65c1\u767d\u62ec\u53f7\u6c61\u67d3" in issue for issue in issues)
