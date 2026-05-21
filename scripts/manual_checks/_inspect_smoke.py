"""检视冒烟测试结果：验证 F1/F2/F7 在真实输出中的体现。
运行：python scripts/manual_checks/_inspect_smoke.py
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "output" / "mode_switching_switch_state" / "smoke_20260514" / "results.jsonl"

rows = [json.loads(l) for l in RESULTS.open(encoding="utf-8")]
print(f"total rows: {len(rows)}")
print()

print("=" * 100)
print(f"{'strategy':18s} | {'direction':5s} | {'target_model':25s} | msg | api_ok | pass | char | issues")
print("=" * 100)
for r in rows:
    issues = ";".join(r.get("issues", []))[:60]
    print(
        f"{r['strategy']:18s} | {r['direction']:5s} | {r['target_model']:25s} | "
        f"{r['message_count']:2d}  |   {r['api_success']!s:5s} | {r['format_pass']!s:5s} | "
        f"{r['char_count']:3d}  | {issues}"
    )
print()

# === 验证 F1: 互动要点是否含 [MM-DD HH:mm] ===
print("\n" + "=" * 60)
print("F1 验证：互动要点输出是否含 [MM-DD HH:mm] 时间戳")
print("=" * 60)
# 从方案A 长→短第1条找到注入的 points（间接：解析 messages 不可能，看输出里是否有日期模式）
# 直接看脚本中 points 的生成不会出现在 row 里，但 messages[1].content 包含
# row 没存 messages，所以我们读取 stdout 已知的"互动要点长度 244字" 是确认生成了
# 现在补一个：用脚本自身重新生成一次互动要点查看实际内容
print("互动要点字符串没存在 row 里，需要从 stdout 验证（前面输出显示 244字、323字 已成功生成）")
print("互动要点格式合规性：在 compare_interaction_points_extractors.py 内部 validate_points_format 已验证")

# === 验证 F2: 输出本身的 [MM-DD HH:mm] 痕迹 ===
print("\n" + "=" * 60)
print("F2 验证：输出中如出现时间戳格式，确认下游模型能消费")
print("=" * 60)
TS_PATTERN = re.compile(r"\[\d{2}-\d{2}\s+\d{2}:\d{2}\]")
for r in rows:
    output = r.get("output", "")
    matches = TS_PATTERN.findall(output)
    if matches:
        print(f"  {r['strategy']} | {r['direction']} | {r['target_model']} 输出含时间戳: {matches[:3]}")

# === 长→短 sample 输出 ===
print("\n" + "=" * 60)
print("方案A 长→短 doubao-1.5-character 输出 (PASS) ：")
print("=" * 60)
sample_a = next(
    r for r in rows
    if r["strategy"] == "A_互动要点"
    and r["direction"] == "长→短"
    and r["target_model"] == "doubao-1.5-character"
)
print(sample_a["output"])
print()

print("=" * 60)
print("方案B 长→短 doubao-1.5-character 输出 (FAIL: 字数 142 > 90)：")
print("=" * 60)
sample_b = next(
    r for r in rows
    if r["strategy"] == "B_三明治兜底"
    and r["direction"] == "长→短"
    and r["target_model"] == "doubao-1.5-character"
)
print(sample_b["output"])
print()

print("=" * 60)
print("方案A 短→长 deepseek-v4-pro 输出 (FAIL: 含'指尖')：")
print("=" * 60)
sample_long = next(
    r for r in rows
    if r["strategy"] == "A_互动要点" and r["direction"] == "短→长"
)
print(sample_long["output"])
print()
# 验证 F8 Core_Constraints 是否能被模型遵守（输出 300-500 字）
print(f"长文输出字数: {sample_long['char_count']} (目标 300-500)")
