"""重新分析192次结果：排除"指尖"禁词，聚焦格式错乱问题"""
import json
import re
from pathlib import Path
from collections import Counter

p = Path(r"E:\提效工具\长文模式生成\output\mode_switching_switch_state\strategy_ab_compare_full_20260514\results.jsonl")
rows = [json.loads(l) for l in p.open(encoding="utf-8")]

print(f"=== 总行数: {len(rows)} ===\n")

# ── 重新评估：排除"指尖"，增加格式错乱检测 ──

def reeval(row):
    """排除指尖禁词，增加格式错乱维度"""
    output = row.get("output", "")
    target_mode = "short" if row["direction"] == "长→短" else "long"
    issues = []
    char_count = len(re.findall(r'[\u4e00-\u9fff]', output))
    
    if target_mode == "short":
        if char_count < 30:
            issues.append(f"字数过少({char_count}<30)")
        elif char_count > 90:
            issues.append(f"字数超标({char_count}>90)")
        
        # 加粗对白（长文格式泄漏）
        bold_patterns = ['**"', '"**', '**\u201c', '\u201d**']
        if any(p in output for p in bold_patterns):
            issues.append("加粗对白泄漏")
        
        # 第三人称叙事
        clean = re.sub(r'（[^）]*）', '', output)
        third_person = [
            "他看着", "她看着", "他转身", "她转身", "他抬手", "她抬手",
            "他低头", "她低头", "他伸手", "她伸手",
            "他望", "她望", "他凝视", "她凝视", "他笑了", "她笑了",
        ]
        for tp in third_person:
            if tp in clean:
                issues.append("第三人称叙事泄漏")
                break
        
        # 格式错乱：换行符过多（短文不该有多段）
        newline_count = output.count('\n')
        if newline_count > 3:
            issues.append(f"换行符过多({newline_count}个)")
        
        # 格式错乱：丢失（）—— 动作描写应该用（）包裹
        # 检测裸露的动作描写（如 *叹气* 或无括号的旁白段）
        if re.search(r'\*[^*]+\*', output):
            issues.append("星号动作(格式泄漏)")
        
        # 长段旁白（超过50字无对话的纯叙述）
        lines = [l.strip() for l in output.split('\n') if l.strip()]
        for line in lines:
            line_chars = len(re.findall(r'[\u4e00-\u9fff]', line))
            if line_chars > 60 and '（' not in line and '"' not in line and '"' not in line:
                issues.append("长段旁白(>60字无括号无对话)")
                break
    
    else:  # long
        if char_count < 300:
            issues.append(f"字数过少({char_count}<300)")
        elif char_count > 500:
            issues.append(f"字数过多({char_count}>500)")
        
        # 短文格式污染
        if output.startswith("（") and char_count < 150:
            issues.append("短文格式污染(括号开头+字数少)")
        
        # 格式错乱：连续多个空行
        if '\n\n\n' in output:
            issues.append("连续空行过多")
        
        # 对白格式检查：长文应该用 **""** 而非裸引号
        if '"' in output and '**"' not in output:
            raw_quotes = len(re.findall(r'(?<!\*\*)"[^"]{1,60}"(?!\*\*)', output))
            if raw_quotes > 0:
                issues.append(f"对白未加粗({raw_quotes}处)")
    
    return {
        "char_count": char_count,
        "issues": issues,
        "format_pass": len(issues) == 0,
    }


# 重新评估所有行
for row in rows:
    new_eval = reeval(row)
    row["new_issues"] = new_eval["issues"]
    row["new_pass"] = new_eval["format_pass"]
    row["new_char"] = new_eval["char_count"]

# ── 输出统计 ──

print("=" * 70)
print("  排除\"指尖\"后的通过率对比")
print("=" * 70)

# 总体
for strat in ["A_互动要点", "B_三明治兜底"]:
    subset = [r for r in rows if r["strategy"] == strat]
    old_pass = sum(1 for r in subset if r["format_pass"])
    new_pass = sum(1 for r in subset if r["new_pass"])
    print(f"\n  {strat}:")
    print(f"    原通过率(含指尖): {old_pass}/{len(subset)} = {old_pass/len(subset)*100:.1f}%")
    print(f"    新通过率(排除指尖): {new_pass}/{len(subset)} = {new_pass/len(subset)*100:.1f}%")

print("\n" + "=" * 70)
print("  按方向+策略")
print("=" * 70)

for d in ["长→短", "短→长"]:
    print(f"\n  --- {d} ---")
    for strat in ["A_互动要点", "B_三明治兜底"]:
        subset = [r for r in rows if r["strategy"] == strat and r["direction"] == d]
        if not subset:
            continue
        new_pass = sum(1 for r in subset if r["new_pass"])
        print(f"    {strat}: {new_pass}/{len(subset)} = {new_pass/len(subset)*100:.1f}%")

