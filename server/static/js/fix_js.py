"""Rewrite initFreeChatPage & sendFreeChat to use slot-based model cards (Volcengine style)."""
path = r"E:\提效工具\长文模式生成\server\static\js\legacy_bundle.js"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# ---- Replace initFreeChatPage ----
old_init_start = "    async function initFreeChatPage() {"
old_init_end = "      } catch (e) { console.warn('\u6a21\u578b\u52a0\u8f7d\u5931\u8d25:', e); }\n    }"

idx_a = content.find(old_init_start)
idx_b = content.find(old_init_end, idx_a)
if idx_a < 0 or idx_b < 0:
    print(f"FAIL initFreeChatPage: start={idx_a}, end={idx_b}"); exit(1)
idx_b += len(old_init_end)

new_init = '''    let _freeChatModelList = [];
    async function initFreeChatPage() {
      if (_freeChatModelList.length > 0) return;
      try {
        const r = await fetch('/api/models'); const data = await r.json();
        _freeChatModelList = (data.models || data || []).map(m => ({ id: m.id || m, name: m.name || m.id || m }));
        // Auto-add first slot
        if ($('freechat-model-slots').children.length === 0) addModelSlot();
      } catch (e) { console.warn('\\u6a21\\u578b\\u52a0\\u8f7d\\u5931\\u8d25:', e); }
    }

    function addModelSlot() {
      const slots = $('freechat-model-slots');
      if (slots.children.length >= 3) { showToast('\\u6700\\u591a\\u652f\\u6301 3 \\u4e2a\\u6a21\\u578b\\u5e76\\u884c', 'warning'); return; }
      const slotIdx = slots.children.length;
      const colors = ['#1664ff', '#00b42a', '#ff7d00'];
      const color = colors[slotIdx % 3];

      const slot = document.createElement('div');
      slot.className = 'fc-model-slot';
      slot.dataset.slotIdx = slotIdx;
      slot.style.cssText = `display:flex;align-items:center;gap:0;padding:0 0;border-right:1px solid var(--border-light);position:relative;`;

      // Model name dropdown button
      const nameBtn = document.createElement('button');
      nameBtn.className = 'fc-slot-name';
      nameBtn.style.cssText = `background:none;border:none;padding:8px 12px;cursor:pointer;font-size:13px;font-weight:600;color:${color};display:flex;align-items:center;gap:4px;white-space:nowrap`;
      const defaultModel = _freeChatModelList[slotIdx] || _freeChatModelList[0] || { id: '', name: '\\u9009\\u62e9\\u6a21\\u578b' };
      slot.dataset.modelId = defaultModel.id;
      slot.dataset.modelName = defaultModel.name;
      nameBtn.innerHTML = `<span class="fc-slot-label">${escapeHtml(defaultModel.name)}</span> <span style="font-size:10px;color:var(--text-tertiary)">\\u25bc</span>`;
      nameBtn.onclick = (e) => toggleModelDropdown(slot, e);

      // \\u22ee settings button
      const settingsBtn = document.createElement('button');
      settingsBtn.style.cssText = 'background:none;border:none;padding:6px 8px;cursor:pointer;color:var(--text-tertiary);font-size:16px;font-weight:bold';
      settingsBtn.title = '\\u7f16\\u8f91\\u72ec\\u7acb System Prompt';
      settingsBtn.innerHTML = '\\u22ee';
      settingsBtn.onclick = () => openFreeChatPrompt(slot.dataset.modelId, slot.dataset.modelName);

      // x close button
      const closeBtn = document.createElement('button');
      closeBtn.style.cssText = 'background:none;border:none;padding:6px 8px;cursor:pointer;color:var(--text-tertiary);font-size:14px';
      closeBtn.innerHTML = '\\u00d7';
      closeBtn.onclick = () => { slot.remove(); };

      slot.appendChild(nameBtn);
      slot.appendChild(settingsBtn);
      slot.appendChild(closeBtn);
      slots.appendChild(slot);
    }

    function toggleModelDropdown(slot, e) {
      // Close any existing dropdown
      document.querySelectorAll('.fc-model-dropdown').forEach(d => d.remove());

      const dropdown = document.createElement('div');
      dropdown.className = 'fc-model-dropdown';
      dropdown.style.cssText = 'position:absolute;top:100%;left:0;background:var(--bg-surface);border:1px solid var(--border-light);border-radius:8px;box-shadow:0 4px 12px rgba(0,0,0,0.1);z-index:100;min-width:220px;max-height:300px;overflow-y:auto;padding:4px 0';

      _freeChatModelList.forEach(m => {
        const item = document.createElement('div');
        const isActive = slot.dataset.modelId === m.id;
        item.style.cssText = `padding:8px 16px;cursor:pointer;font-size:13px;display:flex;justify-content:space-between;align-items:center;${isActive ? 'background:#e6f4ff;color:var(--primary-color)' : ''}`;
        item.innerHTML = `<span>${escapeHtml(m.name)}</span>${isActive ? '<span>\\u2713</span>' : ''}`;
        item.onmouseenter = () => { if (!isActive) item.style.background = 'var(--bg-hover)'; };
        item.onmouseleave = () => { if (!isActive) item.style.background = ''; };
        item.onclick = () => {
          slot.dataset.modelId = m.id;
          slot.dataset.modelName = m.name;
          slot.querySelector('.fc-slot-label').textContent = m.name;
          dropdown.remove();
        };
        dropdown.appendChild(item);
      });

      slot.appendChild(dropdown);
      // Close on outside click
      setTimeout(() => {
        const handler = (ev) => { if (!dropdown.contains(ev.target)) { dropdown.remove(); document.removeEventListener('click', handler); } };
        document.addEventListener('click', handler);
      }, 0);
    }'''

