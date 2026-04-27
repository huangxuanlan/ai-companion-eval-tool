import re

with open('longform_multi_turn.py', 'r', encoding='utf-8') as f:
    text = f.read()

broken_pattern = re.compile(r'        "current_scene",\s+3\. 每 5 轮暂停：调用 mini → 生成摘要 → 注入变量 → 重新渲染 system prompt\s+"""\s+# ── 1\. 加载模板 ──')

fixed_replacement = '''        "current_scene",
    ]:
        variables[key] = ctx.get(key, "")

    # 系统模块变量
    modules = config.get("modules", {})
    for key in [
        "system_module8", "longform_persona", "longform_narrative_style",
        "system_Role_acting", "weekly_schedule", "dialogueStartPrompt",
        "longform_few_shot", "user_Nickname", "user_gender", "user_identity",
    ]:
        variables[key] = modules.get(key, ctx.get(key, char.get(key, "")))
    
    # dialogue_summary 初始为空（由脚本动态生成）
    variables.setdefault("dialogue_summary", "")

    # 合并额外的自定义变量（来自前端变量预览的编辑覆盖）
    custom_vars = config.get("custom_variables", {})
    if custom_vars:
        variables.update(custom_vars)
        
    return variables


def run_conversation_chain(config: dict, max_turns: int = None, dry_run: bool = False):
    """
    执行多轮对话链。

    核心流程：
      1. 加载模板 → 注入变量 → 得到 system prompt
      2. 逐轮执行：组装 messages → 调用 pro API → 拼接历史
      3. 每 5 轮暂停：调用 mini → 生成摘要 → 注入变量 → 重新渲染 system prompt
    """
    # ── 1. 加载模板 ──'''

if broken_pattern.search(text):
    text = broken_pattern.sub(fixed_replacement, text)
    print('Fixed gracefully with regex!')
else:
    print('Still could not find it! Checking what it looks like:')
    start = text.find('current_scene')
    if start != -1:
        print(repr(text[start:start+200]))

with open('longform_multi_turn.py', 'w', encoding='utf-8') as f:
    f.write(text)

