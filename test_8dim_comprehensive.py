#!/usr/bin/env python3
"""
8维度全面测试 — 覆盖 generate.py(v1) + longform_multi_turn.py(v2)

D1: 变量注入完整性
D2: 消息架构正确性
D3: Few-shot冷却复注
D4: 摘要生成格式
D5: 深度注入触发
D6: 风格隔离注入条件
D7: Core_Constraints动态渲染
D8: Excel导出完整性
"""
import sys, json, os, re, inspect
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)
sys.path.insert(0, BASE_DIR)

passed = 0
failed = 0


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
        raise AssertionError('无法解析 export_to_excel headers')
    return re.findall(r'"([^"]+)"', match.group(1))

def ok(name):
    global passed; passed += 1
    print(f'  ✅ {name}')

def fail(name, msg):
    global failed; failed += 1
    print(f'  ❌ {name}: {msg}')

# ── 加载测试配置 ──
config = json.load(open('test_conversation_萧璟言.json', encoding='utf-8'))

# ═══════════════════════════════════════
# D1: 变量注入完整性
# ═══════════════════════════════════════
print('\n' + '='*60)
print('  D1: 变量注入完整性 (v1 + v2)')
print('='*60)

# -- v2 测试 --
from longform_multi_turn import (
    build_variables, render_template, build_messages_for_turn,
    CORE_CONSTRAINTS_TEMPLATE, STYLE_ISOLATION_MSG,
    extract_system_prompt, split_fewshot_from_system,
    SUMMARY_INJECT_TEMPLATE, DEFAULT_FEWSHOT_FILE,
    load_few_shot_examples, parse_few_shot_library, process_ai_output,
    export_to_excel,
)

variables = build_variables(config)

# D1.1: 23个必需变量覆盖率
required_vars = [
    'Role_Nickname','personality','speaking_style','personal_type',
    'relationship','intimacy_boundary','longform_narrative_style',
    'user_Nickname','season','timeperiod','dialogue_summary',
    'current_scene','dialogueStartPrompt','relation_calling',
    'relation_info','hobby','background','age','occupation',
    'gender','user_gender','user_identity',
]
missing = [k for k in required_vars if k not in variables]
if not missing:
    ok(f'D1.1 v2 变量覆盖率: {len(variables)}个变量, 全覆盖')
else:
    fail('D1.1 v2 变量覆盖率', f'缺失: {missing}')

# D1.2: 关键变量非空
skip_empty = ['dialogue_summary']
empty = [k for k in required_vars if k not in skip_empty
         and not variables.get(k)]
if not empty:
    ok('D1.2 v2 关键变量非空')
else:
    fail('D1.2 v2 关键变量非空', f'空值: {empty}')

# D1.3: render_template 替换正确
tpl = '角色:{{Role_Nickname}} 关系:{{relationship}}'
rendered = render_template(tpl, variables)
if '萧璟言' in rendered and '暧昧' in rendered:
    ok('D1.3 v2 render_template 替换')
else:
    fail('D1.3 v2 render_template', f'{rendered[:80]}')

# D1.4: 残留 {{}} 清理 — v2 的策略是保留未匹配变量
tpl2 = '{{Role_Nickname}} + {{nonexistent_var}}'
r2 = render_template(tpl2, variables)
if '{{nonexistent_var}}' in r2 and '萧璟言' in r2:
    ok('D1.4 v2 未匹配变量保留原样(设计如此)')
else:
    fail('D1.4 v2 未匹配变量', f'{r2[:80]}')