content = content[:idx_a] + new_init + content[idx_b:]

# ---- Replace sendFreeChat's model gathering ----
old_checked = "      const checked = [...$('freechat-model-checks').querySelectorAll('input:checked')];"
old_check_len = "      if (!checked.length) { showToast('\\u8bf7\\u81f3\\u5c11\\u9009\\u62e9 1 \\u4e2a\\u6a21\\u578b', 'warning'); return; }"
old_check_max = "      if (checked.length > 3) { showToast('\\u6700\\u591a\\u652f\\u6301 3 \\u4e2a\\u6a21\\u578b\\u5e76\\u884c', 'warning'); return; }"

new_gather = """      const slots = [...$('freechat-model-slots').querySelectorAll('.fc-model-slot')];
      if (!slots.length) { showToast('\\u8bf7\\u5148\\u6dfb\\u52a0\\u6a21\\u578b', 'warning'); return; }"""

idx_c = content.find(old_checked)
if idx_c < 0:
    print("WARN: old checked line not found, trying alternate"); 
    # It might have been already updated
    print("Skipping sendFreeChat model gathering update")
else:
    idx_d = content.find(old_check_max, idx_c)
    if idx_d < 0:
        print("WARN: old check max not found")
    else:
        idx_d += len(old_check_max)
        content = content[:idx_c] + new_gather + content[idx_d:]

# ---- Replace model_ids in fetch body ----
old_body = "model_ids: checked.map(c => c.value)"
new_body = "model_ids: slots.map(s => s.dataset.modelId)"
content = content.replace(old_body, new_body, 1)

# ---- Replace checked[i]?.dataset?.name with slot reference ----
old_name_ref = "checked[i]?.dataset?.name"
new_name_ref = "slots[i]?.dataset?.modelName"
content = content.replace(old_name_ref, new_name_ref, 1)

# ---- Update clearFreeChat to use new HTML ----
old_clear_inner = "freechat-model-checks"
# This doesn't exist anymore in the HTML, so no need to change clearFreeChat

with open(path, "w", encoding="utf-8") as f:
    f.write(content)

print("OK: JS rewritten for slot-based model cards")
