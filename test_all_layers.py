#!/usr/bin/env python3
"""Layer 1-3 分层测试脚本"""
import sys, json, os, re, inspect
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)
sys.path.insert(0, BASE_DIR)

from longform_multi_turn import (
    build_variables, render_template, build_messages_for_turn,
    CORE_CONSTRAINTS_TEMPLATE, STYLE_ISOLATION_MSG,
    DEFAULT_FEWSHOT_FILE, load_few_shot_examples, process_ai_output,
    export_to_excel,
)

config = json.load(open('test_conversation_萧璟言.json', encoding='utf-8'))
passed = 0
failed = 0

def ok(name):
    global passed
    passed += 1
    print(f'✅ {name}: PASS')

def fail(name, msg):
    global failed
    failed += 1
    print(f'❌ {name}: FAIL - {msg}')


def resolve_scoring_template_path():
    scoring_dir = Path(r'E:\提效工具\promptfoo-pipeline\scoring_prompts\长文模式')
    preferred = scoring_dir / 'default_v2.md'
    if preferred.exists():
        return preferred
    candidates = sorted(scoring_dir.glob('*.md'))
    if not candidates:
        raise FileNotFoundError(f'目录下没有可用评分模板: {scoring_dir}')
    return candidates[0]


def resolve_cli_export_headers():
    source = inspect.getsource(export_to_excel)
    match = re.search(r'headers\s*=\s*\[(.*?)\]', source, re.DOTALL)
    if not match:
        raise AssertionError("无法解析 export_to_excel headers")
    return re.findall(r'"([^"]+)"', match.group(1))

# ═══════════════════════════════════════
# Layer 1: 单元级 — 变量注入
# ═══════════════════════════════════════
print('\n' + '='*60)
print('  Layer 1: 单元级 — 变量注入')
print('='*60)

variables = build_variables(config)

# Test 1.1: render_template 替换
template = '角色:{{Role_Nickname}} 性格:{{personality}}'
result = render_template(template, variables)
if '萧璟言' in result and '冷漠矜贵' in result:
    ok('1.1 变量注入基本替换')
else:
    fail('1.1 变量注入基本替换', f'result={result[:100]}')

# Test 1.2: build_variables 覆盖率
required = [
    'Role_Nickname','personality','speaking_style','personal_type',
    'relationship','intimacy_boundary','longform_narrative_style',
    'user_Nickname','season','timeperiod','dialogue_summary',
    'current_scene','dialogueStartPrompt','relation_calling',
    'relation_info','hobby','background','age','occupation',
    'gender','user_gender','user_identity'
]
missing = [k for k in required if k not in variables]
if not missing:
    ok(f'1.2 变量覆盖率 ({len(variables)} 个变量)')
else:
    fail('1.2 变量覆盖率', f'缺失: {missing}')

# Test 1.3: 关键变量非空
empty_ok = ['dialogue_summary']
empty_vars = [k for k in required if k not in empty_ok and not variables.get(k)]
if not empty_vars:
    ok('1.3 关键变量均有值')
else:
    fail('1.3 关键变量均有值', f'空值: {empty_vars}')

# ═══════════════════════════════════════
# Layer 2: 集成级 — 消息拼接结构
# ═══════════════════════════════════════
print('\n' + '='*60)
print('  Layer 2: 集成级 — 消息拼接结构')
print('='*60)

# Test 2.1a: 首轮（无历史，无摘要，无few-shot）
msgs = build_messages_for_turn(
    rendered_system='SYSTEM_PROMPT',
    system_after='',
    few_shot_messages=[],
    conversation_history=[],
    dialogue_summary='',
    current_input='测试输入',
    relationship='暧昧',
    role_name='萧璟言',
    personality='霸道腹黑',
)

if msgs[0]['role'] == 'system' and msgs[-1]['role'] == 'user':
    ok(f'2.1a 首轮消息结构: {len(msgs)} 条')
else:
    fail('2.1a 首轮消息结构', f'首条role={msgs[0]["role"]}, 末条role={msgs[-1]["role"]}')

# 验证 CC 在倒数第二
if '<Core_Constraints>' in msgs[-2]['content']:
    ok('2.1b Core_Constraints 在 N-1 位')
else:
    fail('2.1b Core_Constraints 位置', f'N-1 内容: {msgs[-2]["content"][:80]}')

# 验证用户输入包裹
if '<user_input>' in msgs[-1]['content'] and '</user_input>' in msgs[-1]['content']:
    ok('2.1c 用户输入 XML 包裹')
else:
    fail('2.1c 用户输入 XML 包裹', f'内容: {msgs[-1]["content"]}')