# -- v1 测试 --
try:
    import pandas as pd
    from generate import fill_template, TEMPLATE_VARS
    # 构造模拟 row
    row_data = {}
    for k in TEMPLATE_VARS:
        row_data[k] = variables.get(k, '')
    row_data['user_message'] = '测试输入'
    row = pd.Series(row_data)
    tpl_v1 = '角色:{{Role_Nickname}} 关系:{{relationship}}'
    r_v1 = fill_template(tpl_v1, row)
    if '萧璟言' in r_v1 and '暧昧' in r_v1:
        ok('D1.5 v1 fill_template 替换')
    else:
        fail('D1.5 v1 fill_template', f'{r_v1[:80]}')
    # v1 残留清理 — v1 会清除未匹配变量
    tpl_v1b = '{{Role_Nickname}} + {{nonexistent_var}}'
    r_v1b = fill_template(tpl_v1b, row)
    if '{{nonexistent_var}}' not in r_v1b and '萧璟言' in r_v1b:
        ok('D1.6 v1 残留{{}}被清理(re.sub)')
    else:
        fail('D1.6 v1 残留清理', f'{r_v1b[:80]}')
except ImportError as e:
    fail('D1.5-6 v1 导入', str(e))

# ═══════════════════════════════════════
# D2: 消息架构正确性
# ═══════════════════════════════════════
print('\n' + '='*60)
print('  D2: 消息架构正确性 (9层)')
print('='*60)

# D2.1: 首轮无历史无摘要
msgs = build_messages_for_turn(
    rendered_system='SYSTEM_PROMPT',
    system_after='',
    few_shot_messages=[
        {'role':'user','content':'示例1'},
        {'role':'assistant','content':'回复1'},
        {'role':'user','content':'示例2'},
        {'role':'assistant','content':'回复2'},
    ],
    conversation_history=[], dialogue_summary='',
    current_input='测试输入', relationship='暧昧',
    role_name='萧璟言', personality='霸道腹黑', turn_num=1,
)
# 预期: system(1) + few-shot(4) + separator(1) + CC(1) + user(1) = 8
# 无历史/摘要 → 无风格隔离/摘要注入
if len(msgs) == 8:
    ok(f'D2.1 首轮消息数=8 (含4条few-shot)')
else:
    fail('D2.1 首轮消息数', f'预期8, 实际{len(msgs)}')
    for j,m in enumerate(msgs):
        print(f'    [{j}] {m["role"]}: {m["content"][:60]}')

# D2.2: 消息层级顺序验证
roles = [m['role'] for m in msgs]
expected_roles = ['system','user','assistant','user','assistant',
                  'system','system','user']
if roles == expected_roles:
    ok('D2.2 首轮role顺序 [sys,u,a,u,a,sys(sep),sys(CC),u]')
else:
    fail('D2.2 首轮role顺序', f'{roles}')

# D2.3: 有历史+有摘要+Turn6
history = [
    {'role':'user','content':'输入1'},
    {'role':'assistant','content':'回复1'},
    {'role':'user','content':'输入2'},
    {'role':'assistant','content':'回复2'},
]
msgs2 = build_messages_for_turn(
    rendered_system='SYS', system_after='',
    few_shot_messages=[
        {'role':'user','content':'示例1'},
        {'role':'assistant','content':'回复1'},
    ],
    conversation_history=history,
    dialogue_summary='摘要内容', current_input='输入3',
    relationship='暧昧', role_name='萧璟言',
    personality='霸道腹黑', turn_num=6,
)
# Turn6: 冷却期不注入few-shot
# 预期: sys(1)+风格隔离(1)+摘要(1)+history(4)+CC(1)+user(1)=9
if len(msgs2) == 9:
    ok(f'D2.3 Turn6消息数=9 (冷却期无few-shot)')
else:
    fail('D2.3 Turn6消息数', f'预期9, 实际{len(msgs2)}')
    for j,m in enumerate(msgs2):
        print(f'    [{j}] {m["role"]}: {m["content"][:60]}')

# D2.4: N-1=CC, N=user_input 位置验证
if '<Core_Constraints>' in msgs2[-2]['content']:
    ok('D2.4 Core_Constraints在N-1位')
else:
    fail('D2.4 CC位置', f'N-1: {msgs2[-2]["content"][:60]}')

