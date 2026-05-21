#!/usr/bin/env python3
"""分析Excel批量测试结果"""
import json
from pathlib import Path
from collections import defaultdict

results_file = Path("output/mode_switching_switch_state/excel_sandwich_10t_batch_real_20260513_162323/results.jsonl")

data = []
with open(results_file, encoding='utf-8') as f:
    for line in f:
        data.append(json.loads(line))

print(f"总计: {len(data)}")
print(f"API成功: {sum(1 for d in data if d['success'])}/{len(data)}")
print(f"格式通过: {sum(1 for d in data if d['metrics']['format_pass'])}/{len(data)}")
print(f"平均字数: {sum(d['metrics']['char_count'] for d in data)/len(data):.1f}")

print("\n按模型统计:")
model_stats = defaultdict(lambda: {'total': 0, 'api_ok': 0, 'fmt_ok': 0, 'chars': []})
for d in data:
    m = d['target_model']
    model_stats[m]['total'] += 1
    if d['success']:
        model_stats[m]['api_ok'] += 1
    if d['metrics']['format_pass']:
        model_stats[m]['fmt_ok'] += 1
    model_stats[m]['chars'].append(d['metrics']['char_count'])

for m, s in sorted(model_stats.items()):
    avg_chars = sum(s['chars'])/len(s['chars']) if s['chars'] else 0
    print(f"{m}: {s['fmt_ok']}/{s['total']} 格式通过 ({s['fmt_ok']/s['total']*100:.1f}%), 平均{avg_chars:.0f}字")

print("\n失败原因统计:")
failure_reasons = defaultdict(int)
for d in data:
    if not d['metrics']['format_pass']:
        issues = d['metrics'].get('issues', [])
        for issue in issues:
            failure_reasons[issue] += 1

for reason, count in sorted(failure_reasons.items(), key=lambda x: -x[1]):
    print(f"  {reason}: {count}次")

print("\n按方向统计:")
direction_stats = defaultdict(lambda: {'total': 0, 'fmt_ok': 0})
for d in data:
    direction = d['direction']
    direction_stats[direction]['total'] += 1
    if d['metrics']['format_pass']:
        direction_stats[direction]['fmt_ok'] += 1

for direction, s in sorted(direction_stats.items()):
    print(f"{direction}: {s['fmt_ok']}/{s['total']} 格式通过 ({s['fmt_ok']/s['total']*100:.1f}%)")