# Test 2.2: 有历史 + 有摘要（Turn 6 模拟）
history = [
    {'role':'user','content':'输入1'}, {'role':'assistant','content':'回复1'},
    {'role':'user','content':'输入2'}, {'role':'assistant','content':'回复2'},
    {'role':'user','content':'输入3'}, {'role':'assistant','content':'回复3'},
    {'role':'user','content':'输入4'}, {'role':'assistant','content':'回复4'},
    {'role':'user','content':'输入5'}, {'role':'assistant','content':'回复5'},
]
summary = '=== 对话摘要 ===\nscene_description: 花园散步\npending_hooks: 情感暗示'

msgs2 = build_messages_for_turn(
    rendered_system='SYSTEM_PROMPT',
    system_after='',
    few_shot_messages=[],
    conversation_history=history,
    dialogue_summary=summary,
    current_input='测试6',
    relationship='暧昧',
    role_name='萧璟言',
    personality='霸道腹黑',
)
# 预期: system(1) + 风格隔离(1) + 摘要(1) + 10历史 + CC(1) + user(1) = 15
expected_count = 15
if len(msgs2) == expected_count:
    ok(f'2.2a 有历史+摘要消息数: {len(msgs2)}')
else:
    fail(f'2.2a 消息数', f'预期={expected_count}, 实际={len(msgs2)}')
    for j, m in enumerate(msgs2):
        print(f'    [{j}] {m["role"]}: {m["content"][:60]}')

# 风格隔离应在摘要之前
iso_idx = None
sum_idx = None
for idx, m in enumerate(msgs2):
    if '风格' in m.get('content','') and '遵循' in m.get('content',''):
        iso_idx = idx
    if '对话摘要' in m.get('content',''):
        sum_idx = idx
if iso_idx is not None and sum_idx is not None and iso_idx < sum_idx:
    ok(f'2.2b 风格隔离(idx={iso_idx}) < 摘要(idx={sum_idx})')
else:
    fail('2.2b 消息顺序', f'iso={iso_idx}, sum={sum_idx}')

# Test 2.3: CLI 保守合同下不注入深度注入消息（16条历史 = 8轮）
history_8 = []
for t in range(8):
    history_8.append({'role':'user','content':f'输入{t+1}'})
    history_8.append({'role':'assistant','content':f'回复{t+1}'})

msgs3 = build_messages_for_turn(
    rendered_system='SYSTEM_PROMPT',
    system_after='',
    few_shot_messages=[],
    conversation_history=history_8,
    dialogue_summary='摘要内容',
    current_input='测试9',
    relationship='暧昧',
    role_name='萧璟言',
    personality='霸道腹黑',
)

# 检查 CLI 链路不再额外插入深度注入消息
depth_msgs = [m for m in msgs3 if m['role'] == 'system' and '请记住' in m.get('content','')]
if len(depth_msgs) == 0:
    ok(f'2.3 CLI 不注入深度注入消息 (总消息={len(msgs3)})')
else:
    fail('2.3 CLI 深度注入合同', f'找到 {len(depth_msgs)} 条深度注入消息')

# ═══════════════════════════════════════
# Layer 3: Excel 列名对齐打分提示词
# ═══════════════════════════════════════
print('\n' + '='*60)
print('  Layer 3: Excel 列名 vs 打分提示词变量')
print('='*60)

scoring_template_path = resolve_scoring_template_path()
with open(scoring_template_path, encoding='utf-8') as f:
    scoring_template = f.read()

# 提取打分模板中的所有 {{变量}}
scoring_vars = set(re.findall(r'\{\{(\w+)\}\}', scoring_template))

excel_headers = set(resolve_cli_export_headers())

# config.json 别名映射
aliases = {"user_message": "用户输入", "output": "AI输出", "prompt_name": "测试对应提示词"}

# 检查每个打分变量是否能在 Excel 中找到
missing_in_excel = []
for var in scoring_vars:
    if var in excel_headers:
        continue
    # 通过 alias 查找
    alias_target = aliases.get(var)
    if alias_target and alias_target in excel_headers:
        continue
    missing_in_excel.append(var)

if not missing_in_excel:
    ok(f'3.1 打分模板 {len(scoring_vars)} 个变量全部覆盖')
else:
    fail(f'3.1 打分模板变量覆盖', f'缺失: {missing_in_excel}')

# ═══════════════════════════════════════
# Layer 4: Few-shot 冷却复注策略 (§4.7)
# ═══════════════════════════════════════
print('\n' + '='*60)
print('  Layer 4: Few-shot 冷却复注策略')
print('='*60)

real_fs = load_few_shot_examples(str(DEFAULT_FEWSHOT_FILE), personal_type='霸道腹黑')
if len(real_fs) == 4:
    ok('4.0 真实 Few-shot 示例库可解析并命中 2 组')
else:
    fail('4.0 真实 Few-shot 示例库解析', f'实际={len(real_fs)}')

# Test 4.1: Turn 1 注入全部 Few-shot
msgs_t1 = build_messages_for_turn(
    rendered_system='SYS', system_after='',
    few_shot_messages=real_fs,
    conversation_history=[], dialogue_summary='',
    current_input='输入', relationship='暧昧',
    role_name='测试', personality='测试', turn_num=1,
)
fs_in_t1 = [m for m in msgs_t1 if m['role'] in ('user', 'assistant')][0:4]
if len(fs_in_t1) == 4:
    ok('4.1 Turn1 注入全部 Few-shot (4条)')