print("\n" + "=" * 70)
print("  按方向+策略+模型")
print("=" * 70)

for d in ["长→短", "短→长"]:
    print(f"\n  --- {d} ---")
    for strat in ["A_互动要点", "B_三明治兜底"]:
        subset = [r for r in rows if r["strategy"] == strat and r["direction"] == d]
        models = sorted(set(r["target_model"] for r in subset))
        for m in models:
            ms = [r for r in subset if r["target_model"] == m]
            new_pass = sum(1 for r in ms if r["new_pass"])
            print(f"    {strat:18s} | {m:25s} | {new_pass}/{len(ms)} = {new_pass/len(ms)*100:.1f}%")

print("\n" + "=" * 70)
print("  A vs B 净胜（排除指尖后）")
print("=" * 70)

for d in ["长→短", "短→长"]:
    a_sub = [r for r in rows if r["strategy"] == "A_互动要点" and r["direction"] == d]
    b_sub = [r for r in rows if r["strategy"] == "B_三明治兜底" and r["direction"] == d]
    if a_sub and b_sub:
        models = sorted(set(r["target_model"] for r in a_sub))
        for m in models:
            a_ms = [r for r in a_sub if r["target_model"] == m]
            b_ms = [r for r in b_sub if r["target_model"] == m]
            a_rate = sum(1 for r in a_ms if r["new_pass"]) / len(a_ms) * 100
            b_rate = sum(1 for r in b_ms if r["new_pass"]) / len(b_ms) * 100
            delta = a_rate - b_rate
            winner = "A胜" if delta > 0 else ("B胜" if delta < 0 else "平")
            print(f"  {d} | {m:25s} | A={a_rate:.1f}% B={b_rate:.1f}% | delta={delta:+.1f}pp | {winner}")

print("\n" + "=" * 70)
print("  新失败原因分布（排除指尖后）")
print("=" * 70)

all_new_issues = []
for r in rows:
    if not r["new_pass"]:
        for issue in r["new_issues"]:
            category = issue.split("(")[0].split("（")[0].strip()
            all_new_issues.append(category)

for k, v in Counter(all_new_issues).most_common():
    print(f"  {k}: {v}")

print("\n" + "=" * 70)
print("  格式错乱详情（按策略）")
print("=" * 70)

format_issues_detail = {
    "换行符过多": [],
    "加粗对白泄漏": [],
    "第三人称叙事泄漏": [],
    "长段旁白": [],
    "星号动作": [],
    "连续空行过多": [],
    "对白未加粗": [],
}

for r in rows:
    for issue in r["new_issues"]:
        for key in format_issues_detail:
            if key in issue:
                format_issues_detail[key].append({
                    "strategy": r["strategy"],
                    "direction": r["direction"],
                    "role": r["role_name"],
                    "model": r["target_model"],
                    "issue": issue,
                })

for fmt_type, details in format_issues_detail.items():
    if details:
        print(f"\n  [{fmt_type}] 共 {len(details)} 次")
        # 按策略统计
        a_count = sum(1 for d in details if "A_" in d["strategy"])
        b_count = sum(1 for d in details if "B_" in d["strategy"])
        print(f"    方案A: {a_count} 次 | 方案B: {b_count} 次")
        # 显示前3个样例
        for d in details[:3]:
            print(f"    样例: {d['strategy']} | {d['direction']} | {d['role']} | {d['model']} | {d['issue']}")

# 按角色
print("\n" + "=" * 70)
print("  按角色（排除指尖后）")
print("=" * 70)

def get_label(r):
    return r.get("role_label", "") or r.get("role_name", "") or "unknown"

roles = sorted(set(get_label(r) for r in rows))
for role in roles:
    line = f"  {role:15s} |"
    for strat in ["A_互动要点", "B_三明治兜底"]:
        rs = [r for r in rows if get_label(r) == role and r["strategy"] == strat]
        if rs:
            passed = sum(1 for r in rs if r["new_pass"])
            line += f" {strat}: {passed}/{len(rs)}={passed/len(rs)*100:.0f}% |"
    print(line)

# 字数分布（按方向+策略）
print("\n" + "=" * 70)
print("  字数分布（按方向+策略）")
print("=" * 70)

for d in ["长→短", "短→长"]:
    for strat in ["A_互动要点", "B_三明治兜底"]:
        subset = [r for r in rows if r["strategy"] == strat and r["direction"] == d]
        if not subset:
            continue
        chars = [r["new_char"] for r in subset]
        target = "30-90" if d == "长→短" else "300-500"
        over = sum(1 for c in chars if (c > 90 if d == "长→短" else c > 500))
        under = sum(1 for c in chars if (c < 30 if d == "长→短" else c < 300))
        print(f"  {d} | {strat:18s} | mean={sum(chars)/len(chars):.0f} min={min(chars)} max={max(chars)} | 目标{target} | 超标{over} 过少{under}")
