"""
前端修复补丁脚本，完成三项改动：
1. 将 personal_type 从 <select> 改成 <input>
2. 在 presets.py 添加 /api/presets/variables 接口
3. 在 legacy_bundle.js 添加自动填充逻辑
"""
import os

# ─── 1. 修改 index.html: 性格类型从select改input ───────────────
html_path = r'E:\提效工具\长文模式生成\server\static\index.html'
with open(html_path, 'r', encoding='utf-8') as f:
    html = f.read()

old_personal = '性格类型 {{personal_type}}</label><select id="f-personal-type" class="form-control"><option>ENTJ</option><option>ENFP</option><option>INTJ</option><option>ISFJ</option></select>'
new_personal = '性格类型 {{personal_type}}</label><input type="text" id="f-personal-type" class="form-control" placeholder="ENTJ">'

if old_personal in html:
    html = html.replace(old_personal, new_personal)
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print("[1] personal_type -> input: OK")
else:
    print("[1] personal_type select not found, skipped")

# ─── 2. 修改 presets.py: 添加 /variables 路由 ──────────────────
presets_path = r'E:\提效工具\长文模式生成\server\routers\presets.py'
with open(presets_path, 'r', encoding='utf-8') as f:
    presets_code = f.read()

if '/variables' not in presets_code:
    # 在文件末尾追加新路由
    append_code = '''

@router.get("/variables")
async def get_longform_variables(
    personality: str = "",
    relationship: str = "暧昧",
    gender: str = "男",
):
    """根据性格+关系+性别 返回长文专属变量（persona/narrative_style/关系联动）"""
    from services.prompt_service import PromptService
    from config import PRESET_CHARACTERS, RELATIONSHIP_PRESETS

    ps = PromptService()
    result = {}

    # 1. 查找 persona_file
    persona_file = ""
    for pid, preset in PRESET_CHARACTERS.items():
        if preset["type"] == personality:
            persona_file = preset.get("persona_file", "")
            break

    # 2. 加载 persona block
    if persona_file:
        result["longform_persona"] = ps.load_persona_block(
            persona_file, gender, relationship
        )

    # 3. 加载 narrative_style
    result["longform_narrative_style"] = ps.load_narrative_style(personality)

    # 4. 关系联动
    rel_data = RELATIONSHIP_PRESETS.get(relationship, {})
    result["intimacy_boundary"] = rel_data.get("intimacy_boundary", "")
    result["relation_calling"] = rel_data.get("relation_calling", "")
    result["relation_info"] = rel_data.get("relation_info", "")

    return result
'''
    with open(presets_path, 'a', encoding='utf-8') as f:
        f.write(append_code)
    print("[2] /api/presets/variables route: ADDED")
else:
    print("[2] /variables route already exists, skipped")

# ─── 3. 修改 legacy_bundle.js: 添加自动填充逻辑 ──────────────
js_path = r'E:\提效工具\长文模式生成\server\static\js\legacy_bundle.js'
with open(js_path, 'r', encoding='utf-8') as f:
    js = f.read()

# 在 updateRelLinkage 函数后面添加自动拉取变量逻辑
auto_fill_code = '''
    /* ═══ 长文专属变量自动填充 ═══ */
    async function autoFillLongformVars() {
      const personality = $('f-personality') ? $('f-personality').value : '';
      const relationship = $('f-relationship') ? $('f-relationship').value : '';
      const gender = $('f-gender') ? $('f-gender').value : '男';
      if (!personality) return;
      try {
        const params = new URLSearchParams({ personality, relationship, gender });
        const r = await fetch('/api/presets/variables?' + params);
        const data = await r.json();
        if (data.longform_persona && $('f-sys-persona')) $('f-sys-persona').value = data.longform_persona;
        if (data.longform_narrative_style && $('f-sys-style')) $('f-sys-style').value = data.longform_narrative_style;
        if (data.intimacy_boundary && $('f-intimacy-boundary')) $('f-intimacy-boundary').value = data.intimacy_boundary;
        if (data.relation_calling && $('f-relation-calling')) $('f-relation-calling').value = data.relation_calling;
        if (data.relation_info && $('f-relation-info')) $('f-relation-info').value = data.relation_info;
        showToast('⚡ 长文变量已同步', 'success');
      } catch(e) { console.warn('自动填充失败:', e); }
    }
'''

# 找到 updateRelLinkage 函数的尾巴
anchor = 'function updateRelLinkage()'
if anchor in js and 'autoFillLongformVars' not in js:
    # 在 updateRelLinkage 函数体 } 后面插入
    idx = js.find(anchor)
    # 找到函数体结束的 }
    brace_count = 0
    i = js.find('{', idx)
    for j in range(i, len(js)):
        if js[j] == '{': brace_count += 1
        elif js[j] == '}': brace_count -= 1
        if brace_count == 0:
            # j 是 updateRelLinkage 的结束 }
            insert_pos = j + 1
            break

    # 同时修改 updateRelLinkage 使之触发自动填充
    # 找到该函数的最后一行（}之前）插入 autoFillLongformVars()
    call_inject = '\n      autoFillLongformVars();'

    # 在函数尾部 } 之前注入调用
    js = js[:j] + call_inject + '\n    ' + js[j:]
    # 在函数之后注入定义
    insert_pos = j + len(call_inject) + 6  # 补偿刚插入的字符
    js = js[:insert_pos] + auto_fill_code + js[insert_pos:]

    # 同时给 f-personality 的 onchange 添加事件
    # 通过在 DOMContentLoaded 中绑定
    init_anchor = "document.addEventListener('DOMContentLoaded'"
    if init_anchor in js:
        init_idx = js.find(init_anchor)
        arrow_idx = js.find('{', init_idx)
        bind_code = "\n      if($('f-personality')) $('f-personality').addEventListener('change', autoFillLongformVars);\n      if($('f-gender')) $('f-gender').addEventListener('change', autoFillLongformVars);"
        js = js[:arrow_idx+1] + bind_code + js[arrow_idx+1:]

    with open(js_path, 'w', encoding='utf-8') as f:
        f.write(js)
    print("[3] autoFillLongformVars: ADDED")
else:
    if 'autoFillLongformVars' in js:
        print("[3] autoFillLongformVars already exists, skipped")
    else:
        print("[3] updateRelLinkage not found, skipped")

print("\n=== All patches applied! ===")