else:
    fail('4.1 Turn1 Few-shot', f'实际={len(fs_in_t1)}')

# Test 4.2: Turn 5 冷却期不注入
msgs_t5 = build_messages_for_turn(
    rendered_system='SYS', system_after='',
    few_shot_messages=real_fs,
    conversation_history=[], dialogue_summary='',
    current_input='输入', relationship='暧昧',
    role_name='测试', personality='测试', turn_num=5,
)
fs_in_t5 = [
    m for m in msgs_t5
    if m.get('content') in {item['content'] for item in real_fs}
]
if len(fs_in_t5) == 0:
    ok('4.2 Turn5 冷却期不注入 Few-shot')
else:
    fail('4.2 Turn5 冷却期', f'应为0, 实际={len(fs_in_t5)}')

# Test 4.3: Turn 16+ 复注仅第1组
msgs_t16 = build_messages_for_turn(
    rendered_system='SYS', system_after='',
    few_shot_messages=real_fs,
    conversation_history=[], dialogue_summary='',
    current_input='输入', relationship='暧昧',
    role_name='测试', personality='测试', turn_num=16,
)
fs_in_t16 = [
    m for m in msgs_t16
    if m.get('content') in {item['content'] for item in real_fs}
]
if len(fs_in_t16) == 2 and fs_in_t16[0]['content'] == real_fs[0]['content']:
    ok('4.3 Turn16+ 复注第1组 (2条)')
else:
    fail('4.3 Turn16+ 复注', f'实际={len(fs_in_t16)}')

# ═══════════════════════════════════════
# Layer 5: QualityGuard 质量保障
# ═══════════════════════════════════════
print('\n' + '='*60)
print('  Layer 5: QualityGuard 质量保障')
print('='*60)

# 添加 server/services 到 path
import sys as _sys
_sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'server'))

try:
    from services.quality_guard import QualityGuard
    qa = QualityGuard()

    # Test 5.1: 字数过短触发重试
    short_text = '太短了' * 10  # 30字
    r = qa.check(short_text)
    if r['needs_retry'] and '过短' in r['retry_reason']:
        ok('5.1 字数过短触发重试')
    else:
        fail('5.1 字数过短', f'needs_retry={r["needs_retry"]}')

    # Test 5.2: Emoji 移除
    emoji_text = '这是正常文本😍' + '测试' * 300
    r = qa.check(emoji_text)
    if '😍' not in r['processed_text'] and '移除Emoji' in r['fixes_applied']:
        ok('5.2 Emoji 移除')
    else:
        fail('5.2 Emoji 移除', f'fixes={r["fixes_applied"]}')

    # Test 5.3: 主链路后处理包装
    processed = process_ai_output('好的，先想想\n这是正常文本😍' + '测试' * 300)
    if '😍' not in processed['processed_text'] and '剥离推理过程前缀' in processed['fixes_applied']:
        ok('5.3 process_ai_output 接入 QualityGuard')
    else:
        fail('5.3 process_ai_output', f'processed={processed}')
except ImportError as e:
    fail('5.1 QualityGuard 导入', str(e))
    fail('5.2 QualityGuard 导入', str(e))
    fail('5.3 QualityGuard 导入', str(e))

# ═══════════════════════════════════════
# Layer 6: CLI dry-run 语义
# ═══════════════════════════════════════
print('\n' + '='*60)
print('  Layer 6: CLI dry-run 语义')
print('='*60)

import subprocess
import tempfile
from pathlib import Path

with tempfile.TemporaryDirectory(prefix='longform_dryrun_') as tmpdir:
    out_dir = Path(tmpdir)
    env = os.environ.copy()
    env.pop('PYTHONIOENCODING', None)
    proc = subprocess.run(
        [
            sys.executable,
            'longform_multi_turn.py',
            'test_conversation_萧璟言.json',
            '--dry-run',
            '--turns',
            '2',
            '--output-dir',
            str(out_dir),
        ],
        cwd=BASE_DIR,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding='utf-8',
    )
    if proc.returncode == 0:
        ok('6.1 默认编码下 dry-run 可执行')
    else:
        fail('6.1 默认编码下 dry-run', proc.stderr[:200])

    exported = list(out_dir.glob('*.json')) + list(out_dir.glob('*.xlsx'))
    if not exported:
        ok('6.2 dry-run 不写 JSON/XLSX')
    else:
        fail('6.2 dry-run 导出副作用', str([p.name for p in exported]))

# ═══════════════════════════════════════
# 总结
# ═══════════════════════════════════════
print(f'\n{"="*60}')
print(f'  总结: {passed} passed, {failed} failed')
print(f'{"="*60}')

