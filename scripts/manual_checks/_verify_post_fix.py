"""临时验证：审计修复后的关键函数行为是否符合预期。
运行：python scripts/manual_checks/_verify_post_fix.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "server"))

from compare_switching_strategies import (
    LONG_CORE_CONSTRAINTS,
    build_strategy_a_messages,
    build_strategy_b_messages,
    build_transcript_with_timestamp,
    normalize_bridge_messages,
    parse_longform_dialogue,
    parse_shortform_dialogue,
    render_summary_json_to_labels,
    sandwich_history,
    wrap_user_input,
)


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def assert_eq(actual, expected, label):
    ok = actual == expected
    flag = "PASS" if ok else "FAIL"
    print(f"  [{flag}] {label}")
    if not ok:
        print(f"    expected: {expected!r}")
        print(f"    actual:   {actual!r}")
    return ok


passes = 0
total = 0


def check(actual, expected, label):
    global passes, total
    total += 1
    if assert_eq(actual, expected, label):
        passes += 1


# ── F8: wrap_user_input ──
section("F8 wrap_user_input")
short = wrap_user_input("在吗", "short")
print(f"  short: {short!r}")
check(short, "在吗", "短文方向不包裹")

long_wrapped = wrap_user_input("在吗", "long")
print(f"  long:  {long_wrapped!r}")
expected_long = (
    f"<Core_Constraints>{LONG_CORE_CONSTRAINTS}</Core_Constraints>\n\n"
    f"<user_input>在吗</user_input>"
)
check(long_wrapped, expected_long, "长文方向 <Core_Constraints>+<user_input> 包裹")

# ── F8: build_strategy_a/b 末条 user ──
section("F8 build_strategy_a/b 末条 user 包含 Core_Constraints")
msgs_a_long = build_strategy_a_messages("SYS", "SUM", "PTS", "你好", target_mode="long")
print(f"  方案A 长向 末条: {msgs_a_long[-1]}")
check("<Core_Constraints>" in msgs_a_long[-1]["content"], True, "方案A 长向末条含 Core_Constraints")
check("<user_input>你好</user_input>" in msgs_a_long[-1]["content"], True, "方案A 长向末条含 user_input")

msgs_a_short = build_strategy_a_messages("SYS", "SUM", "PTS", "你好", target_mode="short")
check(msgs_a_short[-1]["content"], "你好", "方案A 短向末条原样")

msgs_b_long = build_strategy_b_messages("SYS", "SUM", [{"role": "user", "content": "H1"}], "你好", target_mode="long")
check("<Core_Constraints>" in msgs_b_long[-1]["content"], True, "方案B 长向末条含 Core_Constraints")

# ── F5: normalize_bridge_messages 占位 user ──
section("F5 normalize_bridge_messages 首条 assistant 插占位 user")
bridge = [
    {"role": "assistant", "content": "A1"},
    {"role": "user", "content": "U1"},
    {"role": "assistant", "content": "A2"},
    {"role": "user", "content": "U2"},
]
result = normalize_bridge_messages(bridge)
print(f"  result: {result}")
check(len(result) > 0, True, "结果非空")
check(result[0]["role"], "user", "首条改为 user")
check(result[0]["content"], "（继续上文）", "首条占位文案正确")
check(result[1]["role"], "assistant", "次条保留原 A1")
check(result[1]["content"], "A1", "A1 内容未丢失")

# 对比：首条是 user 时不应插占位
bridge2 = [
    {"role": "user", "content": "U1"},
    {"role": "assistant", "content": "A1"},
]
result2 = normalize_bridge_messages(bridge2)
print(f"  result2: {result2}")
check(result2[0]["role"], "user", "首条原本就是 user，保持不变")
check(result2[0]["content"], "U1", "U1 内容保留")

# 末尾 user 应被 pop
bridge3 = [
    {"role": "user", "content": "U1"},
    {"role": "assistant", "content": "A1"},
    {"role": "user", "content": "U_tail"},
]
result3 = normalize_bridge_messages(bridge3)
print(f"  result3: {result3}")
check(len(result3), 2, "末尾 user 被 pop")
check(result3[-1]["role"], "assistant", "末条变为 assistant")

# ── F7: render_summary_json_to_labels ──
section("F7 render_summary_json_to_labels")
summary_json = json.dumps({
    "scene_description": "深夜酒店窗台，城市霓虹透进来",
    "plot_summary": "[04-20 14:00]用户上线→[04-20 14:10]角色提议明天约饭",
    "pending_hooks": "[04-21 12:00]约饭未敲定地点",
    "character_emotion": "温柔克制",
    "user_emotion": "疲惫渐放松",
    "relationship_shift": "暧昧期，因约饭提议向前推进",
    "user_profile_signals": "晚睡，工作累",
}, ensure_ascii=False)
rendered = render_summary_json_to_labels(summary_json)
print(f"  rendered:\n{rendered}")
check("【场景】" in rendered, True, "含【场景】标签")
check("【剧情】" in rendered, True, "含【剧情】标签")
check("【关系】" in rendered, True, "含【关系】标签")
check("scene_description" in rendered, False, "去掉了原 JSON 字段名")

# 非 JSON 输入应原样返回
plain = render_summary_json_to_labels("这是一段纯文本摘要")
check(plain, "这是一段纯文本摘要", "非 JSON 输入兜底原样返回")

# ── F2: parser 含 timestamp ──
section("F2 parser 含 timestamp 字段")
long_text = "[04-20 14:00][user]\n你好\n\n[04-20 14:05][assistant]\n嗯"
long_hist = parse_longform_dialogue(long_text)
print(f"  long_hist: {long_hist}")
check(long_hist[0].get("timestamp"), "04-20 14:00", "长文首条 timestamp")
check(long_hist[1].get("timestamp"), "04-20 14:05", "长文次条 timestamp")
check(long_hist[0].get("source_mode"), "long", "source_mode=long")

short_text = "用户\n\n你好\n\nAI\n\n嗯"
short_hist = parse_shortform_dialogue(short_text)
print(f"  short_hist: {short_hist}")
check(short_hist[0].get("timestamp"), "04-20 14:00", "短文首条模拟时间戳")
check(short_hist[1].get("timestamp"), "04-20 14:03", "短文次条 +3 分钟")
check(short_hist[0].get("source_mode"), "short", "source_mode=short")

# ── F1: build_transcript_with_timestamp ──
section("F1 build_transcript_with_timestamp 强制时间戳")
ts_en = build_transcript_with_timestamp(long_hist, role_tag_style="english")
print(f"  english:\n{ts_en}")
check("[04-20 14:00][user]" in ts_en, True, "英文 tag 含 user")
check("[04-20 14:05][assistant]" in ts_en, True, "英文 tag 含 assistant")

ts_zh = build_transcript_with_timestamp(long_hist, role_tag_style="chinese")
print(f"  chinese:\n{ts_zh}")
check("[04-20 14:00][用户]" in ts_zh, True, "中文 tag 含 用户")
check("[04-20 14:05][角色]" in ts_zh, True, "中文 tag 含 角色")

# ── sandwich + normalize 联动 ──
section("sandwich_history 联动 normalize (长→短)")
long_only = [
    {"role": "user", "content": "U1", "source_mode": "long"},
    {"role": "assistant", "content": "A1长文", "source_mode": "long"},
    {"role": "user", "content": "U2", "source_mode": "long"},
    {"role": "assistant", "content": "A2长文", "source_mode": "long"},
]
bridged = sandwich_history(long_only, target_mode="short", turns=5)
print(f"  bridged: {bridged}")
# 全部 assistant 应被三明治包裹
for m in bridged:
    if m["role"] == "assistant":
        check("以下为长文模式回复记录" in m["content"], True, f"assistant 含三明治标签: {m['content'][:30]}")

print()
print(f"==== 总计: {passes}/{total} 通过 ====")
sys.exit(0 if passes == total else 1)
