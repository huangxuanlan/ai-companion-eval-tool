import re
with open(r'E:\提效工具\长文模式生成\server\static\js\legacy_bundle.js', 'r', encoding='utf-8') as f:
    content = f.read()

correct_code = '''    /* ═══ Excel 配置导入/导出 ═══ */
    function getFormConfig() {
      return {
        nickname: $('f-nickname').value, gender: $('f-gender').value, age: $('f-age').value,
        occupation: $('f-occupation').value, personality: $('f-personality').value,
        speaking_style: $('f-speaking-style').value, background: $('f-background').value,
        hobby: $('f-hobby').value, relationship: $('f-relationship').value,
        scene: $('f-scene').value, time_period: $('f-timeperiod').value, season: $('f-season').value,
        user_nickname: $('f-user-nickname').value, user_gender: $('f-user-gender').value,
        user_identity: $('f-user-identity').value, turns: $('f-turns').value,
        prompt_version: $('f-prompt-version').value, summary_interval: $('f-summary-interval').value,
        injection_depth: $('f-injection-depth').value,
        model_pro: $('f-model-pro').value, model_mini: $('f-model-mini').value,
        sys_persona: $('f-sys-persona').value, sys_style: $('f-sys-style').value,
        sys_fewshot: $('f-sys-fewshot').value, sys_startprompt: $('f-sys-startprompt').value,
        sys_summary: $('f-sys-summary').value, sys_module8: $('f-sys-module8').value,
      };
    }
    function setFormConfig(cfg) {
      const map = {
        'f-nickname': cfg.nickname, 'f-gender': cfg.gender, 'f-age': cfg.age,
        'f-occupation': cfg.occupation, 'f-personality': cfg.personality,
        'f-speaking-style': cfg.speaking_style, 'f-background': cfg.background,
        'f-hobby': cfg.hobby, 'f-relationship': cfg.relationship,
        'f-scene': cfg.scene, 'f-timeperiod': cfg.time_period, 'f-season': cfg.season,
        'f-user-nickname': cfg.user_nickname, 'f-user-gender': cfg.user_gender,
        'f-user-identity': cfg.user_identity, 'f-turns': cfg.turns,
        'f-prompt-version': cfg.prompt_version, 'f-summary-interval': cfg.summary_interval,
        'f-injection-depth': cfg.injection_depth,
        'f-model-pro': cfg.model_pro, 'f-model-mini': cfg.model_mini,
        'f-sys-persona': cfg.sys_persona, 'f-sys-style': cfg.sys_style,
        'f-sys-fewshot': cfg.sys_fewshot, 'f-sys-startprompt': cfg.sys_startprompt,
        'f-sys-summary': cfg.sys_summary, 'f-sys-module8': cfg.sys_module8,
      };
      Object.entries(map).forEach(([id, v]) => { const el = $(id); if (el && v !== undefined && v !== null) el.value = v; });
      updateRelLinkage();
      syncLongformModules(true);
      refreshSPPreview();
    }'''

target_pattern = r'    /\* ═══ Excel 配置导入/导出 ═══ \*/[\s\S]*?refreshSPPreview\(\);\n    \}'

content = re.sub(target_pattern, correct_code, content)

with open(r'E:\提效工具\长文模式生成\server\static\js\legacy_bundle.js', 'w', encoding='utf-8') as f:
    f.write(content)

print('Fixed getFormConfig successfully')
