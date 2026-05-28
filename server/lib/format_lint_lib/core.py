"""
Format Lint & Cross-Mode History Bridge Core
"""
import re
from services.message_assembler import (
    SHORTFORM_HISTORY_PREFIX,
    SHORTFORM_HISTORY_SUFFIX,
    LONGFORM_HISTORY_PREFIX,
    LONGFORM_HISTORY_SUFFIX,
)

TEMPLATE_LEAK_PATTERNS = [
    "以下为", "记录结束", "动态摘要", "摘要结束", "内部认知记录",
    "Core_Constraints", "system", "System Prompt", "user_input",
]

# P2-14: 缩小范围，排除 ❶❷ 等序号符（U+2776-U+2793）和非 Emoji Dingbats
EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U00002702-\U00002775\U00002794-\U000027BF\U00002600-\U000026FF]"
)


def calc_ngram_overlap(prev: str, curr: str, n: int = 4) -> float:
    if not prev or not curr or len(curr) < n:
        return 0.0
    g_prev = set(prev[i:i+n] for i in range(len(prev) - n + 1))
    g_curr = set(curr[i:i+n] for i in range(len(curr) - n + 1))
    if not g_curr:
        return 0.0
    return len(g_prev & g_curr) / len(g_curr)


def count_cjk_chars(text: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]", text or ""))


def count_paren_pairs(text: str) -> int:
    return min(text.count("（"), text.count("）"))


def detect_format_leakage(text: str, target_mode: str) -> list[str]:
    issues = []
    cjk_chars = count_cjk_chars(text)
    if target_mode == "long":
        if cjk_chars < 300:
            issues.append(f"长文字数不足({cjk_chars}字)")
        if cjk_chars > 500:
            issues.append(f"长文字数超标({cjk_chars}字)")
        if count_paren_pairs(text) < 3:
            issues.append(f"圆括号不足({count_paren_pairs(text)}对)")
        if EMOJI_RE.search(text):
            issues.append("含Emoji")
        for pattern in TEMPLATE_LEAK_PATTERNS:
            if pattern in text:
                issues.append(f"模板泄漏({pattern})")
                break
    elif target_mode == "short":
        if cjk_chars < 20:
            issues.append(f"短文字数过少({cjk_chars}字)")
        if cjk_chars > 120:
            issues.append(f"短文字数过多({cjk_chars}字)")
        if "**" in text:
            issues.append("含加粗标记")
        if count_paren_pairs(text) >= 3 and cjk_chars > 80:
            issues.append("疑似长文旁白括号污染")
        if text.count("。") > 6:
            issues.append("短文句号过多")
        for pattern in (LONGFORM_HISTORY_PREFIX, LONGFORM_HISTORY_SUFFIX, "第三人称", "长文模式记录"):
            if pattern in text:
                issues.append("长文模板泄漏")
                break
    return issues


def bridge_history(full_history: list[dict], target_mode: str, max_turns: int) -> tuple[list[dict], dict]:
    recent = full_history[-(max_turns * 2):] if len(full_history) > max_turns * 2 else list(full_history)
    bridged = []
    wrapped = 0
    source_counts: dict[str, int] = {}
    for msg in recent:
        role, content = msg["role"], msg["content"]
        src = msg.get("source_mode", "")
        source_counts[src or "unknown"] = source_counts.get(src or "unknown", 0) + 1
        if role == "assistant" and src and src != target_mode:
            if src == "short":
                content = f"{SHORTFORM_HISTORY_PREFIX}\n{content}\n{SHORTFORM_HISTORY_SUFFIX}"
                wrapped += 1
            elif src == "long":
                content = f"{LONGFORM_HISTORY_PREFIX}\n{content}\n{LONGFORM_HISTORY_SUFFIX}"
                wrapped += 1
        bridged.append({"role": role, "content": content})
    meta = {
        "bridge_turns_requested": max_turns,
        "bridge_messages": len(bridged),
        "bridge_effective_turns": len(bridged) // 2,
        "bridge_total_available_messages": len(full_history),
        "bridge_total_available_turns": len(full_history) // 2,
        "hetero_assistant_wrapped": wrapped,
        "source_message_counts": source_counts,
    }
    return bridged, meta
