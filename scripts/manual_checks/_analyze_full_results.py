"""分析正式192次跑的完整结果"""
import json
from pathlib import Path
from collections import Counter

p = Path(r"E:\提效工具\长文模式生成\output\mode_switching_switch_state\strategy_ab_compare_full_20260514\results.jsonl")
rows = [json.loads(l) for l in p.open(encoding="utf-8")]

print(f"=== 总量验证 ===")
print(f"total rows: {len(rows)}")
api_ok = sum(1 for r in rows if r.get("api_success", True))
api_fail = sum(1 for r in rows if not r.get("api_success", True))
print(f"api_success True: {api_ok}")
print(f"api_success False: {api_fail}")
print()

# 按策略+方向统计
print("=== 按策略+方向 ===")
for strat in ["A_互动要点", "B_三明治兜底"]:
    for d in ["长→短", "短→长"]:
        subset = [r for r in rows if r["strategy"] == strat and r["direction"] == d]
        if subset:
            passed = sum(1 for r in subset if r["format_pass"])
            print(f"  {strat:18s} | {d} | total={len(subset):3d} | pass={passed:3d} | rate={passed/len(subset)*100:.1f}%")
print()

# 按策略+方向+模型
print("=== 按策略+方向+模型 ===")
for strat in ["A_互动要点", "B_三明治兜底"]:
    for d in ["长→短", "短→长"]:
        subset = [r for r in rows if r["strategy"] == strat and r["direction"] == d]
        models = sorted(set(r["target_model"] for r in subset))
        for m in models:
            ms = [r for r in subset if r["target_model"] == m]
            passed = sum(1 for r in ms if r["format_pass"])
            print(f"  {strat:18s} | {d} | {m:25s} | total={len(ms):3d} | pass={passed:3d} | rate={passed/len(ms)*100:.1f}%")
    print()

# 失败原因分类
print("=== 失败原因分布 ===")
all_issues = []
for r in rows:
    if not r["format_pass"] and r.get("issues"):
        for issue in r["issues"]:
            for sub in issue.split(";"):
                sub = sub.strip()
                if "禁词" in sub:
                    all_issues.append("禁词:指尖")
                elif "字数超标" in sub:
                    all_issues.append("字数超标(>90)")
                elif "字数过少" in sub:
                    all_issues.append("字数过少(<300)")
                elif "长段旁白" in sub:
                    all_issues.append("长段旁白")
                elif "加粗对白" in sub:
                    all_issues.append("加粗对白")
                elif "第三人称" in sub:
                    all_issues.append("第三人称叙事")
                else:
                    all_issues.append(sub[:30])
for k, v in Counter(all_issues).most_common():
    print(f"  {k}: {v}")
print()

# 按角色统计通过率
print("=== 按角色总通过率 ===")
def get_label(r):
    return r.get("role_label", "") or r.get("role_name", "") or "unknown"

roles = sorted(set(get_label(r) for r in rows))
for role in roles:
    rs = [r for r in rows if get_label(r) == role]
    passed = sum(1 for r in rs if r["format_pass"])
    print(f"  {role}: {passed}/{len(rs)} = {passed/len(rs)*100:.1f}%")
print()

# 按角色+策略
print("=== 按角色+策略 ===")
for role in roles:
    line = f"  {role:15s} |"
    for strat in ["A_互动要点", "B_三明治兜底"]:
        rs = [r for r in rows if get_label(r) == role and r["strategy"] == strat]
        if rs:
            passed = sum(1 for r in rs if r["format_pass"])
            line += f" {strat}: {passed}/{len(rs)}={passed/len(rs)*100:.0f}% |"
    print(line)
print()

# A vs B 净胜矩阵（按方向+模型）
print("=== A vs B 净胜 (通过率差) ===")
for d in ["长→短", "短→长"]:
    a_sub = [r for r in rows if r["strategy"] == "A_互动要点" and r["direction"] == d]
    b_sub = [r for r in rows if r["strategy"] == "B_三明治兜底" and r["direction"] == d]
    if a_sub and b_sub:
        models = sorted(set(r["target_model"] for r in a_sub))
        for m in models:
            a_ms = [r for r in a_sub if r["target_model"] == m]
            b_ms = [r for r in b_sub if r["target_model"] == m]
            a_rate = sum(1 for r in a_ms if r["format_pass"]) / len(a_ms) * 100
            b_rate = sum(1 for r in b_ms if r["format_pass"]) / len(b_ms) * 100
            delta = a_rate - b_rate
            winner = "A胜" if delta > 0 else ("B胜" if delta < 0 else "平")
            print(f"  {d} | {m:25s} | A={a_rate:.1f}% B={b_rate:.1f}% | delta={delta:+.1f}pp | {winner}")
