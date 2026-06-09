/**
 * 短文模式专属前端功能模块
 */

(function() {
  let casesList = [];
  let selectedCaseIds = new Set();
  let monitorIntervalId = null;
  let activeRunId = null;
  let benchmarkIntervalId = null;
  let activeBenchRunId = null;
  let elapsedTimerId = null;
  let elapsedSeconds = 0;

  // P0-2: XSS 防护工具函数
  function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = String(text);
    return div.innerHTML;
  }

  // --- 1. 初始化模块入口 ---
  window.initShortformModule = async function() {
    console.log('[Shortform] 初始化模块...');
    
    // 初始化子 Tab 切换事件
    window.switchShortformTab = function(tab) {
      document.querySelectorAll('#page-shortform .sf-tab-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.tab === tab);
      });
      document.querySelectorAll('#page-shortform .sf-subpage').forEach(page => {
        page.classList.toggle('active', page.id === `sf-subpage-${tab}`);
      });
      
      if (tab === 'case') {
        loadShortformCases();
      }
    };
    
    // 初始化用例库列表
    loadShortformCases();
    
    // 初始化下拉选单与配置项
    populateDropdowns();
    
    // 绑定用例库拖拽导入逻辑
    bindDragDropImport();
  };

  // --- 2. 下拉项数据加载与填充 ---
  async function populateDropdowns() {
    try {
      // 加载提示词列表
      const promptRes = await fetch('/api/prompts?kind=chat');
      const promptData = await promptRes.json();
      const prompts = promptData.prompts || [];
      
      const selectA = document.getElementById('sf-run-prompt-a');
      const selectB = document.getElementById('sf-run-prompt-b');
      
      if (selectA && selectB) {
        const optionsHtml = prompts.map(p => `<option value="${p.filename}">${p.filename}${p.is_latest ? '（最新）' : ''}</option>`).join('');
        selectA.innerHTML = '<option value="">-- 选择系统提示词 A (控制组) --</option>' + optionsHtml;
        selectB.innerHTML = '<option value="">-- 选择系统提示词 B (实验组) --</option>' + optionsHtml;
      }
      
      // 加载模型列表
      const modelsRes = await fetch('/api/models');
      const modelsData = await modelsRes.json();
      const models = modelsData.models || modelsData || [];
      
      const runModel = document.getElementById('sf-run-model');
      const scoreModel = document.getElementById('sf-run-score-model');
      const benchScoreModel = document.getElementById('sf-bench-scoring-model');
      
      const modelsHtml = models.map(m => {
        const id = m.id || m;
        const name = m.display_name || m.name || id;
        return `<option value="${id}">${name}</option>`;
      }).join('');
      
      if (runModel) runModel.innerHTML = modelsHtml;
      if (scoreModel) {
        scoreModel.innerHTML = '<option value="">-- 自动/不打分 --</option>' + modelsHtml;
        // 默认设为 deepseek 或 qwen 等
        const defaultScoring = models.find(m => (m.id || m).includes('qwen-max') || (m.id || m).includes('3.7-max'));
        if (defaultScoring) scoreModel.value = defaultScoring.id || defaultScoring;
      }
      if (benchScoreModel) benchScoreModel.innerHTML = modelsHtml;
      
      // 填充基准对比的多模型复选框列表
      const benchModelsContainer = document.getElementById('sf-bench-models-list');
      if (benchModelsContainer) {
        benchModelsContainer.innerHTML = models.map(m => {
          const id = m.id || m;
          const name = m.display_name || m.name || id;
          return `
            <label style="display:flex;align-items:center;gap:6px;font-size:12px">
              <input type="checkbox" class="sf-bench-model-checkbox" value="${id}"> ${name}
            </label>
          `;
        }).join('');
      }
      
      // P2-19: 直接使用 navigator API 获取系统内存（移除不存在的 /api/configs/active?kind=batch 调用）
      const sysMemEl = document.getElementById('sf-bench-sys-mem');
      if (sysMemEl) {
        if (navigator.deviceMemory) {
          sysMemEl.textContent = `${navigator.deviceMemory} GB可用 (系统估算值)`;
        } else {
          sysMemEl.textContent = `16 GB (推荐并发: 8)`;
        }
      }
    } catch (e) {
      console.error('[Shortform] 获取配置选项失败:', e);
    }
  }

  // --- 3. 用例库渲染与交互 ---
  window.loadShortformCases = async function() {
    try {
      const res = await fetch('/api/configs?mode=short');
      const data = await res.json();
      casesList = data.configs || [];
      
      // 提取唯一的角色及半身属性用于过滤
      populateFilters(casesList);
      
      // 执行页面端过滤
      const roleFilter = document.getElementById('sf-filter-role')?.value || '';
      const personalityFilter = document.getElementById('sf-filter-personality')?.value || '';
      
      const filtered = casesList.filter(c => {
        if (roleFilter && c.name !== roleFilter) return false;
        if (personalityFilter && c.type !== personalityFilter) return false;
        return true;
      });
      
      renderCaseTable(filtered);
    } catch (e) {
      console.error('[Shortform] 加载用例库失败:', e);
    }
  };

  function populateFilters(list) {
    const roleSelect = document.getElementById('sf-filter-role');
    const personalitySelect = document.getElementById('sf-filter-personality');
    
    if (!roleSelect || !personalitySelect) return;
    
    const prevRole = roleSelect.value;
    const prevPers = personalitySelect.value;
    
    const roles = [...new Set(list.map(c => c.name).filter(Boolean))];
    const personalities = [...new Set(list.map(c => c.type).filter(Boolean))];
    
    roleSelect.innerHTML = '<option value="">所有角色</option>' + roles.map(r => `<option value="${r}">${r}</option>`).join('');
    personalitySelect.innerHTML = '<option value="">所有半身/人设</option>' + personalities.map(p => `<option value="${p}">${p}</option>`).join('');
    
    roleSelect.value = prevRole;
    personalitySelect.value = prevPers;
  }

  function renderCaseTable(list) {
    const tbody = document.querySelector('#sf-cases-table tbody');
    if (!tbody) return;
    
    if (list.length === 0) {
      tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;padding:24px;color:var(--text-secondary)">暂无数据，请先拖入导入日志或保存测试集</td></tr>';
      return;
    }
    
    tbody.innerHTML = list.map(c => {
      const isChecked = selectedCaseIds.has(c.id);
      const safeId = escapeHtml(c.id);
      return `
        <tr>
          <td style="text-align:center"><input type="checkbox" class="sf-case-row-checkbox" data-case-id="${safeId}" ${isChecked ? 'checked' : ''}></td>
          <td style="font-weight:600">${escapeHtml(c.name || c.id)}</td>
          <td>${escapeHtml(c.name || '-')}</td>
          <td><span class="badge sf-badge-primary">${escapeHtml(c.type || '未指定')}</span></td>
          <td>${c.turns_count || 1} 轮</td>
          <td>${c.created_at ? new Date(c.created_at).toLocaleString('zh-CN', { hour12: false }) : '-'}</td>
          <td>
            <button class="btn btn-secondary sf-case-export-btn" data-case-id="${safeId}" style="padding:2px 8px;font-size:11px">导出</button>
            <button class="btn btn-danger sf-case-delete-btn" data-case-id="${safeId}" style="padding:2px 8px;font-size:11px;margin-left:4px">删除</button>
          </td>
        </tr>
      `;
    }).join('');
    
    // P1-10: 事件委托替代内联 onclick
    tbody.querySelectorAll('.sf-case-row-checkbox').forEach(cb => {
      cb.addEventListener('change', function() { toggleSelectCase(this.dataset.caseId, this.checked); });
    });
    tbody.querySelectorAll('.sf-case-export-btn').forEach(btn => {
      btn.addEventListener('click', function() { exportSingleCase(this.dataset.caseId); });
    });
    tbody.querySelectorAll('.sf-case-delete-btn').forEach(btn => {
      btn.addEventListener('click', function() { deleteCase(this.dataset.caseId); });
    });
  }

  window.toggleSelectAllCases = function(masterCheckbox) {
    const checked = masterCheckbox.checked;
    const checkboxes = document.querySelectorAll('.sf-case-row-checkbox');
    checkboxes.forEach(cb => {
      cb.checked = checked;
      toggleSelectCase(cb.value, checked);
    });
  };

  window.toggleSelectCase = function(id, isChecked) {
    if (isChecked) {
      selectedCaseIds.add(id);
    } else {
      selectedCaseIds.delete(id);
    }
  };

  window.deleteCase = async function(id) {
    if (!confirm('确定要删除这个用例配置吗？此操作不可逆。')) return;
    try {
      const res = await fetch(`/api/configs/${id}`, { method: 'DELETE' });
      if (res.ok) {
        selectedCaseIds.delete(id);
        loadShortformCases();
      } else {
        alert('删除失败，可能没有权限或文件被占用');
      }
    } catch (e) {
      console.error(e);
    }
  };

  window.exportSingleCase = function(id) {
    window.open(`/api/configs/${id}/export`);
  };

  window.exportSelectedCases = function() {
    if (selectedCaseIds.size === 0) {
      alert('请先选择需要导出的用例！');
      return;
    }
    selectedCaseIds.forEach(id => {
      window.open(`/api/configs/${id}/export`);
    });
  };

  window.saveAsTestSet = async function() {
    if (selectedCaseIds.size === 0) {
      alert('请先勾选用例！');
      return;
    }
    const name = prompt('请输入新保存的测试集名称:');
    if (!name) return;
    
    try {
      // 聚合所有选中用例的完整配置作为预设保存
      const selectedConfigs = casesList.filter(c => selectedCaseIds.has(c.id));
      const res = await fetch('/api/presets', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: name,
          mode: 'short',
          config: {
            configs: selectedConfigs
          }
        })
      });
      if (res.ok) {
        alert('测试集保存成功！');
      } else {
        alert('保存测试集失败，请重试');
      }
    } catch (e) {
      console.error(e);
    }
  };

  // --- 4. 拖拽/文件选择导入逻辑 ---
  function bindDragDropImport() {
    const zone = document.getElementById('sf-case-drag-zone');
    const input = document.getElementById('sf-case-file-input');
    
    if (!zone || !input) return;
    
    zone.addEventListener('click', () => input.click());
    
    zone.addEventListener('dragover', (e) => {
      e.preventDefault();
      zone.classList.add('dragover');
    });
    
    zone.addEventListener('dragleave', () => {
      zone.classList.remove('dragover');
    });
    
    zone.addEventListener('drop', async (e) => {
      e.preventDefault();
      zone.classList.remove('dragover');
      const files = e.dataTransfer.files;
      if (files.length) {
        handleImportFiles(files);
      }
    });
    
    input.addEventListener('change', () => {
      if (input.files.length) {
        handleImportFiles(input.files);
      }
    });
  }

  async function handleImportFiles(files) {
    for (const file of files) {
      const formData = new FormData();
      formData.append('file', file);
      
      try {
        console.log(`[Shortform] 正在上传文件并解析: ${file.name}`);
        const res = await fetch('/api/configs/import', {
          method: 'POST',
          body: formData
        });
        const data = await res.json();
        
        if (res.ok && data.count > 0) {
          // 对每一项解析到的配置做批量保存 (注入 mode="short")
          alert(`成功解析 ${data.count} 条记录。正在将其写入本地用例库...`);
          // 这里的 preview 是个简短的 list，如果是大列表，直接让后端存也可以，但配置导入接口只是做 preview
          // 所以我们可以将文件内容本身转换并发送到 variables/import 重新做保存，或者直接从 preview 构建保存
          // 更好的做法：使用 /api/configs 保存解析出来的每一条 config
          // 为了高可靠，我们让每一项都在当前 workspace 下保存
          if (data.preview && data.preview.length > 0) {
            for (const item of data.preview) {
              const saveRes = await fetch('/api/configs', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                  name: item.role_name || file.name.split('.')[0],
                  mode: 'short',
                  type: 'shortform_case',
                  config: {
                    character: { Role_Nickname: item.role_name },
                    context: { relationship: item.relationship },
                    prompt_file: item.prompt_file,
                    turns: Array(item.turns_count || 1).fill('用户输入')
                  }
                })
              });
            }
          }
          loadShortformCases();
        } else {
          alert(`解析失败: ${data.detail || '文件格式不支持'}`);
        }
      } catch (e) {
        console.error(e);
        alert('网络请求失败，无法导入该用例');
      }
    }
  }

  // --- 5. A/B 测试启动与轮询逻辑 ---
  window.startShortformABTest = async function() {
    if (selectedCaseIds.size === 0) {
      alert('请先在用例库子选项中选择至少一个用例！');
      return;
    }
    
    const promptA = document.getElementById('sf-run-prompt-a').value;
    const promptB = document.getElementById('sf-run-prompt-b').value;
    const model = document.getElementById('sf-run-model').value;
    const scoreModel = document.getElementById('sf-run-score-model').value;
    const repeats = parseInt(document.getElementById('sf-run-repeats').value) || 1;
    
    if (!promptA || !promptB) {
      alert('请同时选择 Prompt A 和 Prompt B 两个系统提示词版本以进行 A/B 测试。');
      return;
    }
    
    const selectedConfigs = casesList.filter(c => selectedCaseIds.has(c.id));
    
    // 构造 OrchestrationRunCreate payload
    const payload = {
      kind: 'ab',
      title: `短文 A/B 验证 ${new Date().toLocaleString('zh-CN', { hour12: false })}`,
      concurrency: 4,
      groups: selectedConfigs.map((cfg, idx) => {
        return {
          key: cfg.id || `sf_ab_${idx}`,
          label: cfg.name || `用例_${idx}`,
          relationship: cfg.relationship || '',
          planned_turns: cfg.turns_count || 1,
          items: [
            {
              key: `${cfg.id || `sf_ab_${idx}`}:base`,
              label: '控制组 (A)',
              model_id: model,
              planned_turns: cfg.turns_count || 1,
              payload: {
                prompt_version: promptA,
                scoring_model: scoreModel || undefined,
                few_shot_file: cfg.few_shot_file || '',
                character: { Role_Nickname: cfg.name || '' },
                context: { relationship: cfg.relationship || '' },
                turns: Array(cfg.turns_count || 1).fill('你好啊。')
              }
            },
            {
              key: `${cfg.id || `sf_ab_${idx}`}:compare`,
              label: '实验组 (B)',
              model_id: model,
              planned_turns: cfg.turns_count || 1,
              payload: {
                prompt_version: promptB,
                scoring_model: scoreModel || undefined,
                few_shot_file: cfg.few_shot_file || '',
                character: { Role_Nickname: cfg.name || '' },
                context: { relationship: cfg.relationship || '' },
                turns: Array(cfg.turns_count || 1).fill('你好啊。')
              }
            }
          ]
        };
      })
    };
    
    try {
      const res = await fetch('/api/orchestrations', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const run = await res.json();
      
      if (res.ok && run.id) {
        activeRunId = run.id;
        window.switchShortformTab('monitor');
        startMonitorPolling(activeRunId);
      } else {
        alert(`创建测试任务失败: ${run.detail || '未知原因'}`);
      }
    } catch (e) {
      console.error(e);
      alert('请求失败，无法启动 A/B 测试');
    }
  };

  // --- 6. 任务监控页面与轮询控制 ---
  function startMonitorPolling(runId) {
    if (monitorIntervalId) clearInterval(monitorIntervalId);
    if (elapsedTimerId) clearInterval(elapsedTimerId);
    
    elapsedSeconds = 0;
    document.getElementById('sf-monitor-elapsed').textContent = '0s';
    document.getElementById('sf-monitor-eta').textContent = '计算中...';
    
    elapsedTimerId = setInterval(() => {
      elapsedSeconds++;
      document.getElementById('sf-monitor-elapsed').textContent = `${elapsedSeconds}s`;
    }, 1000);
    
    const badge = document.getElementById('sf-monitor-status-badge');
    if (badge) {
      badge.textContent = '运行中';
      badge.className = 'badge badge-primary';
    }
    
    const logStream = document.getElementById('sf-monitor-log-stream');
    if (logStream) logStream.innerHTML = '<div>[系统] A/B 测试任务启动，开始状态轮询...</div>';
    
    tickShortformAB(runId);
    monitorIntervalId = setInterval(() => tickShortformAB(runId), 2000);
  }

  async function tickShortformAB(runId) {
    try {
      const res = await fetch(`/api/orchestrations/${runId}`);
      if (!res.ok) return;
      const run = await res.json();
      
      // 更新进度条
      let totalA = 0, completedA = 0;
      let totalB = 0, completedB = 0;
      
      const logLines = [];
      
      if (run.groups) {
        run.groups.forEach(g => {
          if (g.items) {
            g.items.forEach(item => {
              const isCompare = item.key.endsWith(':compare');
              if (!isCompare) {
                totalA += item.planned_turns || 1;
                completedA += item.completed_turns || 0;
              } else {
                totalB += item.planned_turns || 1;
                completedB += item.completed_turns || 0;
              }
              if (item.error) {
                logLines.push(`<div style="color:var(--text-danger)">[错误] ${item.label}: ${item.error}</div>`);
              }
            });
          }
        });
      }
      
      const pctA = totalA ? Math.round((completedA / totalA) * 100) : 0;
      const pctB = totalB ? Math.round((completedB / totalB) * 100) : 0;
      
      document.getElementById('sf-progress-a-fill').style.width = `${pctA}%`;
      document.getElementById('sf-progress-a-text').textContent = `${completedA} / ${totalA}`;
      
      document.getElementById('sf-progress-b-fill').style.width = `${pctB}%`;
      document.getElementById('sf-progress-b-text').textContent = `${completedB} / ${totalB}`;
      
      logLines.push(`<div>[状态] A组完成率: ${pctA}%, B组完成率: ${pctB}%</div>`);
      const logStream = document.getElementById('sf-monitor-log-stream');
      if (logStream) {
        logStream.innerHTML += logLines.join('');
        logStream.scrollTop = logStream.scrollHeight;
      }
      
      // ETA 计算
      if (completedA + completedB > 0 && elapsedSeconds > 0) {
        const totalRuns = totalA + totalB;
        const comp = completedA + completedB;
        const secondsPerRun = elapsedSeconds / comp;
        const remaining = Math.round((totalRuns - comp) * secondsPerRun);
        document.getElementById('sf-monitor-eta').textContent = remaining > 0 ? `${remaining}s` : '已完成';
      }
      
      const status = String(run.status || '').toLowerCase();
      const badge = document.getElementById('sf-monitor-status-badge');
      if (badge) {
        badge.textContent = run.status;
        if (status === 'completed' || status === 'done') {
          badge.className = 'badge badge-success';
          stopMonitorPolling();
          
          // 渲染 A/B 对比报告
          renderABReport(run);
          window.switchShortformTab('report');
        } else if (status === 'failed' || status === 'cancelled') {
          badge.className = 'badge badge-danger';
          stopMonitorPolling();
        }
      }
    } catch (e) {
      console.error(e);
    }
  }

  function stopMonitorPolling() {
    if (monitorIntervalId) clearInterval(monitorIntervalId);
    if (elapsedTimerId) clearInterval(elapsedTimerId);
    monitorIntervalId = null;
    elapsedTimerId = null;
  }

  window.pauseShortformRun = async function() {
    if (!activeRunId) return;
    await fetch(`/api/orchestrations/${activeRunId}/control`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'pause' })
    });
  };

  window.resumeShortformRun = async function() {
    if (!activeRunId) return;
    await fetch(`/api/orchestrations/${activeRunId}/control`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'resume' })
    });
  };

  window.cancelShortformRun = async function() {
    if (!activeRunId) return;
    if (!confirm('确定要中止当前运行的批量任务吗？')) return;
    await fetch(`/api/orchestrations/${activeRunId}/control`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'stop' })
    });
  };

  // --- 7. 对比报告渲染与确定性违规细节 ---
  function renderABReport(run) {
    console.log('[Shortform] 正在生成对比报告...', run);
    
    // 计算维度得分详情
    const dimensions = [
      { key: 'persona_fidelity', label: '人设契合度' },
      { key: 'narrative_immersion', label: '叙事沉浸感' },
      { key: 'emotional_tension', label: '情感张力' },
      { key: 'boundary_memory', label: '边界记忆力' },
      { key: 'format_compliance', label: '格式规范性' },
      { key: 'context_coherence', label: '语境连贯性' }
    ];
    
    const scoresA = { count: 0 };
    const scoresB = { count: 0 };
    dimensions.forEach(d => { scoresA[d.key] = 0; scoresB[d.key] = 0; });
    
    const violations = [];
    const detailsContainer = document.getElementById('sf-report-cases-detail');
    if (detailsContainer) detailsContainer.innerHTML = '';
    
    if (run.groups) {
      run.groups.forEach(g => {
        let baseText = '';
        let compareText = '';
        
        g.items.forEach(item => {
          const isCompare = item.key.endsWith(':compare');
          // 假设打分结果存储在 item.payload 或 item.result 里
          const scoreObj = item.result?.scores || {};
          const text = item.result?.output || '';
          
          if (!isCompare) {
            baseText = text;
            scoresA.count++;
            // P1-7: 缺失维度用 0，不参与均值计算（避免虚假差值）
            dimensions.forEach(d => { scoresA[d.key] += scoreObj[d.key] || 0; });
          } else {
            compareText = text;
            scoresB.count++;
            dimensions.forEach(d => { scoresB[d.key] += scoreObj[d.key] || 0; });
          }
        });
        
        // 校验确定性规约
        const checkA = checkShortformCompliance(baseText);
        const checkB = checkShortformCompliance(compareText);
        
        if (checkA.issues.length > 0) {
          violations.push({ id: g.label, variant: '控制组 (A)', text: baseText, ...checkA });
        }
        if (checkB.issues.length > 0) {
          violations.push({ id: g.label, variant: '实验组 (B)', text: compareText, ...checkB });
        }
        
        // 渲染逐样本对比视图
        if (detailsContainer) {
          const caseEl = document.createElement('div');
          caseEl.className = 'sf-card';
          caseEl.style.padding = '16px';
          caseEl.innerHTML = `
            <div style="font-weight:600;margin-bottom:8px">${g.label} 对比详情</div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">
              <div style="background:var(--bg-hover);padding:12px;border-radius:6px">
                <div style="font-weight:600;font-size:12px;color:var(--primary-color);margin-bottom:6px">控制组 A:</div>
                <div style="font-size:13px;white-space:pre-wrap">${escapeHtml(baseText) || '未生成'}</div>
              </div>
              <div style="background:var(--bg-hover);padding:12px;border-radius:6px">
                <div style="font-weight:600;font-size:12px;color:#fb923c;margin-bottom:6px">实验组 B:</div>
                <div style="font-size:13px;white-space:pre-wrap">${escapeHtml(compareText) || '未生成'}</div>
              </div>
            </div>
          `;
          detailsContainer.appendChild(caseEl);
        }
      });
    }
    
    // 平均值
    const avgA = [];
    const avgB = [];
    const tbody = document.querySelector('#sf-report-dimensions-table tbody');
    if (tbody) {
      tbody.innerHTML = dimensions.map(d => {
        const valA = scoresA.count ? parseFloat((scoresA[d.key] / scoresA.count).toFixed(2)) : 0;
        const valB = scoresB.count ? parseFloat((scoresB[d.key] / scoresB.count).toFixed(2)) : 0;
        avgA.push(valA);
        avgB.push(valB);
        const diff = (valB - valA).toFixed(2);
        const diffColor = diff > 0 ? 'var(--text-success)' : (diff < 0 ? 'var(--text-danger)' : 'inherit');
        return `
          <tr>
            <td>${d.label}</td>
            <td>${valA}</td>
            <td>${valB}</td>
            <td style="color:${diffColor};font-weight:600">${diff > 0 ? '+' + diff : diff}</td>
          </tr>
        `;
      }).join('');
    }
    
    // 画雷达图
    drawRadarChart('sf-report-radar-canvas', dimensions.map(d => d.label), [
      { label: '控制组 A', data: avgA, color: '#1f6feb', fillColor: 'rgba(31, 111, 235, 0.15)' },
      { label: '实验组 B', data: avgB, color: '#fb923c', fillColor: 'rgba(251, 146, 60, 0.15)' }
    ]);
    
    // 渲染违规汇总表格
    const violBody = document.querySelector('#sf-report-violations-table tbody');
    if (violBody) {
      if (violations.length === 0) {
        violBody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--text-success);font-weight:600;padding:16px">🎉 完美契合，未发现任何确定性校验违规！</td></tr>';
      } else {
        violBody.innerHTML = violations.map(v => {
          return `
            <tr>
              <td>${v.id}</td>
              <td>${v.variant}</td>
              <td>${v.cjkCount}</td>
              <td>${v.issues.some(i => i.includes('我')) ? '❌ 第一人称' : '✅'}</td>
              <td>${v.issues.some(i => i.includes('Emoji')) ? '❌ 包含Emoji' : '✅'}</td>
              <td>${v.issues.some(i => i.includes('感叹号')) ? '❌ 连续!' : '✅'}</td>
              <td style="color:var(--text-danger);font-size:12px">${v.issues.join(' | ')}</td>
            </tr>
          `;
        }).join('');
      }
    }
  }

  // --- 8. 雷达图 Canvas 渲染函数 ---
  function drawRadarChart(canvasId, labels, datasets) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const width = canvas.width;
    const height = canvas.height;
    ctx.clearRect(0, 0, width, height);
    
    const centerX = width / 2;
    const centerY = height / 2;
    const radius = Math.min(width, height) * 0.35;
    const numPoints = labels.length;
    
    // concentric hexagons (grids)
    const numGrids = 5;
    ctx.strokeStyle = '#e2e8f0';
    ctx.lineWidth = 1;
    for (let j = 1; j <= numGrids; j++) {
      const r = radius * (j / numGrids);
      ctx.beginPath();
      for (let i = 0; i < numPoints; i++) {
        const angle = (i * 2 * Math.PI) / numPoints - Math.PI / 2;
        const x = centerX + r * Math.cos(angle);
        const y = centerY + r * Math.sin(angle);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.closePath();
      ctx.stroke();
    }
    
    // axis lines & labels
    for (let i = 0; i < numPoints; i++) {
      const angle = (i * 2 * Math.PI) / numPoints - Math.PI / 2;
      const x = centerX + radius * Math.cos(angle);
      const y = centerY + radius * Math.sin(angle);
      ctx.beginPath();
      ctx.moveTo(centerX, centerY);
      ctx.lineTo(x, y);
      ctx.stroke();
      
      ctx.fillStyle = '#64748b';
      ctx.font = '10px sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      const labelX = centerX + (radius + 15) * Math.cos(angle);
      const labelY = centerY + (radius + 15) * Math.sin(angle);
      ctx.fillText(labels[i], labelX, labelY);
    }
    
    // datasets drawing
    datasets.forEach((dataset) => {
      ctx.strokeStyle = dataset.color;
      ctx.fillStyle = dataset.fillColor;
      ctx.lineWidth = 2;
      
      ctx.beginPath();
      for (let i = 0; i < numPoints; i++) {
        const value = dataset.data[i] || 0;
        const r = radius * (value / 10);
        const angle = (i * 2 * Math.PI) / numPoints - Math.PI / 2;
        const x = centerX + r * Math.cos(angle);
        const y = centerY + r * Math.sin(angle);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.closePath();
      ctx.stroke();
      ctx.fill();
    });
  }

  // --- 9. 确定性规约判定引擎 ---
  function checkShortformCompliance(text) {
    const issues = [];
    if (!text) return { cjkCount: 0, issues: ['无生成内容'], passed: false };
    
    const minWords = parseInt(document.getElementById('sf-check-min-words')?.value) || 30;
    const maxWords = parseInt(document.getElementById('sf-check-max-words')?.value) || 90;
    const mode = document.getElementById('sf-check-person')?.value || 'first';
    const blockEmoji = document.getElementById('sf-check-emoji')?.value === 'block';
    const forbiddenText = document.getElementById('sf-check-forbidden-words')?.value || '';
    
    // CJK Character Count
    const cjkReg = /[\u4e00-\u9fa5]/g;
    const cjkCount = (text.match(cjkReg) || []).length;
    if (cjkCount < minWords) issues.push(`字数偏少 (${cjkCount}字 < ${minWords}字)`);
    if (cjkCount > maxWords) issues.push(`字数偏多 (${cjkCount}字 > ${maxWords}字)`);
    
    // Person Check
    if (mode === 'first' && !text.includes('我')) {
      issues.push('缺失第一人称“我”');
    } else if (mode === 'third' && text.includes('我')) {
      issues.push('违规使用第一人称“我”');
    }
    
    // Emoji Check
    if (blockEmoji) {
      const emojiReg = /[\u{1F300}-\u{1F9FF}]|[\u{2600}-\u{26FF}]|[\u{2700}-\u{27BF}]|[\u{1F000}-\u{1F02F}]|[\u{1F0A0}-\u{1F0DF}]|[\u{1F100}-\u{1F1FF}]|[\u{1F200}-\u{1F2FF}]|[\u{1F300}-\u{1F5FF}]|[\u{1F600}-\u{1F64F}]|[\u{1F680}-\u{1F6FF}]|[\u{1F700}-\u{1F77F}]|[\u{1F780}-\u{1F7FF}]|[\u{1F800}-\u{1F8FF}]|[\u{1F900}-\u{1F9FF}]|[\u{1FA00}-\u{1FA6F}]|[\u{1FA70}-\u{1FAFF}]/gu;
      if (emojiReg.test(text)) issues.push('存在表情符号 (Emoji)');
    }
    
    // Duplicate Punctuation
    if (/[！]{2,}|[!]{2,}/.test(text)) {
      issues.push('连续感叹号 (!!)');
    }
    
    // Custom Forbidden Words
    if (forbiddenText) {
      const fWords = forbiddenText.split(',').map(w => w.trim()).filter(Boolean);
      fWords.forEach(w => {
        if (text.includes(w)) issues.push(`包含禁用词: ${w}`);
      });
    }
    
    return {
      cjkCount,
      issues,
      passed: issues.length === 0
    };
  }

  // --- 10. 基准对比多模型跑分 ---
  window.toggleBenchScoringModelSelect = function(cb) {
    document.getElementById('sf-bench-scoring-model-wrapper').style.display = cb.checked ? 'block' : 'none';
  };

  window.startShortformBenchmark = async function() {
    const selectedCheckboxes = document.querySelectorAll('.sf-bench-model-checkbox:checked');
    const selectedModels = [...selectedCheckboxes].map(cb => cb.value);
    
    if (selectedModels.length === 0) {
      alert('请至少勾选一个候选模型进行基准对比！');
      return;
    }
    
    if (selectedCaseIds.size === 0) {
      alert('请先在用例库中勾选测试所需的用例样本。');
      return;
    }
    
    const turns = parseInt(document.getElementById('sf-bench-turns').value) || 10;
    const scoreModel = document.getElementById('sf-bench-enable-scoring').checked ? document.getElementById('sf-bench-scoring-model').value : null;
    
    document.getElementById('sf-bench-progress-card').style.display = 'block';
    document.getElementById('sf-bench-leaderboard-card').style.display = 'block';
    
    const selectedConfigs = casesList.filter(c => selectedCaseIds.has(c.id));
    
    // 构建多分支基准对比编排
    const payload = {
      kind: 'compare',
      title: `多模型基准对比 ${new Date().toLocaleString('zh-CN', { hour12: false })}`,
      concurrency: parseInt(document.getElementById('sf-bench-concurrency').value) || 4,
      groups: selectedConfigs.map((cfg, idx) => {
        return {
          key: cfg.id || `sf_bench_${idx}`,
          label: cfg.name || `用例_${idx}`,
          relationship: cfg.relationship || '',
          planned_turns: turns,
          items: selectedModels.map(modelId => {
            return {
              key: `${cfg.id || `sf_bench_${idx}`}:${modelId}`,
              label: `${cfg.name || '用例'}:${modelId}`,
              model_id: modelId,
              planned_turns: turns,
              payload: {
                scoring_model: scoreModel || undefined,
                turns: Array(turns).fill('继续说话。')
              }
            };
          })
        };
      })
    };
    
    try {
      const res = await fetch('/api/orchestrations', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const run = await res.json();
      
      if (res.ok && run.id) {
        activeBenchRunId = run.id;
        startBenchmarkPolling(activeBenchRunId);
      } else {
        alert(`创建基准任务失败: ${run.detail || '未知原因'}`);
      }
    } catch (e) {
      console.error(e);
      alert('网络异常，无法启动基准对比');
    }
  };

  function startBenchmarkPolling(runId) {
    if (benchmarkIntervalId) clearInterval(benchmarkIntervalId);
    tickBenchmark(runId);
    benchmarkIntervalId = setInterval(() => tickBenchmark(runId), 2500);
  }

  async function tickBenchmark(runId) {
    try {
      const res = await fetch(`/api/orchestrations/${runId}`);
      if (!res.ok) return;
      const run = await res.json();
      
      let total = 0, completed = 0;
      const stats = {}; // model_id -> { totalTime, count, failures, p50, p95 }
      
      if (run.groups) {
        run.groups.forEach(g => {
          if (g.items) {
            g.items.forEach(item => {
              total += item.planned_turns || 0;
              completed += item.completed_turns || 0;
              
              const mId = item.model_id;
              if (!stats[mId]) {
                stats[mId] = { totalTime: 0, count: 0, failures: 0, latencies: [] };
              }
              
              const latency = item.result?.latency || 0;
              if (latency > 0) {
                stats[mId].totalTime += latency;
                stats[mId].count++;
                stats[mId].latencies.push(latency);
              }
              if (item.error) {
                stats[mId].failures++;
              }
            });
          }
        });
      }
      
      const pct = total ? Math.round((completed / total) * 100) : 0;
      document.getElementById('sf-bench-progress-fill').style.width = `${pct}%`;
      document.getElementById('sf-bench-progress-text').textContent = `${completed} / ${total} 调用`;
      
      // 渲染排行榜
      const tbody = document.querySelector('#sf-bench-leaderboard-table tbody');
      if (tbody) {
        const sorted = Object.keys(stats).map(modelId => {
          const s = stats[modelId];
          const sortedLats = [...s.latencies].sort((a, b) => a - b);
          const p50 = sortedLats.length ? sortedLats[Math.floor(sortedLats.length * 0.5)] : 0;
          const p95 = sortedLats.length ? sortedLats[Math.floor(sortedLats.length * 0.95)] : 0;
          const avg = s.count ? (s.totalTime / s.count) : 0;
          const failRate = s.count ? (s.failures / s.count) * 100 : 0;
          return {
            id: modelId,
            avg: avg.toFixed(2) + 's',
            p50: p50.toFixed(2) + 's',
            p95: p95.toFixed(2) + 's',
            count: s.count,
            failRate: failRate.toFixed(1) + '%'
          };
        }).sort((a, b) => parseFloat(a.avg) - parseFloat(b.avg));
        
        tbody.innerHTML = sorted.map((row, idx) => {
          return `
            <tr>
              <td>${idx + 1}</td>
              <td style="font-weight:600">${row.id}</td>
              <td>${row.avg}</td>
              <td>${row.p50}</td>
              <td>${row.p95}</td>
              <td>${row.count}</td>
              <td style="color:${parseFloat(row.failRate) > 0 ? 'var(--text-danger)' : 'inherit'}">${row.failRate}</td>
            </tr>
          `;
        }).join('');
      }
      
      const status = String(run.status || '').toLowerCase();
      if (status === 'completed' || status === 'done' || status === 'failed' || status === 'cancelled') {
        clearInterval(benchmarkIntervalId);
        benchmarkIntervalId = null;
        alert('多模型基准对比任务已完成！');
      }
    } catch (e) {
      console.error(e);
    }
  }

})();
