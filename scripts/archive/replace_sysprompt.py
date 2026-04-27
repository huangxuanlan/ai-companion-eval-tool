import os

filepath = r'E:\提效工具\长文模式生成\server\static\index.html'

with open(filepath, 'r', encoding='utf-8') as f:
    text = f.read()

start_tag = '<div class="form-item">\n          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">'
end_tag = '<div style="display:flex;align-items:center;gap:8px;margin-top:8px"><label class="switch">'

s_idx = text.find(start_tag)
e_idx = text.find(end_tag, s_idx)

if s_idx == -1 or e_idx == -1:
    print('Error finding sys prompt tags!')
    exit(1)

new_content = """<div class="form-item accordion open">
          <div class="accordion-header" style="justify-content:space-between;align-items:center;margin-bottom:6px;padding:0;background:transparent;border:none" onclick="this.parentElement.classList.toggle('open')">
            <div style="display:flex;align-items:center;gap:4px">
              <label class="form-label" style="margin-bottom:0;cursor:pointer">System Prompt</label>
              <svg viewBox="0 0 24 24" class="icon chevron" fill="none" stroke="currentColor"><polyline points="6 9 12 15 18 9"/></svg>
            </div>
          </div>
          <div class="accordion-content" style="padding:0">
            <div style="display:flex;justify-content:flex-end;gap:4px;margin-bottom:6px">
              <button class="btn btn-secondary" style="padding:2px 6px;font-size:12px" title="编辑" onclick="toggleSystemPromptEdit(event)">✏️</button>
              <button class="btn btn-secondary" style="padding:2px 6px;font-size:12px" title="全屏" onclick="switchPage('prompts');event.stopPropagation()">↗</button>
              <button class="btn btn-secondary" style="padding:2px 6px;font-size:12px" title="导入" onclick="document.getElementById('sys-prompt-upload').click();event.stopPropagation()">📥</button>
              <input type="file" id="sys-prompt-upload" accept=".md,.txt" style="display:none" onchange="importSystemPrompt(event)">
            </div>
            <div id="sys-prompt-display" class="form-control" style="font-family:var(--font);min-height:120px;max-height:240px;overflow-y:auto;background:var(--bg-surface);font-size:12px;line-height:1.5;white-space:pre-wrap;cursor:pointer" ondblclick="toggleSystemPromptEdit(event)">（双击编辑，或点击 ✏️ 图标）</div>
            <textarea id="f-sys-prompt" class="form-control" style="font-family:var(--font);min-height:120px;max-height:240px;display:none;font-size:12px;line-height:1.5" placeholder="在此输入 System Prompt..."></textarea>
            <div style="text-align:right;margin-top:4px"><button id="btn-preview-vars" class="btn btn-secondary" style="font-size:12px;padding:2px 8px" onclick="previewReplacedPrompt(event)">👁 预览替换后</button></div>
          </div>
        </div>

        """

new_text = text[:s_idx] + new_content + text[e_idx:]

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(new_text)

print("Sys Prompt Replacement Complete")