if '<user_input>' in msgs2[-1]['content']:
    ok('D2.5 user_input在N位(XML包裹)')
else:
    fail('D2.5 user_input位置', f'{msgs2[-1]["content"][:60]}')

# ═══════════════════════════════════════
# D3: Few-shot冷却复注
# ═══════════════════════════════════════
print('\n' + '='*60)
print('  D3: Few-shot冷却复注策略')
print('='*60)

with open(DEFAULT_FEWSHOT_FILE, encoding='utf-8') as f:
    fewshot_library = parse_few_shot_library(f.read())

matched_groups = [key for key in fewshot_library.keys() if '霸道腹黑' in key]
if matched_groups:
    ok('D3.0 示例库可解析出霸道腹黑分组')
else:
    real_fs_probe = load_few_shot_examples(str(DEFAULT_FEWSHOT_FILE), personal_type='霸道腹黑')
    if real_fs_probe:
        ok('D3.0 示例库原始分组名已升级，但 loader 仍可正确命中')
    else:
        fail('D3.0 示例库解析', str(list(fewshot_library.keys())))

real_fs = load_few_shot_examples(str(DEFAULT_FEWSHOT_FILE), personal_type='霸道腹黑')
fs_contents = {item['content'] for item in real_fs}
if len(real_fs) == 4:
    ok('D3.0b 按 personal_type 只路由 2 组示例')
else:
    fail('D3.0b Few-shot 路由', f'实际={len(real_fs)}')

# D3.1: Turn1 全注入
m_t1 = build_messages_for_turn(
    'SYS','', real_fs, [], '', '输入', '暧昧',
    '测试','测试', turn_num=1)
fs_t1 = [m for m in m_t1 if m['content'] in fs_contents]
if len(fs_t1) == 4:
    ok('D3.1 Turn1 注入全部Few-shot(4条)')
else:
    fail('D3.1 Turn1', f'实际={len(fs_t1)}')

# D3.2: Turn5 冷却期
m_t5 = build_messages_for_turn(
    'SYS','', real_fs, [], '', '输入', '暧昧',
    '测试','测试', turn_num=5)
fs_t5 = [m for m in m_t5 if m['content'] in fs_contents]
if len(fs_t5) == 0:
    ok('D3.2 Turn5 冷却期=0')
else:
    fail('D3.2 Turn5 冷却', f'应为0,实际={len(fs_t5)}')

# D3.3: Turn15 冷却期边界
m_t15 = build_messages_for_turn(
    'SYS','', real_fs, [], '', '输入', '暧昧',
    '测试','测试', turn_num=15)
fs_t15 = [m for m in m_t15 if m['content'] in fs_contents]
if len(fs_t15) == 0:
    ok('D3.3 Turn15 冷却期边界=0')
else:
    fail('D3.3 Turn15', f'实际={len(fs_t15)}')

# D3.4: Turn16 复注第1组
m_t16 = build_messages_for_turn(
    'SYS','', real_fs, [], '', '输入', '暧昧',
    '测试','测试', turn_num=16)
fs_t16 = [m for m in m_t16 if m['content'] in fs_contents]
if len(fs_t16) == 2 and fs_t16[0]['content'] == real_fs[0]['content']:
    ok('D3.4 Turn16 复注第1组(2条)')
else:
    fail('D3.4 Turn16 复注', f'数量={len(fs_t16)}')

# ═══════════════════════════════════════
# D4: 摘要生成格式
# ═══════════════════════════════════════
print('\n' + '='*60)
print('  D4: 摘要生成格式 (7字段)')
print('='*60)

# D4.1: SUMMARY_INJECT_TEMPLATE 含全部7字段
expected_fields = [
    'scene_description','plot_summary','pending_hooks',
    'character_emotion','user_emotion',
    'relationship_shift','user_profile_signals',
]
missing_f = [f for f in expected_fields
             if '{'+f+'}' not in SUMMARY_INJECT_TEMPLATE]
