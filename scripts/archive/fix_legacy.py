import re

with open('server/static/js/legacy_bundle.js', 'r', encoding='utf-8') as f:
    text = f.read()

pattern = r"function renderVariablePreviewTags\(varMap\) \{.*?\}.*?function resolveSystemPromptPreview\(spRaw, varMap\) \{"
match = re.search(pattern, text, re.DOTALL)
if match:
    old_text = match.group(0)
    
    new_text = '''function renderVariablePreviewTags(varMap) {
    const container = sp-variable-preview;
    if(!container) return;
    
    window.customVarOverrides = window.customVarOverrides || {};
    const keys = Object.keys(varMap);

    if(keys.length === 0) {
      container.innerHTML = '<span class="tag">暂无提取到的变量</span>';
      return;
    }
    
    let html = '<div style="display:flex;flex-direction:column;gap:8px;padding:8px 0;">';
    keys.forEach(k => {
      const originalVal = varMap[k] || '';
      const currentVal = window.customVarOverrides[k] !== undefined ? window.customVarOverrides[k] : originalVal;
      const isMissing = !originalVal || originalVal.trim() === '';
      const isOverridden = window.customVarOverrides[k] !== undefined && window.customVarOverrides[k] !== originalVal;
      
      html += 
        <div style="display:flex;align-items:center;gap:12px;">
          <span style="width:140px;text-align:right;font-size:12px;font-weight:600;color:var(--text-primary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="">{{}}</span>
          <input type="text" 
                 class="form-control" 
                 style="flex:1;height:28px;font-size:12px;font-family:monospace;" 
                 value="" 
                 placeholder=""
                 oninput="window.updateCustomVar('', this.value)"
                 >
        </div>;
    });
    html += '</div><div style="font-size:12px;color:var(--text-tertiary);margin-top:4px;padding-left:152px;">💡 提示：直接在此修改变量值，下方预览将实时同步，并会在点击「开始独立测试」或「多模型对比」时生效参与大模型对话。</div>';
    
    container.innerHTML = html;
}

window.updateCustomVar = function(key, val) {
    window.customVarOverrides = window.customVarOverrides || {};
    window.customVarOverrides[key] = val;
    
    const spRaw = window._currentSP || '';
    if(spRaw) {
        const varMap = Object.assign({}, window._lastVarMap || {});
        Object.assign(varMap, window.customVarOverrides);
        let resolved = resolveSystemPromptPreview(spRaw, varMap);
        const previewEl = sp-preview-content;
        if (previewEl) {
            previewEl.innerHTML = resolved;
        }
    }
};

function resolveSystemPromptPreview(spRaw, varMap) {
    let resolved = spRaw;
    window._lastVarMap = Object.assign({}, varMap);
    const mergedMap = Object.assign({}, varMap, window.customVarOverrides || {});
    varMap = mergedMap;'''

    text = text.replace(old_text, new_text)
    print("Replaced successfully!")
else:
    print("Pattern not found!")

with open('server/static/js/legacy_bundle.js', 'w', encoding='utf-8') as f:
    f.write(text)