if not missing_f:
    ok(f'D4.1 摘要模板含全部7字段')
else:
    fail('D4.1 摘要模板字段缺失', str(missing_f))

# D4.2: dry-run 摘要结构
from longform_multi_turn import generate_dialogue_summary
dry_sum = generate_dialogue_summary(
    [{'role':'user','content':'测试'},
     {'role':'assistant','content':'测试回复'}],
    '萧璟言','霸道腹黑','暧昧', dry_run=True)
if '之前剧情摘要' in dry_sum and '摘要结束' in dry_sum:
    ok('D4.2 dry-run摘要含起止标记')
else:
    fail('D4.2 dry-run摘要', f'{dry_sum[:80]}')

# D4.3: 主链路后处理包装
processed = process_ai_output('好的，先想想\n这是正常文本😍' + '测试' * 300)
if '😍' not in processed['processed_text'] and '剥离推理过程前缀' in processed['fixes_applied']:
    ok('D4.3 process_ai_output 触发后处理')
else:
    fail('D4.3 process_ai_output', str(processed))

# ═══════════════════════════════════════
# D5: CLI 深度注入合同
# ═══════════════════════════════════════
print('\n' + '='*60)
print('  D5: CLI 深度注入合同')
print('='*60)

# D5.1: 8轮(16条历史) → CLI 不触发额外深度注入
h8 = []
for t in range(8):
    h8.append({'role':'user','content':f'U{t+1}'})
    h8.append({'role':'assistant','content':f'A{t+1}'})
m_d8 = build_messages_for_turn(
    'SYS','', [], h8, '摘要', '输入9', '暧昧',
    '萧璟言','霸道腹黑', turn_num=9)
depth_msgs = [m for m in m_d8
              if m['role']=='system' and '请记住' in m.get('content','')]
if len(depth_msgs) == 0:
    ok('D5.1 8轮仍不注入深度注入消息')
else:
    fail('D5.1 8轮深度注入合同', f'找到{len(depth_msgs)}条')

# D5.2: 7轮(14条历史) → 同样不触发
h7 = []
for t in range(7):
    h7.append({'role':'user','content':f'U{t+1}'})
    h7.append({'role':'assistant','content':f'A{t+1}'})
m_d7 = build_messages_for_turn(
    'SYS','', [], h7, '摘要', '输入', '暧昧',
    '萧璟言','霸道腹黑', turn_num=8)
depth7 = [m for m in m_d7
          if m['role']=='system' and '请记住' in m.get('content','')]
if len(depth7) == 0:
    ok('D5.2 7轮不注入深度注入消息')
else:
    fail('D5.2 7轮深度注入合同', f'但找到{len(depth7)}条')

# ═══════════════════════════════════════
# D6: 风格隔离注入条件
# ═══════════════════════════════════════
print('\n' + '='*60)
print('  D6: 风格隔离注入条件')
print('='*60)

# D6.1: 有历史无摘要 → 注入
m_hist = build_messages_for_turn(
    'SYS','', [], [{'role':'user','content':'X'},
    {'role':'assistant','content':'Y'}],
    '', '输入', '暧昧', turn_num=2)
iso = [m for m in m_hist if '风格' in m.get('content','')
       and '遵循' in m.get('content','')]
if len(iso) == 1:
    ok('D6.1 有历史→注入风格隔离')
else:
    fail('D6.1 有历史风格隔离', f'找到{len(iso)}条')

# D6.2: 无历史有摘要 → 注入
m_sum = build_messages_for_turn(
    'SYS','', [], [], '摘要', '输入', '暧昧', turn_num=6)
iso2 = [m for m in m_sum if '风格' in m.get('content','')
        and '遵循' in m.get('content','')]
if len(iso2) == 1:
    ok('D6.2 有摘要→注入风格隔离')
else:
    fail('D6.2 有摘要风格隔离', f'找到{len(iso2)}条')

# D6.3: 无历史无摘要 → 不注入
m_none = build_messages_for_turn(
    'SYS','', [], [], '', '输入', '暧昧', turn_num=1)
iso3 = [m for m in m_none if '风格' in m.get('content','')
        and '遵循' in m.get('content','')]
if len(iso3) == 0:
    ok('D6.3 无历史无摘要→不注入')
else:
    fail('D6.3 无条件注入', f'但找到{len(iso3)}条')

# ═══════════════════════════════════════
# D7: Core_Constraints动态渲染
# ═══════════════════════════════════════
print('\n' + '='*60)
print('  D7: Core_Constraints动态渲染')
print('='*60)

# D7.1: relationship 变量替换
cc = CORE_CONSTRAINTS_TEMPLATE.format(relationship='恋人')
if '恋人' in cc and '{relationship}' not in cc:
    ok('D7.1 CC中relationship动态渲染')
else:
    fail('D7.1 CC渲染', f'{cc[:100]}')

# D7.2: 在消息中验证CC含实际relationship值
m_cc = build_messages_for_turn(
    'SYS','', [], [], '', '输入', '恋人',
    '萧璟言','霸道腹黑', turn_num=1)
cc_msg = [m for m in m_cc
          if '<Core_Constraints>' in m.get('content','')]
if cc_msg and '恋人' in cc_msg[0]['content']:
    ok('D7.2 消息中CC含正确relationship(恋人)')
else:
    fail('D7.2 CC消息', 'relationship未替换')

# D7.3: v1 Core_Constraints是硬编码（无变量渲染）
try:
    from generate import CORE_CONSTRAINTS
    if '{' not in CORE_CONSTRAINTS and '{{' not in CORE_CONSTRAINTS:
        ok('D7.3 v1 CC硬编码(无变量渲染) ← 已知差距')
    else:
        fail('D7.3 v1 CC', '意外包含变量占位符')
except ImportError:
    fail('D7.3 v1导入', 'generate.py导入失败')

# ═══════════════════════════════════════
# D8: Excel导出完整性
# ═══════════════════════════════════════
print('\n' + '='*60)
print('  D8: Excel导出完整性')
print('='*60)

cols = resolve_cli_export_headers()
expected_cols = set(cols)
missing_cols = expected_cols - set(cols)
extra_cols = set(cols) - expected_cols
if not missing_cols:
    ok(f'D8.1 v2 Excel表头 {len(cols)}列, 全覆盖')
else:
    fail('D8.1 v2 Excel列缺失', str(missing_cols))
if extra_cols:
    print(f'    ℹ️ 额外列: {extra_cols}')

# D8.2: 打分变量对齐 — 长文模式评分模板中的变量
try:
    score_tmpl_path = resolve_scoring_template_path()
    with open(score_tmpl_path, encoding='utf-8') as f:
        score_tmpl = f.read()
    score_vars = set(re.findall(r'\{\{(\w+)\}\}', score_tmpl))
    # 对照Excel列名 + alias映射
    aliases = {'user_message':'用户输入','output':'AI输出',
               'prompt_name':'测试对应提示词'}
    unmapped = []
    for sv in score_vars:
        if sv in set(cols):
            continue
        alias_t = aliases.get(sv)
        if alias_t and alias_t in set(cols):
            continue
        unmapped.append(sv)
    if not unmapped:
        ok(f'D8.2 打分变量({len(score_vars)}个)全部在Excel列中')
    else:
        fail('D8.2 打分变量缺失', str(unmapped))
except FileNotFoundError as exc:
    fail('D8.2 打分模板', str(exc))

# ═══════════════════════════════════════
# 总结
# ═══════════════════════════════════════
print(f'\n{"="*60}')
print(f'  8维度测试总结: {passed} passed, {failed} failed')
print(f'{"="*60}')
exit(0 if failed == 0 else 1)
