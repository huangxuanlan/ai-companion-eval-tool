/* ═══ 工具函数 ═══ */
const $ = id => document.getElementById(id);
const escapeHtml = s => { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; };
const DEFAULT_SUMMARY_INTERVAL = 10;
const DEFAULT_INJECTION_DEPTH = 4;
const DEFAULT_PRIMARY_MODEL_ID = 'gemma4-31b-local';
const DEFAULT_SUMMARY_MODEL_ID = 'doubao-lite';
const DEFAULT_SCORING_MODEL_ID = 'qwen3.6-plus';
const DEFAULT_PROFILE_MODEL_ID = 'doubao-lite';
const DEFAULT_AI_SUMMARY_REPORT_MODEL_ID = 'qwen-plus';
const DEFAULT_SCORING_CONCURRENCY = 24;
const DEFAULT_SCORING_RETRY_COUNT = 3;
const DEFAULT_LOW_SCORE_THRESHOLD = 6.0;
const MAX_BATCH_CONCURRENCY = 24;
const AB_BATCH_BRANCHES_PER_ROLE = 2;
const DEFAULT_AB_BATCH_ROLE_CONCURRENCY = 1;
const MAX_AB_BATCH_ROLE_CONCURRENCY = Math.max(1, Math.floor(MAX_BATCH_CONCURRENCY / AB_BATCH_BRANCHES_PER_ROLE));
const TEST_CENTER_NAV_STORAGE_KEY = 'longformTestCenterNavState';
const DEFAULT_VOICE_FORBIDDEN = '当前为文字聊天场景，禁止输出任何语音条、语音时长、语音播报提示或"发语音给你"这类表述；只能用文字叙事和对白完成互动。';
const DEFAULT_THINKING_ENABLED = false;
const DEFAULT_THINKING_EFFORT = 'high';
const DEFAULT_SCORING_THINKING_ENABLED = true;
const DEFAULT_SCORING_THINKING_EFFORT = 'high';
const GEMMA_DEFAULT_THINKING_EFFORT = 'high';
const GEMMA_THINKING_DEFAULT_MODEL_IDS = new Set(['gemma4-31b', 'gemma4-31b-local']);
const THINKING_EFFORT_OPTIONS = new Set(['disabled', 'low', 'medium', 'high']);
const SCORING_DEFAULTS_STORAGE_KEY = 'longformScoringDefaults';
const MODEL_ID_ALIAS_MAP = Object.freeze({
  'doubao-seed-2-0-lite-260215': 'doubao-lite',
});
let _dialogueThinkingEffortDraft = GEMMA_DEFAULT_THINKING_EFFORT;
let _scoringThinkingEffortDraft = GEMMA_DEFAULT_THINKING_EFFORT;
let _scoringModalRefreshTimer = null;
const _scoreResultWatchers = new Map();
function showToast(msg, type = 'info', ms = 3000) {
  const c = $('toast-container'), t = document.createElement('div');
  t.className = 'toast ' + type; t.textContent = msg; c.appendChild(t);
  setTimeout(() => { t.style.opacity = '0'; setTimeout(() => t.remove(), 300); }, ms);
}
const delay = (ms) => new Promise(resolve => setTimeout(resolve, ms));

function getLowScoreThreshold() {
  const stored = Number.parseFloat(localStorage.getItem('lowScoreThreshold') || '');
  if (Number.isFinite(stored)) return Math.max(0, Math.min(stored, 10));
  return DEFAULT_LOW_SCORE_THRESHOLD;
}

function setLowScoreThreshold(value) {
  const nextValue = Math.max(0, Math.min(Number.parseFloat(value || DEFAULT_LOW_SCORE_THRESHOLD), 10));
  localStorage.setItem('lowScoreThreshold', String(nextValue));
  state.lowScoreThreshold = nextValue;
  _lowScoreNavCursor = -1;
  if ($('score-low-threshold')) $('score-low-threshold').value = String(nextValue);
  if ($('score-low-threshold-display')) $('score-low-threshold-display').textContent = nextValue.toFixed(1);
  return nextValue;
}

function getActiveLowScoreThreshold() {
  return Number.isFinite(state.lowScoreThreshold) ? state.lowScoreThreshold : getLowScoreThreshold();
}

function getScoreTurnTotal(score) {
  const total = Number.parseFloat(score?.total_score ?? score?.total ?? 0);
  return Number.isFinite(total) ? total : 0;
}

function isLowScoreTurn(score) {
  return getScoreTurnTotal(score) < getActiveLowScoreThreshold();
}

let _titleFlashTimer = null;
let _titleFlashBase = document.title;
let _lowScoreNavCursor = -1;

function stopTitleFlash() {
  if (_titleFlashTimer) {
    clearInterval(_titleFlashTimer);
    _titleFlashTimer = null;
  }
  document.title = _titleFlashBase;
}

function flashDocumentTitle(message) {
  stopTitleFlash();
  _titleFlashBase = document.title || '长文模式生成';
  let visible = false;
  document.title = message;
  _titleFlashTimer = setInterval(() => {
    visible = !visible;
    document.title = visible ? message : _titleFlashBase;
  }, 1000);
  setTimeout(() => stopTitleFlash(), 12000);
}

async function requestTaskNotificationPermission() {
  if (state.notificationPermissionRequested) return;
  state.notificationPermissionRequested = true;
  if (typeof Notification === 'undefined') return;
  if (Notification.permission === 'default') {
    try {
      await Notification.requestPermission();
    } catch (_) { /* ignore */ }
  }
}

async function notifyTaskCompletion(title, options = {}) {
  const resolvedTitle = String(title || '任务状态更新').trim() || '任务状态更新';
  const body = String(options.body || '').trim();
  const requestPermission = !!options.requestPermission;
  if (requestPermission) {
    await requestTaskNotificationPermission();
  }
  flashDocumentTitle(resolvedTitle);
  if (typeof Notification !== 'undefined' && Notification.permission === 'granted') {
    try {
      const notification = new Notification(resolvedTitle, { body });
      setTimeout(() => notification.close(), 6000);
    } catch (_) { /* ignore */ }
  }
}

function normalizeScoringConcurrency(value) {
  const parsed = parseInt(String(value || '').trim(), 10);
  if (!Number.isFinite(parsed)) return DEFAULT_SCORING_CONCURRENCY;
  return Math.max(1, Math.min(parsed, 24));
}

function normalizeBatchConcurrency(value, fallback = 1) {
  const fallbackNumber = Number(fallback);
  const safeFallback = Number.isFinite(fallbackNumber) ? fallbackNumber : 1;
  const parsed = parseInt(String(value || '').trim(), 10);
  if (!Number.isFinite(parsed)) {
    return Math.max(1, Math.min(safeFallback, MAX_BATCH_CONCURRENCY));
  }
  return Math.max(1, Math.min(parsed, MAX_BATCH_CONCURRENCY));
}

function normalizeABBatchRoleConcurrency(value, fallback = DEFAULT_AB_BATCH_ROLE_CONCURRENCY) {
  const fallbackNumber = Number(fallback);
  const safeFallback = Number.isFinite(fallbackNumber) ? fallbackNumber : DEFAULT_AB_BATCH_ROLE_CONCURRENCY;
  const parsed = parseInt(String(value || '').trim(), 10);
  if (!Number.isFinite(parsed)) {
    return Math.max(1, Math.min(safeFallback, MAX_AB_BATCH_ROLE_CONCURRENCY));
  }
  return Math.max(1, Math.min(parsed, MAX_AB_BATCH_ROLE_CONCURRENCY));
}

function normalizeScoringRetryCount(value) {
  const parsed = parseInt(String(value || '').trim(), 10);
  if (!Number.isFinite(parsed)) return DEFAULT_SCORING_RETRY_COUNT;
  return Math.max(0, Math.min(parsed, 10));
}

function buildBuiltinScoringDefaults() {
  return {
    scoring_model_id: DEFAULT_SCORING_MODEL_ID,
    scoring_thinking_enabled: DEFAULT_SCORING_THINKING_ENABLED,
    scoring_thinking_effort: DEFAULT_SCORING_THINKING_EFFORT,
    scoring_max_workers: DEFAULT_SCORING_CONCURRENCY,
    scoring_retry_count: DEFAULT_SCORING_RETRY_COUNT,
  };
}

function normalizeScoringDefaults(source = {}) {
  const base = buildBuiltinScoringDefaults();
  return {
    scoring_model_id: normalizeModelId(source.scoring_model_id, base.scoring_model_id),
    scoring_thinking_enabled: coerceOptionalBoolean(source.scoring_thinking_enabled) ?? base.scoring_thinking_enabled,
    scoring_thinking_effort: normalizeThinkingEffortOption(
      source.scoring_thinking_effort || base.scoring_thinking_effort,
      base.scoring_thinking_effort,
    ),
    scoring_max_workers: normalizeScoringConcurrency(source.scoring_max_workers),
    scoring_retry_count: normalizeScoringRetryCount(source.scoring_retry_count),
  };
}

function getSavedScoringDefaults() {
  try {
    const raw = localStorage.getItem(SCORING_DEFAULTS_STORAGE_KEY);
    if (!raw) return normalizeScoringDefaults(buildBuiltinScoringDefaults());
    return normalizeScoringDefaults(JSON.parse(raw));
  } catch (_) {
    return normalizeScoringDefaults(buildBuiltinScoringDefaults());
  }
}

function buildCurrentScoringDefaultsDraft() {
  const scoringModelId = normalizeModelId(
    getInputValue('tc-scoring-model').trim() || getInputValue('f-scoring-model').trim() || DEFAULT_SCORING_MODEL_ID,
    DEFAULT_SCORING_MODEL_ID,
  );
  const scoringThinking = getScoringThinkingState(scoringModelId);
  return normalizeScoringDefaults({
    scoring_model_id: scoringModelId,
    scoring_thinking_enabled: scoringThinking.enabled,
    scoring_thinking_effort: scoringThinking.effort,
    scoring_max_workers: getInputValue('tc-scoring-concurrency'),
    scoring_retry_count: getInputValue('tc-scoring-retry'),
  });
}

function scoringDefaultsEqual(left = {}, right = {}) {
  const a = normalizeScoringDefaults(left);
  const b = normalizeScoringDefaults(right);
  return (
    a.scoring_model_id === b.scoring_model_id
    && a.scoring_thinking_enabled === b.scoring_thinking_enabled
    && a.scoring_thinking_effort === b.scoring_thinking_effort
    && a.scoring_max_workers === b.scoring_max_workers
    && a.scoring_retry_count === b.scoring_retry_count
  );
}

function formatScoringDefaultsSummary(config = {}) {
  const normalized = normalizeScoringDefaults(config);
  const thinkingLabel = normalized.scoring_thinking_enabled
    ? `思考 ${normalized.scoring_thinking_effort}`
    : `思考 关闭（保留 ${normalized.scoring_thinking_effort}）`;
  return `已保存默认：${normalized.scoring_model_id} / ${thinkingLabel} / 并发 ${normalized.scoring_max_workers} / 重试 ${normalized.scoring_retry_count} 次`;
}

function refreshScoringDefaultsStatus(message = '') {
  const statusEl = $('tc-scoring-default-status');
  const saveBtn = $('tc-scoring-save-defaults');
  const resetBtn = $('tc-scoring-reset-defaults');
  const current = buildCurrentScoringDefaultsDraft();
  const saved = getSavedScoringDefaults();
  const builtin = buildBuiltinScoringDefaults();
  const dirty = !scoringDefaultsEqual(current, saved);
  const usingBuiltin = scoringDefaultsEqual(saved, builtin);
  if (statusEl) {
    statusEl.textContent = message || (
      dirty
        ? `当前修改未保存；本次运行会生效，刷新页面后会丢失。${formatScoringDefaultsSummary(saved)}`
        : formatScoringDefaultsSummary(saved)
    );
    statusEl.dataset.state = dirty ? 'dirty' : 'saved';
    statusEl.style.color = dirty ? 'var(--warning-color)' : 'var(--text-tertiary)';
  }
  if (saveBtn) saveBtn.disabled = !dirty;
  if (resetBtn) resetBtn.disabled = usingBuiltin && !dirty;
}

async function applyScoringDefaultsToControls(defaults = {}, { syncServer = false } = {}) {
  const normalized = normalizeScoringDefaults(defaults);
  if ($('f-scoring-model')) {
    $('f-scoring-model').value = selectPreferredModel('f-scoring-model', normalized.scoring_model_id) || normalized.scoring_model_id;
  }
  if ($('tc-scoring-model')) {
    $('tc-scoring-model').value = selectPreferredModel('tc-scoring-model', normalized.scoring_model_id) || normalized.scoring_model_id;
  }
  if ($('f-scoring-thinking-enabled')) $('f-scoring-thinking-enabled').dataset.userTouched = '';
  if ($('f-scoring-thinking-effort')) $('f-scoring-thinking-effort').dataset.userTouched = '';
  syncScoringThinkingControls({
    enabled: normalized.scoring_thinking_enabled,
    effort: normalized.scoring_thinking_effort,
    modelId: normalized.scoring_model_id || getPrimaryModelId(),
    force: true,
  });
  if ($('tc-scoring-thinking-effort')) {
    $('tc-scoring-thinking-effort').value = normalized.scoring_thinking_enabled
      ? normalized.scoring_thinking_effort
      : 'disabled';
  }
  if ($('tc-scoring-concurrency')) $('tc-scoring-concurrency').value = String(normalized.scoring_max_workers);
  if ($('tc-scoring-concurrency-display')) $('tc-scoring-concurrency-display').textContent = String(normalized.scoring_max_workers);
  if ($('tc-scoring-retry')) $('tc-scoring-retry').value = String(normalized.scoring_retry_count);
  if (syncServer) {
    await syncScoringConfigToServer({ max_workers: normalized.scoring_max_workers });
  }
  syncScoringAdvancedPanel({ modelId: normalized.scoring_model_id || getPrimaryModelId() });
  refreshTestCenterShell();
  refreshScoringDefaultsStatus();
  return normalized;
}

async function saveScoringDefaults() {
  const normalized = buildCurrentScoringDefaultsDraft();
  localStorage.setItem(SCORING_DEFAULTS_STORAGE_KEY, JSON.stringify(normalized));
  try {
    await syncScoringConfigToServer({ max_workers: normalized.scoring_max_workers });
  } catch (err) {
    showToast('默认值已保存到浏览器，但同步并发到后端失败: ' + err.message, 'warning');
  }
  refreshScoringDefaultsStatus('打分默认配置已保存');
  showToast('打分默认配置已保存', 'success');
}

async function resetScoringDefaults() {
  localStorage.removeItem(SCORING_DEFAULTS_STORAGE_KEY);
  const builtin = buildBuiltinScoringDefaults();
  try {
    await applyScoringDefaultsToControls(builtin, { syncServer: true });
    refreshScoringDefaultsStatus('已恢复系统默认值');
    showToast('已恢复系统默认值', 'success');
  } catch (err) {
    showToast('恢复系统默认值失败: ' + err.message, 'error');
  }
}

async function syncScoringConfigToServer(payload = {}) {
  if (!payload || typeof payload !== 'object') return null;
  const response = await fetch('/api/scoring/config', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || response.statusText || '同步打分配置失败');
  }
  return data;
}

/* ═══ 全局状态 ═══ */
function getInputValue(id) {
  const el = $(id);
  return el && typeof el.value !== 'undefined' ? el.value : '';
}

function normalizeModelId(value, fallback = '') {
  const requested = String(value || '').trim();
  if (!requested) return String(fallback || '').trim();
  return MODEL_ID_ALIAS_MAP[requested] || requested;
}

const EXCEL_PLACEHOLDER_EMPTY_VALUES = new Set(['暂时留空', '可留空']);

function normalizeImportedCellValue(value) {
  if (value === undefined || value === null) return '';
  const normalized = String(value).trim();
  return EXCEL_PLACEHOLDER_EMPTY_VALUES.has(normalized) ? '' : normalized;
}

function resolveConfigPersonalType(source = null) {
  if (!source || typeof source !== 'object') return '';
  return normalizeImportedCellValue(source.personal_type || '')
    || normalizeImportedCellValue(source.personality || '');
}

const BATCH_PERSONALITY_HINTS = Object.freeze({
  '霸道腹黑': ['霸道腹黑', '霸道', '腹黑', '高冷', '高岭之花', '危险', '神秘', '阴郁', '野性', '掌控', '占有', '傲娇', '毒舌', '桀骜', '狂妄', '将帅', '病态', '病娇'],
  '温暖陪伴': ['温暖陪伴', '温暖', '陪伴', '治愈', '阳光', '开朗', '爹系', '绅士', '通透', '体贴', '专属独宠', '知己伴侣'],
  '理性沉稳': ['理性沉稳', '理性', '沉稳', '冷静', '克制', '内敛', '高智商', '清醒', '完美主义', '老干部', '严苛'],
  '可爱活泼': ['可爱活泼', '可爱', '活泼', '元气', '直球', '大金毛', '俏皮', '跳脱', '叛逆', '天马行空'],
});

function collectPresetPersonalityTypes(presetCatalog = []) {
  const presetTypes = Array.isArray(presetCatalog)
    ? presetCatalog
      .map(item => normalizeImportedCellValue(item.personality_type || item.type || ''))
      .filter(Boolean)
    : [];
  return [...new Set([...Object.keys(BATCH_PERSONALITY_HINTS), ...presetTypes])];
}

function scoreBatchPersonalityHints(text, hints, weight) {
  const sourceText = normalizeImportedCellValue(text);
  if (!sourceText) return 0;
  return hints.reduce((total, hint) => {
    if (!hint || !sourceText.includes(hint)) return total;
    return total + ((hint.length >= 3 ? 2 : 1) * weight);
  }, 0);
}

function resolveBatchModulePersonalityType(source = null, presetCatalog = []) {
  if (!source || typeof source !== 'object') return '';
  const rawPersonalType = normalizeImportedCellValue(source.personal_type || '');
  const rawPersonality = normalizeImportedCellValue(source.personality || '');
  const knownTypes = collectPresetPersonalityTypes(presetCatalog);
  if (!knownTypes.length) return '';

  const exactType = knownTypes.find(type => rawPersonalType && (rawPersonalType === type || rawPersonalType.includes(type)));
  if (exactType) return exactType;

  const declaredType = knownTypes.find(type => rawPersonality && (
    rawPersonality.includes(`${type}\u578b`)
    || /\u6027\u683c\u7c7b\u578b/.test(rawPersonality) && rawPersonality.includes(type)
  ));
  if (declaredType) return declaredType;

  let bestType = '';
  let bestScore = 0;
  knownTypes.forEach(type => {
    const hints = [...new Set([type, ...(BATCH_PERSONALITY_HINTS[type] || [])])];
    const score = scoreBatchPersonalityHints(rawPersonalType, hints, 3)
      + scoreBatchPersonalityHints(rawPersonality, hints, 1);
    if (score > bestScore) {
      bestScore = score;
      bestType = type;
    }
  });

  return bestScore >= 2 ? bestType : '';
}

function buildSystemModulesPayload(source = null) {
  const pick = (keys, fallbackId = '') => {
    if (source) {
      for (const key of keys) {
        const value = normalizeImportedCellValue(source[key]);
        if (value) return value;
      }
      return '';
    }
    return normalizeImportedCellValue(getInputValue(fallbackId));
  };
  return {
    longform_persona: pick(['sys_persona', 'longform_persona'], 'f-sys-persona'),
    longform_narrative_style: pick(['sys_style', 'longform_narrative_style'], 'f-sys-style'),
    longform_dialogue_guideline: pick(['longform_dialogue_guideline'], 'f-sys-dialogue-guideline'),
    longform_few_shot: pick(['sys_fewshot', 'longform_few_shot', 'few_shot_file'], 'f-sys-fewshot'),
    dialogueStartPrompt: pick(['sys_startprompt', 'dialogueStartPrompt'], 'f-sys-startprompt'),
    dialogue_summary: pick(['sys_summary', 'dialogue_summary'], 'f-sys-summary'),
    moments: pick(['moments'], ''),
    monthly_schedule: pick(['monthly_schedule'], ''),
    weekly_schedule: pick(['weekly_schedule', 'sys_schedule'], 'f-sys-schedule'),
    system_module8: pick(['sys_module8', 'system_module8'], 'f-sys-module8'),
    system_Role_acting: pick(['sys_role_acting', 'system_Role_acting'], 'f-sys-role-acting-module') || getInputValue('f-sys-role-acting').trim(),
    voice_forbidden: pick(['voice_forbidden'], 'f-voice-forbidden') || DEFAULT_VOICE_FORBIDDEN,
    system_prompt: pick(['system_prompt'], 'f-system-prompt'),
  };
}

function getMergedCustomVariables() {
  return {
    ...(window.runtimePromptBaseValues || {}),
    ...(window.customVarOverrides || {}),
  };
}

function formatPromptPreviewDate(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  const hours = String(date.getHours()).padStart(2, '0');
  const minutes = String(date.getMinutes()).padStart(2, '0');
  return `${year}-${month}-${day} ${hours}:${minutes}`;
}

function getPromptPreviewWeekday(date) {
  const labels = ['星期日', '星期一', '星期二', '星期三', '星期四', '星期五', '星期六'];
  return labels[date.getDay()];
}

function inferPromptPreviewTimeperiod(hour) {
  if (hour >= 5 && hour < 11) return '早晨';
  if (hour >= 11 && hour < 14) return '中午';
  if (hour >= 14 && hour < 18) return '下午';
  if (hour >= 18 && hour < 23) return '傍晚';
  return '深夜';
}

function inferPromptPreviewSeason(month) {
  if ([3, 4, 5].includes(month)) return '春季';
  if ([6, 7, 8].includes(month)) return '夏季';
  if ([9, 10, 11].includes(month)) return '秋季';
  return '冬季';
}
function toFixedScore(value, fallback = 8.0) {
  const num = Number.parseFloat(value);
  return Number.isFinite(num) ? num.toFixed(1) : Number(fallback).toFixed(1);
}
let state = {
  convId: null,
  turns: [],
  expectedTurnCount: 0,
  debugData: [],
  scoreData: null,
  scoreMeta: null,
  scoreSummary: null,
  scoreWs: null,
  compareReportId: '',
  ws: null,
  running: false,
  historyItems: [],
  historyCompareSelection: [],
  presetItems: [],
  chatSessionMode: 'idle',
  rightPanelOpen: true,
  inlineScoreInflight: {},
  testMode: 'batch',
  abMode: 'live',
  waitingTrackers: {},
  selectedPresetId: '',
  interactiveConfigSignature: '',
  batchPaused: false,
  batchStopRequested: false,
  batchAutoScoringEnabled: false,
  batchRunId: '',
  batchRunStatus: '',
  compareRunId: '',
  compareRunStatus: '',
  compareRetryableItems: 0,
  abBatchRunId: '',
  abBatchRunStatus: '',
  activeConversationStatus: '',
  historyEventConvId: '',
  historyEvents: [],
  lowScoreThreshold: getLowScoreThreshold(),
  notificationPermissionRequested: false,
};
window._linkedRelationshipVars = window._linkedRelationshipVars || {};
window.customVarOverrides = window.customVarOverrides || {};
window.runtimePromptBaseValues = window.runtimePromptBaseValues || {};
let _allModelOptions = [];
let _chatPromptOptions = [];
let _activeChatPromptFilename = '';
let _runtimePromptListings = { summary: null, scoring: null, profile: null };
let _promptManagerKind = 'chat';
let _runtimePromptContentCache = new Map();
const AUTO_GENERATED_PROMPT_VARS = new Set(['currentTime', 'weekDay', '完整时间信息']);
const RUNTIME_PROMPT_EXTRA_KEYS = ['moments', 'monthly_schedule', 'last_cst_type', '完整时间信息'];
let _runtimePromptEditorContext = null;
let _promptEditFilename = null;
let _promptEditKind = 'chat';
let _debugPanelMode = 'messages';
let _pendingPresetDelete = null;
let _actionConfirmState = null;
let _batchRunPollTimer = null;
let _compareRunPollTimer = null;
let _abBatchRunPollTimer = null;
const _orchestrationFetchErrorToastState = new Map();
const _batchRescoreRowStatus = new Map(); // convId -> 'pending'|'scoring'|'success'|'failed'
let _batchRescoreTotal = 0;
let _batchRescoreFinished = 0;
let _batchRescoreSuccessCount = 0;
let _batchRescoreFailCount = 0;
let _batchRescoreCancelled = false;
let _batchRescoreAutoHideTimer = null;
let _historySummaryTaskAutoHideTimer = null;
let _scoreQuickFilter = '';
let _orchestrationHealthProbeTimer = null;
let _compareRunSnapshot = null;
let _abBatchRunSnapshot = null;
let _abBatchLastTerminalRunId = '';
const _compareScoreSockets = new Map();
const _compareLiveScoreState = new Map();
const ORCHESTRATION_HEALTHCHECK_TTL_MS = 15000;
const ORCHESTRATION_ACTION_BUTTON_IDS = [
  'btn-batch-start',
  'btn-batch-pause',
  'btn-batch-resume',
  'btn-batch-stop',
  'btn-compare-start',
  'btn-compare-pause',
  'btn-compare-resume',
  'btn-compare-stop',
  'btn-compare-retry',
];
const _orchestrationEnvironmentState = {
  reachable: null,
  blockedByFileProtocol: false,
  message: '',
  lastCheckedAt: 0,
  recoveryBootstrapped: false,
};
let abSessionState = {
  id: '',
  status: '',
  currentTurn: 0,
  baseConversationId: '',
  compareConversationId: '',
  sharedConfig: {},
  baseConfig: {},
  compareConfig: {},
  sides: {
    base: {
      convId: '',
      ws: null,
      scoreWs: null,
      awaitingTurn: 0,
      latestTurn: 0,
      latestReply: '',
      scoreSummary: null,
      generationStatus: '',
      error: '',
    },
    compare: {
      convId: '',
      ws: null,
      scoreWs: null,
      awaitingTurn: 0,
      latestTurn: 0,
      latestReply: '',
      scoreSummary: null,
      generationStatus: '',
      error: '',
    },
  },
};

function getPrimaryModelId() {
  return getInputValue('header-global-model').trim()
    || getInputValue('f-model-pro').trim()
    || DEFAULT_PRIMARY_MODEL_ID;
}

function isGemmaThinkingDefaultModel(modelId = '') {
  return GEMMA_THINKING_DEFAULT_MODEL_IDS.has(String(modelId || '').trim());
}

function getDefaultThinkingEffortForModel(modelId = '') {
  return isGemmaThinkingDefaultModel(modelId)
    ? GEMMA_DEFAULT_THINKING_EFFORT
    : DEFAULT_THINKING_EFFORT;
}

function normalizeThinkingEffortOption(value, fallback = DEFAULT_THINKING_EFFORT) {
  const normalized = String(value || '').trim().toLowerCase();
  if (THINKING_EFFORT_OPTIONS.has(normalized)) return normalized;
  return THINKING_EFFORT_OPTIONS.has(fallback) ? fallback : DEFAULT_THINKING_EFFORT;
}

function coerceOptionalBoolean(value) {
  if (value === true || value === false) return value;
  const normalized = String(value ?? '').trim().toLowerCase();
  if (!normalized) return null;
  if (['true', '1', 'yes', 'on'].includes(normalized)) return true;
  if (['false', '0', 'no', 'off'].includes(normalized)) return false;
  return null;
}

function modelSupportsThinking(modelId = '') {
  const caps = _modelCapabilities[String(modelId || '').trim()];
  if (!caps) return true;
  return !!caps.thinking;
}

function resolveThinkingPayload(modelId = '', enabled = true, effort = '') {
  const supported = modelSupportsThinking(modelId);
  const fallbackEffort = getDefaultThinkingEffortForModel(modelId);
  const normalizedEffort = normalizeThinkingEffortOption(
    effort || fallbackEffort,
    fallbackEffort,
  );
  if (!supported || !enabled) {
    return {
      supported,
      enabled: false,
      effort: normalizedEffort,
      thinking_effort: 'disabled',
    };
  }
  return {
    supported,
    enabled: true,
    effort: normalizedEffort,
    thinking_effort: normalizedEffort,
  };
}

function getDialogueThinkingState(modelId = getPrimaryModelId()) {
  const fallbackEffort = getDefaultThinkingEffortForModel(modelId);
  const checkbox = $('f-thinking-enabled');
  const select = $('f-thinking-effort');
  const enabled = checkbox ? !!checkbox.checked : DEFAULT_THINKING_ENABLED;
  const effort = normalizeThinkingEffortOption(
    (select && select.value) || _dialogueThinkingEffortDraft || fallbackEffort,
    fallbackEffort,
  );
  return resolveThinkingPayload(modelId, enabled, effort);
}

function getScoringThinkingState(modelId = getInputValue('f-scoring-model').trim() || getPrimaryModelId()) {
  const fallbackEffort = DEFAULT_SCORING_THINKING_EFFORT;
  const checkbox = $('f-scoring-thinking-enabled');
  const select = $('f-scoring-thinking-effort');
  const enabled = checkbox ? !!checkbox.checked : DEFAULT_SCORING_THINKING_ENABLED;
  const effort = normalizeThinkingEffortOption(
    (select && select.value) || _scoringThinkingEffortDraft || fallbackEffort,
    fallbackEffort,
  );
  return resolveThinkingPayload(modelId, enabled, effort);
}

function syncDialogueThinkingControls({ enabled = null, effort = '', modelId = '', force = false } = {}) {
  const resolvedModelId = modelId || getPrimaryModelId();
  const fallbackEffort = getDefaultThinkingEffortForModel(resolvedModelId);
  const mainEnabled = $('f-thinking-enabled');
  const mainEffort = $('f-thinking-effort');
  const dockEffort = $('f-thinking-effort-chat');
  const freeEffort = $('sel-thinking');
  const userTouched = !!(
    mainEnabled?.dataset.userTouched
    || mainEffort?.dataset.userTouched
    || dockEffort?.dataset.userTouched
    || freeEffort?.dataset.userTouched
  );
  const currentEnabled = mainEnabled
    ? !!mainEnabled.checked
    : ((dockEffort && dockEffort.value !== 'disabled') || (freeEffort && freeEffort.value !== 'disabled'));
  const nextEnabled = enabled == null
    ? ((force || !userTouched) ? DEFAULT_THINKING_ENABLED : currentEnabled)
    : !!enabled;
  const requestedEffort = normalizeThinkingEffortOption(
    effort
      || (mainEffort && mainEffort.value)
      || _dialogueThinkingEffortDraft
      || fallbackEffort,
    fallbackEffort,
  );
  _dialogueThinkingEffortDraft = requestedEffort === 'disabled' ? fallbackEffort : requestedEffort;
  const payload = resolveThinkingPayload(resolvedModelId, nextEnabled, _dialogueThinkingEffortDraft);

  if (mainEnabled) {
    mainEnabled.checked = payload.enabled;
    mainEnabled.disabled = !payload.supported;
    mainEnabled.title = payload.supported ? '' : '当前模型不支持思考';
  }
  if (mainEffort) {
    mainEffort.value = _dialogueThinkingEffortDraft;
    mainEffort.disabled = !payload.supported;
    mainEffort.title = payload.supported ? '' : '当前模型不支持思考';
  }
  if (dockEffort) {
    dockEffort.value = payload.supported
      ? (payload.enabled ? _dialogueThinkingEffortDraft : 'disabled')
      : 'disabled';
    dockEffort.disabled = !payload.supported;
    dockEffort.title = payload.supported ? '' : '当前模型不支持思考';
  }
  if (freeEffort) {
    freeEffort.value = payload.supported
      ? (payload.enabled ? _dialogueThinkingEffortDraft : 'disabled')
      : 'disabled';
    freeEffort.disabled = !payload.supported;
    freeEffort.title = payload.supported ? '' : '当前模型不支持思考';
  }
  const hint = $('f-thinking-support-hint');
  if (hint) {
    hint.textContent = payload.supported
      ? (payload.enabled ? `默认深度：${_dialogueThinkingEffortDraft}` : `已关闭，保留深度：${_dialogueThinkingEffortDraft}`)
      : '当前模型不支持思考';
  }
  _thinkingEffort = payload.thinking_effort;
  return payload;
}

function syncScoringThinkingControls({ enabled = null, effort = '', modelId = '', force = false } = {}) {
  const resolvedModelId = modelId || getInputValue('f-scoring-model').trim() || getPrimaryModelId();
  const fallbackEffort = DEFAULT_SCORING_THINKING_EFFORT;
  const checkbox = $('f-scoring-thinking-enabled');
  const select = $('f-scoring-thinking-effort');
  const userTouched = !!(checkbox?.dataset.userTouched || select?.dataset.userTouched);
  const currentEnabled = checkbox ? !!checkbox.checked : DEFAULT_SCORING_THINKING_ENABLED;
  const nextEnabled = enabled == null
    ? ((force || !userTouched) ? DEFAULT_SCORING_THINKING_ENABLED : currentEnabled)
    : !!enabled;
  const requestedEffort = normalizeThinkingEffortOption(
    effort || (select && select.value) || _scoringThinkingEffortDraft || fallbackEffort,
    fallbackEffort,
  );
  _scoringThinkingEffortDraft = requestedEffort === 'disabled' ? fallbackEffort : requestedEffort;
  const payload = resolveThinkingPayload(resolvedModelId, nextEnabled, _scoringThinkingEffortDraft);

  if (checkbox) {
    checkbox.checked = payload.enabled;
    checkbox.disabled = !payload.supported;
    checkbox.title = payload.supported ? '' : '当前模型不支持思考';
  }
  if (select) {
    select.value = _scoringThinkingEffortDraft;
    select.disabled = !payload.supported;
    select.title = payload.supported ? '' : '当前模型不支持思考';
  }
  const hint = $('f-scoring-thinking-support-hint');
  if (hint) {
    hint.textContent = payload.supported
      ? (payload.enabled ? `默认深度：${_scoringThinkingEffortDraft}` : `已关闭，保留深度：${_scoringThinkingEffortDraft}`)
      : '当前模型不支持思考';
  }
  syncScoringAdvancedPanel({ modelId: resolvedModelId });
  return payload;
}

function syncScoringAdvancedPanel({ modelId = '' } = {}) {
  const resolvedModelId = normalizeModelId(
    modelId || getInputValue('f-scoring-model').trim() || getPrimaryModelId(),
    DEFAULT_SCORING_MODEL_ID,
  );
  const panelModel = $('tc-scoring-model');
  if (panelModel) {
    const optionValues = [...panelModel.options].map(option => option.value);
    if (optionValues.includes(resolvedModelId)) {
      panelModel.value = resolvedModelId;
    }
  }

  const scoringThinking = getScoringThinkingState(resolvedModelId);
  const panelThinking = $('tc-scoring-thinking-effort');
  if (panelThinking) {
    panelThinking.value = scoringThinking.supported
      ? (scoringThinking.enabled ? scoringThinking.effort : 'disabled')
      : 'disabled';
    panelThinking.disabled = !scoringThinking.supported;
    panelThinking.title = scoringThinking.supported ? '' : '当前模型不支持思考';
  }
  const panelThinkingHint = $('tc-scoring-thinking-hint');
  if (panelThinkingHint) {
    panelThinkingHint.textContent = scoringThinking.supported
      ? (scoringThinking.enabled ? `默认深度：${scoringThinking.effort}` : `已关闭，保留深度：${_scoringThinkingEffortDraft}`)
      : '当前模型不支持思考';
  }

  const concurrency = normalizeScoringConcurrency(getInputValue('tc-scoring-concurrency'));
  if ($('tc-scoring-concurrency')) $('tc-scoring-concurrency').value = String(concurrency);
  if ($('tc-scoring-concurrency-display')) $('tc-scoring-concurrency-display').textContent = String(concurrency);
  if ($('tc-scoring-retry')) $('tc-scoring-retry').value = String(normalizeScoringRetryCount(getInputValue('tc-scoring-retry')));
}

function resolveScoringPromptRequestVersion({ preferLatestPrompt = false } = {}) {
  const latestFilename = getRuntimePromptFallbackFilename('scoring') || 'latest';
  if (preferLatestPrompt) return latestFilename;
  return getInputValue('f-scoring-prompt-version').trim() || latestFilename;
}

function buildScoringRuntimeRequest({ preferLatestPrompt = false } = {}) {
  const scoringModelId = normalizeModelId(
    getInputValue('tc-scoring-model').trim() || getInputValue('f-scoring-model').trim() || getPrimaryModelId(),
    DEFAULT_SCORING_MODEL_ID,
  );
  const scoringThinking = getScoringThinkingState(scoringModelId);
  return {
    scoring_model_id: scoringModelId,
    scoring_prompt_version: resolveScoringPromptRequestVersion({ preferLatestPrompt }),
    scoring_thinking_enabled: scoringThinking.enabled,
    scoring_thinking_effort: scoringThinking.thinking_effort,
    max_workers: normalizeScoringConcurrency(getInputValue('tc-scoring-concurrency')),
    scoring_retry_count: normalizeScoringRetryCount(getInputValue('tc-scoring-retry')),
  };
}

function syncChatThinkingEffortDefault(force = false) {
  syncDialogueThinkingControls({ modelId: getPrimaryModelId(), force });
}

function syncFreeChatThinkingEffortDefault(force = false) {
  syncDialogueThinkingControls({ modelId: getPrimaryModelId(), force });
}

function syncScoringThinkingDefault(force = false) {
  syncScoringThinkingControls({
    modelId: getInputValue('f-scoring-model').trim() || getPrimaryModelId(),
    force,
  });
}

function onDialogueThinkingEnabledChange() {
  const checkbox = $('f-thinking-enabled');
  if (checkbox) checkbox.dataset.userTouched = '1';
  syncDialogueThinkingControls({
    enabled: checkbox ? checkbox.checked : DEFAULT_THINKING_ENABLED,
    effort: getInputValue('f-thinking-effort').trim() || _dialogueThinkingEffortDraft,
    modelId: getPrimaryModelId(),
    force: true,
  });
}

function onDialogueThinkingEffortChange() {
  const select = $('f-thinking-effort');
  if (select) select.dataset.userTouched = '1';
  syncDialogueThinkingControls({
    enabled: $('f-thinking-enabled') ? !!$('f-thinking-enabled').checked : DEFAULT_THINKING_ENABLED,
    effort: getInputValue('f-thinking-effort').trim() || _dialogueThinkingEffortDraft,
    modelId: getPrimaryModelId(),
    force: true,
  });
}

function onScoringThinkingEnabledChange() {
  const checkbox = $('f-scoring-thinking-enabled');
  if (checkbox) checkbox.dataset.userTouched = '1';
  syncScoringThinkingControls({
    enabled: checkbox ? checkbox.checked : DEFAULT_SCORING_THINKING_ENABLED,
    effort: getInputValue('f-scoring-thinking-effort').trim() || _scoringThinkingEffortDraft,
    modelId: getInputValue('f-scoring-model').trim() || getPrimaryModelId(),
    force: true,
  });
  refreshTestCenterShell();
  refreshScoringDefaultsStatus();
}

function onScoringThinkingEffortChange() {
  const select = $('f-scoring-thinking-effort');
  if (select) select.dataset.userTouched = '1';
  syncScoringThinkingControls({
    enabled: $('f-scoring-thinking-enabled') ? !!$('f-scoring-thinking-enabled').checked : DEFAULT_SCORING_THINKING_ENABLED,
    effort: getInputValue('f-scoring-thinking-effort').trim() || _scoringThinkingEffortDraft,
    modelId: getInputValue('f-scoring-model').trim() || getPrimaryModelId(),
    force: true,
  });
  refreshTestCenterShell();
  refreshScoringDefaultsStatus();
}

function onChatThinkingEffortChange() {
  const sel = $('f-thinking-effort-chat');
  if (sel) sel.dataset.userTouched = '1';
  const raw = normalizeThinkingEffortOption(sel ? sel.value : '', _dialogueThinkingEffortDraft);
  syncDialogueThinkingControls({
    enabled: raw !== 'disabled',
    effort: raw === 'disabled' ? _dialogueThinkingEffortDraft : raw,
    modelId: getPrimaryModelId(),
    force: true,
  });
}

function normalizeInjectionDepthValue(value) {
  const parsed = parseInt(String(value || '').trim(), 10);
  if (!Number.isFinite(parsed)) return DEFAULT_INJECTION_DEPTH;
  return Math.max(1, parsed);
}

function showInjectionDepthHelp() {
  showToast('注入深度表示角色深度锚定插入到历史消息中的位置：2=倒数第2条，数值越大越靠前；推荐 2/3/4/5，也支持自定义。', 'info', 4200);
}

function adjustInjectionDepth(delta = 0) {
  const input = $('f-injection-depth');
  if (!input) return;
  const nextValue = normalizeInjectionDepthValue((parseInt(input.value || String(DEFAULT_INJECTION_DEPTH), 10) || DEFAULT_INJECTION_DEPTH) + Number(delta || 0));
  input.value = String(nextValue);
  input.dispatchEvent(new Event('change', { bubbles: true }));
}

const GENERATION_PRESET_CONFIGS = {
  precise: { temperature: 0.2, top_p: 0.7 },
  balanced: { temperature: 1, top_p: 0.95 },
  creative: { temperature: 0.8, top_p: 1 },
};

const GENERATION_FIELD_RULES = {
  temperature: { min: 0, max: 2, step: 0.05, fallback: GENERATION_PRESET_CONFIGS.balanced.temperature },
  top_p: { min: 0, max: 1, step: 0.05, fallback: GENERATION_PRESET_CONFIGS.balanced.top_p },
};

function formatGenerationNumber(value) {
  const num = Number.parseFloat(value);
  if (!Number.isFinite(num)) return '0';
  const rounded = Math.round(num * 100) / 100;
  if (Number.isInteger(rounded)) return String(rounded);
  return rounded.toFixed(2).replace(/0+$/, '').replace(/\.$/, '');
}

function normalizeGenerationValue(field, value) {
  const rule = GENERATION_FIELD_RULES[field];
  if (!rule) return 0;
  const parsed = Number.parseFloat(String(value ?? '').trim());
  const base = Number.isFinite(parsed) ? parsed : rule.fallback;
  const clamped = Math.min(rule.max, Math.max(rule.min, base));
  const steps = Math.round(clamped / rule.step);
  return Math.round(steps * rule.step * 100) / 100;
}

function detectGenerationPresetKey(temperature, topP) {
  const temp = normalizeGenerationValue('temperature', temperature);
  const top = normalizeGenerationValue('top_p', topP);
  const hit = Object.entries(GENERATION_PRESET_CONFIGS).find(([, preset]) => (
    Math.abs(preset.temperature - temp) < 0.001
    && Math.abs(preset.top_p - top) < 0.001
  ));
  return hit ? hit[0] : 'custom';
}

const GLOBAL_GENERATION_BUTTON_IDS = {
  precise: ['btn-generation-preset-precise', 'sp-btn-generation-preset-precise'],
  balanced: ['btn-generation-preset-balanced', 'sp-btn-generation-preset-balanced'],
  creative: ['btn-generation-preset-creative', 'sp-btn-generation-preset-creative'],
  custom: ['btn-generation-preset-custom', 'sp-btn-generation-preset-custom'],
};

const GLOBAL_GENERATION_INPUT_IDS = {
  temperature: ['f-temperature', 'f-temperature-range', 'sp-temperature', 'sp-temperature-range'],
  top_p: ['f-top-p', 'f-top-p-range', 'sp-top-p', 'sp-top-p-range'],
};

function updateGenerationPresetButtons(presetKey = 'custom') {
  ['precise', 'balanced', 'creative', 'custom'].forEach(key => {
    (GLOBAL_GENERATION_BUTTON_IDS[key] || []).forEach(id => {
      const button = $(id);
      if (!button) return;
      button.classList.toggle('active', key === presetKey);
      button.setAttribute('aria-pressed', key === presetKey ? 'true' : 'false');
    });
  });
}

function syncGenerationField(field, value, source = 'number', options = {}) {
  const nextValue = normalizeGenerationValue(field, value);
  const targetIds = GLOBAL_GENERATION_INPUT_IDS[field] || [];
  targetIds.forEach(id => {
    const el = $(id);
    if (!el) return;
    el.value = formatGenerationNumber(nextValue);
  });
  if (!options.keepPreset) {
    const current = getGenerationSamplingConfig();
    updateGenerationPresetButtons(detectGenerationPresetKey(current.temperature, current.top_p));
  }
  refreshHeaderModelSettingsButtonState();
  return nextValue;
}

function getGenerationSamplingConfig(source = null) {
  if (source) {
    return {
      temperature: normalizeGenerationValue('temperature', source.temperature),
      top_p: normalizeGenerationValue('top_p', source.top_p),
    };
  }
  return {
    temperature: normalizeGenerationValue('temperature', getInputValue('f-temperature')),
    top_p: normalizeGenerationValue('top_p', getInputValue('f-top-p')),
  };
}

function setGenerationPreset(presetKey = 'balanced') {
  if (presetKey === 'custom') {
    updateGenerationPresetButtons('custom');
    return;
  }
  const preset = GENERATION_PRESET_CONFIGS[presetKey] || GENERATION_PRESET_CONFIGS.balanced;
  syncGenerationField('temperature', preset.temperature, 'preset', { keepPreset: true });
  syncGenerationField('top_p', preset.top_p, 'preset', { keepPreset: true });
  updateGenerationPresetButtons(presetKey);
}

function adjustGenerationField(field, delta = 0) {
  const current = getGenerationSamplingConfig();
  const nextValue = field === 'temperature'
    ? current.temperature + Number(delta || 0)
    : current.top_p + Number(delta || 0);
  syncGenerationField(field, nextValue);
}

function syncGenerationControlsFromConfig(source = null) {
  const sampling = getGenerationSamplingConfig(source);
  syncGenerationField('temperature', sampling.temperature, 'config', { keepPreset: true });
  syncGenerationField('top_p', sampling.top_p, 'config', { keepPreset: true });
  updateGenerationPresetButtons(detectGenerationPresetKey(sampling.temperature, sampling.top_p));
  refreshHeaderModelSettingsButtonState();
}

const FREECHAT_GENERATION_BUTTON_IDS = {
  precise: 'fc-btn-generation-preset-precise',
  balanced: 'fc-btn-generation-preset-balanced',
  creative: 'fc-btn-generation-preset-creative',
  custom: 'fc-btn-generation-preset-custom',
};

const FREECHAT_GENERATION_INPUT_IDS = {
  temperature: ['fc-temperature', 'fc-temperature-range'],
  top_p: ['fc-top-p', 'fc-top-p-range'],
};

function updateFreeChatGenerationPresetButtons(presetKey = 'custom') {
  ['precise', 'balanced', 'creative', 'custom'].forEach(key => {
    const button = $(FREECHAT_GENERATION_BUTTON_IDS[key]);
    if (!button) return;
    button.classList.toggle('active', key === presetKey);
    button.setAttribute('aria-pressed', key === presetKey ? 'true' : 'false');
  });
}

function getStoredFreeChatSamplingConfig(modelId = '') {
  const saved = (modelId && freeChatSamplingConfigs[modelId]) || {};
  const fallback = getGenerationSamplingConfig();
  return {
    temperature: normalizeGenerationValue('temperature', saved.temperature ?? fallback.temperature),
    top_p: normalizeGenerationValue('top_p', saved.top_p ?? fallback.top_p),
  };
}

function syncFreeChatGenerationField(field, value, source = 'number', options = {}) {
  const nextValue = normalizeGenerationValue(field, value);
  (FREECHAT_GENERATION_INPUT_IDS[field] || []).forEach(id => {
    const el = $(id);
    if (!el) return;
    el.value = formatGenerationNumber(nextValue);
  });
  if (!options.keepPreset) {
    const current = getFreeChatSamplingDraft();
    updateFreeChatGenerationPresetButtons(detectGenerationPresetKey(current.temperature, current.top_p));
  }
  return nextValue;
}

function getFreeChatSamplingDraft() {
  return {
    temperature: normalizeGenerationValue('temperature', getInputValue('fc-temperature')),
    top_p: normalizeGenerationValue('top_p', getInputValue('fc-top-p')),
  };
}

function syncFreeChatGenerationControls(modelId = '') {
  const sampling = getStoredFreeChatSamplingConfig(modelId);
  syncFreeChatGenerationField('temperature', sampling.temperature, 'config', { keepPreset: true });
  syncFreeChatGenerationField('top_p', sampling.top_p, 'config', { keepPreset: true });
  updateFreeChatGenerationPresetButtons(detectGenerationPresetKey(sampling.temperature, sampling.top_p));
}

function setFreeChatGenerationPreset(presetKey = 'balanced') {
  if (presetKey === 'custom') {
    updateFreeChatGenerationPresetButtons('custom');
    return;
  }
  const preset = GENERATION_PRESET_CONFIGS[presetKey] || GENERATION_PRESET_CONFIGS.balanced;
  syncFreeChatGenerationField('temperature', preset.temperature, 'preset', { keepPreset: true });
  syncFreeChatGenerationField('top_p', preset.top_p, 'preset', { keepPreset: true });
  updateFreeChatGenerationPresetButtons(presetKey);
}

function adjustFreeChatGenerationField(field, delta = 0) {
  const current = getFreeChatSamplingDraft();
  const nextValue = field === 'temperature'
    ? current.temperature + Number(delta || 0)
    : current.top_p + Number(delta || 0);
  syncFreeChatGenerationField(field, nextValue);
}

function truncateText(value, max = 20) {
  const text = String(value || '').replace(/\s+/g, ' ').trim();
  if (!text) return '';
  return text.length > max ? `${text.slice(0, max)}…` : text;
}

function normalizeSqliteUtcTimestamp(value) {
  if (!value) return '';
  // SQLite CURRENT_TIMESTAMP 存储 UTC 但无时区标记，手动追加 Z 强制 UTC 解析
  let raw = String(value).trim();
  if (/^\d{4}-\d{2}-\d{2}[\sT]\d{2}:\d{2}/.test(raw) && !/[Z+-]/.test(raw.slice(-6))) {
    raw = raw.replace(' ', 'T') + 'Z';
  }
  return raw;
}

function parseSqliteUtcDate(value) {
  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? null : value;
  }
  if (typeof value === 'number') {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? null : date;
  }
  const raw = normalizeSqliteUtcTimestamp(value);
  const date = new Date(raw || '');
  return Number.isNaN(date.getTime()) ? null : date;
}

function formatBeijingDateTime(value) {
  const date = parseSqliteUtcDate(value);
  if (!date) return '';
  try {
    return date.toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' });
  } catch (_) {
    return date.toLocaleString('zh-CN');
  }
}

function formatRelativeTime(value) {
  if (!value) return '';
  const date = parseSqliteUtcDate(value);
  if (!date) return '';
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 1) return '刚刚';
  if (diffMin < 60) return `${diffMin}分钟前`;
  const diffHour = Math.floor(diffMin / 60);
  if (diffHour < 24) return `${diffHour}小时前`;
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (
    date.getFullYear() === yesterday.getFullYear()
    && date.getMonth() === yesterday.getMonth()
    && date.getDate() === yesterday.getDate()
  ) {
    return `昨天 ${date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}`;
  }
  if (date.getFullYear() === now.getFullYear()) {
    return `${date.getMonth() + 1}月${date.getDate()}日`;
  }
  return date.toLocaleDateString('zh-CN');
}

const WAITING_STAGE_FALLBACKS = [
  { untilMs: 5000, label: '请求已发送' },
  { untilMs: 15000, label: '模型处理中' },
  { untilMs: Number.POSITIVE_INFINITY, label: '结果整理中' },
];

function resolveWaitingStageLabel(elapsedMs) {
  const target = WAITING_STAGE_FALLBACKS.find(item => elapsedMs < item.untilMs) || WAITING_STAGE_FALLBACKS[WAITING_STAGE_FALLBACKS.length - 1];
  return target.label;
}

function formatWaitingElapsed(elapsedMs) {
  const seconds = Math.max(1, Math.floor(elapsedMs / 1000));
  return `已等待 ${seconds} 秒`;
}

function stopWaitingTracker(key) {
  const tracker = state.waitingTrackers[key];
  if (!tracker) return null;
  window.clearInterval(tracker.timerId);
  delete state.waitingTrackers[key];
  return tracker;
}

function startWaitingTracker(key, options = {}) {
  stopWaitingTracker(key);
  const tracker = {
    key,
    prefix: options.prefix || '',
    forcedStage: options.forcedStage || '',
    startedAt: Date.now(),
    onUpdate: typeof options.onUpdate === 'function' ? options.onUpdate : () => { },
  };
  const emit = () => {
    const elapsedMs = Math.max(0, Date.now() - tracker.startedAt);
    const stageLabel = tracker.forcedStage || resolveWaitingStageLabel(elapsedMs);
    tracker.onUpdate({
      key,
      prefix: tracker.prefix,
      stageLabel,
      elapsedMs,
      elapsedText: formatWaitingElapsed(elapsedMs),
    });
  };
  tracker.setPrefix = (prefix) => {
    tracker.prefix = prefix || '';
    emit();
  };
  tracker.setStage = (stageLabel = '') => {
    tracker.forcedStage = stageLabel || '';
    emit();
  };
  tracker.reset = () => {
    tracker.startedAt = Date.now();
    emit();
  };
  tracker.clearStage = () => {
    tracker.forcedStage = '';
    emit();
  };
  tracker.stop = () => stopWaitingTracker(key);
  tracker.timerId = window.setInterval(emit, 1000);
  state.waitingTrackers[key] = tracker;
  emit();
  return tracker;
}

function buildDebugPayloadSnapshot({ modelId = '', messages = [], webSearch = false, thinkingEffort = 'disabled' } = {}) {
  const formConfig = typeof getFormConfig === 'function' ? getFormConfig() : {};
  const modules = typeof buildSystemModulesPayload === 'function' ? buildSystemModulesPayload(formConfig) : {};
  const activeModelId = modelId || formConfig.model_pro || getPrimaryModelId();
  const dialogueThinking = resolveThinkingPayload(
    activeModelId,
    coerceOptionalBoolean(formConfig.thinking_enabled) ?? true,
    formConfig.thinking_effort || thinkingEffort,
  );
  const scoringThinking = resolveThinkingPayload(
    formConfig.scoring_model_id || activeModelId,
    coerceOptionalBoolean(formConfig.scoring_thinking_enabled) ?? true,
    formConfig.scoring_thinking_effort || '',
  );
  return {
    model_id: activeModelId,
    messages: Array.isArray(messages) ? messages.map(item => ({ ...item })) : [],
    web_search: !!webSearch,
    thinking_enabled: dialogueThinking.enabled,
    thinking_effort: dialogueThinking.thinking_effort,
    prompt_version: formConfig.prompt_version || '',
    summary_prompt_version: formConfig.summary_prompt_version || '',
    scoring_prompt_version: formConfig.scoring_prompt_version || '',
    scoring_model_id: formConfig.scoring_model_id || activeModelId,
    scoring_thinking_enabled: scoringThinking.enabled,
    scoring_thinking_effort: scoringThinking.thinking_effort,
    summary_interval: formConfig.summary_interval,
    injection_depth: formConfig.injection_depth,
    temperature: formConfig.temperature,
    top_p: formConfig.top_p,
    role_name: formConfig.nickname || '',
    relationship: formConfig.relationship || '',
    personality: formConfig.personality || '',
    system_prompt: modules.system_prompt || getInputValue('f-system-prompt'),
    system_after: '',
    custom_variables: getMergedCustomVariables(),
    character: {
      Role_Nickname: formConfig.nickname || '',
      personality: formConfig.personality || '',
    },
  };
}

function inferConversationChannelFromPrompt(promptText = getInputValue('f-system-prompt')) {
  const text = String(promptText || '').trim();
  if (!text) return '';
  if (/(1V1语音聊天|语音聊天|电话聊天|语音通话)/.test(text)) return '电话聊天沟通';
  if (/(文字聊天|文本聊天)/.test(text)) return '文字聊天沟通';
  return '';
}

function formatLastConversationType(channel) {
  const text = String(channel || '').trim();
  if (!text) return '';
  return text.startsWith('上一次在') ? text : `上一次在${text}`;
}

function resolvePreviousConversationType(roleName = getInputValue('f-nickname').trim()) {
  const items = Array.isArray(state.historyItems) ? state.historyItems : [];
  const currentId = String(state.convId || '').trim();
  const targetRole = String(roleName || '').trim();

  for (const item of items) {
    if (currentId && String(item.id || '').trim() === currentId) continue;
    if (targetRole && String(item.nickname || '').trim() !== targetRole) continue;
    const resolved = formatLastConversationType(item.conversation_channel || '');
    if (resolved) return resolved;
  }
  for (const item of items) {
    if (currentId && String(item.id || '').trim() === currentId) continue;
    const resolved = formatLastConversationType(item.conversation_channel || '');
    if (resolved) return resolved;
  }
  return '';
}

function normalizeDebugEntry(source = {}, fallback = {}) {
  const basePayload = source.request_payload_snapshot || fallback.request_payload_snapshot || {};
  const sourceMessages = source.messages || source.request_messages || fallback.messages || fallback.request_messages || [];
  const payloadMessages = Array.isArray(basePayload.messages) && basePayload.messages.length ? basePayload.messages : sourceMessages;
  const normalizedMessages = Array.isArray(payloadMessages) ? payloadMessages : [];
  const requestPayload = {
    ...basePayload,
    prompt_version: basePayload.prompt_version ?? source.prompt_version ?? fallback.prompt_version ?? '',
    summary_prompt_version: basePayload.summary_prompt_version ?? source.summary_prompt_version ?? fallback.summary_prompt_version ?? '',
    scoring_prompt_version: basePayload.scoring_prompt_version ?? source.scoring_prompt_version ?? fallback.scoring_prompt_version ?? '',
    scoring_model_id: basePayload.scoring_model_id ?? source.scoring_model_id ?? fallback.scoring_model_id ?? '',
    role_name: basePayload.role_name ?? source.role_name ?? fallback.role_name ?? '',
    relationship: basePayload.relationship ?? source.relationship ?? fallback.relationship ?? '',
    personality: basePayload.personality ?? source.personality ?? fallback.personality ?? '',
    system_prompt: basePayload.system_prompt ?? source.system_prompt ?? fallback.system_prompt ?? '',
    system_after: basePayload.system_after ?? source.system_after ?? fallback.system_after ?? '',
    custom_variables: basePayload.custom_variables || source.custom_variables || fallback.custom_variables || {},
    character: basePayload.character || source.character || fallback.character || {},
    messages: normalizedMessages.map(item => ({ ...item })),
  };
  return {
    ...source,
    messages: normalizedMessages,
    request_messages: normalizedMessages,
    request_payload_snapshot: requestPayload,
    trim_level: source.trim_level ?? fallback.trim_level ?? 0,
    total_tokens: source.total_tokens ?? fallback.total_tokens ?? 0,
    has_deep_injection: source.has_deep_injection ?? fallback.has_deep_injection ?? false,
    quality_retries: source.quality_retries ?? fallback.quality_retries ?? 0,
    model: source.model || requestPayload.model_id || fallback.model || '',
  };
}

function getDebugMessages(debugEntry = {}) {
  const payload = debugEntry.request_payload_snapshot || {};
  if (Array.isArray(payload.messages) && payload.messages.length) return payload.messages;
  if (Array.isArray(debugEntry.messages)) return debugEntry.messages;
  if (Array.isArray(debugEntry.request_messages)) return debugEntry.request_messages;
  return [];
}

function buildTurnDebugEntry(turn = {}, options = {}) {
  const requestPayloadSnapshot = turn.request_payload_snapshot || buildDebugPayloadSnapshot({
    modelId: turn.model_id || options.modelId || '',
    messages: turn.messages || turn.messages_snapshot || [],
  });
  return normalizeDebugEntry(
    turn.debug_info || {
      messages: turn.messages || turn.messages_snapshot || [],
      trim_level: turn.token_trim_level || 0,
      total_tokens: turn.input_tokens || 0,
      has_deep_injection: !!turn.has_deep_injection,
      quality_retries: turn.quality_retries || 0,
      request_payload_snapshot: requestPayloadSnapshot,
      model: turn.model_id || options.modelId || '',
    },
    {
      messages: turn.messages || turn.messages_snapshot || [],
      request_payload_snapshot: requestPayloadSnapshot,
      trim_level: turn.token_trim_level || 0,
      total_tokens: turn.input_tokens || 0,
      has_deep_injection: !!turn.has_deep_injection,
      quality_retries: turn.quality_retries || 0,
      model: turn.model_id || options.modelId || '',
    }
  );
}

function renderDebugRequestDetails(payload = {}, messages = []) {
  const host = $('debug-request-details');
  if (!host) return;
  const safeMessages = Array.isArray(messages) ? messages : [];
  const roleCounts = safeMessages.reduce((acc, item) => {
    const role = item && item.role ? String(item.role) : 'unknown';
    acc[role] = (acc[role] || 0) + 1;
    return acc;
  }, {});
  const overviewRows = [
    ['消息总数', safeMessages.length || 0],
    ['system/user/assistant', `${roleCounts.system || 0}/${roleCounts.user || 0}/${roleCounts.assistant || 0}`],
    ['联网', payload.web_search ? '开启' : '关闭'],
    ['思考强度', payload.thinking_effort || 'disabled'],
    ['摘要间隔', payload.summary_interval || '-'],
    ['注入深度', payload.injection_depth || '-'],
    ['Temperature', payload.temperature ?? '-'],
    ['Top P', payload.top_p ?? '-'],
  ];
  const renderRows = (rows = []) => (
    `<div class="debug-request-list">${rows.map(([label, value]) => `
      <div class="debug-request-row">
        <span>${escapeHtml(String(label))}</span>
        <strong>${escapeHtml(String(value ?? '-'))}</strong>
      </div>`).join('')}</div>`
  );

  const sections = [
    `<section class="debug-request-card"><h4>请求摘要</h4>${renderRows(overviewRows)}</section>`,
  ];

  const character = payload.character && typeof payload.character === 'object' ? payload.character : {};
  const characterRows = Object.entries(character).filter(([, value]) => value !== undefined && value !== null && String(value).trim() !== '');
  if (characterRows.length || payload.role_name || payload.relationship || payload.personality) {
    const rows = [
      ['角色名', payload.role_name || character.Role_Nickname || '-'],
      ['关系阶段', payload.relationship || '-'],
      ['性格', payload.personality || character.personality || '-'],
    ];
    sections.push(`<section class="debug-request-card"><h4>角色上下文</h4>${renderRows(rows)}</section>`);
  }

  const customVariables = payload.custom_variables && typeof payload.custom_variables === 'object' ? payload.custom_variables : {};
  const customRows = Object.entries(customVariables)
    .filter(([, value]) => value !== undefined && value !== null && String(value).trim() !== '')
    .map(([key, value]) => [key, value]);
  if (customRows.length) {
    sections.push(`<section class="debug-request-card"><h4>变量覆盖</h4>${renderRows(customRows)}</section>`);
  }

  if (payload.system_prompt) {
    sections.push(
      `<section class="debug-request-card"><h4>主 System Prompt</h4><pre class="debug-request-pre">${escapeHtml(String(payload.system_prompt))}</pre></section>`
    );
  }
  if (payload.system_after) {
    sections.push(
      `<section class="debug-request-card"><h4>Few-shot 之后的 System 片段</h4><pre class="debug-request-pre">${escapeHtml(String(payload.system_after))}</pre></section>`
    );
  }

  if (!sections.length) {
    host.innerHTML = '<div class="debug-request-empty">当前轮次未记录结构化请求信息。</div>';
    return;
  }
  host.innerHTML = sections.join('');
}

function switchDebugPanel(panel) {
  _debugPanelMode = panel === 'request' ? 'request' : 'messages';
  const isRequest = _debugPanelMode === 'request';
  $('debug-tab-messages')?.classList.toggle('active', !isRequest);
  $('debug-tab-request')?.classList.toggle('active', isRequest);
  if ($('debug-view-messages')) $('debug-view-messages').style.display = isRequest ? 'none' : 'block';
  if ($('debug-view-request')) $('debug-view-request').style.display = isRequest ? 'block' : 'none';
}

async function copyCurrentDebugJson() {
  if (!state.debugData.length) {
    showToast('暂无可复制的调试数据', 'warning');
    return;
  }
  const idx = Math.max(0, parseInt($('debug-turn-select')?.value || '0', 10) || 0);
  const entry = normalizeDebugEntry(state.debugData[idx] || {});
  const text = JSON.stringify(entry.request_payload_snapshot || {}, null, 2);
  try {
    await navigator.clipboard.writeText(text);
    showToast('完整请求 JSON 已复制', 'success');
  } catch (e) {
    showToast('复制失败: ' + e.message, 'error');
  }
}

function showModal(modalId) {
  const modalEl = typeof modalId === 'string' ? $(modalId) : modalId;
  if (!modalEl) return;
  modalEl._returnFocus = document.activeElement;
  modalEl.style.display = 'flex';
  modalEl.setAttribute('aria-hidden', 'false');
  trapFocus(modalEl);
}

function closeModal(modalId) {
  const modalEl = typeof modalId === 'string' ? $(modalId) : modalId;
  if (!modalEl) return;
  if (modalEl.id === 'modal-action-confirm' && _actionConfirmState?.resolve) {
    const resolve = _actionConfirmState.resolve;
    _actionConfirmState = null;
    resolve(false);
  }
  releaseFocus(modalEl);
  modalEl.style.display = 'none';
  modalEl.setAttribute('aria-hidden', 'true');
  if (modalEl.id === 'modal-sp-edit') {
    _runtimePromptEditorContext = null;
  }
  if (modalEl.id === 'modal-preset-delete') {
    _pendingPresetDelete = null;
  }
  if (modalEl.id === 'modal-ai-summary') {
    _aiSummaryModalState = null;
    setAiSummaryDownloadState(false);
  }
  if (modalEl.id === 'modal-freechat-prompt') {
    _currentFreeChatModel = null;
  }
  const returnFocus = modalEl._returnFocus;
  if (returnFocus && typeof returnFocus.focus === 'function' && document.contains(returnFocus)) {
    returnFocus.focus();
  }
}

function openActionConfirmDialog({
  title = '确认执行操作',
  message = '请确认是否继续。',
  note = '',
  confirmText = '确认',
  confirmTone = 'primary',
} = {}) {
  const modal = $('modal-action-confirm');
  if (!modal) return Promise.resolve(confirm(message));
  if (_actionConfirmState?.resolve) {
    _actionConfirmState.resolve(false);
    _actionConfirmState = null;
  }
  if ($('action-confirm-title')) $('action-confirm-title').textContent = title;
  if ($('action-confirm-message')) $('action-confirm-message').textContent = message;
  const noteEl = $('action-confirm-note');
  if (noteEl) {
    noteEl.textContent = note || '';
    noteEl.style.display = note ? 'block' : 'none';
  }
  const confirmBtn = $('btn-action-confirm');
  if (confirmBtn) {
    confirmBtn.textContent = confirmText || '确认';
    confirmBtn.className = confirmTone === 'danger' ? 'btn btn-danger' : 'btn btn-primary';
  }
  return new Promise((resolve) => {
    _actionConfirmState = { resolve };
    showModal(modal);
  });
}

function resolveActionConfirmDialog(confirmed) {
  const snapshot = _actionConfirmState;
  _actionConfirmState = null;
  const modal = $('modal-action-confirm');
  if (modal) {
    releaseFocus(modal);
    modal.style.display = 'none';
    modal.setAttribute('aria-hidden', 'true');
    const returnFocus = modal._returnFocus;
    if (returnFocus && typeof returnFocus.focus === 'function' && document.contains(returnFocus)) {
      returnFocus.focus();
    }
  }
  if (snapshot?.resolve) {
    snapshot.resolve(Boolean(confirmed));
  }
}

function buildConversationFormConfig(data) {
  const config = data.config || {};
  const character = config.character || {};
  const context = config.context || {};
  const modules = config.modules || {};
  const runtime = config.runtime || {};
  const promptBaseValues = {
    currentTime: context.currentTime || '',
    weekDay: context.weekDay || '',
    timeperiod: context.timeperiod || context.time_period || '',
    season: context.season || '',
    moments: modules.moments || '',
    monthly_schedule: modules.monthly_schedule || '',
    last_cst_type: context.last_cst_type || '',
    完整时间信息: context['完整时间信息'] || '',
  };
  return {
    nickname: character.Role_Nickname || '',
    gender: character.gender || '男',
    age: character.age || 25,
    occupation: character.occupation || '',
    role_info_works: character.Role_info_works || '',
    personality: character.personality || character.personal_type || '',
    speaking_style: character.speaking_style || '',
    background: character.background || '',
    hobby: character.hobby || '',
    relationship: context.relationship || '暧昧',
    scene: context.scene || context.current_scene || '',
    time_period: context.time_period || context.timeperiod || '',
    season: context.season || '',
    user_nickname: context.user_nickname || modules.user_Nickname || '小鹿',
    user_gender: context.user_gender || modules.user_gender || '女',
    user_identity: context.user_identity || modules.user_identity || '',
    prompt_version: data.prompt_version || data.prompt_file || config.prompt_file || '',
    summary_prompt_version: data.summary_prompt_version || runtime.summary_prompt_version || '',
    scoring_prompt_version: data.scoring_prompt_version || runtime.scoring_prompt_version || '',
    summary_interval: data.summary_interval || runtime.summary_interval || DEFAULT_SUMMARY_INTERVAL,
    injection_depth: runtime.injection_depth || DEFAULT_INJECTION_DEPTH,
    temperature: data.temperature ?? runtime.temperature ?? GENERATION_PRESET_CONFIGS.balanced.temperature,
    top_p: data.top_p ?? runtime.top_p ?? GENERATION_PRESET_CONFIGS.balanced.top_p,
    model_pro: normalizeModelId(data.model_id || runtime.model_id || ''),
    model_mini: normalizeModelId(data.model_mini || runtime.model_mini || '', DEFAULT_SUMMARY_MODEL_ID),
    scoring_model_id: data.scoring_model_id || runtime.scoring_model_id || data.model_id || '',
    thinking_enabled: runtime.thinking_enabled,
    thinking_effort: runtime.thinking_effort || '',
    scoring_thinking_enabled: runtime.scoring_thinking_enabled,
    scoring_thinking_effort: runtime.scoring_thinking_effort || '',
    scoring_max_workers: normalizeScoringConcurrency(data.scoring_max_workers ?? runtime.scoring_max_workers ?? DEFAULT_SCORING_CONCURRENCY),
    scoring_retry_count: normalizeScoringRetryCount(data.scoring_retry_count ?? runtime.scoring_retry_count ?? DEFAULT_SCORING_RETRY_COUNT),
    sys_persona: modules.longform_persona || '',
    sys_style: modules.longform_narrative_style || '',
    longform_dialogue_guideline: modules.longform_dialogue_guideline || '',
    sys_fewshot: modules.longform_few_shot || '',
    sys_startprompt: modules.dialogueStartPrompt || '',
    sys_summary: modules.dialogue_summary || '',
    sys_module8: modules.system_module8 || '',
    weekly_schedule: modules.weekly_schedule || '',
    sys_role_acting: modules.system_Role_acting || '',
    voice_forbidden: modules.voice_forbidden || DEFAULT_VOICE_FORBIDDEN,
    system_prompt: modules.system_prompt || '',
    custom_variables: config.custom_variables || data.custom_variables || {},
    prompt_base_values: promptBaseValues,
  };
}

function closeAllModelPickers(except = null) {
  document.querySelectorAll('.shared-model-picker.open').forEach(node => {
    if (except && node === except) return;
    node.classList.remove('open');
    const menu = node.querySelector('.shared-model-picker-menu');
    if (menu) menu.remove();
  });
}

function renderSharedModelPicker(target, {
  options = [],
  value = '',
  onChange = null,
  accentColor = '',
  showIcon = false,
} = {}) {
  const container = typeof target === 'string' ? $(target) : target;
  if (!container) return;
  const active = options.find(item => item.id === value) || options[0] || { id: '', name: '等待加载模型...' };
  container.className = `shared-model-picker ${container.className || ''}`.trim();
  container.innerHTML = `
    <button type="button" class="shared-model-picker-btn">
      <span class="shared-model-picker-label">
        ${showIcon ? `<svg viewBox="0 0 24 24" width="16" height="16" fill="var(--primary-color)"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg>` : ''}
        <span class="shared-model-picker-title" style="${accentColor ? `color:${accentColor}` : ''}">${escapeHtml(active.name || active.id || '选择模型')}</span>
      </span>
      <span class="shared-model-picker-caret">▼</span>
    </button>
  `;
  const button = container.querySelector('.shared-model-picker-btn');
  button.onclick = (event) => {
    event.stopPropagation();
    if (container.classList.contains('open')) {
      closeAllModelPickers();
      return;
    }
    closeAllModelPickers(container);
    const menu = document.createElement('div');
    menu.className = 'shared-model-picker-menu';
    options.forEach(item => {
      const row = document.createElement('button');
      row.type = 'button';
      row.className = `shared-model-picker-item ${item.id === active.id ? 'active' : ''}`;
      row.innerHTML = `<span>${escapeHtml(item.name || item.id || '')}</span>${item.id === active.id ? '<span class="shared-model-picker-check">✓</span>' : ''}`;
      row.onclick = (ev) => {
        ev.stopPropagation();
        closeAllModelPickers();
        if (typeof onChange === 'function') onChange(item);
      };
      menu.appendChild(row);
    });
    container.appendChild(menu);
    container.classList.add('open');
  };
}

function setPrimaryModelId(modelId) {
  if ($('header-global-model')) $('header-global-model').value = modelId || '';
  if ($('f-model-pro')) $('f-model-pro').value = modelId || '';
  renderHeaderModelPicker();
  updateControlStates(modelId || '');
}

function renderHeaderModelPicker() {
  renderSharedModelPicker('header-model-picker', {
    options: _allModelOptions,
    value: getPrimaryModelId(),
    onChange: (item) => setPrimaryModelId(item.id),
    showIcon: true,
  });
  refreshHeaderModelSettingsButtonState();
}

function refreshHeaderModelSettingsButtonState() {
  const button = $('btn-header-model-settings');
  if (!button) return;
  button.disabled = !getPrimaryModelId();
  const sampling = getGenerationSamplingConfig();
  const hasCustomSampling = detectGenerationPresetKey(sampling.temperature, sampling.top_p) !== 'balanced';
  const currentPrompt = getInputValue('f-prompt-version').trim();
  const hasPinnedPrompt = !!currentPrompt && !!_activeChatPromptFilename && currentPrompt !== _activeChatPromptFilename;
  button.classList.toggle('active', hasCustomSampling || hasPinnedPrompt);
  button.title = hasCustomSampling || hasPinnedPrompt
    ? '当前模型已配置自定义 Prompt 或多样性'
    : '编辑当前模型的 Prompt 与多样性';
}

window.openHeaderModelSettings = function () {
  if (!getPrimaryModelId()) {
    showToast('请先选择主模型', 'warning');
    return;
  }
  openRuntimePromptEditor('chat');
};

/* ═══ 页面切换 ═══ */
function shouldShowChatChrome(name) {
  return name === 'chat' || name === 'freechat';
}

function setRightPanelVisible(visible) {
  document.body.classList.toggle('right-panel-open', !!visible);
  const panel = $('rightPanel');
  if (!panel) return;
  panel.style.display = visible ? 'flex' : 'none';
}

function syncPageChrome(name) {
  const inChatPage = shouldShowChatChrome(name);
  const topTools = $('chat-top-tools');
  if (topTools) topTools.style.display = inChatPage ? 'flex' : 'none';
  const toggleBtn = $('togglePanelBtn');
  if (toggleBtn) toggleBtn.style.display = inChatPage ? 'inline-flex' : 'none';
  const headerModelShell = $('header-model-shell');
  if (headerModelShell) headerModelShell.style.display = name === 'chat' ? 'flex' : 'none';
  setRightPanelVisible(inChatPage && state.rightPanelOpen);
}

function openRightPanel() {
  state.rightPanelOpen = true;
  syncPageChrome(getCurrentPageName());
}

function closeRightPanel() {
  state.rightPanelOpen = false;
  syncPageChrome(getCurrentPageName());
}

function getCurrentPageName() {
  const activePage = document.querySelector('.page.active');
  return activePage ? activePage.id.replace(/^page-/, '') : 'chat';
}

function normalizePersistedTestCenterNavigation(raw = {}) {
  const page = ['chat', 'freechat', 'test-center', 'prompts', 'history'].includes(raw?.page)
    ? raw.page
    : 'chat';
  const testMode = ['batch', 'compare', 'prompt-ab'].includes(raw?.testMode)
    ? raw.testMode
    : 'batch';
  const abMode = raw?.abMode === 'batch' ? 'batch' : 'live';
  return { page, testMode, abMode };
}

function readPersistedTestCenterNavigation() {
  try {
    const raw = localStorage.getItem(TEST_CENTER_NAV_STORAGE_KEY);
    return normalizePersistedTestCenterNavigation(raw ? JSON.parse(raw) : {});
  } catch (_) {
    return normalizePersistedTestCenterNavigation();
  }
}

function persistTestCenterNavigationState(patch = {}) {
  const next = normalizePersistedTestCenterNavigation({
    ...readPersistedTestCenterNavigation(),
    ...patch,
  });
  try {
    localStorage.setItem(TEST_CENTER_NAV_STORAGE_KEY, JSON.stringify(next));
  } catch (_) { /* ignore */ }
  return next;
}

function restorePersistedTestCenterNavigation() {
  const persisted = readPersistedTestCenterNavigation();
  switchABMode(persisted.abMode, { refreshShell: false, persist: false });
  switchTestCenterMode(persisted.testMode, { refreshShell: false, persist: false });
  if (persisted.page === 'test-center') {
    switchPage('test-center', { persist: false });
  }
  refreshTestCenterShell();
  return persisted;
}

function focusRecoveredTestCenter(mode, { abMode = null } = {}) {
  switchPage('test-center');
  switchTestCenterMode(mode, { refreshShell: mode === 'prompt-ab' ? false : true });
  if (mode === 'prompt-ab') {
    switchABMode(abMode === 'batch' ? 'batch' : 'live', { refreshShell: false });
    refreshTestCenterShell();
  }
}

function switchPage(name, { persist = true } = {}) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  const target = $('page-' + name);
  if (target) target.classList.add('active');
  document.querySelectorAll('.nav-item').forEach(n => {
    n.classList.toggle('active', n.dataset.page === name || (name === 'freechat' && n.dataset.page === 'chat'));
  });
  if (persist && target) {
    persistTestCenterNavigationState({ page: name });
  }
  syncPageChrome(name);
  if (name === 'history') loadHistory();
  if (name === 'prompts') loadPrompts();
  if (name === 'test-center') refreshTestCenterShell();
}

function switchRightTab(event, tabId) {
  document.querySelectorAll('.panel-tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
  event.currentTarget.classList.add('active');
  const target = $('tab-' + tabId);
  if (target) target.classList.add('active');
}

function getTestCenterModeMeta(mode) {
  const promptABBatchMode = state?.abMode === 'batch';
  const meta = {
    batch: {
      title: '批量测试',
      desc: '先加载测试配置，再输入多轮对白并启动批量执行。',
      required: '测试配置 + 多轮输入',
      hint: '配置导入、模板参考和打分上传都收敛在下方内容区，避免同一动作出现多处重复入口。',
    },
    compare: {
      title: '模型对比',
      desc: '同一角色和输入，对多个候选模型做横向对比。',
      required: '已同步配置 + 至少 2 个模型',
      hint: '模型对比会沿用当前角色配置和多轮输入，优先关注模型选择、演练模式和详情回看。',
    },
    'prompt-ab': {
      title: 'Prompt A/B',
      desc: promptABBatchMode
        ? '同一角色和多轮输入，对控制组和实验组做批量 A/B 回归。'
        : '推荐固定同一模型，对控制组和实验组提示词做实时对照。',
      required: promptABBatchMode
        ? '配置来源 + 多轮输入 + 控制组/实验组提示词'
        : '输入 + 控制组/实验组提示词',
      hint: promptABBatchMode
        ? '批量模式会复用当前右侧配置或 Excel 配置，并接入测试中心编排任务。'
        : '实时模式适合逐句追问；历史对比仍统一收口到历史记录页。',
    },
  };
  return meta[mode] || meta.batch;
}

function clearCompareModelSelection() {
  $('compare-model-checkboxes')?.querySelectorAll('input[type="checkbox"]').forEach(input => {
    input.checked = false;
  });
  syncToggleAllBtnText();
  checkProviderConflicts();
  refreshTestCenterShell();
}

function toggleSelectAllCompareModels() {
  const box = $('compare-model-checkboxes');
  if (!box) return;
  const all = [...box.querySelectorAll('input[type="checkbox"]')];
  const allChecked = all.length > 0 && all.every(cb => cb.checked);
  all.forEach(cb => { cb.checked = !allChecked; });
  syncToggleAllBtnText();
  checkProviderConflicts();
  refreshTestCenterShell();
}

function syncToggleAllBtnText() {
  const btn = $('btn-toggle-all-compare');
  if (!btn) return;
  const box = $('compare-model-checkboxes');
  if (!box) return;
  const all = [...box.querySelectorAll('input[type="checkbox"]')];
  const allChecked = all.length > 0 && all.every(cb => cb.checked);
  btn.textContent = allChecked ? '\u53d6\u6d88\u5168\u9009' : '\u5168\u9009';
}

function getBatchModelSummaryText() {
  const batchModelSel = $('batch-model');
  if (!batchModelSel) return '';
  const selectedValue = batchModelSel.value || '';
  if (selectedValue === '使用配置面板模型') {
    const activeModelId = getPrimaryModelId();
    const activeModelName = _allModelOptions.find(item => item.id === activeModelId)?.name || activeModelId;
    return activeModelName ? `批量主模型: ${activeModelName}（同步顶栏）` : '批量主模型: 同步顶栏主模型';
  }
  const selectedText = batchModelSel.options[batchModelSel.selectedIndex]?.textContent || '';
  if (!selectedText) return '';
  return `批量主模型: ${selectedText}`;
}

function fillSelectWithOptions(selectId, options, preferredValue = '') {
  const sel = $(selectId);
  if (!sel) return;
  const currentValue = sel.value;
  sel.innerHTML = '';
  options.forEach(item => {
    const opt = document.createElement('option');
    opt.value = item.value;
    opt.textContent = item.label;
    sel.appendChild(opt);
  });
  const targetValue = [currentValue, preferredValue].find(value =>
    value && options.some(item => item.value === value)
  ) || options[0]?.value || '';
  sel.value = targetValue;
}

function syncABModelLock({ refreshShell = true } = {}) {
  const lock = $('ab-lock-model');
  const baseSel = $('ab-base-model');
  const compareSel = $('ab-compare-model');
  const note = $('ab-compare-model-note');
  if (!lock || !baseSel || !compareSel) return;
  if (lock.checked) {
    compareSel.value = baseSel.value || compareSel.value;
    compareSel.disabled = true;
    if (note) note.textContent = '已锁定控制组模型，推荐只比较提示词差异。';
  } else {
    compareSel.disabled = false;
    if (note) note.textContent = '已解锁，可做模型 + 提示词联合实验。';
  }
  if (refreshShell) refreshTestCenterShell();
}

function populateABModelSelectors() {
  if (!_allModelOptions.length) return;
  const options = _allModelOptions.map(item => ({
    value: item.id,
    label: item.name,
  }));
  const defaultValue = getPrimaryModelId() || _allModelOptions[0]?.id || '';
  fillSelectWithOptions('ab-base-model', options, defaultValue);
  fillSelectWithOptions('ab-compare-model', options, defaultValue);
  syncABModelLock({ refreshShell: false });
}

function populateABPromptSelectors() {
  if (!_chatPromptOptions.length) return;
  const options = _chatPromptOptions.map(item => ({
    value: item.filename,
    label: item.is_latest ? `${item.filename}（最新）` : item.filename,
  }));
  const defaultValue = getInputValue('f-prompt-version').trim()
    || _chatPromptOptions.find(item => item.is_active)?.filename
    || _chatPromptOptions.find(item => item.is_latest)?.filename
    || options[0]?.value
    || '';
  fillSelectWithOptions('ab-base-prompt', options, defaultValue);
  fillSelectWithOptions('ab-compare-prompt', options, defaultValue);
}

function renderTestCenterAdvancedActions(mode) {
  const actionWrap = $('tc-advanced-actions');
  const hintNode = $('tc-advanced-hint');
  const titleNode = $('tc-advanced-secondary-title');
  if (!actionWrap || !hintNode) return;
  actionWrap.innerHTML = '';
  if (titleNode) {
    titleNode.textContent = mode === 'compare' ? '辅助操作' : '模式提示';
  }
  const addAction = (label, handler, className = 'btn btn-secondary') => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = className;
    button.textContent = label;
    button.addEventListener('click', handler);
    actionWrap.appendChild(button);
  };

  if (mode === 'compare') {
    addAction('清空已选模型', clearCompareModelSelection);
    addAction('查看已选模型', () => {
      const selected = [...($('compare-model-checkboxes')?.querySelectorAll('input:checked') || [])]
        .map(input => input.dataset.name || input.value);
      showToast(selected.length ? `已选模型: ${selected.join('、')}` : '当前还没有选中模型', selected.length ? 'info' : 'warning');
    });
  } else {
    actionWrap.innerHTML = '<span style="font-size:12px;color:var(--text-secondary)">主要入口已收纳到下方内容区，避免重复按钮和重复路径。</span>';
  }

  hintNode.textContent = getTestCenterModeMeta(mode).hint;
}

function getCompareModelSummaryText() {
  const selected = [...($('compare-model-checkboxes')?.querySelectorAll('input:checked') || [])]
    .map(input => input.value || input.dataset.name || '')
    .filter(Boolean);
  return selected.length ? `对比模型: ${selected.join(', ')}` : '';
}

function refreshTestCenterShell() {
  const mode = state.testMode || 'batch';
  const meta = getTestCenterModeMeta(mode);
  if ($('tc-current-mode-title')) $('tc-current-mode-title').textContent = meta.title;
  if ($('tc-current-mode-desc')) $('tc-current-mode-desc').textContent = meta.desc;
  if ($('tc-required-fields')) $('tc-required-fields').textContent = meta.required;

  if ($('tc-config-sync-status')) {
    let syncText = '当前尚未同步配置面板';
    if (mode === 'batch' && batchConfigs.length) {
      syncText = `已同步 ${batchConfigs.length} 组批量配置`;
    } else if (mode === 'compare' && compareConfig) {
      syncText = `已同步角色: ${compareConfig.nickname || '未命名角色'}`;
    } else if (mode === 'prompt-ab') {
      if (state.abMode === 'batch' && Array.isArray(abBatchExcelConfigs) && abBatchExcelConfigs.length) {
        syncText = `已同步 ${abBatchExcelConfigs.length} 组 A/B 批量配置`;
      } else if (state.abMode === 'batch' && abBatchConfig) {
        syncText = `已同步角色: ${abBatchConfig.nickname || '未命名角色'}`;
      } else {
        syncText = '实时 A/B 默认直接读取当前右侧参数配置';
      }
    }
    $('tc-config-sync-status').textContent = syncText;
  }

  const chipsWrap = $('tc-advanced-config-chips');
  if (chipsWrap) {
    const cfg = typeof getFormConfig === 'function' ? getFormConfig() : {};
    const compareModelSummary = mode === 'compare' ? getCompareModelSummaryText() : '';
    const chips = [
      compareModelSummary || (cfg.model_pro ? `主模型: ${cfg.model_pro}` : ''),
      cfg.model_mini ? `摘要模型: ${cfg.model_mini}` : '',
      cfg.scoring_model_id ? `打分模型: ${cfg.scoring_model_id}` : '',
      cfg.prompt_version ? `主提示词: ${cfg.prompt_version}` : '',
      cfg.summary_prompt_version ? `摘要提示词: ${cfg.summary_prompt_version}` : '',
      cfg.scoring_prompt_version ? `打分提示词: ${cfg.scoring_prompt_version}` : '',
      cfg.thinking_enabled === false ? '对话思考: 关闭' : (cfg.thinking_effort ? `对话思考: ${cfg.thinking_effort}` : ''),
      cfg.scoring_thinking_enabled === false ? '打分思考: 关闭' : (cfg.scoring_thinking_effort ? `打分思考: ${cfg.scoring_thinking_effort}` : ''),
      cfg.scoring_max_workers ? `打分并发: ${cfg.scoring_max_workers}` : '',
      cfg.scoring_retry_count !== undefined ? `失败重试: ${cfg.scoring_retry_count} 次` : '',
      cfg.summary_interval ? `摘要间隔: ${cfg.summary_interval}` : '',
      cfg.injection_depth ? `注入深度: ${cfg.injection_depth}` : '',
      cfg.temperature !== undefined ? `Temperature: ${formatGenerationNumber(cfg.temperature)}` : '',
      cfg.top_p !== undefined ? `Top P: ${formatGenerationNumber(cfg.top_p)}` : '',
      mode === 'batch' ? getBatchModelSummaryText() : '',
      mode === 'prompt-ab' ? `A/B 模式: ${state.abMode === 'batch' ? '批量测试' : '实时实验'}` : '',
      mode === 'prompt-ab' ? ($('ab-lock-model')?.checked ? 'A/B 模型策略: 锁定同模型（推荐）' : 'A/B 模型策略: 已解锁联合实验') : '',
    ].filter(Boolean);
    chipsWrap.innerHTML = chips.length
      ? chips.map(text => `<span class="meta-chip">${escapeHtml(text)}</span>`).join('')
      : '<span style="font-size:12px;color:var(--text-secondary)">当前还没有可展示的高级配置。</span>';
  }

  renderTestCenterAdvancedActions(mode);
}

function buildTrackerText(prefix, stageLabel, elapsedMs, elapsedText) {
  if (elapsedMs < 5000) return prefix || stageLabel;
  return [prefix, stageLabel, elapsedText].filter(Boolean).join(' · ');
}

function switchTestCenterMode(mode, { refreshShell = true, persist = true } = {}) {
  state.testMode = mode;
  if (persist) {
    persistTestCenterNavigationState({ testMode: mode });
  }
  document.querySelectorAll('#page-test-center .test-mode-card').forEach(card => {
    card.classList.toggle('active', card.id === `tc-mode-${mode}`);
  });
  document.querySelectorAll('#page-test-center .tc-tab-content').forEach(content => {
    content.classList.toggle('active', content.id === `tc-tab-${mode}`);
  });
  if (refreshShell) refreshTestCenterShell();
}

function switchTestCenterTab(event, tabId) {
  if (event?.preventDefault) event.preventDefault();
  switchTestCenterMode(tabId);
}

function resetChatCanvas(title = '新会话已开启', description = '发送消息以开始交谈') {
  const empty = $('chat-empty');
  const area = $('chat-area');
  state.turns = [];
  state.expectedTurnCount = 0;
  state.debugData = [];
  state.scoreData = null;
  state.activeConversationStatus = '';
  window._chatHistory = [];
  if (area) {
    area.innerHTML = '';
  }
  if (empty) {
    empty.style.display = 'block';
    const titleNode = empty.querySelector('.title');
    if (titleNode) titleNode.textContent = title;
    const descNode = empty.querySelector('p');
    if (descNode) descNode.textContent = description;
    // 不再把 empty 移入 area 内部，避免 innerHTML='' 清除后 $('chat-empty') 返回 null
  }
  const chatNav = $('chat-nav');
  if (chatNav) chatNav.style.display = 'none';
  const chatProgress = $('chat-progress');
  if (chatProgress) chatProgress.style.display = 'none';
  const chatTyping = $('chat-typing');
  if (chatTyping) chatTyping.style.display = 'none';
  if ($('chat-typing-text')) $('chat-typing-text').textContent = '请求已发送';
  renderConversationControlRow();
}

function buildInteractiveConversationPayload() {
  const payload = buildConversationRunPayload();
  return {
    model_id: payload.model_id,
    model_mini: payload.model_mini,
    scoring_model_id: payload.scoring_model_id,
    thinking_enabled: payload.thinking_enabled,
    thinking_effort: payload.thinking_effort,
    scoring_thinking_enabled: payload.scoring_thinking_enabled,
    scoring_thinking_effort: payload.scoring_thinking_effort,
    scoring_max_workers: payload.scoring_max_workers,
    scoring_retry_count: payload.scoring_retry_count,
    prompt_version: payload.prompt_version,
    summary_prompt_version: payload.summary_prompt_version,
    scoring_prompt_version: payload.scoring_prompt_version,
    summary_interval: payload.summary_interval,
    injection_depth: payload.injection_depth,
    temperature: payload.temperature,
    top_p: payload.top_p,
    auto_scoring: $('f-auto-score-chat') ? !!$('f-auto-score-chat').checked : true,
    character: payload.character || {},
    context: payload.context || {},
    modules: payload.modules || {},
    few_shot_file: payload.few_shot_file || '',
    custom_variables: payload.custom_variables || {},
  };
}

function buildABConversationPayload({ modelId = '', promptVersion = '', variant = '', abSessionId = '' } = {}) {
  const payload = buildInteractiveConversationPayload();
  payload.model_id = normalizeModelId(modelId || payload.model_id, payload.model_id || DEFAULT_PRIMARY_MODEL_ID);
  payload.prompt_version = String(promptVersion || payload.prompt_version || '').trim();
  payload.auto_scoring = true;
  if (abSessionId) payload.ab_session_id = abSessionId;
  if (variant) payload.ab_variant = variant;
  return payload;
}

function stableSerializeForSignature(value) {
  if (Array.isArray(value)) {
    return `[${value.map(item => stableSerializeForSignature(item)).join(',')}]`;
  }
  if (value && typeof value === 'object') {
    return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${stableSerializeForSignature(value[key])}`).join(',')}}`;
  }
  return JSON.stringify(value ?? null);
}

function buildInteractiveConfigSignature(payload = buildInteractiveConversationPayload()) {
  return stableSerializeForSignature({
    model_id: String(payload.model_id || '').trim(),
    prompt_version: String(payload.prompt_version || '').trim(),
    auto_scoring: !!payload.auto_scoring,
    character: payload.character || {},
    context: payload.context || {},
    modules: payload.modules || {},
    few_shot_file: String(payload.few_shot_file || '').trim(),
    custom_variables: payload.custom_variables || {},
  });
}

function buildConversationRunPayload(cfg = null, {
  modelId = '',
  modelIds = [],
  turns = [],
  dryRun = false,
  compareMode = '',
} = {}) {
  const source = cfg || getFormConfig();
  const modules = buildSystemModulesPayload(source);
  const resolvedModelId = normalizeModelId(modelId || source.model_pro || getPrimaryModelId(), DEFAULT_PRIMARY_MODEL_ID);
  const resolvedModelIds = Array.isArray(modelIds)
    ? [...new Set(modelIds.map(item => String(item || '').trim()).filter(Boolean))]
    : [];
  const resolvedTurns = Array.isArray(turns)
    ? turns.filter(item => String(item || '').trim())
    : String(source.turns || '').split('\n').filter(item => item.trim());
  const lastConversationType = resolvePreviousConversationType(String(source.nickname || '').trim());
  const extraCustomVars = {};
  for (const key of ['moments', 'monthly_schedule', '完整时间信息']) {
    const value = source[key];
    if (value !== undefined && value !== null && String(value).trim() !== '') {
      extraCustomVars[key] = String(value).trim();
    }
  }
  const customVariables = { ...getMergedCustomVariables(), ...extraCustomVars };
  const sampling = getGenerationSamplingConfig(source);
  const runtimeCompleteTimeInfo = String(source['完整时间信息'] || '').trim();
  const runtimeCurrentTime = String(source.currentTime || '').trim();
  const runtimeWeekDay = String(source.weekDay || '').trim();
  const runtimeTimeperiod = String(source.timeperiod || '').trim();
  const runtimeSeason = String(source.season || '').trim();
  const runtimeLastCstType = String(source.last_cst_type || '').trim();
  const runtimeIntimacyBoundary = String(source.intimacy_boundary || '').trim();
  const runtimeRelationCalling = String(source.relation_calling || '').trim();
  const runtimeRelationInfo = String(source.relation_info || '').trim();
  const runtimePersonalType = resolveConfigPersonalType(source);
  const resolvedPromptVersion = String(source.prompt_version || '').trim() || getInputValue('f-prompt-version').trim();
  const resolvedSummaryPromptVersion = String(source.summary_prompt_version || '').trim() || getInputValue('f-summary-prompt-version').trim();
  const resolvedScoringPromptVersion = String(source.scoring_prompt_version || '').trim() || getInputValue('f-scoring-prompt-version').trim();
  const scoringModelId = normalizeModelId(source.scoring_model_id || getInputValue('f-scoring-model').trim() || resolvedModelId, resolvedModelId);
  const dialogueThinking = resolveThinkingPayload(
    resolvedModelId,
    coerceOptionalBoolean(source.thinking_enabled) ?? getDialogueThinkingState(resolvedModelId).enabled,
    source.thinking_effort || getDialogueThinkingState(resolvedModelId).effort,
  );
  const scoringThinking = resolveThinkingPayload(
    scoringModelId,
    coerceOptionalBoolean(source.scoring_thinking_enabled) ?? getScoringThinkingState(scoringModelId).enabled,
    source.scoring_thinking_effort || getScoringThinkingState(scoringModelId).effort,
  );

  return {
    model_id: resolvedModelId,
    model_ids: resolvedModelIds.length ? resolvedModelIds : (resolvedModelId ? [resolvedModelId] : []),
    compare_mode: compareMode || undefined,
    model_mini: normalizeModelId(source.model_mini || getInputValue('f-model-mini').trim() || DEFAULT_SUMMARY_MODEL_ID, DEFAULT_SUMMARY_MODEL_ID),
    scoring_model_id: scoringModelId,
    thinking_enabled: dialogueThinking.enabled,
    thinking_effort: dialogueThinking.thinking_effort,
    scoring_thinking_enabled: scoringThinking.enabled,
    scoring_thinking_effort: scoringThinking.thinking_effort,
    scoring_max_workers: normalizeScoringConcurrency(source.scoring_max_workers),
    scoring_retry_count: normalizeScoringRetryCount(source.scoring_retry_count),
    prompt_version: resolvedPromptVersion,
    summary_prompt_version: resolvedSummaryPromptVersion,
    scoring_prompt_version: resolvedScoringPromptVersion,
    profile_model_id: normalizeModelId(source.profile_model_id || getInputValue('f-profile-model').trim() || DEFAULT_PROFILE_MODEL_ID, DEFAULT_PROFILE_MODEL_ID),
    profile_prompt_version: String(source.profile_prompt_version || '').trim() || getInputValue('f-profile-prompt-version').trim(),
    summary_interval: parseInt(source.summary_interval, 10) || DEFAULT_SUMMARY_INTERVAL,
    injection_depth: normalizeInjectionDepthValue(source.injection_depth),
    temperature: sampling.temperature,
    top_p: sampling.top_p,
    dry_run: !!dryRun,
    turns: resolvedTurns,
    character: {
      Role_Nickname: String(source.nickname || '').trim(),
      personality: String(source.personality || '').trim(),
      personal_type: runtimePersonalType,
      gender: source.gender || '男',
      age: parseInt(source.age, 10) || 25,
      occupation: String(source.occupation || '').trim(),
      Role_info_works: String(source.role_info_works || '').trim(),
      speaking_style: String(source.speaking_style || '').trim(),
      background: String(source.background || '').trim(),
      hobby: String(source.hobby || '').trim(),
    },
    context: {
      relationship: source.relationship || '暧昧',
      scene: String(source.scene || '').trim(),
      time_period: source.time_period || '下午',
      season: source.season || '春季',
      last_cst_type: runtimeLastCstType || lastConversationType,
      user_nickname: String(source.user_nickname || '').trim() || '小鹿',
      user_gender: source.user_gender || '女',
      user_identity: String(source.user_identity || '').trim(),
      ...(runtimeCurrentTime ? { currentTime: runtimeCurrentTime } : {}),
      ...(runtimeWeekDay ? { weekDay: runtimeWeekDay } : {}),
      ...(runtimeTimeperiod ? { timeperiod: runtimeTimeperiod } : {}),
      ...(runtimeSeason ? { season: runtimeSeason } : {}),
      ...(runtimeCompleteTimeInfo ? { '完整时间信息': runtimeCompleteTimeInfo } : {}),
      ...(runtimeIntimacyBoundary ? { intimacy_boundary: runtimeIntimacyBoundary } : {}),
      ...(runtimeRelationCalling ? { relation_calling: runtimeRelationCalling } : {}),
      ...(runtimeRelationInfo ? { relation_info: runtimeRelationInfo } : {}),
    },
    modules,
    few_shot_file: modules.longform_few_shot || '',
    custom_variables: customVariables,
  };
}

function buildConfigSnapshotRequest(name, type = 'quick_chat') {
  const payload = buildInteractiveConversationPayload();
  return {
    name,
    type,
    config: {
      prompt_file: payload.prompt_version || '',
      character: {
        ...payload.character,
      },
      context: {
        relationship: payload.context.relationship || '',
        current_scene: payload.context.scene || '',
        timeperiod: payload.context.time_period || '',
        season: payload.context.season || '',
      },
      modules: {
        user_Nickname: payload.context.user_nickname || '',
        user_gender: payload.context.user_gender || '',
        user_identity: payload.context.user_identity || '',
        longform_persona: payload.modules.longform_persona || '',
        longform_narrative_style: payload.modules.longform_narrative_style || '',
        longform_dialogue_guideline: payload.modules.longform_dialogue_guideline || '',
        longform_few_shot: payload.modules.longform_few_shot || '',
        dialogueStartPrompt: payload.modules.dialogueStartPrompt || '',
        dialogue_summary: payload.modules.dialogue_summary || '',
        weekly_schedule: payload.modules.weekly_schedule || '',
        system_module8: payload.modules.system_module8 || '',
        system_Role_acting: payload.modules.system_Role_acting || '',
        voice_forbidden: payload.modules.voice_forbidden || DEFAULT_VOICE_FORBIDDEN,
        system_prompt: payload.modules.system_prompt || '',
      },
      few_shot_file: payload.few_shot_file || payload.modules.longform_few_shot || '',
      runtime: {
        model_ids: payload.model_id ? [payload.model_id] : [],
        model_mini: payload.model_mini || '',
        scoring_model_id: payload.scoring_model_id || payload.model_id || '',
        thinking_enabled: payload.thinking_enabled,
        thinking_effort: payload.thinking_effort || 'disabled',
        scoring_thinking_enabled: payload.scoring_thinking_enabled,
        scoring_thinking_effort: payload.scoring_thinking_effort || 'disabled',
        scoring_max_workers: normalizeScoringConcurrency(payload.scoring_max_workers),
        scoring_retry_count: normalizeScoringRetryCount(payload.scoring_retry_count),
        summary_interval: payload.summary_interval,
        injection_depth: payload.injection_depth,
        temperature: payload.temperature,
        top_p: payload.top_p,
        prompt_version: payload.prompt_version || '',
        summary_prompt_version: payload.summary_prompt_version || '',
        scoring_prompt_version: payload.scoring_prompt_version || '',
      },
      custom_variables: payload.custom_variables || {},
    },
  };
}

async function fetchConversationDetailById(convId) {
  const response = await fetch(`/api/conversations/${encodeURIComponent(convId)}`);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || response.statusText || '读取会话详情失败');
  return data;
}

async function syncActiveConversationScores(convId) {
  const conversationId = String(convId || '').trim();
  if (!conversationId || String(state.convId || '').trim() !== conversationId) return null;
  const conversation = await fetchConversationDetailById(conversationId);
  state.turns = Array.isArray(conversation.results) ? conversation.results : [];
  state.debugData = state.turns.map(turn => buildTurnDebugEntry(turn));
  syncChatHistoryFromTurns();
  rebuildChatFromTurns();
  return conversation;
}

function closeConversationScoreWebSocket() {
  try {
    if (state.scoreWs) state.scoreWs.close();
  } catch (_) { }
  state.scoreWs = null;
}

function connectConversationScoreWebSocket(convId) {
  const conversationId = String(convId || '').trim();
  if (!conversationId) return;
  closeConversationScoreWebSocket();
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const ws = new WebSocket(`${proto}//${location.host}/api/scoring/ws/${conversationId}`);
  state.scoreWs = ws;
  ws.onmessage = (event) => {
    let msg = {};
    try {
      msg = JSON.parse(event.data);
    } catch (_) {
      return;
    }
    if (msg.type === 'score_updated') {
      applyLiveScoreUpdate(msg);
      syncActiveConversationScores(conversationId).catch(() => { });
    } else if (msg.type === 'retry') {
      showRetryBadge(msg.turn, msg.attempt, msg.max_retries);
    }
  };
  ws.onclose = () => {
    if (state.scoreWs === ws) state.scoreWs = null;
  };
  ws.onerror = () => {
    if (state.scoreWs === ws) state.scoreWs = null;
  };
}

async function createInteractiveConversationSession() {
  const payload = buildInteractiveConversationPayload();
  const response = await fetch('/api/conversations/interactive', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || response.statusText || '创建交互式会话失败');
  state.convId = data.id;
  state.chatSessionMode = 'interactive';
  state.interactiveConfigSignature = buildInteractiveConfigSignature(payload);
  connectConversationScoreWebSocket(data.id);
  return data;
}

async function ensureInteractiveConversationSession({ resetOnConfigChange = false } = {}) {
  const nextSignature = buildInteractiveConfigSignature();
  if (state.chatSessionMode === 'interactive' && state.convId) {
    if (!state.interactiveConfigSignature || state.interactiveConfigSignature === nextSignature) {
      state.interactiveConfigSignature = state.interactiveConfigSignature || nextSignature;
      return { id: state.convId, recreated: false, reason: '' };
    }
    await completeInteractiveConversationSession();
    state.convId = null;
    state.chatSessionMode = 'idle';
    state.interactiveConfigSignature = '';
    if (resetOnConfigChange) {
      state.turns = [];
      state.expectedTurnCount = 0;
      state.debugData = [];
      state.scoreData = null;
      state.scoreMeta = null;
      setActiveConversationStatus('running');
      resetChatCanvas('已按新配置开启会话', '旧上下文已隔离，避免角色串台');
      const chatNav = $('chat-nav');
      if (chatNav) chatNav.style.display = 'flex';
      const chatProgress = $('chat-progress');
      if (chatProgress) chatProgress.style.display = 'flex';
      updateProgress(0, 1);
    }
    const session = await createInteractiveConversationSession();
    return { id: session.id, recreated: true, reason: 'config-changed' };
  }
  const session = await createInteractiveConversationSession();
  return { id: session.id, recreated: true, reason: 'created' };
}

async function completeInteractiveConversationSession() {
  if (state.chatSessionMode !== 'interactive' || !state.convId) return;
  try {
    await fetch(`/api/conversations/${state.convId}/complete`, { method: 'POST' });
  } catch (_) { }
  closeConversationScoreWebSocket();
  state.interactiveConfigSignature = '';
}

async function applyDefaultPreset() {
  if (!Array.isArray(state.presetItems) || state.presetItems.length === 0) return;
  const preferredPresetId = state.selectedPresetId || (state.presetItems[0] && state.presetItems[0].id);
  const targetPreset = state.presetItems.find(item => item.id === preferredPresetId) || state.presetItems[0];
  const escapedId = typeof CSS !== 'undefined' && CSS.escape ? CSS.escape(String(targetPreset?.id || '')) : String(targetPreset?.id || '');
  const targetCard = document.querySelector(`.preset-card[data-preset-id="${escapedId}"]`) || document.querySelector('.preset-card');
  if (targetPreset) await applyPreset(targetPreset, targetCard);
}

async function confirmClearChatContext() {
  if (!confirm('确定清除当前会话消息历史吗？角色配置和参数配置将被保留。')) return;
  try {
    if (state.chatSessionMode === 'interactive' && state.convId) {
      const response = await fetch(`/api/conversations/${state.convId}/turns`, { method: 'DELETE' });
      if (!response.ok) throw new Error('清空会话失败');
    }
    resetChatCanvas('新会话已开启', '发送消息以开始交谈');
    showToast('已清除当前会话消息历史，角色和参数配置已保留', 'success');
    loadHistory();
  } catch (e) {
    showToast('清除上下文失败: ' + e.message, 'error');
  }
}

async function handleNewChatSession() {
  try {
    await completeInteractiveConversationSession();
    await applyDefaultPreset();
    resetChatCanvas('新会话已开启', '发送消息以开始交谈');
    await createInteractiveConversationSession();
    showToast('已创建新会话，旧会话已保留到历史记录', 'success');
    loadHistory();
  } catch (e) {
    showToast('新建会话失败: ' + e.message, 'error');
  }
}

/* ═══ 加载预设 ═══ */
async function fetchPresets() {
  try {
    const r = await fetch('/api/presets'); const data = await r.json();
    const presets = data.presets || data || [];
    state.presetItems = presets;
    const grid = $('preset-grid'); grid.innerHTML = '';
    presets.forEach(p => {
      const card = document.createElement('div'); card.className = 'preset-card';
      card.dataset.presetId = p.id || '';
      const canDelete = !p.is_builtin;
      card.innerHTML = `
        <div class="preset-card-header">
          <div class="preset-card-meta">
            <span class="preset-name">${escapeHtml(p.nickname || p.name || '')}</span>
            <span class="preset-type">${escapeHtml(p.personality_type || p.type || '')}</span>
          </div>
          ${canDelete ? `<button type="button" class="preset-card-delete" title="删除自定义模板" aria-label="删除自定义模板">删除</button>` : ''}
        </div>
      `;
      card.onclick = () => applyPreset(p, card);
      card.querySelector('.preset-card-delete')?.addEventListener('click', (event) => {
        event.stopPropagation();
        showPresetDeleteDialog(p);
      });
      grid.appendChild(card);
    });
    if (state.selectedPresetId) {
      const selectedPreset = presets.find(item => item.id === state.selectedPresetId);
      const selectedCard = grid.querySelector(`.preset-card[data-preset-id="${CSS.escape(state.selectedPresetId)}"]`);
      if (selectedPreset && selectedCard) {
        await applyPreset(selectedPreset, selectedCard);
        return;
      }
    }
    if (!$('f-nickname').value.trim() && presets.length > 0) {
      await applyPreset(presets[0], grid.querySelector('.preset-card'));
    }
  } catch (e) { console.warn('预设加载失败:', e); }
}

function showPresetDeleteDialog(preset) {
  _pendingPresetDelete = preset || null;
  $('preset-delete-message').textContent = `确定删除「${preset?.nickname || preset?.name || '未命名模板'}」吗？`;
  showModal('modal-preset-delete');
}

async function confirmDeletePreset() {
  if (!_pendingPresetDelete?.id) return;
  const presetId = _pendingPresetDelete.id;
  try {
    const response = await fetch(`/api/presets/${encodeURIComponent(presetId)}`, { method: 'DELETE' });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || payload.error || '删除模板失败');
    if (state.selectedPresetId === presetId) state.selectedPresetId = '';
    closeModal('modal-preset-delete');
    _pendingPresetDelete = null;
    showToast('自定义模板已删除', 'success');
    await fetchPresets();
    if (!getInputValue('f-nickname').trim()) await applyDefaultPreset();
  } catch (e) {
    showToast('删除模板失败: ' + e.message, 'error');
  }
}

async function applyPreset(p, card) {
  document.querySelectorAll('.preset-card').forEach(c => c.classList.remove('selected'));
  if (card) card.classList.add('selected');
  state.selectedPresetId = p.id || '';
  try {
    const detailResponse = await fetch(`/api/presets/${encodeURIComponent(p.id || p.type || p.name || '')}`);
    const detail = detailResponse.ok ? await detailResponse.json() : {};
    const rawConfig = detail.config || p.config || {};
    const character = rawConfig.character || {};
    const context = rawConfig.context || {};
    const modules = rawConfig.modules || {};
    const defaults = rawConfig.character_defaults || character || rawConfig || {};
    const relationship = context.relationship || p.relationship || rawConfig.default_relationship || rawConfig.relationship || p.default_relationship || '暧昧';
    const personality = character.personal_type || character.personality || p.personality_type || p.type || rawConfig.type || defaults.personality || '';
    const gender = character.gender || p.gender || rawConfig.gender || defaults.gender || '男';

    const map = {
      'f-nickname': character.Role_Nickname || p.nickname || p.name || rawConfig.name || '',
      'f-gender': gender,
      'f-age': p.age || defaults.age || 25,
      'f-occupation': p.occupation || defaults.occupation || '',
      'f-role-info-works': character.Role_info_works || defaults.Role_info_works || defaults.role_info_works || defaults.works || '',
      'f-personality': personality,
      'f-speaking-style': character.speaking_style || p.speaking_style || defaults.speaking_style || '',
      'f-background': character.background || p.background || defaults.background || '',
      'f-hobby': character.hobby || p.hobby || defaults.hobby || '',
      'f-scene': context.current_scene || context.scene || p.scene || rawConfig.scene || '',
      'f-relationship': relationship,
      'f-sys-fewshot': modules.longform_few_shot || p.sys_fewshot || defaults.sys_fewshot || '',
      'f-sys-startprompt': modules.dialogueStartPrompt || p.sys_startprompt || defaults.sys_startprompt || '',
      'f-sys-schedule': modules.weekly_schedule || p.weekly_schedule || defaults.weekly_schedule || p.sys_schedule || defaults.sys_schedule || '',
      'f-sys-module8': modules.system_module8 || p.sys_module8 || defaults.sys_module8 || '',
      'f-sys-summary': modules.dialogue_summary || p.sys_summary || defaults.sys_summary || '',
      'f-sys-role-acting': modules.system_Role_acting || p.sys_role_acting || defaults.sys_role_acting || '',
      'f-sys-role-acting-module': modules.system_Role_acting || p.sys_role_acting || defaults.sys_role_acting || '',
      'f-voice-forbidden': modules.voice_forbidden || DEFAULT_VOICE_FORBIDDEN,
      'f-user-nickname': modules.user_Nickname || p.user_nickname || defaults.user_nickname || rawConfig.user_nickname || '小鹿',
      'f-user-gender': modules.user_gender || p.user_gender || defaults.user_gender || rawConfig.user_gender || '女',
      'f-user-identity': modules.user_identity || p.user_identity || defaults.user_identity || rawConfig.user_identity || '',
    };
    Object.entries(map).forEach(([id, v]) => { const el = $(id); if (el && v !== undefined && v !== null) el.value = v; });
    if (rawConfig.runtime) {
      if ($('f-summary-interval')) $('f-summary-interval').value = String(rawConfig.runtime.summary_interval || DEFAULT_SUMMARY_INTERVAL);
      if ($('f-injection-depth')) $('f-injection-depth').value = String(rawConfig.runtime.injection_depth || DEFAULT_INJECTION_DEPTH);
    }
    if (Array.isArray(p.user_inputs) && $('f-turns')) $('f-turns').value = p.user_inputs.join('\n');

    updateRelLinkage();
    await syncLongformModules(false);
    refreshSPPreview();
    showToast(`已加载预设: ${p.nickname || p.name}`, 'success');
  } catch (e) {
    showToast('加载预设失败: ' + e.message, 'error');
  }
}

/* ═══ 加载模型列表 ═══ */
async function fillModelSelect(selectId, tier) {
  const url = tier ? `/api/models?tier=${tier}` : '/api/models';
  const r = await fetch(url); const data = await r.json();
  const models = data.models || data || [];
  const sel = $(selectId); sel.innerHTML = '';
  models.forEach(m => {
    const o = document.createElement('option'); o.value = m.id || m; o.textContent = m.name || m.id || m; sel.appendChild(o);
  });
  return models;
}

function selectPreferredModel(selectId, preferredId) {
  const select = $(selectId);
  if (!select) return '';
  preferredId = normalizeModelId(preferredId);
  const options = [...select.options].map(option => option.value);
  const nextValue = options.includes(preferredId) ? preferredId : (options[0] || '');
  if (nextValue) select.value = nextValue;
  return nextValue;
}

async function fetchModels() {
  try {
    await fillModelSelect('f-model-pro', 'pro');
    await fillModelSelect('f-model-mini', 'mini');
    await fillModelSelect('f-scoring-model', 'pro');
    await fillModelSelect('tc-scoring-model', 'pro');
    await fillModelSelect('f-profile-model', null);

    const allR = await fetch('/api/models'); const allData = await allR.json();
    const allModels = allData.models || allData || [];
    _allModelOptions = allModels.map(m => ({
      id: m.id || m,
      name: m.name || m.id || m,
      provider: m.provider || '',
      capabilities: m.capabilities || {},
    }));
    _allModelOptions.forEach(m => { if (m.capabilities) _modelCapabilities[m.id] = m.capabilities; });

    const miniSelect = $('f-model-mini');
    const recommendedMini = _allModelOptions.find(m => m.id === DEFAULT_SUMMARY_MODEL_ID);
    if (miniSelect && recommendedMini) {
      const values = [...miniSelect.options].map(opt => opt.value);
      if (!values.includes(recommendedMini.id)) {
        const opt = document.createElement('option');
        opt.value = recommendedMini.id;
        opt.textContent = `${recommendedMini.name || recommendedMini.id}（推荐）`;
        miniSelect.insertBefore(opt, miniSelect.firstChild);
      }
    }

    const globalHeader = $('header-global-model');
    const batchModelSel = $('batch-model');
    if (globalHeader) {
      globalHeader.innerHTML = '';
      _allModelOptions.forEach(item => {
        const opt = document.createElement('option');
        opt.value = item.id;
        opt.textContent = item.name;
        globalHeader.appendChild(opt);
      });
    }
    if (batchModelSel) {
      batchModelSel.innerHTML = '<option value="使用配置面板模型">同步顶栏主模型</option>';
      _allModelOptions.forEach(item => {
        const opt = document.createElement('option');
        opt.value = item.id;
        opt.textContent = item.name;
        batchModelSel.appendChild(opt);
      });
    }

    const targetModel = _allModelOptions.find(m => m.id === DEFAULT_PRIMARY_MODEL_ID) || _allModelOptions[0];
    if (targetModel) {
      const savedScoringDefaults = getSavedScoringDefaults();
      setPrimaryModelId(targetModel.id);
      selectPreferredModel('f-model-mini', DEFAULT_SUMMARY_MODEL_ID);
      selectPreferredModel('f-scoring-model', savedScoringDefaults.scoring_model_id || DEFAULT_SCORING_MODEL_ID);
      selectPreferredModel('tc-scoring-model', getInputValue('f-scoring-model').trim() || savedScoringDefaults.scoring_model_id || DEFAULT_SCORING_MODEL_ID);
      selectPreferredModel('f-profile-model', DEFAULT_PROFILE_MODEL_ID);
      syncDialogueThinkingControls({ modelId: targetModel.id, force: true });
      syncScoringThinkingControls({
        enabled: savedScoringDefaults.scoring_thinking_enabled,
        effort: savedScoringDefaults.scoring_thinking_effort,
        modelId: getInputValue('f-scoring-model').trim() || savedScoringDefaults.scoring_model_id || targetModel.id,
        force: true,
      });
      if ($('tc-scoring-concurrency')) $('tc-scoring-concurrency').value = String(savedScoringDefaults.scoring_max_workers);
      if ($('tc-scoring-concurrency-display')) $('tc-scoring-concurrency-display').textContent = String(savedScoringDefaults.scoring_max_workers);
      if ($('tc-scoring-retry')) $('tc-scoring-retry').value = String(savedScoringDefaults.scoring_retry_count);
      syncScoringAdvancedPanel({
        modelId: getInputValue('f-scoring-model').trim() || savedScoringDefaults.scoring_model_id || targetModel.id,
      });
      refreshScoringDefaultsStatus();
    }
    populateABModelSelectors();
    renderHeaderModelPicker();
    refreshTestCenterShell();
  } catch (e) { console.warn('模型列表加载失败:', e); }
}

/* ═══ 表单验证 ═══ */
function validateForm() {
  const nickname = $('f-nickname').value.trim();
  if (!nickname) { showToast('请填写角色昵称', 'warning'); $('f-nickname').focus(); return false; }
  const turnsEl = $('f-turns');
  if (turnsEl) {
    const turns = turnsEl.value.trim();
    if (!turns) { showToast('请至少输入一轮对话', 'warning'); turnsEl.focus(); return false; }
  }
  const pro = getPrimaryModelId(), mini = $('f-model-mini').value;
  if (pro && mini && pro === mini) { showToast('⚠️ 主模型和摘要模型相同，可能影响效果', 'warning'); }
  return true;
}

/* ═══ 开始测试 ═══ */
async function startTest() {
  if (state.running) return;
  if (!validateForm()) return;
  state.running = true; state.turns = []; state.debugData = []; state.scoreData = null; state.chatSessionMode = 'batch';
  $('btn-start').disabled = true; $('btn-start').textContent = '⏳ 测试中...';
  const _chatEmpty = $('chat-empty');
  if (_chatEmpty) _chatEmpty.style.display = 'none';
  const _chatArea = $('chat-area');
  if (_chatArea) _chatArea.innerHTML = '';
  const _chatProgress = $('chat-progress');
  if (_chatProgress) _chatProgress.style.display = 'flex';
  const _chatNav = $('chat-nav');
  if (_chatNav) _chatNav.style.display = 'none';

  const userInputs = $('f-turns') ? $('f-turns').value.trim().split('\n').filter(l => l.trim()) : [];
  state.expectedTurnCount = userInputs.length;
  const payload = buildConversationRunPayload(null, {
    turns: userInputs,
    dryRun: $('f-dryrun').checked,
  });
  setPrimaryModelId(payload.model_id);

  try {
    const r = await fetch('/api/conversations', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    if (!r.ok) throw new Error('创建对话失败: ' + r.status);
    const data = await r.json();
    state.convId = data.conversation_id || data.id;
    setActiveConversationStatus(data.status || 'queued');
    connectWebSocket(state.convId);
  } catch (e) {
    showToast('启动失败: ' + e.message, 'error');
    setActiveConversationStatus('');
    resetTestUI();
  }
}

function resetTestUI() {
  state.running = false;
  $('btn-start').disabled = false; $('btn-start').textContent = '💬 开始对话';
  const _typing = $('chat-typing');
  if (_typing) _typing.style.display = 'none';
  ['chat-runner', 'inline-chat', 'batch-task', 'compare-task', 'ab-base-task', 'ab-compare-task']
    .forEach(stopWaitingTracker);
  if ($('chat-typing-text')) $('chat-typing-text').textContent = '请求已发送';
  renderConversationControlRow();
}

function normalizeConversationStatus(status) {
  const normalized = String(status || '').trim().toLowerCase();
  if (normalized === 'cancelling') return 'cancelled';
  if (normalized === 'done') return 'completed';
  return normalized;
}

function isControllableConversationStatus(status) {
  return ['queued', 'running', 'paused'].includes(normalizeConversationStatus(status));
}

function setActiveConversationStatus(status) {
  state.activeConversationStatus = normalizeConversationStatus(status);
  renderConversationControlRow();
  return state.activeConversationStatus;
}

function renderConversationControlRow() {
  const row = $('chat-control-row');
  if (!row) return;
  const normalizedStatus = normalizeConversationStatus(state.activeConversationStatus);
  const isActive = !!state.convId
    && state.chatSessionMode !== 'interactive'
    && isControllableConversationStatus(normalizedStatus);
  row.style.display = isActive ? 'flex' : 'none';
  const isPaused = normalizedStatus === 'paused';
  if ($('btn-chat-pause')) $('btn-chat-pause').style.display = isActive && !isPaused ? 'inline-flex' : 'none';
  if ($('btn-chat-resume')) $('btn-chat-resume').style.display = isActive && isPaused ? 'inline-flex' : 'none';
  if ($('btn-chat-cancel')) $('btn-chat-cancel').style.display = isActive ? 'inline-flex' : 'none';
}

async function controlConversationRun(convId, action) {
  const response = await fetch(`/api/conversations/${encodeURIComponent(convId)}/control`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action }),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || response.statusText || '控制会话失败');
  return data;
}

async function pauseActiveConversation() {
  if (!state.convId || !isControllableConversationStatus(state.activeConversationStatus)) return;
  if (normalizeConversationStatus(state.activeConversationStatus) === 'paused') return;
  try {
    const result = await controlConversationRun(state.convId, 'pause');
    setActiveConversationStatus(result.status || 'paused');
    if ($('chat-status-text')) $('chat-status-text').textContent = '已暂停';
    await loadHistory();
    showToast('已暂停当前会话', 'info');
  } catch (e) {
    showToast('暂停会话失败: ' + e.message, 'error');
  }
}

async function resumeActiveConversation() {
  if (!state.convId || normalizeConversationStatus(state.activeConversationStatus) !== 'paused') return;
  try {
    const result = await controlConversationRun(state.convId, 'resume');
    const status = setActiveConversationStatus(result.status || 'queued');
    if ($('chat-status-text')) $('chat-status-text').textContent = status === 'running' ? '模型处理中' : '已恢复排队';
    await loadHistory();
    showToast(status === 'running' ? '已恢复当前会话' : '当前会话已恢复排队', 'success');
  } catch (e) {
    showToast('恢复会话失败: ' + e.message, 'error');
  }
}

async function cancelActiveConversation() {
  if (!state.convId || !isControllableConversationStatus(state.activeConversationStatus)) return;
  try {
    await controlConversationRun(state.convId, 'cancel');
    setActiveConversationStatus('cancelled');
    if ($('chat-status-text')) $('chat-status-text').textContent = '取消中';
    await loadHistory();
    showToast('已发送取消请求', 'warning');
  } catch (e) {
    showToast('取消会话失败: ' + e.message, 'error');
  }
}

/* ═══ 保存配置并开始对话 ═══ */
async function saveConfigAndStartChat() {
  const nickname = $('f-nickname').value.trim();
  if (!nickname) { showToast('请先填写角色昵称', 'warning'); $('f-nickname').focus(); return; }
  await requestTaskNotificationPermission();
  const config = getFormConfig();
  const snapshotPayload = buildConfigSnapshotRequest(nickname + '_' + Date.now(), 'quick_chat');
  try {
    const saveResponse = await fetch('/api/configs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(snapshotPayload),
    });
    if (!saveResponse.ok) {
      const saveData = await saveResponse.json().catch(() => ({}));
      throw new Error(saveData.detail || saveResponse.statusText || '配置快照保存失败');
    }
  } catch (e) {
    showToast('配置快照保存失败: ' + e.message, 'warning');
  }
  switchPage('chat');
  if (typeof _compareModeActive !== 'undefined' && _compareModeActive) toggleCompareMode();
  if (config.model_pro) setPrimaryModelId(config.model_pro);
  await completeInteractiveConversationSession();
  resetChatCanvas('准备开始对话', '发送消息以开始交谈');
  const dock = $('chat-input-dock');
  if (dock) dock.style.display = 'block';
  try {
    await createInteractiveConversationSession();
    loadHistory();
    showToast('✅ 配置已保存，已创建新的交互式会话', 'success');
  } catch (e) {
    showToast('创建交互式会话失败: ' + e.message, 'error');
  }
}

/* ═══ 对话页聊天 ═══ */
let _chatHistory = [];

/* ═══ 星星渲染 & AI打分Popover 工具函数 ═══ */
function renderStars10Interactive(score) {
  let h = '';
  for (let i = 1; i <= 10; i++) {
    const f = i <= Math.round(score);
    h += `<span class="star-10" data-val="${i}" style="cursor:pointer;font-size:20px;line-height:1;color:${f ? 'var(--warning-color)' : '#ddd'}">${f ? '⭐' : '☆'}</span>`;
  }
  return h;
}
function bindStar10Events(container, turnIdx) {
  const ratingArea = container.querySelector('.star-rating-10');
  const disp = container.querySelector('.star-score-display');
  const comment = container.querySelector('.inline-manual-comment');
  const saveBtn = container.querySelector('.inline-manual-save');
  let cur = 0;
  if (ratingArea) {
    ratingArea.addEventListener('click', (e) => {
      const star = e.target.closest('.star-10');
      if (star && star.dataset.val) {
        cur = Math.max(0.1, Math.min(10.0, parseFloat(star.dataset.val) || 0));
      } else {
        const rect = ratingArea.getBoundingClientRect();
        const x = e.clientX - rect.left;
        cur = Math.round(x / rect.width * 100) / 10;
        cur = Math.max(0.1, Math.min(10.0, Math.round(cur * 10) / 10));
      }
      const filled = Math.round(cur);
      ratingArea.querySelectorAll('.star-10').forEach(s => {
        const v = parseInt(s.dataset.val);
        s.textContent = v <= filled ? '⭐' : '☆';
        s.style.color = v <= filled ? 'var(--warning-color)' : '#ddd';
      });
      if (disp) disp.textContent = `[${cur.toFixed(1)}]`;
    });
    ratingArea.addEventListener('mousemove', (e) => {
      const rect = ratingArea.getBoundingClientRect();
      const hv = Math.max(1, Math.min(10, Math.ceil((e.clientX - rect.left) / rect.width * 10)));
      ratingArea.querySelectorAll('.star-10').forEach(s => {
        s.style.color = parseInt(s.dataset.val) <= hv ? 'var(--warning-color)' : '#ddd';
      });
    });
    ratingArea.addEventListener('mouseleave', () => {
      const filled = Math.round(cur);
      ratingArea.querySelectorAll('.star-10').forEach(s => {
        s.style.color = parseInt(s.dataset.val) <= filled ? 'var(--warning-color)' : '#ddd';
      });
    });
  }
  if (saveBtn) saveBtn.addEventListener('click', () => {
    if (cur > 0) saveInlineManualScore(turnIdx, cur, comment?.value || '', saveBtn);
    else showToast('请先点击星星评分', 'warning');
  });
}
function showAiScorePopover(triggerEl, scoreData) {
  document.querySelectorAll('.score-popover').forEach(p => p.remove());
  const normalized = normalizeAiScoreData(scoreData);
  if (!normalized || !normalized.dimensions.length) { showToast('暂无AI打分数据', 'info'); return; }
  const pop = document.createElement('div'); pop.className = 'score-popover';
  pop.style.cssText = 'position:absolute;z-index:100;background:var(--bg-surface);border:1px solid var(--border-light);border-radius:8px;padding:12px;box-shadow:0 4px 12px rgba(0,0,0,0.15);font-size:12px;min-width:300px;bottom:100%;left:0;margin-bottom:4px';
  let html = '<div style="font-weight:600;margin-bottom:8px">AI 打分依据</div>';
  normalized.dimensions.forEach(d => {
    const pct = (d.score / 5 * 100).toFixed(0);
    html += `<div style="display:flex;align-items:center;gap:6px;margin-bottom:4px"><span style="width:72px;flex-shrink:0">${d.name}</span><span style="width:40px;text-align:right">${d.score.toFixed(1)}/5</span><div style="flex:1;height:5px;background:var(--bg-hover);border-radius:3px;overflow:hidden"><div style="width:${pct}%;height:100%;background:var(--primary-color);border-radius:3px"></div></div><span style="color:var(--text-tertiary);max-width:100px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:11px">"${escapeHtml(d.comment || '')}"</span></div>`;
  });
  const total = normalized.total || 0;
  html += `<div style="border-top:1px solid var(--border-light);margin-top:6px;padding-top:6px;font-weight:600">总分: ${total.toFixed(1)}/10</div>`;
  if (normalized.reasoning) {
    html += `<div style="margin-top:8px;padding-top:8px;border-top:1px solid var(--border-light);color:var(--text-secondary);line-height:1.5">${escapeHtml(normalized.reasoning)}</div>`;
  }
  html += `<div style="text-align:right;margin-top:4px"><span style="cursor:pointer;color:var(--primary-color)" onclick="this.closest('.score-popover').remove()">关闭</span></div>`;
  pop.innerHTML = html;
  triggerEl.style.position = 'relative'; triggerEl.appendChild(pop);
  setTimeout(() => { document.addEventListener('click', function cl(e) { if (!pop.contains(e.target)) { pop.remove(); document.removeEventListener('click', cl); } }); }, 100);
}

const AI_SCORE_DIM_LABELS = {
  persona_fidelity: '人设一致性',
  narrative_immersion: '叙事沉浸度',
  emotional_tension: '情感张力',
  boundary_memory: '关系边界',
  format_compliance: '格式合规',
  context_coherence: '上下文衔接度',
};

function normalizeAiScoreData(scoreData) {
  if (!scoreData) return null;
  if (Array.isArray(scoreData.dimensions)) {
    return {
      total: Number(scoreData.total || scoreData.weighted_score || 0),
      reasoning: scoreData.reasoning || scoreData.explanation || '',
      dimensions: scoreData.dimensions.map(item => ({
        name: item.name || '',
        score: Number(item.score || 0),
        comment: item.comment || '',
      })),
    };
  }
  const rawScores = scoreData.scores || scoreData.dimensions || scoreData.avg_scores || null;
  if (rawScores && typeof rawScores === 'object' && !Array.isArray(rawScores)) {
    return {
      total: Number(scoreData.total || scoreData.mapped_total || scoreData.weighted_score || 0),
      reasoning: scoreData.reasoning || scoreData.explanation || '',
      dimensions: Object.entries(rawScores).map(([key, value]) => ({
        name: AI_SCORE_DIM_LABELS[key] || key,
        score: Number(value || 0),
        comment: '',
      })),
    };
  }
  return null;
}

function buildInlineMessageItems(messages) {
  return (messages || []).map((m, i) => {
    const content = String(m.content || '');
    const roleColor = m.role === 'system' ? '#e11d48' : m.role === 'user' ? '#2563eb' : '#16a34a';
    const tokens = m.tokens || Math.max(1, Math.round(content.length / 2));
    return `<div style="margin:6px 0;padding:8px 10px;border-left:3px solid ${roleColor};background:var(--bg-body);border-radius:6px;border:1px solid var(--border-light)"><div style="display:flex;justify-content:space-between;gap:8px"><span style="color:${roleColor};font-weight:600">[${i}] ${escapeHtml(m.role || 'unknown')}</span><span style="color:var(--text-tertiary)">${tokens} tokens</span></div><div style="margin-top:6px;white-space:pre-wrap;word-break:break-word;line-height:1.6">${escapeHtml(content)}</div></div>`;
  }).join('');
}

function syncChatHistoryFromTurns() {
  _chatHistory = [];
  (state.turns || []).forEach((turn) => {
    const userInput = String(turn.user_input || turn.user_message || '').trim();
    const aiOutput = String(turn.ai_output || turn.assistant_reply || turn.ai_response || turn.response || '').trim();
    if (userInput) _chatHistory.push({ role: 'user', content: userInput });
    if (aiOutput) _chatHistory.push({ role: 'assistant', content: aiOutput });
  });
}

function rebuildChatFromTurns() {
  const area = $('chat-area');
  const empty = $('chat-empty');
  if (!area) return;
  area.innerHTML = '';
  if (empty) empty.style.display = state.turns.length ? 'none' : 'block';
  (state.turns || []).forEach((turn, index) => renderTurnBubbles(turn, index + 1));
}

function showInlineWaitingBubble() {
  const area = $('chat-area');
  if (!area) return null;
  const bubble = document.createElement('div');
  bubble.className = 'chat-bubble ai chat-bubble-loading';
  bubble.innerHTML = `
    <div class="chat-label" style="color:var(--primary-color)">🤖 AI 正在回复</div>
    <div class="reply-waiting-shell">
      <div class="reply-waiting-line line-lg"></div>
      <div class="reply-waiting-line line-md"></div>
      <div class="reply-waiting-line line-sm"></div>
      <div class="reply-waiting-dots" aria-hidden="true">
        <span></span><span></span><span></span>
      </div>
      <div class="reply-waiting-status" style="display:none;font-size:12px;color:var(--text-secondary);margin-top:10px"></div>
    </div>
  `;
  area.appendChild(bubble);
  area.scrollTop = area.scrollHeight;
  return bubble;
}

function appendChatErrorBubble({ area = $('chat-area'), title = '模型调用失败', message = '未知错误', modelId = '', hint = '' } = {}) {
  if (!area) return null;
  const bubble = document.createElement('div');
  bubble.className = 'chat-bubble ai';
  bubble.dataset.errorCard = 'true';
  bubble.style.cssText = [
    'align-self:flex-start',
    'max-width:85%',
    'border:1px solid rgba(220, 38, 38, 0.28)',
    'background:linear-gradient(180deg, rgba(255,245,245,0.96), rgba(255,251,251,0.96))',
    'box-shadow:0 12px 24px rgba(220, 38, 38, 0.08)',
  ].join(';');
  const metaParts = [];
  if (modelId) metaParts.push(`<div style="font-size:11px;color:var(--text-secondary);margin-top:8px">模型：${escapeHtml(modelId)}</div>`);
  if (hint) metaParts.push(`<div style="font-size:11px;color:var(--text-tertiary);margin-top:4px">建议：${escapeHtml(hint)}</div>`);
  bubble.innerHTML = `
    <div class="chat-label" style="color:var(--danger-color)">⚠️ ${escapeHtml(title)}</div>
    <div style="line-height:1.7;font-size:13px;color:var(--danger-color);white-space:pre-wrap">${escapeHtml(message || '未知错误')}</div>
    ${metaParts.join('')}
  `;
  area.appendChild(bubble);
  area.scrollTop = area.scrollHeight;
  return bubble;
}

function buildChatScoreConfig() {
  return buildConfigSnapshotRequest('inline_score', 'quick_chat').config;
}

const CHAT_SCORE_TIMEOUT_MS = 95000;

function turnHasPersistedInlineScore(turn) {
  if (!turn || !turn.ai_score) return false;
  const status = String(turn.score_status || '').toLowerCase();
  return status === 'scored' || Number(turn.score_total || 0) > 0;
}

function shouldAutoBackfillInlineScore(turn) {
  if (!turn) return false;
  const status = String(turn.score_status || '').toLowerCase();
  const total = Number(turn.score_total || 0);
  return !!String(turn.ai_output || '').trim() && (status !== 'scored' || total <= 0);
}

async function persistInlineAiScoreResult({ turnNumber, scores, mappedTotal, reasoning, refreshHistory = true }) {
  if (!state.convId) return false;
  const response = await fetch(`/api/conversations/${state.convId}/turns/${turnNumber}/scores`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      scores,
      mapped_total: mappedTotal,
      reasoning,
      success: true,
    })
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.detail || payload.error || response.statusText || '评分落库失败');
  }
  if (refreshHistory) loadHistory().catch(() => { });
  return true;
}

async function runConversationInlineScoreBackfill() {
  const autoScore = $('f-auto-score-chat') ? !!$('f-auto-score-chat').checked : true;
  if (!autoScore || !state.convId) return;
  const convId = state.convId;
  const token = (state.inlineScoreBackfillToken || 0) + 1;
  state.inlineScoreBackfillToken = token;
  let wroteAny = false;
  const pendingTurns = state.turns
    .filter(shouldAutoBackfillInlineScore)
    .map(turn => Number(turn.turn || turn.turn_order || 0))
    .filter(turnNumber => Number.isFinite(turnNumber) && turnNumber > 0);
  for (const turnNumber of pendingTurns) {
    if (state.inlineScoreBackfillToken !== token || state.convId !== convId) return;
    const turn = state.turns.find(item => (item.turn || item.turn_order) === turnNumber);
    if (!shouldAutoBackfillInlineScore(turn)) continue;
    try {
      await triggerInlineAiScoreForTurn(turnNumber, { refreshHistory: false });
      wroteAny = wroteAny || String(turn?.score_status || '').toLowerCase() === 'scored';
    } catch (_) { }
  }
  if (state.inlineScoreBackfillToken === token && state.convId === convId && wroteAny) {
    loadHistory().catch(() => { });
  }
}

async function runInlineAiScore({ turnNumber, userInput, aiOutput, scoreTrigger, scoreDetailBtn, scoreLine, force = false, refreshHistory = true }) {
  if (!scoreTrigger) return;
  if (state.inlineScoreInflight[turnNumber]) return;
  const turn = state.turns.find(item => (item.turn || item.turn_order) === turnNumber);
  if (turnHasPersistedInlineScore(turn) && !force) {
    scoreTrigger.textContent = `AI评:${Number(turn.ai_score.total || 0).toFixed(1)}/10`;
    scoreTrigger.style.color = 'var(--primary-color)';
    scoreTrigger.style.pointerEvents = 'auto';
    if (scoreDetailBtn) scoreDetailBtn.style.display = 'inline';
    return;
  }
  state.inlineScoreInflight[turnNumber] = true;
  scoreTrigger.textContent = 'AI评分中...';
  scoreTrigger.style.pointerEvents = 'none';
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), CHAT_SCORE_TIMEOUT_MS);
  try {
    const sr = await fetch('/api/chat/score', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      signal: controller.signal,
      body: JSON.stringify({
        user_input: userInput,
        ai_output: aiOutput,
        config: buildChatScoreConfig(),
        scoring_prompt_version: getInputValue('f-scoring-prompt-version').trim(),
        scoring_model_id: getInputValue('f-scoring-model').trim() || getPrimaryModelId(),
        scoring_thinking_enabled: getScoringThinkingState(getInputValue('f-scoring-model').trim() || getPrimaryModelId()).enabled,
        scoring_thinking_effort: getScoringThinkingState(getInputValue('f-scoring-model').trim() || getPrimaryModelId()).thinking_effort,
      })
    });
    const sd = await sr.json();
    if (!sr.ok) throw new Error(sd.detail || sd.error || sr.statusText || 'AI打分失败');
    if (!(sd.success && sd.scores)) throw new Error(sd.error || 'AI打分失败');
    const normalized = normalizeAiScoreData({
      scores: sd.scores,
      mapped_total: sd.mapped_total || sd.scores.total || 0,
      reasoning: sd.reasoning || '',
    });
    if (!normalized) throw new Error('AI打分结果格式无效');
    if (normalized.total <= 0.01) throw new Error('模型输出无法解析(0分)');

    const currentTurn = state.turns.find(item => (item.turn || item.turn_order) === turnNumber);
    if (currentTurn) currentTurn.ai_score = normalized;
    scoreTrigger.textContent = `AI评:${normalized.total.toFixed(1)}/10`;
    scoreTrigger.style.color = 'var(--primary-color)';
    scoreTrigger.style.pointerEvents = 'auto';
    if (scoreDetailBtn) scoreDetailBtn.style.display = 'inline';
    const showPopover = () => showAiScorePopover(scoreLine, normalized);
    scoreTrigger.onclick = showPopover;
    if (scoreDetailBtn) scoreDetailBtn.onclick = showPopover;

    if (state.convId) {
      await persistInlineAiScoreResult({
        turnNumber,
        scores: sd.scores,
        mappedTotal: normalized.total,
        reasoning: sd.reasoning || '',
        refreshHistory,
      });
      if (currentTurn) {
        currentTurn.score_total = normalized.total;
        currentTurn.score_reasoning = sd.reasoning || '';
        currentTurn.score_status = 'scored';
      }
    }
  } catch (e) {
    const isTimeout = e && (e.name === 'AbortError' || String(e.message || '').includes('超时'));
    const is0Score = String(e.message || '').includes('0分');
    scoreTrigger.textContent = isTimeout ? '重试(超时)' : (is0Score ? '重打分(异常0分)' : '重试打分');
    scoreTrigger.style.color = 'var(--warning-color)';
    scoreTrigger.style.pointerEvents = 'auto';
    if (scoreDetailBtn) scoreDetailBtn.style.display = 'none';
    scoreTrigger.onclick = () => runInlineAiScore({ turnNumber, userInput, aiOutput, scoreTrigger, scoreDetailBtn, scoreLine, force: true });
    showToast(isTimeout ? 'AI打分超时，已切换为手动重试' : ('AI打分失败: ' + e.message), 'warning');
  } finally {
    window.clearTimeout(timeoutId);
    delete state.inlineScoreInflight[turnNumber];
  }
}

async function sendChatMessage() {
  const input = $('chat-input');
  const msg = input.value.trim();
  if (!msg) return;
  const hadInteractiveSession = state.chatSessionMode === 'interactive' && !!state.convId;
  let sessionState = null;
  try {
    sessionState = await ensureInteractiveConversationSession({ resetOnConfigChange: true });
    if (sessionState?.reason === 'config-changed') {
      _chatHistory = [];
      await loadHistory();
      showToast('检测到角色或提示词已变更，已自动切换到新会话', 'info');
    }
  } catch (e) {
    showToast('创建会话失败: ' + e.message, 'error');
    return;
  }

  if (!hadInteractiveSession && sessionState?.reason === 'created') {
    resetChatCanvas('新会话已开启', '发送消息以开始交谈');
  }
  input.value = '';

  // 隐藏空态
  const empty = $('chat-empty');
  if (empty) empty.style.display = 'none';

  // 渲染用户气泡
  const area = $('chat-area');
  const userBubble = document.createElement('div');
  userBubble.className = 'chat-bubble user';
  userBubble.style.cssText = 'align-self:flex-end;max-width:70%';
  userBubble.innerHTML = `<div class="chat-label">\ud83d\udc64 你</div><div style="line-height:1.6">${escapeHtml(msg)}</div>`;
  area.appendChild(userBubble);
  const pendingBubble = showInlineWaitingBubble();
  const inlineWaitingTracker = startWaitingTracker('inline-chat', {
    onUpdate: ({ stageLabel, elapsedMs, elapsedText }) => {
      const statusNode = pendingBubble?.querySelector('.reply-waiting-status');
      if (statusNode) {
        if (elapsedMs >= 5000) {
          statusNode.style.display = 'block';
          statusNode.textContent = `${stageLabel} · ${elapsedText}`;
        } else {
          statusNode.style.display = 'none';
          statusNode.textContent = '';
        }
      }
    }
  });

  _chatHistory.push({ role: 'user', content: msg });

  // 禁用发送按钮
  const sendBtn = $('btn-chat-send');
  sendBtn.disabled = true;
  sendBtn.textContent = '⏳';
  const activeConvId = sessionState?.id || state.convId;

  // 获取当前选中模型
  const globalModelSel = $('header-global-model');
  const modelId = globalModelSel ? globalModelSel.value : DEFAULT_PRIMARY_MODEL_ID;
  const sampling = getGenerationSamplingConfig();
  const dialogueThinking = getDialogueThinkingState(modelId);
  const payload = {
    user_input: msg,
    model_id: modelId,
    web_search: $('f-web-search-chat') ? !!$('f-web-search-chat').checked : false,
    thinking_enabled: dialogueThinking.enabled,
    thinking_effort: dialogueThinking.thinking_effort,
    temperature: sampling.temperature,
    top_p: sampling.top_p,
  };

  try {
    const r = await fetch(`/api/conversations/${activeConvId}/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const first = await r.json();
    if (!r.ok) throw new Error(first.detail || first.error || '生成失败');
    if (first && first.success) {
      inlineWaitingTracker?.stop();
      pendingBubble?.remove();
      const aiOutput = first.ai_output || '';
      const messagesSnapshot = Array.isArray(first.messages_snapshot) ? first.messages_snapshot : [];
      const requestPayloadSnapshot = first.request_payload_snapshot || buildDebugPayloadSnapshot({
        modelId: first.model_id || modelId,
        messages: messagesSnapshot,
        webSearch: payload.web_search,
        thinkingEffort: payload.thinking_effort,
      });
      _chatHistory.push({ role: 'assistant', content: aiOutput });
      const turnIdx = first.turn || Math.floor(_chatHistory.length / 2);
      const aiBubble = document.createElement('div');
      aiBubble.className = 'chat-bubble ai';
      aiBubble.style.cssText = 'align-self:flex-start;max-width:85%';
      const wordCount = first.word_count || (aiOutput ? aiOutput.length : 0);
      const metaText = `字数:${wordCount} · tokens:${first.input_tokens || 0}→${first.output_tokens || 0} · 延迟:${(first.latency_s || 0).toFixed(1)}s`;

      aiBubble.innerHTML = `
        <div class="chat-label" style="color:var(--primary-color)">🤖 ${escapeHtml(first.model_id || modelId)}</div>
        <div class="chat-content" style="line-height:1.6;font-size:13px">${formatNarration ? formatNarration(aiOutput) : escapeHtml(aiOutput)}</div>
        <div style="font-size:11px;color:var(--text-tertiary);margin-top:6px">${metaText}</div>
        <div style="font-size:12px;margin-top:4px;display:flex;align-items:center;justify-content:space-between;gap:4px;flex-wrap:wrap">
          <div style="display:flex;align-items:center;gap:6px" class="ai-score-line">
            <span class="ai-score-trigger score-popover-trigger" style="cursor:pointer;color:var(--text-tertiary)" title="点击查看打分依据">AI评:—/10</span>
            <span class="ai-score-detail-btn score-popover-trigger" style="cursor:pointer;font-size:11px;color:var(--primary-color);display:none" title="查看打分依据">[查看依据]</span>
            <span class="manual-score-trigger" style="cursor:pointer;opacity:0.7" title="人工打分">[✏️]</span>
          </div>
          <div style="display:flex;align-items:center;gap:8px">
            <span style="cursor:pointer;opacity:0.7" title="复制" onclick="navigator.clipboard.writeText(this.closest('.chat-bubble').querySelector('.chat-content').textContent).then(()=>window.showToast('已复制','success'))">📋</span>
            <span class="msg-regenerate-trigger" style="cursor:pointer;opacity:0.7" title="重新生成最后一轮">🔄</span>
            <span class="msg-debug-toggle" style="cursor:pointer;opacity:0.7;font-size:11px" title="查看调试详情">📄调试</span>
          </div>
        </div>
      `;
      area.appendChild(aiBubble);
      aiBubble.dataset.turn = String(turnIdx);
      const turnData = {
        ...first,
        user_input: msg,
        ai_output: aiOutput,
        input_tokens: first.input_tokens || 0,
        output_tokens: first.output_tokens || 0,
        latency_s: first.latency_s || 0,
        word_count: wordCount,
        model_id: first.model_id || modelId,
        messages_snapshot: messagesSnapshot,
        request_payload_snapshot: requestPayloadSnapshot,
      };
      state.turns.push(turnData);
      state.debugData.push(normalizeDebugEntry({
        messages: messagesSnapshot,
        trim_level: first.token_trim_level || 0,
        total_tokens: first.input_tokens || 0,
        has_deep_injection: !!first.has_deep_injection,
        quality_retries: first.quality_retries || 0,
        request_payload_snapshot: requestPayloadSnapshot,
        model: first.model_id || modelId,
      }));
      loadHistory();

      // 10星人工评分（初始隐藏，点击✏️展开）
      const manualDiv = document.createElement('div');
      manualDiv.className = 'inline-manual-score';
      manualDiv.style.cssText = 'display:none;align-self:flex-start;margin-top:4px;margin-left:12px;padding:6px 12px;border:1px solid var(--border-light);border-radius:8px;background:var(--bg-hover);font-size:12px';
      manualDiv.innerHTML = `
        <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">
          <span>人工评分:</span>
          <span class="star-rating-10">${renderStars10Interactive(0)}</span>
          <span class="star-score-display" style="font-weight:bold;min-width:28px">[—]</span>
          <input type="text" class="inline-manual-comment" placeholder="评语..." style="flex:1;min-width:100px;border:none;border-bottom:1px solid var(--border-light);background:transparent;font-size:11px;outline:none">
          <button class="btn btn-secondary inline-manual-save" style="padding:2px 8px;font-size:11px">保存</button>
        </div>
      `;
      area.appendChild(manualDiv);
      aiBubble.querySelector('.manual-score-trigger')?.addEventListener('click', () => {
        manualDiv.style.display = manualDiv.style.display === 'none' ? 'block' : 'none';
      });
      bindStar10Events(manualDiv, turnIdx);

      const scoreTrigger = aiBubble.querySelector('.ai-score-trigger');
      const scoreDetailBtn = aiBubble.querySelector('.ai-score-detail-btn');
      const scoreLine = aiBubble.querySelector('.ai-score-line');
      const triggerScore = () => runInlineAiScore({
        turnNumber: turnIdx,
        userInput: msg,
        aiOutput,
        scoreTrigger,
        scoreDetailBtn,
        scoreLine,
      });
      const autoScore = $('f-auto-score-chat') ? !!$('f-auto-score-chat').checked : true;
      if (autoScore) {
        if (scoreTrigger) {
          scoreTrigger.textContent = 'AI 打分中';
          scoreTrigger.style.color = 'var(--text-tertiary)';
          scoreTrigger.onclick = null;
        }
      } else if (scoreTrigger) {
        scoreTrigger.textContent = '点击AI打分';
        scoreTrigger.style.color = 'var(--warning-color)';
        scoreTrigger.onclick = triggerScore;
      }

      const regenerateTrigger = aiBubble.querySelector('.msg-regenerate-trigger');
      regenerateTrigger?.addEventListener('click', () => triggerRegenerateTurn(turnIdx, regenerateTrigger));

      // ── 消息拼接详情（点击查看发送给API的完整messages） ──
      const debugToggle = aiBubble.querySelector('.msg-debug-toggle');
      if (debugToggle) {
        debugToggle.addEventListener('click', () => {
          switchDebugPanel('messages');
          showModal('modal-debug');
          renderDebugView(Math.max(0, turnIdx - 1));
        });
      }
    } else {
      inlineWaitingTracker?.stop();
      pendingBubble?.remove();
      appendChatErrorBubble({
        area,
        title: '模型调用失败',
        message: first?.error || '未知错误',
        modelId: first?.model_id || modelId,
        hint: '请检查 API Key、模型配置，或稍后重试',
      });
    }
  } catch (e) {
    inlineWaitingTracker?.stop();
    pendingBubble?.remove();
    appendChatErrorBubble({
      area,
      title: '模型调用失败',
      message: e.message || '生成失败',
      modelId,
      hint: '请检查 API Key、模型配置，或稍后重试',
    });
    showToast('发送失败: ' + e.message, 'error');
  }

  sendBtn.disabled = false;
  sendBtn.textContent = '↑';
  area.scrollTop = area.scrollHeight;
  input.focus();
}


/* ═══ WebSocket ═══ */
function connectWebSocket(convId) {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const ws = new WebSocket(`${proto}//${location.host}/ws/conversations/${convId}`);
  state.ws = ws;
  setActiveConversationStatus('queued');
  const _wsTyping = $('chat-typing');
  if (_wsTyping) _wsTyping.style.display = 'flex';
  const chatRunnerTracker = startWaitingTracker('chat-runner', {
    forcedStage: '请求已发送',
    onUpdate: ({ stageLabel, elapsedMs, elapsedText }) => {
      $('chat-status-text').textContent = elapsedMs >= 5000
        ? `${stageLabel} · ${elapsedText}`
        : stageLabel;
    }
  });

  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.type === 'turn_result' || msg.type === 'turn') {
      setActiveConversationStatus('running');
      const turn = msg.data || msg;
      const turnNumber = turn.turn || turn.turn_order || (state.turns.length + 1);
      const existingIndex = state.turns.findIndex(item => (item.turn || item.turn_order || 0) === turnNumber);
      if (existingIndex >= 0) {
        state.turns[existingIndex] = turn;
        state.debugData[existingIndex] = buildTurnDebugEntry(turn);
        if (!document.querySelector(`#chat-area .chat-bubble.ai[data-turn="${turnNumber}"]`)) {
          rebuildChatFromTurns();
        }
      } else {
        state.turns.push(turn);
        state.debugData.push(buildTurnDebugEntry(turn));
        renderTurnBubbles(turn, state.turns.length);
      }
      chatRunnerTracker.setStage('结果整理中');
      const fallbackTotal = $('f-turns')
        ? parseInt($('f-turns').value.trim().split('\n').filter(l => l.trim()).length)
        : state.turns.length;
      updateProgress(state.turns.length, state.expectedTurnCount || fallbackTotal || state.turns.length);
    } else if (msg.type === 'queued') {
      setActiveConversationStatus('queued');
      chatRunnerTracker.setStage('请求已发送');
    } else if (msg.type === 'started') {
      setActiveConversationStatus('running');
      chatRunnerTracker.setStage('模型处理中');
    } else if (msg.type === 'turn_started') {
      setActiveConversationStatus('running');
      const turnNum = msg.turn || 0;
      const totalTurns = msg.total_turns || state.expectedTurnCount || turnNum;
      chatRunnerTracker.setStage(`正在生成第 ${turnNum}/${totalTurns} 轮`);
      updateProgress(turnNum - 1, totalTurns);
    } else if (msg.type === 'paused') {
      setActiveConversationStatus('paused');
      chatRunnerTracker.setStage('已暂停');
      if ($('chat-status-text')) $('chat-status-text').textContent = '已暂停';
      showToast('会话已暂停', 'info');
      loadHistory();
    } else if (msg.type === 'resumed') {
      setActiveConversationStatus('running');
      chatRunnerTracker.setStage('模型处理中');
      if ($('chat-status-text')) $('chat-status-text').textContent = '已恢复';
      showToast('会话已恢复', 'success');
      loadHistory();
    } else if (msg.type === 'cancelled') {
      setActiveConversationStatus('cancelled');
      chatRunnerTracker.stop();
      if ($('chat-status-text')) $('chat-status-text').textContent = '已取消';
      showToast('会话已取消', 'warning');
      void notifyTaskCompletion('对话生成已取消', {
        body: state.convId ? `会话 ${state.convId} 已取消` : '当前对话已取消',
      });
      ws.close();
      resetTestUI();
      loadHistory();
    } else if (msg.type === 'task_status') {
      const status = String(msg.status || '').trim().toLowerCase();
      setActiveConversationStatus(status);
      if (status === 'queued') {
        chatRunnerTracker.setStage('请求已发送');
      } else if (status === 'running') {
        chatRunnerTracker.setStage('模型处理中');
      } else if (status === 'paused') {
        chatRunnerTracker.setStage('已暂停');
      } else if (status === 'cancelled') {
        if ($('chat-status-text')) $('chat-status-text').textContent = '已取消';
      }
    } else if (msg.type === 'completed' || msg.type === 'done') {
      setActiveConversationStatus('completed');
      chatRunnerTracker.stop();
      ws.close();
      onTestComplete();
    } else if (msg.type === 'error') {
      setActiveConversationStatus('failed');
      chatRunnerTracker.stop();
      showToast('错误: ' + (msg.error || msg.message || msg.data?.message || '未知错误'), 'error');
      void notifyTaskCompletion('对话生成失败', {
        body: msg.error || msg.message || msg.data?.message || '未知错误',
      });
      ws.close(); resetTestUI();
    }
  };
  ws.onerror = () => {
    chatRunnerTracker.stop();
    showToast('WebSocket 连接错误', 'error');
    resetTestUI();
  };
  ws.onclose = () => {
    chatRunnerTracker.stop();
    const chatTyping = $('chat-typing');
    if (chatTyping) chatTyping.style.display = 'none';
  };
}

function updateProgress(current, total) {
  total = total || 1;
  const pct = Math.round(current / total * 100);
  const progressText = $('chat-progress-text');
  if (progressText) progressText.textContent = `Turn ${current}/${total}`;
  const progressFill = $('chat-progress-fill');
  if (progressFill) progressFill.style.width = pct + '%';
  const progressPct = $('chat-progress-pct');
  if (progressPct) progressPct.textContent = pct + '%';
  if (!state.waitingTrackers['chat-runner']) {
    const statusText = $('chat-status-text');
    if (statusText) statusText.textContent = current >= total ? '已完成' : '生成中...';
  }
}

function onTestComplete() {
  stopWaitingTracker('chat-runner');
  setActiveConversationStatus('completed');
  resetTestUI();
  state.chatSessionMode = 'batch';
  const _nav = $('chat-nav');
  if (_nav) _nav.style.display = 'flex';
  const _status = $('chat-status-text');
  if (_status) _status.textContent = '已完成';
  showToast('🎉 对话测试完成!', 'success');
  void notifyTaskCompletion('对话生成已完成', {
    body: state.convId ? `会话 ${state.convId} 已完成` : '当前对话已完成',
  });
  loadHistory();
}

/* ═══ 渲染对话气泡 ═══ */
function renderTurnBubbles(turn, turnIdx) {
  const area = $('chat-area');
  // User bubble
  const userInput = turn.user_input || turn.user_message || '';
  if (userInput) {
    const ub = document.createElement('div'); ub.className = 'chat-bubble user';
    ub.innerHTML = `<div class="chat-label">👤 用户 · Turn ${turnIdx}</div><div>${escapeHtml(userInput)}</div>`;
    area.appendChild(ub);
  }
  // AI bubble
  const aiReply = turn.ai_output || turn.assistant_reply || turn.ai_response || turn.response || '';
  if (aiReply) {
    const ab = document.createElement('div'); ab.className = 'chat-bubble ai';
    const formatted = formatNarration(aiReply);
    const turnNumber = turn.turn || turn.turn_order || turnIdx;
    ab.dataset.turn = String(turnNumber);
    const hasManualScore = turn.manual_star_score !== undefined
      && turn.manual_star_score !== null
      && turn.manual_star_score !== '';
    const manualScoreValue = hasManualScore ? toFixedScore(turn.manual_star_score, 0) : '';
    const manualComment = turn.manual_comment || '';
    const wordCount = aiReply.length;
    const wcClass = wordCount >= 300 && wordCount <= 500 ? 'word-count-ok' : 'word-count-warn';
    const inTok = turn.input_tokens || 0, outTok = turn.output_tokens || turn.token_count || 0;
    const lat = ((turn.latency_s || (turn.latency ? turn.latency / 1000 : 0)) || 0).toFixed(1);
    const metaHtml = `<div style="font-size:11px;color:var(--text-tertiary);margin-top:6px">字数:<span class="${wcClass}">${wordCount}</span> · tokens:${inTok}→${outTok} · 延迟:${lat}s</div>`;

    const tags = buildTurnStatusTags(turn);
    let tagsHtml = '';
    if (tags.length > 0) {
      tagsHtml = `<div class="msg-tags">` + tags.map(t => `<span class="msg-tag ${t.cls}">${escapeHtml(t.text)}</span>`).join('') + `</div>`;
    }
    const debugHtml = renderInlineDebugBlock(turn, turnIdx);

    // AI评分 + 底栏操作（10分制）
    const persistedAiScore = turn.score_total !== undefined && turn.score_total !== null ? {
      total: Number(turn.score_total) || 0,
      dimensions: [
        { name: '人设一致性', score: Number(turn.score_persona_fidelity) || 0, comment: '' },
        { name: '叙事沉浸度', score: Number(turn.score_narrative_immersion) || 0, comment: '' },
        { name: '情感张力', score: Number(turn.score_emotional_tension) || 0, comment: '' },
        { name: '关系边界', score: Number(turn.score_boundary_memory) || 0, comment: '' },
        { name: '格式合规', score: Number(turn.score_format_compliance) || 0, comment: '' },
        { name: '上下文衔接度', score: Number(turn.score_context_coherence) || 0, comment: '' },
      ],
      reasoning: turn.score_reasoning || '',
    } : null;
    const aiScore = turn.ai_score || turn.score_data || persistedAiScore || null;
    const isAiScoreValid = aiScore && (typeof aiScore.total === 'number' ? aiScore.total > 0.01 : true);
    const aiTotal = isAiScoreValid ? (aiScore.total || aiScore.weighted_score || 0) : 0;
    const aiScoreText = isAiScoreValid ? `AI评:${aiTotal.toFixed(1)}/10` : (aiScore ? '重打分(异常0分)' : 'AI评:—/10');
    const manualScoreInit = hasManualScore ? (parseFloat(manualScoreValue) || 0) : 0;
    const canRegenerate = state.chatSessionMode === 'interactive' && !!state.convId && turnNumber === state.turns.length;
    const regenerateTitle = canRegenerate ? '重新生成最后一轮' : '仅当前交互式会话的最后一轮支持重生成';
    const regenerateStyle = canRegenerate
      ? 'cursor:pointer;opacity:0.7'
      : 'cursor:not-allowed;opacity:0.3';

    const bottomBarHtml = `
      <div style="font-size:12px;margin-top:4px;display:flex;align-items:center;justify-content:space-between;gap:4px;flex-wrap:wrap">
        <div style="display:flex;align-items:center;gap:6px" class="ai-score-line">
          <span class="ai-score-trigger score-popover-trigger" style="cursor:pointer;color:${isAiScoreValid ? 'var(--primary-color)' : (aiScore ? 'var(--warning-color)' : 'var(--text-tertiary)')};font-weight:500" title="${isAiScoreValid ? '点击查看打分依据' : '点击触发重新打分'}">${aiScoreText}</span>
          <span class="ai-score-detail-btn score-popover-trigger" style="cursor:pointer;font-size:11px;color:var(--primary-color);${isAiScoreValid ? '' : 'display:none'}" title="查看打分依据">[查看依据]</span>
          <span class="manual-score-trigger" style="cursor:pointer;opacity:0.7" title="人工打分">[✏️]</span>
        </div>
        <div style="display:flex;align-items:center;gap:8px">
          <span style="cursor:pointer;opacity:0.7" title="复制" onclick="navigator.clipboard.writeText(this.closest('.chat-bubble').querySelector('div:nth-child(3)').textContent).then(()=>window.showToast('已复制','success'))">📋</span>
          <span class="msg-regenerate-trigger" style="${regenerateStyle}" title="${regenerateTitle}">🔄</span>
          <span class="msg-debug-toggle" style="cursor:pointer;opacity:0.7;font-size:11px" title="查看调试详情">📄调试</span>
        </div>
      </div>`;

    const manualHtml = `
      <div class="inline-manual-score" style="margin-top:8px;padding:8px 12px;border:1px solid var(--border-light);border-radius:8px;background:var(--bg-hover);font-size:12px">
        <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">
          <span>人工评分:</span>
          <span class="star-rating-10">${renderStars10Interactive(manualScoreInit)}</span>
          <span class="star-score-display" style="font-weight:bold;min-width:28px">[${hasManualScore ? manualScoreValue : '—'}]</span>
          <input type="text" class="inline-manual-comment" value="${escapeHtml(manualComment)}" placeholder="评语..." style="flex:1;min-width:100px;border:none;border-bottom:1px solid var(--border-light);background:transparent;font-size:11px;outline:none">
          <button class="btn btn-secondary inline-manual-save" type="button" style="padding:2px 8px;font-size:11px">保存</button>
        </div>
      </div>`;

    ab.innerHTML = `<div class="chat-label">🤖 AI · Turn ${turnIdx}</div>${tagsHtml}<div>${formatted}</div>${metaHtml}${bottomBarHtml}${manualHtml}${debugHtml}`;

    // AI评分 Popover 点击事件
    const aiScoreTrigger = ab.querySelector('.ai-score-trigger');
    const aiDetailBtn = ab.querySelector('.ai-score-detail-btn');
    
    const triggerRescore = () => runInlineAiScore({
      turnNumber,
      userInput,
      aiOutput: aiReply,
      scoreTrigger: aiScoreTrigger,
      scoreDetailBtn: aiDetailBtn,
      scoreLine: ab.querySelector('.ai-score-line'),
      force: true
    });

    if (aiDetailBtn && isAiScoreValid) {
      const normalized = normalizeAiScoreData(aiScore);
      const showPopover = () => showAiScorePopover(aiDetailBtn.parentElement, normalized);
      aiDetailBtn.addEventListener('click', showPopover);
      aiScoreTrigger?.addEventListener('click', showPopover);
    } else if (aiScoreTrigger) {
      if (!aiScore) {
        aiScoreTrigger.textContent = '点击AI打分';
      }
      aiScoreTrigger.style.color = 'var(--warning-color)';
      aiScoreTrigger.addEventListener('click', triggerRescore);
    }
    const regenerateTrigger = ab.querySelector('.msg-regenerate-trigger');
    if (regenerateTrigger) {
      regenerateTrigger.addEventListener('click', () => triggerRegenerateTurn(turnNumber, regenerateTrigger));
    }
    const debugTrigger = ab.querySelector('.msg-debug-toggle');
    if (debugTrigger) {
      debugTrigger.addEventListener('click', () => {
        switchDebugPanel('messages');
        showModal('modal-debug');
        renderDebugView(Math.max(0, turnIdx - 1));
      });
    }
    // ✏️ 切换人工评分区域
    ab.querySelector('.manual-score-trigger')?.addEventListener('click', () => {
      const ms = ab.querySelector('.inline-manual-score');
      if (ms) ms.style.display = ms.style.display === 'none' ? 'block' : 'none';
    });
    // 10星事件绑定
    bindStar10Events(ab, turnNumber);
    area.appendChild(ab);
  }
  area.scrollTop = area.scrollHeight;
}

function buildTurnStatusTags(turn) {
  const tags = [];
  const debugInfo = turn.debug_info || {};
  if (turn.summary_generated || debugInfo.summary_generated) tags.push({ text: '🟡 摘要已生成', cls: 'yellow' });
  const trimLv = turn.token_trim_level !== undefined ? turn.token_trim_level : debugInfo.trim_level;
  if (trimLv > 0) tags.push({ text: `🟠 Token截断 L${trimLv}`, cls: 'orange' });
  if (turn.has_deep_injection || debugInfo.has_deep_injection) tags.push({ text: '🔵 深度注入', cls: 'blue' });
  const retries = turn.quality_retries !== undefined ? turn.quality_retries : debugInfo.quality_retries;
  if (retries > 0) tags.push({ text: `🔴 质量重试 (${retries})`, cls: 'red' });
  if (turn.has_cooldown_reinject || debugInfo.has_cooldown_reinject) tags.push({ text: '🟣 冷却复注', cls: 'purple' });
  if (turn.has_style_isolation || debugInfo.has_style_isolation) tags.push({ text: '🔷 风格隔离', cls: 'lightblue' });
  if (turn.score_status === 'scored') tags.push({ text: '🟢 AI已评分', cls: 'green' });
  if (turn.manual_star_score !== undefined && turn.manual_star_score !== null && turn.manual_star_score !== '') tags.push({ text: '🟢 人工已评分', cls: 'green' });
  return tags;
}

function renderInlineDebugBlock(turn, turnIdx) {
  const debugInfo = turn.debug_info || {};
  const entry = buildTurnDebugEntry(turn);
  const messages = getDebugMessages(entry);
  if (!Array.isArray(messages) || !messages.length) return '';
  const trimLevel = turn.token_trim_level !== undefined ? turn.token_trim_level : (debugInfo.trim_level || 0);
  const totalTokens = debugInfo.total_tokens || turn.input_tokens || 0;
  const itemsHtml = buildInlineMessageItems(messages);

  return `<details style="margin-top:12px;border:1px solid var(--border-light);border-radius:10px;background:var(--bg-hover);padding:10px 12px">
        <summary style="cursor:pointer;font-size:13px;font-weight:600;color:var(--text-primary)">查看消息快照 · Turn ${turnIdx}</summary>
        <div style="display:flex;gap:12px;flex-wrap:wrap;margin-top:10px;font-size:12px;color:var(--text-secondary)">
          <span>消息数: ${messages.length}</span>
          <span>Trim: ${trimLevel}</span>
          <span>Tokens: ${totalTokens}</span>
        </div>
        <div style="margin-top:10px">${itemsHtml}</div>
      </details>`;
}

function updateTurnManualState(turnNumber, starScore, comment) {
  const parsedScore = Number.parseFloat(starScore);
  const scoreValue = Number.isFinite(parsedScore) ? parsedScore : null;
  const target = state.turns.find((item, idx) => (item.turn || item.turn_order || (idx + 1)) === turnNumber);
  if (target) {
    target.manual_star_score = scoreValue;
    target.manual_comment = comment || '';
  }
  if (Array.isArray(state.scoreData) && state.scoreData[turnNumber - 1]) {
    state.scoreData[turnNumber - 1].manual_star_score = scoreValue;
    state.scoreData[turnNumber - 1].manual_comment = comment || '';
  }
}

function computeManualAvgScore() {
  if (!Array.isArray(state.turns) || !state.turns.length) return null;
  const manualScores = state.turns
    .map(item => Number.parseFloat(item.manual_star_score))
    .filter(value => Number.isFinite(value));
  if (!manualScores.length) return null;
  return manualScores.reduce((sum, value) => sum + value, 0) / manualScores.length;
}

function refreshScoreSummary() {
  const avgNode = $('score-avg');
  if (avgNode) {
    const avgScore = computeAvgScore();
    avgNode.textContent = avgScore === null ? '--' : avgScore.toFixed(1);
  }
  const manualNode = $('score-manual-avg');
  if (manualNode) {
    const manualAvg = computeManualAvgScore();
    manualNode.textContent = manualAvg === null ? '人工均分: -' : `人工均分: ${manualAvg.toFixed(1)}`;
  }
}

function renderScoringMeta() {
  const meta = state.scoreMeta || {};
  const chipWrap = $('scoring-meta-chips');
  const summaryBlock = $('scoring-summary-block');
  const summaryText = $('scoring-summary-text');
  if (chipWrap) {
    const chips = [
      meta.model_id ? `<span class="meta-chip">对话模型: ${escapeHtml(meta.model_id)}</span>` : '',
      meta.scoring_model_id ? `<span class="meta-chip">打分模型: ${escapeHtml(meta.scoring_model_id)}</span>` : '',
      meta.prompt_version ? `<span class="meta-chip">主提示词: ${escapeHtml(meta.prompt_version)}</span>` : '',
      meta.summary_prompt_version ? `<span class="meta-chip">摘要提示词: ${escapeHtml(meta.summary_prompt_version)}</span>` : '',
      meta.scoring_prompt_version ? `<span class="meta-chip">打分提示词: ${escapeHtml(meta.scoring_prompt_version)}</span>` : '',
    ].filter(Boolean);
    chipWrap.innerHTML = chips.join('');
  }
  if (summaryBlock && summaryText) {
    const summary = String(meta.dialogue_summary || '').trim();
    summaryBlock.style.display = summary ? 'block' : 'none';
    summaryText.textContent = summary;
  }
}

function renderScoreCards() {
  const container = $('score-cards');
  if (!container) return;
  container.innerHTML = '';
  (state.scoreData || []).forEach((score, index) => renderScoreCard(score, index + 1));
  refreshScoreSummary();
}

function closeAllScorePopovers() {
  document.querySelectorAll('.score-popover').forEach(node => {
    node.style.display = 'none';
  });
}

function buildConversationReportMeta(data = {}) {
  const summary = data.summary || {};
  const meta = data.meta || {};
  return {
    ai_report_status: meta.ai_report_status || summary.report_status || '',
    ai_report_label: meta.ai_report_label || summary.report_label || '',
    ai_report_ready: meta.ai_report_ready ?? summary.report_ready ?? false,
    ai_report_updated_at: meta.ai_report_updated_at || summary.report_updated_at || '',
    ai_report_event: meta.ai_report_event || summary.report_event || '',
    ai_report_count: meta.ai_report_count,
  };
}

function applyConversationScoreResults(data = {}) {
  if (!data || typeof data !== 'object') return null;
  state.scoreMeta = data.meta || null;
  state.scoreSummary = data.summary || null;
  const turns = Array.isArray(data.turns) ? data.turns : [];
  state.scoreData = turns.map(item => ({
    ...item.scores,
    total: item.total,
    reasoning: item.reasoning,
    status: item.status,
    manual_star_score: item.manual_star_score,
    manual_comment: item.manual_comment,
  }));
  turns.forEach(item => updateTurnManualState(item.turn, item.manual_star_score, item.manual_comment || ''));
  renderScoreCards();
  renderScoringMeta();

  const conversationId = String(data.conversation_id || state.convId || '').trim();
  const avgTotal = Number(data?.summary?.avg_total);
  if (conversationId) {
    const reportMeta = buildConversationReportMeta(data);
    updateHistoryRowScore(conversationId, avgTotal, data.summary || {}, reportMeta);
    updateSidebarScore(conversationId, avgTotal, data.summary || {});
  }
  return data;
}

async function syncScoreResults() {
  if (!state.convId) return;
  const response = await fetch(`/api/scoring/${state.convId}/results`);
  if (!response.ok) return;
  const data = await response.json();
  applyConversationScoreResults(data);
}

async function saveInlineManualScore(turnNumber, starScore, comment, button) {
  if (!state.convId) {
    showToast('请先运行一次对话测试', 'warning');
    return;
  }
  const scoreValue = Number.parseFloat(starScore);
  if (!Number.isFinite(scoreValue)) {
    showToast('人工分数无效', 'warning');
    return;
  }

  const prevText = button ? button.textContent : '';
  try {
    if (button) {
      button.disabled = true;
      button.textContent = '保存中...';
    }
    const response = await fetch(`/api/scoring/${state.convId}/turn/${turnNumber}/manual`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ star_score: Number(scoreValue.toFixed(1)), comment: comment || '' }),
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.detail || response.statusText || '保存失败');
    }
    updateTurnManualState(turnNumber, scoreValue, comment || '');
    if ($('modal-scoring')?.style.display === 'flex' && Array.isArray(state.scoreData) && state.scoreData.length) {
      renderScoreCards();
    } else {
      refreshScoreSummary();
    }
    showToast(`Turn ${turnNumber} 人工评分已保存`, 'success');
  } catch (e) {
    showToast('保存人工评分失败: ' + e.message, 'error');
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = prevText || '保存人工分';
    }
  }
}

function triggerInlineAiScoreForTurn(turnNumber, options = {}) {
  const bubble = document.querySelector(`.chat-bubble.ai[data-turn="${turnNumber}"]`);
  const turn = state.turns.find(item => (item.turn || item.turn_order) === turnNumber);
  if (!bubble || !turn) return;
  return runInlineAiScore({
    turnNumber,
    userInput: turn.user_input || '',
    aiOutput: turn.ai_output || '',
    scoreTrigger: bubble.querySelector('.ai-score-trigger'),
    scoreDetailBtn: bubble.querySelector('.ai-score-detail-btn'),
    scoreLine: bubble.querySelector('.ai-score-line'),
    refreshHistory: options.refreshHistory,
  });
}

async function triggerRegenerateTurn(turnNumber, regenerateTrigger) {
  if (state.chatSessionMode !== 'interactive' || !state.convId) {
    showToast('仅当前交互式会话支持重新生成', 'warning');
    return;
  }
  if (turnNumber !== state.turns.length) {
    showToast('仅支持重新生成最后一轮，避免破坏后续上下文', 'warning');
    return;
  }
  const originalText = regenerateTrigger ? regenerateTrigger.textContent : '🔄';
  if (regenerateTrigger) {
    regenerateTrigger.textContent = '⏳';
    regenerateTrigger.style.pointerEvents = 'none';
  }
  const globalModelSel = $('header-global-model');
  const modelId = globalModelSel ? globalModelSel.value : 'doubao-pro';
  const sampling = getGenerationSamplingConfig();
  const dialogueThinking = getDialogueThinkingState(modelId);
  try {
    const response = await fetch(`/api/conversations/${state.convId}/turns/${turnNumber}/regenerate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model_id: modelId,
        web_search: $('f-web-search-chat') ? !!$('f-web-search-chat').checked : false,
        thinking_enabled: dialogueThinking.enabled,
        thinking_effort: dialogueThinking.thinking_effort,
        temperature: sampling.temperature,
        top_p: sampling.top_p,
      }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || data.error || '重新生成失败');

    const targetIndex = state.turns.findIndex(item => (item.turn || item.turn_order) === turnNumber);
    if (targetIndex >= 0) {
      state.turns[targetIndex] = { ...data };
    }
    syncChatHistoryFromTurns();
    rebuildChatFromTurns();
    loadHistory();
    showToast('已重新生成最后一轮', 'success');
  } catch (e) {
    showToast('重新生成失败: ' + e.message, 'error');
  } finally {
    if (regenerateTrigger) {
      regenerateTrigger.textContent = originalText;
      regenerateTrigger.style.pointerEvents = 'auto';
    }
  }
}

function formatNarration(text) {
  if (!text) return '';
  const normalizeDialogueText = value => String(value || '')
    .trim()
    .replace(/\*\*/g, '')
    .replace(/^[""「]/, '')
    .replace(/[""」]$/, '');
  const normalizeDialogueLine = line => {
    const trimmed = String(line || '').trim();
    if (!trimmed) return line;
    const match = trimmed.match(/^(?:\*\*)?(?:[""「])(?:\*\*)?(.+?)(?:\*\*)?(?:[""」])(?:\*\*)?$/);
    if (!match) return line;
    const body = normalizeDialogueText(match[1]);
    if (!body) return line;
    return line.replace(trimmed, `**"${body}"**`);
  };
  const stripPseudoXmlLinePrefix = line => {
    const match = String(line || '').match(
      /^([\s\u3000]*)(?:[\u0022\u201C\u201D\uFF02「]\s*)?(?:<\s*)?(dialogue|narration)\s*(?:[\u0022\u201C\u201D\uFF02」]\s*)?[>:\uFF1E\uFF1A]\s*(.*)$/i
    );
    if (!match) return line;
    const lead = match[1] || '';
    const tag = String(match[2] || '').toLowerCase();
    let body = String(match[3] || '').replace(/^\s+/, '');
    if (tag === 'dialogue' && body && !/^(?:["\u201C\uFF02「])/.test(body)) {
      body = `"${body}`;
    }
    return `${lead}${body}`;
  };
  // 预处理：保留 v2.6 的对白格式，旧版旁白/对白仅做兼容，不再回退到旧中间态
  // 额外兜底：旧会话可能已存入 `"dialogue">"..."` 这类模型幻觉前缀，前端渲染时剥离。
  const pre = String(text)
    .replace(/<span\s+class=["']dialogue["'][^>]*>([\s\S]*?)<\/span>/gi, (_, content) => `**"${normalizeDialogueText(content)}"**`)
    .replace(/<dialogue>([\s\S]*?)<\/dialogue>/gi, (_, content) => `**"${normalizeDialogueText(content)}"**`)
    .replace(/<span\s+class=["']narration["'][^>]*>([\s\S]*?)<\/span>/gi, '$1')
    .replace(/<narration>([\s\S]*?)<\/narration>/gi, '$1')
    // 剥离残留的 <dialogue>/<narration> 开合标签（含属性形态）
    .replace(/<\s*\/?\s*(?:dialogue|narration)[^>]*>/gi, '');
  const normalized = pre
    .split('\n')
    .map(stripPseudoXmlLinePrefix)
    .map(normalizeDialogueLine)
    .join('\n');
  return escapeHtml(normalized)
    .replace(/\*\*"([^"\n]+?)"\*\*/g, '<strong class="dialogue">"$1"</strong>')
    .replace(/「([^」]+)」/g, '<strong class="dialogue">「$1」</strong>')
    .replace(/(^|[^<>=\w])"([^"\n]+)"/g, '$1<strong class="dialogue">"$2"</strong>')
    .replace(/(^|[^\*])\*([^*\n]+)\*(?!\*)/g, '$1<span class="narration">$2</span>')
    .replace(/\n/g, '<br>');
}

/* ═══ 调试视图 ═══ */
function renderDebugView(turnIdx) {
  if (!state.debugData.length) {
    $('debug-no-data').style.display = 'block';
    $('debug-content').style.display = 'none';
    if ($('btn-copy-debug-json')) $('btn-copy-debug-json').disabled = true;
    return;
  }
  $('debug-no-data').style.display = 'none';
  $('debug-content').style.display = 'block';
  if ($('btn-copy-debug-json')) $('btn-copy-debug-json').disabled = false;
  const normalizedIndex = Math.max(0, Math.min(turnIdx || 0, state.debugData.length - 1));
  const sel = $('debug-turn-select');
  sel.innerHTML = '';
  state.debugData.forEach((d, i) => {
    const o = document.createElement('option');
    o.value = i;
    o.textContent = `Turn ${i + 1}`;
    sel.appendChild(o);
  });
  sel.value = String(normalizedIndex);
  sel.onchange = () => renderDebugView(parseInt(sel.value, 10));

  const d = normalizeDebugEntry(state.debugData[normalizedIndex] || {});
  state.debugData[normalizedIndex] = d;
  const msgs = getDebugMessages(d);
  const list = $('debug-msg-list');
  const badges = $('debug-badges');
  const requestMeta = $('debug-request-meta');
  const requestDetails = $('debug-request-details');
  list.innerHTML = '';
  badges.innerHTML = '';
  requestMeta.innerHTML = '';
  if (requestDetails) requestDetails.innerHTML = '';
  switchDebugPanel(_debugPanelMode);

  if (d.total_tokens) badges.innerHTML += `<span class="badge badge-info">Tokens: ${d.total_tokens}</span>`;
  if (d.trim_level !== undefined) badges.innerHTML += `<span class="badge badge-warning">裁剪级别: ${d.trim_level}/7</span>`;
  if (d.model) badges.innerHTML += `<span class="badge badge-success">${escapeHtml(d.model)}</span>`;
  if (d.has_deep_injection) badges.innerHTML += `<span class="badge badge-info">深度注入</span>`;
  if (d.quality_retries) badges.innerHTML += `<span class="badge badge-danger">质量重试 ${d.quality_retries}</span>`;

  const trimSegs = $('debug-trim-segments');
  trimSegs.innerHTML = '';
  const trimLv = d.trim_level || 0;
  for (let i = 0; i < 7; i++) {
    const s = document.createElement('div');
    s.className = 'trim-seg';
    if (i < trimLv) s.classList.add(i < 3 ? 'active' : i < 5 ? 'high' : 'critical');
    trimSegs.appendChild(s);
  }
  $('debug-trim-value').textContent = `${trimLv}/7`;

  msgs.forEach((m, idx) => {
    const item = document.createElement('div');
    item.className = 'msg-item';
    const content = m.content || '';
    const tokens = m.tokens || (content.length / 2) | 0;
    // D-1: 消息层级标签
    let layerTag = '';
    if (m.role === 'system') {
      if (idx === 0) layerTag = '<span class="badge badge-info" style="font-size:10px;margin-left:6px">L0-L4 System</span>';
      else if (/以上为.*示例|风格参考|以下为真实对话/.test(content)) layerTag = '<span class="badge badge-warning" style="font-size:10px;margin-left:6px">隔离声明</span>';
      else if (/请记住.*你是|记住.*性格|当前关系阶段/.test(content)) layerTag = '<span class="badge badge-info" style="font-size:10px;margin-left:6px">Depth注入</span>';
      else if (/Core_Constraints|长度.*300.*500|旁白纯文本/.test(content)) layerTag = '<span class="badge badge-danger" style="font-size:10px;margin-left:6px">Core约束</span>';
      else if (/记忆上下文|用户画像|摘要/.test(content)) layerTag = '<span class="badge badge-success" style="font-size:10px;margin-left:6px">记忆上下文</span>';
      else if (/内心戏记录|短文模式.*记录|非叙事格式/.test(content)) layerTag = '<span class="badge badge-warning" style="font-size:10px;margin-left:6px">异质隔离</span>';
    } else if (m.role === 'user' && idx === 1) {
      layerTag = '<span class="badge badge-info" style="font-size:10px;margin-left:6px">Few-shot</span>';
    } else if (m.role === 'assistant' && idx === 2) {
      layerTag = '<span class="badge badge-info" style="font-size:10px;margin-left:6px">Few-shot</span>';
    }
    item.innerHTML = `<div class="msg-header" onclick="this.parentElement.classList.toggle('expanded')"><span class="msg-chevron">▶</span><span class="msg-role ${m.role}">${m.role}</span>${layerTag}<span class="msg-tokens">${tokens} tokens</span></div><div class="msg-body">${escapeHtml(content)}</div>`;
    list.appendChild(item);
  });
  if (!msgs.length) {
    list.innerHTML = `<div class="empty-state" style="padding:24px 16px"><div class="title">暂无消息快照</div><p>当前轮次没有可展示的 messages 数据。</p></div>`;
  }

  const payload = d.request_payload_snapshot || {};
  const requestChips = [
    payload.model_id ? `模型: ${payload.model_id}` : '',
    payload.prompt_version ? `主提示词: ${payload.prompt_version}` : '',
    payload.summary_prompt_version ? `摘要提示词: ${payload.summary_prompt_version}` : '',
    payload.scoring_prompt_version ? `打分提示词: ${payload.scoring_prompt_version}` : '',
    payload.scoring_model_id ? `打分模型: ${payload.scoring_model_id}` : '',
    payload.injection_depth ? `注入深度: ${payload.injection_depth}` : '',
    payload.temperature !== undefined ? `Temperature: ${formatGenerationNumber(payload.temperature)}` : '',
    payload.top_p !== undefined ? `Top P: ${formatGenerationNumber(payload.top_p)}` : '',
  ].filter(Boolean);
  requestMeta.innerHTML = requestChips.map(text => `<span class="meta-chip">${escapeHtml(text)}</span>`).join('');
  if (!requestChips.length) {
    requestMeta.innerHTML = `<span class="meta-chip">未记录额外请求元信息</span>`;
  }
  renderDebugRequestDetails(payload, msgs);
  $('debug-request-json').textContent = JSON.stringify(payload, null, 2);
}

/* ═══ 历史记录 ═══ */
function getHistoryFilterState() {
  return {
    role: getInputValue('history-filter-role').trim().toLowerCase(),
    model: getInputValue('history-filter-model').trim().toLowerCase(),
    prompt: getInputValue('history-filter-prompt').trim().toLowerCase(),
    status: getInputValue('history-filter-status'),
    dateFrom: getInputValue('history-filter-date-from'),
    dateTo: getInputValue('history-filter-date-to'),
    scoreMin: getInputValue('history-filter-score-min'),
    scoreMax: getInputValue('history-filter-score-max'),
    includeArchived: !!$('history-filter-include-archived')?.checked,
  };
}

function getHistoryRoleLabel(item = {}) {
  return String(item.nickname || item.character_name || '').trim() || '未命名角色';
}

function getHistoryModelLabel(item = {}) {
  return String(item.model || item.model_pro || item.model_id || '').trim() || '未命名模型';
}

function getHistoryPromptLabel(item = {}) {
  return String(item.prompt_version || item.prompt_file || '').trim() || '未命名提示词';
}

function filterHistoryItems(items) {
  const filters = getHistoryFilterState();
  return (items || []).filter(item => {
    const role = getHistoryRoleLabel(item).toLowerCase();
    const model = getHistoryModelLabel(item).toLowerCase();
    const prompt = getHistoryPromptLabel(item).toLowerCase();
    const status = String(item.status || '').trim().toLowerCase();
    const date = parseSqliteUtcDate(item.created_at || item.timestamp || Date.now()) || new Date();
    const scoreAvg = Number.parseFloat(item.score_avg);
    const scoreMin = Number.parseFloat(filters.scoreMin);
    const scoreMax = Number.parseFloat(filters.scoreMax);
    if (filters.role && !role.includes(filters.role)) return false;
    if (filters.model && !model.includes(filters.model)) return false;
    if (filters.prompt && !prompt.includes(filters.prompt)) return false;
    if (filters.status && status !== String(filters.status || '').trim().toLowerCase()) return false;
    if (!filters.includeArchived && item.archived) return false;
    if (filters.dateFrom) {
      const from = new Date(`${filters.dateFrom}T00:00:00`);
      if (date < from) return false;
    }
    if (filters.dateTo) {
      const to = new Date(`${filters.dateTo}T23:59:59`);
      if (date > to) return false;
    }
    if (Number.isFinite(scoreMin) && (!Number.isFinite(scoreAvg) || scoreAvg < scoreMin)) return false;
    if (Number.isFinite(scoreMax) && (!Number.isFinite(scoreAvg) || scoreAvg > scoreMax)) return false;
    if (_scoreQuickFilter === 'scored' && !Number.isFinite(scoreAvg)) return false;
    if (_scoreQuickFilter === 'unscored' && (status !== 'completed' || Number.isFinite(scoreAvg))) return false;
    if (_scoreQuickFilter === 'failed' && !(Number(item.failed_turns || 0) > 0 || String(item.status || '').includes('scoring_failed'))) return false;
    return true;
  });
}

function renderHistoryWithCurrentFilters() {
  renderHistory(filterHistoryItems(state.historyItems || []));
}

function setScoreQuickFilter(val) {
  _scoreQuickFilter = String(val || '').trim();
  document.querySelectorAll('.score-quick-filter-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.filter === _scoreQuickFilter);
  });
  renderHistoryWithCurrentFilters();
}

function toggleSelectAllHistory() {
  const allBox = $('history-select-all');
  if (!allBox) return;
  const visibleIds = filterHistoryItems(state.historyItems || []).map(c => c.id || c.conversation_id).filter(Boolean);
  if (allBox.checked) {
    state.historyCompareSelection = [...new Set([...(state.historyCompareSelection || []), ...visibleIds])];
  } else {
    state.historyCompareSelection = (state.historyCompareSelection || []).filter(id => !visibleIds.includes(id));
  }
  renderHistoryWithCurrentFilters();
}

function getConversationStatusLabel(status) {
  const normalized = String(status || '').trim().toLowerCase();
  return {
    running: '运行中',
    scoring: '打分中',
    cancelling: '停止中',
    queued: '排队中',
    paused: '已暂停',
    cancelled: '已取消',
    completed: '已完成',
    failed: '已失败',
    interrupted: '已中断',
    pending: '待执行',
  }[normalized] || (status || '未知');
}

function buildHistoryQueryParams() {
  const params = new URLSearchParams();
  // 历史筛选改成前端即时过滤；这里始终拉全量（含归档），避免输入时多次全表重载。
  params.set('include_archived', 'true');
  return params;
}

function getHistoryScoringStats(item = {}) {
  const totalTurns = Math.max(0, Number(item.total_turns || item.turns || 0));
  const scoredTurns = Math.max(0, Number(item.scored_turns || 0));
  const failedTurns = Math.max(0, Number(item.failed_turns || 0));
  const skippedTurns = Math.max(0, Number(item.skipped_turns || 0));
  const doneTurns = scoredTurns + failedTurns + skippedTurns;
  return {
    totalTurns,
    scoredTurns,
    failedTurns,
    skippedTurns,
    doneTurns,
    scoringComplete: totalTurns > 0 && doneTurns >= totalTurns,
  };
}

function getHistoryAiReportMeta(item = {}) {
  const stats = getHistoryScoringStats(item);
  let status = String(item.ai_report_status || '').trim().toLowerCase();
  if (!status) {
    if (item.ai_report_ready || Number(item.ai_report_count || 0) > 0) status = 'ready';
    else if (stats.totalTurns <= 0) status = 'idle';
    else if (!stats.scoringComplete) status = 'waiting_scoring';
    else if (stats.scoredTurns <= 0) status = 'blocked_no_score';
    else status = 'pending';
  }
  const fallback = {
    ready: { label: '报告就绪', actionLabel: 'AI报告', tone: 'success', disabled: false, retryable: false },
    generating: { label: '报告生成中', actionLabel: '报告生成中', tone: 'info', disabled: true, retryable: false },
    pending: { label: '等待生成报告', actionLabel: '等待生成', tone: 'warning', disabled: true, retryable: true },
    failed: { label: '报告生成失败', actionLabel: '报告失败', tone: 'danger', disabled: true, retryable: true },
    waiting_scoring: { label: '待评分完成', actionLabel: '待评分完成', tone: 'warning', disabled: true, retryable: false },
    waiting_generation: { label: '生成中，待评分', actionLabel: '生成中', tone: 'muted', disabled: true, retryable: false },
    blocked_no_score: { label: '无已评分轮次', actionLabel: '无报告', tone: 'muted', disabled: true, retryable: false },
    idle: { label: '暂无报告', actionLabel: '暂无报告', tone: 'muted', disabled: true, retryable: false },
  }[status] || { label: '等待生成报告', actionLabel: '等待生成', tone: 'warning', disabled: true, retryable: true };
  return {
    status,
    label: String(item.ai_report_label || fallback.label).trim() || fallback.label,
    actionLabel: fallback.actionLabel,
    tone: fallback.tone,
    disabled: fallback.disabled,
    retryable: fallback.retryable,
    ready: status === 'ready',
    updatedAt: String(item.ai_report_updated_at || '').trim(),
  };
}

function getHistoryStatusDetail(item = {}, stats = getHistoryScoringStats(item), reportMeta = getHistoryAiReportMeta(item)) {
  const normalizedStatus = String(item.status || '').trim().toLowerCase();
  const generatedTurns = Math.max(0, Number(item.completed_turns ?? item.next_turn_index ?? 0));
  if (['running', 'queued', 'pending'].includes(normalizedStatus) && stats.totalTurns > 0) {
    return { text: `已生成 ${Math.min(generatedTurns, stats.totalTurns)}/${stats.totalTurns} 轮`, tone: 'muted' };
  }
  if (normalizedStatus === 'completed' && stats.totalTurns > 0 && !stats.scoringComplete) {
    return { text: `部分评分 ${stats.doneTurns}/${stats.totalTurns}`, tone: 'warning' };
  }
  return { text: reportMeta.label, tone: reportMeta.tone };
}

function getHistoryScoringActionMeta(item = {}, stats = getHistoryScoringStats(item), reportMeta = getHistoryAiReportMeta(item)) {
  const normalizedStatus = String(item.status || '').trim().toLowerCase();
  if (['running', 'queued', 'pending'].includes(normalizedStatus) && stats.totalTurns > 0 && !stats.scoringComplete) {
    return { key: 'resume_sync', label: '继续同步', title: '后台处理中，继续同步评分结果' };
  }
  if (stats.scoringComplete && stats.scoredTurns > 0 && reportMeta.status !== 'ready') {
    return { key: 'repair_summary', label: '汇总评分', title: '重算均分并生成 AI 报告' };
  }
  if (stats.totalTurns > 0 && !stats.scoringComplete && stats.scoredTurns > 0) {
    return { key: 'retry_failed_turns', label: '重试失败项', title: '仅重试失败/未完成轮次' };
  }
  if ((stats.failedTurns > 0 && stats.scoredTurns <= 0) || (stats.totalTurns > 0 && stats.doneTurns <= 0)) {
    return { key: 'rescore_all', label: '重新全部打分', title: '当前没有可用评分结果，将重新对整段会话评分' };
  }
  return { key: 'view_results', label: '查看结果', title: '当前会话已有可用评分结果' };
}

function renderSidebarHistory(convs) {
  const sb = $('sidebar-history');
  if (!sb) return;
  sb.innerHTML = '';
  (convs || []).forEach(c => {
    const convId = c.id || c.conversation_id;
    const roleName = c.nickname || c.character_name || '默认角色';
    const characterType = c.character_type || '';
    const titleText = `🎭 ${roleName}${characterType ? `·${characterType}` : ''}`;
    const previewText = truncateText(c.last_message_preview || '暂无消息', 20);
    const timeText = formatRelativeTime(c.updated_at || c.created_at || c.timestamp);
    const item = document.createElement('div');
    item.className = `history-item${state.convId === convId ? ' active' : ''}${c.pinned ? ' pinned' : ''}`;
    item.dataset.status = String(c.status || 'pending').replace(/^completed_.*/, 'completed');
    item.setAttribute('role', 'button');
    item.setAttribute('tabindex', '0');
    item.title = `${roleName} · ${timeText || '刚刚'} · ${getConversationStatusLabel(c.status)}`;
    item.innerHTML = `
      <span class="history-avatar">${escapeHtml(roleName.slice(0, 1) || '默')}</span>
      <span class="history-body">
        <span class="history-title-row">
          <span class="history-title">${escapeHtml(titleText)}</span>
        </span>
        <span class="history-preview">${escapeHtml(previewText)}</span>
        <span class="history-meta">${escapeHtml(`${timeText || '刚刚'} · ${getConversationStatusLabel(c.status)}`)}</span>
      </span>
      <span class="history-actions">
        ${['interrupted', 'cancelled'].includes(String(c.status || '')) ? '<button type="button" class="history-action" aria-label="继续执行" title="继续执行" data-action="resume">▶</button>' : ''}
        <button type="button" class="history-action" aria-label="${c.archived ? '取消归档' : '归档对话'}" title="${c.archived ? '取消归档' : '归档'}" data-action="archive">${c.archived ? '📂' : '🗂️'}</button>
        <button type="button" class="history-action" aria-label="查看日志" title="日志" data-action="events">🧾</button>
        <button type="button" class="history-action" aria-label="${c.pinned ? '取消置顶' : '置顶对话'}" title="${c.pinned ? '取消置顶' : '置顶'}" data-action="pin">${c.pinned ? '📌' : '📍'}</button>
        <button type="button" class="history-action danger" aria-label="删除对话" title="删除" data-action="delete">🗑️</button>
      </span>
    `;
    item.addEventListener('click', () => viewConversation(convId));
    item.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        viewConversation(convId);
      }
    });
    item.querySelector('[data-action="pin"]')?.addEventListener('click', async (event) => {
      event.stopPropagation();
      await toggleConversationPin(convId, !c.pinned);
    });
    item.querySelector('[data-action="resume"]')?.addEventListener('click', async (event) => {
      event.stopPropagation();
      await resumeConversation(convId);
    });
    item.querySelector('[data-action="archive"]')?.addEventListener('click', async (event) => {
      event.stopPropagation();
      await toggleConversationArchive(convId, !c.archived);
    });
    item.querySelector('[data-action="events"]')?.addEventListener('click', async (event) => {
      event.stopPropagation();
      await showConversationEvents(convId);
    });
    item.querySelector('[data-action="delete"]')?.addEventListener('click', async (event) => {
      event.stopPropagation();
      await deleteConversation(convId);
    });
    sb.appendChild(item);
  });
}

function syncHistoryCompareSelection() {
  const existingIds = new Set((state.historyItems || []).map(item => item.id || item.conversation_id).filter(Boolean));
  state.historyCompareSelection = (state.historyCompareSelection || []).filter(id => existingIds.has(id));
}

function getSelectedHistoryConversationIds() {
  return [...new Set((state.historyCompareSelection || []).filter(Boolean))];
}

function getSelectedHistoryConversations() {
  const selectedIds = new Set(getSelectedHistoryConversationIds());
  return (state.historyItems || []).filter(item => selectedIds.has(item.id || item.conversation_id));
}

function getHistorySelectionSummaryContext(selectedConversations = getSelectedHistoryConversations()) {
  const conversations = Array.isArray(selectedConversations) ? selectedConversations : [];
  const roleValues = new Set(conversations.map(getHistoryRoleLabel).filter(Boolean));
  const modelValues = new Set(conversations.map(getHistoryModelLabel).filter(Boolean));
  const promptValues = new Set(conversations.map(getHistoryPromptLabel).filter(Boolean));
  const turnCounts = new Set(conversations.map(item => Number(item.total_turns || item.turns || 0)).filter(num => Number.isFinite(num) && num > 0));
  const allCompleted = conversations.every(item => String(item.status || '').trim().toLowerCase() === 'completed');
  const comparableTurnCount = turnCounts.size <= 1;
  const selectionCount = conversations.length;
  let summaryType = 'empty';
  let reportTitle = '评分摘要';
  let actionLabel = '生成评分摘要';
  let helperText = '请选择至少 2 条历史记录。';

  if (selectionCount >= 2) {
    if (roleValues.size === 1 && modelValues.size > 1 && promptValues.size === 1) {
      summaryType = 'model_summary';
      reportTitle = '模型评分摘要';
      actionLabel = '生成模型评分摘要';
      helperText = '同角色、同提示词、不同模型，聚焦比较模型表现。';
    } else if (roleValues.size === 1 && modelValues.size === 1 && promptValues.size > 1) {
      summaryType = 'prompt_summary';
      reportTitle = '提示词评分摘要';
      actionLabel = '生成提示词评分摘要';
      helperText = '同角色、同模型、不同提示词，聚焦比较提示词版本表现。';
    } else if (roleValues.size > 1 && modelValues.size === 1 && promptValues.size === 1) {
      summaryType = 'role_summary';
      reportTitle = '角色评分摘要';
      actionLabel = '生成角色评分摘要';
      helperText = '同模型、同提示词、不同角色，聚焦比较角色适配度。';
    } else if (promptValues.size === 1) {
      summaryType = 'mode_summary';
      reportTitle = '模式评分摘要';
      actionLabel = '生成模式评分摘要';
      helperText = '提示词保持一致，聚焦看模式在不同角色/模型上的稳健性。';
    } else if (roleValues.size === 1 || modelValues.size === 1 || promptValues.size === 1) {
      summaryType = 'matrix_summary';
      reportTitle = '实验矩阵评分摘要';
      actionLabel = '生成实验矩阵摘要';
      helperText = '存在单轴固定但不是纯模型/纯提示词对比，适合输出实验矩阵摘要。';
    } else {
      summaryType = 'mixed_summary';
      reportTitle = '混合样本评分盘点';
      actionLabel = '生成混合样本盘点';
      helperText = '角色、模型、提示词同时变化，只适合做盘点型摘要。';
    }
  }

  const compareEligible = selectionCount >= 2
    && selectionCount <= 3
    && allCompleted
    && comparableTurnCount
    && ['model_summary', 'prompt_summary'].includes(summaryType);

  return {
    selectionCount,
    roleCount: roleValues.size,
    modelCount: modelValues.size,
    promptCount: promptValues.size,
    allCompleted,
    comparableTurnCount,
    summaryType,
    reportTitle,
    actionLabel,
    helperText,
    compareEligible,
  };
}

function updateHistoryCompareActions() {
  const selectedConversations = getSelectedHistoryConversations();
  const context = getHistorySelectionSummaryContext(selectedConversations);
  const selectedCount = context.selectionCount;
  const exportBtn = $('history-export-selected-btn');
  const summaryBtn = $('history-summary-selected-btn');
  const rescoreBtn = $('history-rescore-selected-btn');
  const compareBtn = $('history-compare-selected-btn');
  const deleteBtn = $('history-delete-selected-btn');
  const clearBtn = $('history-clear-selection-btn');
  const status = $('history-compare-status');
  if (summaryBtn) {
    summaryBtn.disabled = selectedCount < 2;
    summaryBtn.textContent = selectedCount ? `${context.actionLabel} (${selectedCount})` : '🧠 生成评分摘要';
  }
  if (exportBtn) {
    exportBtn.disabled = selectedCount === 0;
    exportBtn.textContent = selectedCount ? `批量导出选中记录 (${selectedCount})` : '批量导出选中记录';
  }
  if (rescoreBtn) {
    rescoreBtn.disabled = selectedCount === 0;
    rescoreBtn.textContent = selectedCount ? `批量重打分选中记录 (${selectedCount})` : '批量重打分选中记录';
  }
  if (compareBtn) {
    compareBtn.disabled = !context.compareEligible;
    compareBtn.textContent = selectedCount ? `📊 对比选中记录 (${selectedCount})` : '📊 对比选中记录';
  }
  if (deleteBtn) {
    deleteBtn.disabled = selectedCount === 0;
    deleteBtn.textContent = selectedCount ? `批量删除选中记录 (${selectedCount})` : '批量删除选中记录';
  }
  if (clearBtn) clearBtn.disabled = selectedCount === 0;
  if (status) {
    status.textContent = selectedCount
      ? `已选 ${selectedCount} 条记录。当前归类为「${context.reportTitle}」。${context.helperText}${context.compareEligible ? ' 当前也满足历史对比报告条件。' : ' 历史对比仍仅支持 2-3 条、已完成、轮数一致且属于纯模型/纯提示词对比的记录。'}`
      : '可多选历史记录进行批量导出、批量重打分或生成评分摘要；其中 2-3 条结构一致的记录仍可直接生成历史对比报告。';
  }
}

function toggleHistoryCompareSelection(convId, checked) {
  const current = new Set(state.historyCompareSelection || []);
  if (checked) {
    current.add(convId);
  } else {
    current.delete(convId);
  }
  state.historyCompareSelection = [...current];
  updateHistoryCompareActions();
}

function clearHistoryCompareSelection() {
  state.historyCompareSelection = [];
  renderHistory(filterHistoryItems(state.historyItems || []));
}

async function deleteSelectedHistoryConversations() {
  const selectedIds = getSelectedHistoryConversationIds();
  if (!selectedIds.length) {
    showToast('请先勾选要删除的历史记录', 'warning');
    return;
  }
  const confirmed = await openActionConfirmDialog({
    title: '确认批量删除',
    message: `确定删除选中的 ${selectedIds.length} 条历史记录吗？`,
    note: '删除后无法恢复，历史列表会立即刷新。',
    confirmText: '确认删除',
    confirmTone: 'danger',
  });
  if (!confirmed) return;

  const results = await Promise.allSettled(selectedIds.map(async (id) => {
    const response = await fetch(`/api/conversations/${id}`, { method: 'DELETE' });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.detail || response.statusText || '删除失败');
    }
    return id;
  }));

  const successIds = results
    .filter(result => result.status === 'fulfilled')
    .map(result => result.value);
  const failedCount = results.length - successIds.length;

  state.historyCompareSelection = (state.historyCompareSelection || []).filter(id => !successIds.includes(id));
  if (successIds.includes(state.convId)) {
    state.convId = null;
    state.interactiveConfigSignature = '';
    resetChatCanvas();
  }

  if (successIds.length) {
    showToast(`已删除 ${successIds.length} 条记录${failedCount ? `，失败 ${failedCount} 条` : ''}`, failedCount ? 'warning' : 'success');
  } else {
    showToast('批量删除失败', 'error');
  }
  await loadHistory();
}

function updateBatchRescoreProgress() {
  const fill = $('history-batch-rescore-fill');
  const counter = $('history-batch-rescore-counter');
  const successBadge = $('history-batch-rescore-success-badge');
  const failBadge = $('history-batch-rescore-fail-badge');
  const successNum = $('history-batch-rescore-success-num');
  const failNum = $('history-batch-rescore-fail-num');
  const pct = _batchRescoreTotal ? ((_batchRescoreFinished / _batchRescoreTotal) * 100).toFixed(1) : 0;
  if (fill) fill.style.width = `${pct}%`;
  if (counter) counter.textContent = `${_batchRescoreFinished} / ${_batchRescoreTotal}`;
  if (successBadge) successBadge.style.display = _batchRescoreSuccessCount > 0 ? 'inline' : 'none';
  if (successNum) successNum.textContent = String(_batchRescoreSuccessCount);
  if (failBadge) failBadge.style.display = _batchRescoreFailCount > 0 ? 'inline' : 'none';
  if (failNum) failNum.textContent = String(_batchRescoreFailCount);
}

function applyBatchRescoreRowStatus(convId, status) {
  _batchRescoreRowStatus.set(convId, status);
  const tr = document.querySelector(`#history-tbody tr[data-conv-id="${CSS.escape(String(convId || ''))}"]`);
  if (!tr) return;
  tr.classList.remove('history-row-scoring', 'history-row-score-done', 'history-row-score-fail');
  const scoreCell = tr.querySelector('.history-score-cell');
  if (status === 'scoring') {
    tr.classList.add('history-row-scoring');
    if (scoreCell) scoreCell.innerHTML = '<span class="score-chip-scoring">打分中…</span>';
  } else if (status === 'success') {
    tr.classList.add('history-row-score-done');
    if (scoreCell) scoreCell.innerHTML = '<span style="color:var(--success-color,#00b42a);font-size:12px" title="打分完成，刷新中">✓</span>';
  } else if (status === 'failed') {
    tr.classList.add('history-row-score-fail');
    if (scoreCell) scoreCell.innerHTML = '<span style="color:var(--danger-color,#ef4444);font-size:12px" title="打分失败">✗</span>';
  }
}

function dismissBatchRescoreProgress() {
  _batchRescoreRowStatus.clear();
  if (_batchRescoreAutoHideTimer) { clearTimeout(_batchRescoreAutoHideTimer); _batchRescoreAutoHideTimer = null; }
  const panel = $('history-batch-rescore-progress');
  if (panel) panel.style.display = 'none';
}

function cancelBatchRescore() {
  _batchRescoreCancelled = true;
  const cancelBtn = $('history-batch-rescore-cancel-btn');
  if (cancelBtn) { cancelBtn.disabled = true; cancelBtn.textContent = '取消中…'; }
  showToast('已发送取消指令，等待进行中任务完成', 'warning');
}

async function batchRescoreSelectedHistoryConversations() {
  const selectedIds = getSelectedHistoryConversationIds();
  if (!selectedIds.length) {
    showToast('请先勾选要重打分的历史记录', 'warning');
    return;
  }
  const confirmed = await openActionConfirmDialog({
    title: '确认批量重打分',
    message: `确定对选中的 ${selectedIds.length} 条历史记录执行全量重打分吗？`,
    note: '会清空旧分、按最新打分提示词重新评分，并在完成后自动重建评分摘要。',
    confirmText: '确认重打分',
  });
  if (!confirmed) return;

  // 初始化进度状态
  _batchRescoreCancelled = false;
  if (_batchRescoreAutoHideTimer) { clearTimeout(_batchRescoreAutoHideTimer); _batchRescoreAutoHideTimer = null; }
  _batchRescoreRowStatus.clear();
  _batchRescoreTotal = selectedIds.length;
  _batchRescoreFinished = 0;
  _batchRescoreSuccessCount = 0;
  _batchRescoreFailCount = 0;
  selectedIds.forEach(id => _batchRescoreRowStatus.set(id, 'pending'));

  // 显示浮动进度条
  const panel = $('history-batch-rescore-progress');
  const titleEl = $('history-batch-rescore-title');
  const spinnerEl = $('history-batch-rescore-spinner');
  const dismissBtn = $('history-batch-rescore-dismiss-btn');
  const cancelBtn = $('history-batch-rescore-cancel-btn');
  if (panel) panel.style.display = 'block';
  if (titleEl) titleEl.textContent = '⏳ 批量重打分进行中';
  if (spinnerEl) spinnerEl.style.display = 'inline-block';
  if (dismissBtn) dismissBtn.style.display = 'none';
  if (cancelBtn) { cancelBtn.style.display = 'inline-block'; cancelBtn.disabled = false; cancelBtn.textContent = '取消'; }
  updateBatchRescoreProgress();
  showToast(`已开始批量重打分，共 ${selectedIds.length} 条记录`, 'info');

  const actionBtn = $('history-rescore-selected-btn');
  const originalText = actionBtn ? actionBtn.textContent : '';
  if (actionBtn) {
    actionBtn.disabled = true;
    actionBtn.textContent = `打分中 0/${selectedIds.length}`;
  }
  let finished = 0;
  let scoreSuccessCount = 0;
  let scoreFailCount = 0;
  let summarySuccessCount = 0;
  let summaryFailCount = 0;
  await requestTaskNotificationPermission();

  try {
    await _mapPool(selectedIds, 2, async (convId) => {
      if (_batchRescoreCancelled) return;
      applyBatchRescoreRowStatus(convId, 'scoring');
      setConversationAiReportState(convId, 'waiting_scoring', {
        ai_report_label: '待评分完成',
        ai_report_ready: false,
        ai_report_count: 0,
        ai_report_updated_at: '',
      });
      try {
        const response = await fetch(`/api/scoring/${convId}/rescore-all`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(buildScoringRuntimeRequest({ preferLatestPrompt: true })),
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(payload.detail || '全量重打分失败');
        const latest = await watchConversationScoreRefresh(convId);
        if (
          isConversationScoringComplete(latest)
          && (
            Number(latest?.summary?.scored_count || 0) > 0
            || Number(latest?.summary?.skipped_count || 0) > 0
          )
        ) {
          scoreSuccessCount++;
          applyBatchRescoreRowStatus(convId, 'success');
        } else {
          scoreFailCount++;
          applyBatchRescoreRowStatus(convId, 'failed');
        }
        const summaryResult = await regenerateConversationAiSummarySilently(convId);
        if (summaryResult.success) {
          summarySuccessCount++;
        } else {
          summaryFailCount++;
        }
      } catch (error) {
        console.warn(`[history-batch-rescore] ${convId} 失败:`, error?.message || error);
        scoreFailCount++;
        applyBatchRescoreRowStatus(convId, 'failed');
      } finally {
        finished++;
        _batchRescoreFinished = finished;
        _batchRescoreSuccessCount = scoreSuccessCount;
        _batchRescoreFailCount = scoreFailCount;
        updateBatchRescoreProgress();
        if (actionBtn) actionBtn.textContent = `打分中 ${finished}/${selectedIds.length}`;
      }
    });
    await loadHistory();
    const message = _batchRescoreCancelled
      ? `批量重打分已取消：${scoreSuccessCount} 条已完成，${scoreFailCount} 条失败`
      : `批量重打分完成：${scoreSuccessCount} 条评分完成，${scoreFailCount} 条失败；AI报告更新 ${summarySuccessCount} 条${summaryFailCount ? `，失败 ${summaryFailCount} 条` : ''}`;
    if (titleEl) titleEl.textContent = _batchRescoreCancelled ? '🚫 批量重打分已取消' : scoreFailCount ? '⚠️ 批量重打分完成（部分失败）' : '✅ 批量重打分完成';
    if (spinnerEl) spinnerEl.style.display = 'none';
    if (cancelBtn) cancelBtn.style.display = 'none';
    if (dismissBtn) dismissBtn.style.display = 'inline-block';
    if (!_batchRescoreCancelled) {
      showToast(message, scoreFailCount || summaryFailCount ? 'warning' : 'success');
      void notifyTaskCompletion('批量重打分已完成', { body: message });
    }
    _batchRescoreAutoHideTimer = setTimeout(dismissBatchRescoreProgress, 8000);
  } catch (error) {
    if (titleEl) titleEl.textContent = '❌ 批量重打分出错';
    if (spinnerEl) spinnerEl.style.display = 'none';
    if (cancelBtn) cancelBtn.style.display = 'none';
    if (dismissBtn) dismissBtn.style.display = 'inline-block';
    showToast('批量重打分失败: ' + (error?.message || error), 'error');
  } finally {
    if (actionBtn) {
      actionBtn.disabled = false;
      actionBtn.textContent = originalText || '批量重打分选中记录';
    }
    updateHistoryCompareActions();
  }
}

function dismissHistorySummaryTaskProgress() {
  if (_historySummaryTaskAutoHideTimer) {
    clearTimeout(_historySummaryTaskAutoHideTimer);
    _historySummaryTaskAutoHideTimer = null;
  }
  const panel = $('history-summary-task-progress');
  if (panel) panel.style.display = 'none';
}

function setHistorySummaryTaskProgress({
  title = '🧠 历史摘要生成中',
  current = 0,
  total = 1,
  detail = '',
  spinning = true,
  allowDismiss = false,
} = {}) {
  if (_historySummaryTaskAutoHideTimer) {
    clearTimeout(_historySummaryTaskAutoHideTimer);
    _historySummaryTaskAutoHideTimer = null;
  }
  const panel = $('history-summary-task-progress');
  const titleEl = $('history-summary-task-title');
  const counterEl = $('history-summary-task-counter');
  const detailEl = $('history-summary-task-detail');
  const spinnerEl = $('history-summary-task-spinner');
  const dismissBtn = $('history-summary-task-dismiss-btn');
  const fillEl = $('history-summary-task-fill');
  const safeTotal = Math.max(1, Number(total || 1));
  const safeCurrent = Math.max(0, Math.min(Number(current || 0), safeTotal));
  const pct = ((safeCurrent / safeTotal) * 100).toFixed(1);
  if (panel) panel.style.display = 'block';
  if (titleEl) titleEl.textContent = title;
  if (counterEl) counterEl.textContent = `${safeCurrent} / ${safeTotal}`;
  if (detailEl) detailEl.textContent = detail || '';
  if (spinnerEl) spinnerEl.style.display = spinning ? 'inline-block' : 'none';
  if (dismissBtn) dismissBtn.style.display = allowDismiss ? 'inline-block' : 'none';
  if (fillEl) fillEl.style.width = `${pct}%`;
}

function completeHistorySummaryTaskProgress({
  title = '✅ 历史摘要已完成',
  current = 1,
  total = 1,
  detail = '',
  autoHideMs = 8000,
} = {}) {
  setHistorySummaryTaskProgress({
    title,
    current,
    total,
    detail,
    spinning: false,
    allowDismiss: true,
  });
  _historySummaryTaskAutoHideTimer = setTimeout(dismissHistorySummaryTaskProgress, autoHideMs);
}

function failHistorySummaryTaskProgress({
  title = '❌ 历史摘要生成失败',
  current = 0,
  total = 1,
  detail = '',
} = {}) {
  setHistorySummaryTaskProgress({
    title,
    current,
    total,
    detail,
    spinning: false,
    allowDismiss: true,
  });
}

function getHistoryReportModeLabel(report = {}) {
  const summaryType = String(report.summary_type || report.compare_mode || '').trim();
  return {
    model: '模型对比',
    prompt: '提示词对比',
    mixed: '混合对比',
    model_summary: '模型评分摘要',
    prompt_summary: '提示词评分摘要',
    role_summary: '角色评分摘要',
    mode_summary: '模式评分摘要',
    matrix_summary: '实验矩阵评分摘要',
    mixed_summary: '混合样本盘点',
    single_combination: '单组合评分摘要',
  }[summaryType] || '历史评分报告';
}

function closeHistoryCompareReport() {
  state.compareReportId = '';
  const panel = $('history-report-panel');
  if (panel) panel.style.display = 'none';
  if ($('history-report-content')) $('history-report-content').innerHTML = '';
  if ($('history-report-meta')) $('history-report-meta').textContent = '';
  if ($('history-report-title')) $('history-report-title').textContent = '📊 历史对比报告';
}

function getConversationDisplayLabel(conversation) {
  const role = getHistoryRoleLabel(conversation);
  const model = getHistoryModelLabel(conversation);
  const prompt = getHistoryPromptLabel(conversation);
  const compareMode = conversation.compare_mode || '';
  if (compareMode === 'prompt') return `${role} · ${prompt || '未命名提示词'}`;
  if (compareMode === 'model') return `${role} · ${model || '未命名模型'}`;
  return `${role} · ${model || prompt || '未命名记录'}`;
}

async function fetchConversationScoreResults(convId) {
  const response = await fetch(`/api/scoring/${convId}/results`);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || response.statusText || '读取评分结果失败');
  return data;
}

function getConversationScoringActionMeta(scoreData = {}, { forceFullRescore = false } = {}) {
  if (forceFullRescore) {
    return {
      action: 'rescore_all',
      label: '重新全部打分',
      progressText: '正在重新对整段会话评分...',
      startedText: '已触发全量重打分',
    };
  }
  const summary = scoreData?.summary || {};
  const meta = scoreData?.meta || {};
  const action = String(
    summary.recommended_action
    || meta.recommended_action
    || scoreData?.action?.recommended_action
    || ''
  ).trim().toLowerCase();
  const mapping = {
    start_scoring: {
      action: 'start_scoring',
      label: '开始打分',
      progressText: '正在开始评分...',
      startedText: '已开始评分',
    },
    retry_failed_turns: {
      action: 'retry_failed_turns',
      label: '重试失败项',
      progressText: '正在重试失败/未完成轮次...',
      startedText: '已发起失败/未完成轮次重试',
    },
    rescore_all: {
      action: 'rescore_all',
      label: '重新全部打分',
      progressText: '正在重新对整段会话评分...',
      startedText: '已触发全量重打分',
    },
    repair_summary: {
      action: 'repair_summary',
      label: '汇总评分',
      progressText: '正在汇总评分并生成报告...',
      startedText: '正在汇总评分并生成报告',
    },
    resume_sync: {
      action: 'resume_sync',
      label: '继续同步',
      progressText: '后台处理中，正在继续同步结果...',
      startedText: '正在继续同步评分结果',
    },
    view_results: {
      action: 'view_results',
      label: '查看结果',
      progressText: '正在刷新评分结果...',
      startedText: '当前会话已有可用评分结果',
    },
  };
  if (mapping[action]) return mapping[action];

  const total = Number(summary.total_count || 0);
  const scored = Number(summary.scored_count || 0);
  const failed = Number(summary.failed_count || 0);
  const skipped = Number(summary.skipped_count || 0);
  const pending = Math.max(0, total - scored - failed - skipped);
  if (pending > 0 && scored > 0) return mapping.retry_failed_turns;
  if (pending > 0 && failed > 0) return mapping.rescore_all;
  if (pending > 0) return mapping.start_scoring;
  if (scored > 0) return mapping.view_results;
  return mapping.start_scoring;
}

async function runConversationScoringAction(convId, action, { preferLatestPrompt = true } = {}) {
  const normalizedAction = String(action || 'start_scoring').trim().toLowerCase();
  if (normalizedAction === 'view_results') {
    return { status: 'already_scored', conversation_id: convId };
  }
  const requestInit = {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
  };
  if (normalizedAction !== 'resume_sync') {
    requestInit.body = JSON.stringify(buildScoringRuntimeRequest({ preferLatestPrompt }));
  }
  const url = {
    start_scoring: `/api/scoring/${convId}`,
    retry_failed_turns: `/api/scoring/${convId}/retry-failed-turns`,
    rescore_all: `/api/scoring/${convId}/rescore-all`,
    repair_summary: `/api/scoring/${convId}/repair-summary`,
    resume_sync: `/api/scoring/${convId}/resume-sync`,
  }[normalizedAction] || `/api/scoring/${convId}`;
  const response = await fetch(url, requestInit);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || response.statusText || '触发评分失败');
  }
  return data;
}

function isConversationScoringComplete(scoreData) {
  const summary = scoreData?.summary || {};
  const totalCount = Number(summary.total_count || 0);
  const doneCount = Number(summary.scored_count || 0)
    + Number(summary.failed_count || 0)
    + Number(summary.skipped_count || 0);
  return totalCount > 0 && doneCount >= totalCount;
}

function updateHistoryRowScore(conversationId, avgTotal, summary = {}, reportMeta = {}) {
  const items = Array.isArray(state.historyItems) ? state.historyItems : [];
  const target = items.find(item => String(item.id || item.conversation_id || '') === String(conversationId || ''));
  if (target) {
    if (Number.isFinite(avgTotal)) target.score_avg = avgTotal;
    if (summary && typeof summary === 'object') {
      if (summary.scored_count !== undefined) target.scored_turns = Number(summary.scored_count || 0);
      if (summary.failed_count !== undefined) target.failed_turns = Number(summary.failed_count || 0);
      if (summary.skipped_count !== undefined) target.skipped_turns = Number(summary.skipped_count || 0);
    }
    if (reportMeta && typeof reportMeta === 'object') {
      if (reportMeta.ai_report_status !== undefined) target.ai_report_status = String(reportMeta.ai_report_status || '');
      if (reportMeta.ai_report_label !== undefined) target.ai_report_label = String(reportMeta.ai_report_label || '');
      if (reportMeta.ai_report_ready !== undefined) target.ai_report_ready = !!reportMeta.ai_report_ready;
      if (reportMeta.ai_report_updated_at !== undefined) target.ai_report_updated_at = String(reportMeta.ai_report_updated_at || '');
      if (reportMeta.ai_report_event !== undefined) target.ai_report_event = String(reportMeta.ai_report_event || '');
      if (reportMeta.ai_report_count !== undefined) target.ai_report_count = Number(reportMeta.ai_report_count || 0);
    }
  }
  renderHistory(filterHistoryItems(items));
}

function updateSidebarScore(conversationId, avgTotal, summary = {}) {
  const items = Array.isArray(state.historyItems) ? state.historyItems : [];
  const target = items.find(item => String(item.id || item.conversation_id || '') === String(conversationId || ''));
  if (target) {
    if (Number.isFinite(avgTotal)) target.score_avg = avgTotal;
    if (summary && typeof summary === 'object') {
      if (summary.scored_count !== undefined) target.scored_turns = Number(summary.scored_count || 0);
      if (summary.failed_count !== undefined) target.failed_turns = Number(summary.failed_count || 0);
      if (summary.skipped_count !== undefined) target.skipped_turns = Number(summary.skipped_count || 0);
    }
  }
  renderSidebarHistory(items);
}

function setConversationAiReportState(conversationId, status, extra = {}) {
  const items = Array.isArray(state.historyItems) ? state.historyItems : [];
  const target = items.find(item => String(item.id || item.conversation_id || '') === String(conversationId || ''));
  if (!target) return;
  if (status !== undefined) target.ai_report_status = String(status || '').trim();
  if (extra && typeof extra === 'object') {
    Object.entries(extra).forEach(([key, value]) => {
      target[key] = value;
    });
  }
  if (status === 'ready') {
    target.ai_report_ready = true;
    target.ai_report_count = Math.max(1, Number(target.ai_report_count || 0));
  } else if (status && status !== 'ready') {
    target.ai_report_ready = false;
    if (extra.ai_report_count === undefined) target.ai_report_count = 0;
  }
  renderHistory(filterHistoryItems(items));
}

function updateScoringModalSummary(data = {}) {
  const conversationId = String(data.conversation_id || '').trim();
  if (!conversationId || conversationId !== String(state.convId || '')) return;
  if (_scoringModalRefreshTimer) clearTimeout(_scoringModalRefreshTimer);
  _scoringModalRefreshTimer = setTimeout(() => {
    syncScoreResults()
      .then(() => {
        refreshScoreSummary();
        renderRadarChart();
        renderScoreTrend();
      })
      .catch(err => console.warn('实时刷新打分弹窗失败:', err))
      .finally(() => {
        _scoringModalRefreshTimer = null;
      });
  }, 120);
}

function showRetryBadge(turn, attempt, maxRetries) {
  const badge = $('scoring-failed-badge');
  if (!badge) return;
  badge.style.display = 'inline';
  badge.textContent = `Turn ${turn} 重试 ${attempt}/${maxRetries}`;
  badge.title = '打分自动重试中';
}

function applyLiveScoreUpdate(data = {}) {
  const conversationId = String(data.conversation_id || '').trim();
  const summary = data.summary || {};
  const avgTotal = Number(data.avg_total ?? summary.avg_total);
  const reportMeta = {
    ai_report_status: data.report_status || data.report_meta?.ai_report_status || summary.report_status || '',
    ai_report_label: data.report_label || data.report_meta?.ai_report_label || summary.report_label || '',
    ai_report_ready: data.report_ready ?? data.report_meta?.ai_report_ready ?? summary.report_ready,
    ai_report_updated_at: data.report_updated_at || data.report_meta?.ai_report_updated_at || summary.report_updated_at || '',
    ai_report_event: data.report_event || data.report_meta?.ai_report_event || '',
    ai_report_count: data.report_meta?.ai_report_count,
  };
  if (conversationId && conversationId === String(state.convId || '').trim()) {
    state.scoreSummary = {
      ...(state.scoreSummary || {}),
      ...summary,
      report_status: reportMeta.ai_report_status || summary.report_status || '',
      report_label: reportMeta.ai_report_label || summary.report_label || '',
      report_ready: reportMeta.ai_report_ready ?? summary.report_ready ?? false,
      report_updated_at: reportMeta.ai_report_updated_at || summary.report_updated_at || '',
    };
    if (Number.isFinite(avgTotal)) {
      state.scoreSummary.avg_total = avgTotal;
    }
    refreshScoreSummary();
  }
  if (conversationId) {
    updateHistoryRowScore(conversationId, avgTotal, summary, reportMeta);
    updateSidebarScore(conversationId, avgTotal, summary);
  }
  updateScoringModalSummary({ ...data, conversation_id: conversationId });
}

function watchConversationScoreRefresh(convId, { timeoutMs = 120000, intervalMs = 1200, allowDelayed = false } = {}) {
  const conversationId = String(convId || '').trim();
  if (!conversationId) return Promise.resolve(null);
  if (_scoreResultWatchers.has(conversationId)) {
    return _scoreResultWatchers.get(conversationId);
  }
  const task = (async () => {
    const deadline = Date.now() + timeoutMs;
    let latest = null;
    while (Date.now() < deadline) {
      latest = await fetchConversationScoreResults(conversationId);
      applyLiveScoreUpdate({
        conversation_id: conversationId,
        summary: latest?.summary || {},
        avg_total: latest?.summary?.avg_total,
      });
      if (isConversationScoringComplete(latest)) {
        return latest;
      }
      await delay(intervalMs);
    }
    if (allowDelayed) {
      const scoringActive = !!(
        latest?.summary?.scoring_active
        || latest?.meta?.scoring_active
        || latest?.action?.scoring_active
      );
      if (scoringActive) {
        return { ...(latest || {}), _sync_delayed: true };
      }
    }
    throw new Error(`对话 ${conversationId} 评分同步超时`);
  })().finally(() => {
    _scoreResultWatchers.delete(conversationId);
  });
  _scoreResultWatchers.set(conversationId, task);
  return task;
}

async function ensureConversationScored(convId, { skipTrigger = false, preferLatestPrompt = true } = {}) {
  const current = await fetchConversationScoreResults(convId);
  if (
    isConversationScoringComplete(current)
    && (
      Number(current?.summary?.scored_count || 0) > 0
      || Number(current?.summary?.skipped_count || 0) > 0
    )
  ) {
    return current;
  }
  if (!skipTrigger) {
    const trigger = await fetch(`/api/scoring/${convId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(buildScoringRuntimeRequest({ preferLatestPrompt })),
    });
    const triggerData = await trigger.json().catch(() => ({}));
    if (!trigger.ok) {
      throw new Error(triggerData.detail || trigger.statusText || '触发评分失败');
    }
    if (triggerData.status === 'already_scored') {
      return {
        ...current,
        conversation_id: triggerData.conversation_id || current?.conversation_id || convId,
        summary: triggerData.summary || current?.summary || {},
      };
    }
  }
  const deadline = Date.now() + 120000;
  let latest = current;
  while (Date.now() < deadline) {
    await delay(1500);
    latest = await fetchConversationScoreResults(convId);
    if (isConversationScoringComplete(latest)) {
      if (
        Number(latest?.summary?.scored_count || 0) <= 0
        && Number(latest?.summary?.skipped_count || 0) <= 0
      ) {
        throw new Error(`对话 ${convId} 未产生可用评分结果`);
      }
      return latest;
    }
  }
  throw new Error(`对话 ${convId} 评分超时`);
}

function renderCompareReportView(report) {
  const panel = $('history-report-panel');
  const titleEl = $('history-report-title');
  const meta = $('history-report-meta');
  const content = $('history-report-content');
  if (!panel || !meta || !content) return;
  const reportMode = getHistoryReportModeLabel(report);
  const reportTitle = String(report.report_title || '').trim() || reportMode;
  const reportMeta = report.report_meta || {};
  const dimensionNames = {
    persona_fidelity: '人设一致性',
    narrative_immersion: '叙事沉浸度',
    emotional_tension: '情感张力',
    boundary_memory: '关系边界与记忆',
    format_compliance: '格式合规',
    context_coherence: '上下文衔接度',
    total: '总分',
  };
  const groupCards = (report.group_results || []).map(group => `
    <div style="padding:14px;border:1px solid var(--border-light);border-radius:12px;background:var(--bg-hover)">
      <div style="font-size:14px;font-weight:600;margin-bottom:8px">${escapeHtml(group.label || group.conv_id || '')}</div>
      <div style="font-size:12px;color:var(--text-secondary);display:grid;gap:4px">
        <div>模型: ${escapeHtml(group.model_id || '-')}</div>
        <div>提示词: ${escapeHtml(group.prompt_version || '-')}</div>
        <div>轮次: ${group.turn_count || 0}</div>
        <div>已评分: ${group.scored_count || 0}</div>
        <div>失败/未完成: ${group.failed_count || 0} / ${group.pending_count || 0}</div>
        <div>Token: ${(group.total_input_tokens || 0) + (group.total_output_tokens || 0)}</div>
        <div>平均延迟: ${Number(group.avg_latency_s || 0).toFixed(2)}s</div>
      </div>
      ${group.conv_id ? `<button class="btn btn-secondary" style="margin-top:10px;width:100%;justify-content:center" onclick="viewConversation('${group.conv_id}')">查看原对话</button>` : ''}
    </div>
  `).join('');
  const perDimRows = Object.entries(report.per_dim_comparison || {}).map(([dimension, item]) => {
    const scores = Object.entries(item.scores || {}).map(([label, score]) => `
      <span class="meta-chip">${escapeHtml(label)}: ${Number(score || 0).toFixed(2)}</span>
    `).join('');
    const winner = Array.isArray(item.winner) ? item.winner.join(' / ') : item.winner || '—';
    return `
      <div style="padding:12px;border:1px solid var(--border-light);border-radius:10px;background:var(--bg-hover)">
        <div style="display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;margin-bottom:8px">
          <strong>${escapeHtml(dimensionNames[dimension] || dimension)}</strong>
          <span style="font-size:12px;color:var(--text-secondary)">最佳: ${escapeHtml(winner)}</span>
        </div>
        <div style="display:flex;gap:8px;flex-wrap:wrap">${scores}</div>
      </div>
    `;
  }).join('');
  const perTurnRows = (report.per_turn_comparison || []).map(row => {
    const winners = (row.winners || []).length ? row.winners.join(' / ') : '—';
    const cards = (row.groups || []).map(group => `
      <div style="padding:12px;border-radius:10px;border:1px solid var(--border-light);background:var(--bg-surface)">
        <div style="display:flex;justify-content:space-between;gap:8px;align-items:center;margin-bottom:6px">
          <strong>${escapeHtml(group.label || '')}</strong>
          <span style="font-size:12px;color:var(--text-secondary)">${group.status === 'scored' ? `${Number(group.total || 0).toFixed(2)} 分` : escapeHtml(group.status || 'missing')}</span>
        </div>
        <div style="font-size:12px;color:var(--text-secondary)">模型: ${escapeHtml(group.model_id || '-')}</div>
        <div style="font-size:12px;color:var(--text-secondary)">提示词: ${escapeHtml(group.prompt_version || '-')}</div>
      </div>
    `).join('');
    return `
      <div style="padding:14px;border:1px solid var(--border-light);border-radius:12px;margin-top:12px">
        <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:10px">
          <strong>Turn ${row.turn}</strong>
          <span style="font-size:12px;color:var(--text-secondary)">本轮胜出: ${escapeHtml(winners)}</span>
        </div>
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px">${cards}</div>
      </div>
    `;
  }).join('');
  state.compareReportId = report.id || '';
  if (titleEl) titleEl.textContent = `📊 ${reportTitle}`;
  meta.textContent = [
    reportMode,
    `${report.group_results?.length || 0} 组`,
    reportMeta.role_count ? `角色 ${reportMeta.role_count}` : '',
    reportMeta.model_count ? `模型 ${reportMeta.model_count}` : '',
    reportMeta.prompt_count ? `提示词 ${reportMeta.prompt_count}` : '',
    `报告 ID: ${report.id || '-'}`,
  ].filter(Boolean).join(' · ');
  if ($('history-report-ai-summary-btn')) {
    $('history-report-ai-summary-btn').textContent = report.summary_type && report.summary_type !== 'model' && report.summary_type !== 'prompt'
      ? '🤖 AI 摘要分析'
      : '🤖 AI 对比分析';
  }
  content.innerHTML = `
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;margin-bottom:16px">${groupCards}</div>
    <div style="font-weight:600;margin-bottom:10px">维度汇总</div>
    <div style="display:grid;gap:10px">${perDimRows}</div>
    <div style="font-weight:600;margin:18px 0 10px">逐轮对比</div>
    <div>${perTurnRows || '<div style="font-size:12px;color:var(--text-secondary)">暂无逐轮数据</div>'}</div>
  `;
  panel.style.display = 'block';
  panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

async function openCompareReportOnHistoryPage(report, selectedIds = []) {
  state.historyCompareSelection = [...selectedIds];
  switchPage('history');
  await loadHistory();
  renderCompareReportView(report);
}

async function exportSelectedHistoryConversations() {
  const selectedIds = getSelectedHistoryConversationIds();
  if (!selectedIds.length) {
    showToast('请先勾选要导出的历史记录', 'warning');
    return;
  }
  const actionBtn = $('history-export-selected-btn');
  const originalText = actionBtn ? actionBtn.textContent : '';
  try {
    if (actionBtn) {
      actionBtn.disabled = true;
      actionBtn.textContent = `导出中 ${selectedIds.length} 条...`;
    }
    const url = `/api/scoring/multi-model/export?conv_ids=${encodeURIComponent(selectedIds.join(','))}&summary=false`;
    const response = await fetch(url);
    if (!response.ok) throw new Error(await readResponseErrorDetail(response, '批量导出失败'));
    await assertExcelDownloadResponse(response, '批量导出失败');
    const filename = resolveDownloadFilenameFromHeaders(response.headers, `history_export_${selectedIds.length}.xlsx`);
    const blob = await response.blob();
    const objectUrl = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = objectUrl;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(objectUrl);
    showToast(`已导出 ${selectedIds.length} 条历史记录`, 'success');
  } catch (error) {
    showToast(`批量导出失败: ${error?.message || error}`, 'error');
  } finally {
    if (actionBtn) {
      actionBtn.disabled = false;
      actionBtn.textContent = originalText || '批量导出选中记录';
    }
    updateHistoryCompareActions();
  }
}

async function createHistorySelectionReportFromConversationIds(ids) {
  const selectedIds = [...new Set((ids || []).filter(Boolean))];
  if (selectedIds.length < 2) {
    throw new Error('至少选择 2 条历史记录');
  }
  if (selectedIds.length > 24) {
    throw new Error('评分摘要最多支持 24 条历史记录');
  }
  const response = await fetch('/api/reports/history-selection', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ conversation_ids: selectedIds }),
  });
  const report = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(report.detail || response.statusText || '生成评分摘要失败');
  }
  return report;
}

async function createCompareReportFromConversationIds(ids, labelsById = {}) {
  const selectedIds = [...new Set((ids || []).filter(Boolean))];
  if (selectedIds.length < 2 || selectedIds.length > 3) {
    throw new Error('历史对比仅支持 2-3 条记录');
  }
  const selectedConversations = await Promise.all(selectedIds.map(async (id) => {
    const cached = (state.historyItems || []).find(item => (item.id || item.conversation_id) === id);
    if (cached) return cached;
    const response = await fetch(`/api/conversations/${id}`);
    const detail = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(detail.detail || response.statusText || `读取对话 ${id} 失败`);
    return detail;
  }));
  if (selectedConversations.some(item => !item)) {
    throw new Error('存在无效的历史记录，无法生成报告');
  }
  if (selectedConversations.some(item => item.status !== 'completed')) {
    throw new Error('仅支持已完成记录生成历史对比报告');
  }
  for (const convId of selectedIds) {
    await ensureConversationScored(convId);
  }
  const groups = selectedConversations.map(item => {
    const convId = item.id || item.conversation_id;
    return {
      conv_id: convId,
      label: labelsById[convId] || getConversationDisplayLabel(item),
      model_id: item.model || item.model_id || item.model_pro || '',
      prompt_version: item.prompt_version || item.prompt_file || '',
    };
  });
  const response = await fetch('/api/reports/compare', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ groups }),
  });
  const report = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(report.detail || response.statusText || '生成对比报告失败');
  }
  return report;
}

async function startHistorySelectionSummaryFromSelection() {
  const selectedIds = getSelectedHistoryConversationIds();
  const selectedConversations = getSelectedHistoryConversations();
  const context = getHistorySelectionSummaryContext(selectedConversations);
  if (selectedIds.length < 2) {
    showToast('请选择至少 2 条历史记录', 'warning');
    return;
  }
  if (selectedIds.length > 24) {
    showToast('评分摘要最多支持 24 条历史记录', 'warning');
    return;
  }
  const confirmed = await openActionConfirmDialog({
    title: `确认生成${context.reportTitle}`,
    message: `确定基于选中的 ${selectedIds.length} 条历史记录生成${context.reportTitle}吗？`,
    note: `${context.helperText} 系统会先核查评分完整性；缺分时才会自动补评分，然后生成结构化报告和 AI 摘要。`,
    confirmText: '确认生成',
  });
  if (!confirmed) return;

  const totalSteps = selectedIds.length + 3;
  let finishedSteps = 0;
  const actionBtn = $('history-summary-selected-btn');
  const originalText = actionBtn ? actionBtn.textContent : '';
  try {
    await requestTaskNotificationPermission();
    if (actionBtn) {
      actionBtn.disabled = true;
      actionBtn.textContent = `生成中 0/${totalSteps}`;
    }
    setHistorySummaryTaskProgress({
      title: `🧠 ${context.reportTitle}生成中`,
      current: finishedSteps,
      total: totalSteps,
      detail: '正在核查已选历史记录的评分状态',
      spinning: true,
      allowDismiss: false,
    });

    for (const conversation of selectedConversations) {
      const convId = conversation.id || conversation.conversation_id;
      const label = getConversationDisplayLabel(conversation);
      setHistorySummaryTaskProgress({
        title: `🧠 ${context.reportTitle}生成中`,
        current: finishedSteps,
        total: totalSteps,
        detail: `正在核查 ${label} 的评分数据`,
        spinning: true,
        allowDismiss: false,
      });
      await ensureConversationScored(convId);
      finishedSteps += 1;
      if (actionBtn) actionBtn.textContent = `生成中 ${finishedSteps}/${totalSteps}`;
      setHistorySummaryTaskProgress({
        title: `🧠 ${context.reportTitle}生成中`,
        current: finishedSteps,
        total: totalSteps,
        detail: `${label} 评分状态已就绪`,
        spinning: true,
        allowDismiss: false,
      });
    }

    setHistorySummaryTaskProgress({
      title: `🧠 ${context.reportTitle}生成中`,
      current: finishedSteps,
      total: totalSteps,
      detail: '正在创建结构化评分报告',
      spinning: true,
      allowDismiss: false,
    });
    const report = await createHistorySelectionReportFromConversationIds(selectedIds);
    finishedSteps += 1;
    if (actionBtn) actionBtn.textContent = `生成中 ${finishedSteps}/${totalSteps}`;

    setHistorySummaryTaskProgress({
      title: `🧠 ${context.reportTitle}生成中`,
      current: finishedSteps,
      total: totalSteps,
      detail: '正在同步历史页并展示结构化报告',
      spinning: true,
      allowDismiss: false,
    });
    await openCompareReportOnHistoryPage(report, selectedIds);
    finishedSteps += 1;
    if (actionBtn) actionBtn.textContent = `生成中 ${finishedSteps}/${totalSteps}`;

    setHistorySummaryTaskProgress({
      title: `🧠 ${context.reportTitle}生成中`,
      current: finishedSteps,
      total: totalSteps,
      detail: '正在生成 AI 评分摘要',
      spinning: true,
      allowDismiss: false,
    });
    const aiSummary = await fetchCompareAiSummary(report.id);
    finishedSteps += 1;
    openAiSummaryModal(`🤖 ${report.report_title || context.reportTitle}`);
    renderAiSummaryMarkdown(aiSummary);

    const completionMessage = `${context.reportTitle}已完成，共处理 ${selectedIds.length} 条历史记录`;
    completeHistorySummaryTaskProgress({
      title: `✅ ${context.reportTitle}已完成`,
      current: finishedSteps,
      total: totalSteps,
      detail: completionMessage,
    });
    showToast(completionMessage, 'success');
    void notifyTaskCompletion(`${context.reportTitle}已完成`, {
      body: completionMessage,
    });
  } catch (error) {
    failHistorySummaryTaskProgress({
      title: `❌ ${context.reportTitle}生成失败`,
      current: finishedSteps,
      total: totalSteps,
      detail: error?.message || '未知错误',
    });
    showToast(`${context.reportTitle}失败: ${error?.message || error}`, 'error');
    void notifyTaskCompletion(`${context.reportTitle}失败`, {
      body: error?.message || '未知错误',
    });
  } finally {
    if (actionBtn) {
      actionBtn.disabled = false;
      actionBtn.textContent = originalText || '🧠 生成评分摘要';
    }
    updateHistoryCompareActions();
  }
}

async function startHistoryCompareFromSelection() {
  const selectedIds = getSelectedHistoryConversationIds();
  if (selectedIds.length < 2 || selectedIds.length > 3) {
    showToast('请选择 2-3 条历史记录', 'warning');
    return;
  }
  const confirmed = await openActionConfirmDialog({
    title: '确认生成历史对比分析',
    message: `确定对选中的 ${selectedIds.length} 条历史记录生成对比分析吗？`,
    note: '系统会先校验评分完整性；必要时自动补评分，再生成历史对比报告。',
    confirmText: '确认生成',
  });
  if (!confirmed) return;
  try {
    await requestTaskNotificationPermission();
    const report = await createCompareReportFromConversationIds(selectedIds);
    await openCompareReportOnHistoryPage(report, selectedIds);
    showToast('历史对比报告已生成', 'success');
    void notifyTaskCompletion('历史对比报告已完成', {
      body: `共生成 ${selectedIds.length} 条记录的对比报告`,
    });
  } catch (e) {
    showToast('历史对比失败: ' + e.message, 'error');
    void notifyTaskCompletion('历史对比报告失败', {
      body: e.message || '未知错误',
    });
  }
}

function renderHistory(convs) {
  syncHistoryCompareSelection();
  const hasAnyHistory = Array.isArray(state.historyItems) && state.historyItems.length > 0;
  if (!hasAnyHistory) {
    $('history-empty').style.display = 'block';
    $('history-content').style.display = 'none';
    closeHistoryCompareReport();
    updateHistoryCompareActions();
    renderSidebarHistory([]);
    return;
  }
  $('history-empty').style.display = 'none';
  $('history-content').style.display = 'block';
  const tbody = $('history-tbody'); tbody.innerHTML = '';
  if (convs.length === 0) {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td colspan="9" style="text-align:center;color:var(--text-tertiary);padding:24px">没有符合当前筛选条件的记录</td>`;
    tbody.appendChild(tr);
  }
  convs.forEach(c => {
    const tr = document.createElement('tr');
    const convId = c.id || c.conversation_id;
    tr.dataset.convId = convId;
    const rawStatus = c.status || 'completed';
    const promptLabel = getHistoryPromptLabel(c);
    const roleLabel = getHistoryRoleLabel(c);
    const modelLabel = getHistoryModelLabel(c);
    const checked = (state.historyCompareSelection || []).includes(convId);
    const stats = getHistoryScoringStats(c);
    const scoredTurns = stats.scoredTurns;
    const failedTurns = stats.failedTurns;
    const skippedTurns = stats.skippedTurns;
    const doneTurns = stats.doneTurns;
    const totalTurns = stats.totalTurns;
    const scoringComplete = stats.scoringComplete;
    const completedTurns = c.completed_turns ?? c.total_turns ?? 0;
    const reportMeta = getHistoryAiReportMeta(c);

    // 状态派生：生成成功但标记 failed（打分中断/异常）→ 显示「已完成·打分失败」
    let status = rawStatus;
    let statusLabel = getConversationStatusLabel(rawStatus);
    let statusCls = 'status-' + rawStatus;
    if (rawStatus === 'failed' && completedTurns > 0 && completedTurns >= totalTurns) {
      statusLabel = '已完成·打分失败';
      statusCls = 'status-scoring-failed';
      status = 'scoring_failed';
    }

    let scoreLabel = '-';
    let scoreColor = 'var(--text-tertiary)';
    let scoreTitle = '';
    let scoreSubLabel = '';
    const scoreAvg = Number.parseFloat(c.score_avg);
    if (Number.isFinite(scoreAvg)) {
      scoreLabel = scoreAvg.toFixed(1);
      scoreColor = scoreAvg >= 7 ? 'var(--success-color)' : scoreAvg >= 5 ? 'var(--warning-color)' : 'var(--text-tertiary)';
    }
    if (totalTurns > 0) {
      if (scoredTurns > 0 || failedTurns > 0 || skippedTurns > 0) {
        const parts = [`已评分 ${scoredTurns}/${totalTurns}`];
        if (failedTurns > 0) parts.push(`失败 ${failedTurns}`);
        if (skippedTurns > 0) parts.push(`跳过 ${skippedTurns}`);
        scoreSubLabel = parts.join(' · ');
      } else if (rawStatus === 'completed') {
        scoreSubLabel = '尚未发起评分';
      }
    }
    if (scoreSubLabel) {
      scoreTitle = scoreSubLabel;
    }
    if (Number.isFinite(scoreAvg) && scoreAvg < getActiveLowScoreThreshold()) {
      tr.classList.add('low-score-history');
    }
    // 行级批量打分状态
    const rescoreStatus = _batchRescoreRowStatus.get(convId);
    if (rescoreStatus === 'scoring') tr.classList.add('history-row-scoring');
    else if (rescoreStatus === 'success') tr.classList.add('history-row-score-done');
    else if (rescoreStatus === 'failed') tr.classList.add('history-row-score-fail');
    let scoreMainHtml = `<div class="history-score-main" style="color:${scoreColor}">${escapeHtml(scoreLabel)}</div>`;
    if (rescoreStatus === 'failed') {
      scoreMainHtml = '<div class="history-score-main history-score-main-danger">✗ 失败</div>';
      scoreSubLabel = '本次重打分失败';
    } else if (rescoreStatus === 'scoring' && !Number.isFinite(scoreAvg)) {
      scoreMainHtml = '<span class="score-chip-scoring">打分中…</span>';
      scoreSubLabel = totalTurns > 0 ? `已评分 ${scoredTurns}/${totalTurns}` : '评分进行中';
    } else if (!Number.isFinite(scoreAvg) && rawStatus === 'completed' && totalTurns > 0) {
      scoreMainHtml = '<span class="score-chip-unscored">待打分</span>';
    }
    const scoreSubHtml = scoreSubLabel
      ? `<div class="history-score-sub" title="${escapeHtml(scoreSubLabel)}">${escapeHtml(scoreSubLabel)}</div>`
      : '';
    const statusDetail = getHistoryStatusDetail(c, stats, reportMeta);
    const scoringAction = getHistoryScoringActionMeta(c, stats, reportMeta);
    const statusDetailCls = statusDetail.tone ? ` history-state-detail-${statusDetail.tone}` : '';
    const canRetryScoring = scoringAction.key !== 'view_results';
    const retryScoringTitle = scoringAction.title;
    const canResumeConversation = ['interrupted', 'cancelled'].includes(String(rawStatus || '').trim().toLowerCase());
    const canRetryReport = reportMeta.retryable && !canResumeConversation;
    const reportActionTitle = reportMeta.ready ? '查看 AI 报告' : reportMeta.label;
    if (rescoreStatus === 'scoring' && !Number.isFinite(scoreAvg)) {
      scoreTitle = scoreSubLabel;
    }
    const archiveLabel = c.archived ? '取消归档' : '归档';
    const secondaryActionHtml = canResumeConversation
      ? `<button class="btn btn-secondary" type="button" onclick="resumeConversation('${convId}')">继续执行</button>`
      : reportMeta.ready
        ? `<button class="btn btn-secondary" type="button" onclick="showScoringSummary('${convId}')" title="${escapeHtml(reportActionTitle)}">AI报告</button>`
        : `<button class="btn btn-secondary" type="button" disabled title="${escapeHtml(reportActionTitle)}">${escapeHtml(reportMeta.actionLabel)}</button>`;
    const menuButtons = [
      `<button class="btn btn-secondary" type="button" onclick="exportConversation('${convId}')">导出</button>`,
      canRetryScoring
        ? `<button class="btn btn-secondary" type="button" style="border-color:var(--warning-color,#f59e0b);color:var(--warning-color,#f59e0b)" onclick="retryFailedScoringForConv('${convId}',this)" title="${retryScoringTitle}">${escapeHtml(scoringAction.label)}</button>`
        : '',
      canRetryReport
        ? `<button class="btn btn-secondary" type="button" onclick="retryConversationAiReport('${convId}',this)">${reportMeta.status === 'failed' ? '重试报告' : '生成报告'}</button>`
        : '',
      `<button class="btn btn-secondary" type="button" onclick="toggleConversationArchive('${convId}', ${c.archived ? 'false' : 'true'})">${archiveLabel}</button>`,
      `<button class="btn btn-secondary" type="button" onclick="showConversationEvents('${convId}')">日志</button>`,
      `<button class="btn btn-danger" type="button" onclick="deleteConversation('${convId}',this)">删除</button>`,
    ].filter(Boolean).join('');
    tr.innerHTML = `
      <td class="history-select-cell"><input type="checkbox" class="history-compare-checkbox" data-conv-id="${escapeHtml(convId)}" ${checked ? 'checked' : ''}></td>
      <td class="history-time-cell">${escapeHtml(formatBeijingDateTime(c.created_at || c.timestamp || Date.now()) || '')}</td>
      <td class="history-prompt-cell" title="${escapeHtml(promptLabel)}"><div class="history-text-ellipsis">${escapeHtml(promptLabel)}</div></td>
      <td class="history-role-cell" title="${escapeHtml(roleLabel)}"><div class="history-text-ellipsis">${escapeHtml(roleLabel)}</div></td>
      <td class="history-model-cell" title="${escapeHtml(modelLabel)}"><div class="history-text-ellipsis">${escapeHtml(modelLabel)}</div></td>
      <td class="history-turns-cell">${totalTurns}</td>
      <td class="history-score-cell" title="${escapeHtml(scoreTitle || reportMeta.label)}"><div class="history-score-stack">${scoreMainHtml}${scoreSubHtml}</div></td>
      <td class="history-status-cell"><div class="history-state-stack"><span class="status-badge ${statusCls}" title="${escapeHtml(rawStatus)}">${escapeHtml(statusLabel)}</span><div class="history-state-detail${statusDetailCls}" title="${escapeHtml(statusDetail.text)}">${escapeHtml(statusDetail.text)}</div></div></td>
      <td class="history-actions-cell">
        <div class="history-row-actions">
          <button class="btn btn-secondary" type="button" onclick="viewConversation('${convId}')">查看</button>
          ${secondaryActionHtml}
          <details class="history-row-menu">
            <summary class="btn btn-secondary history-row-menu-trigger" title="更多操作" aria-label="更多操作">⋯</summary>
            <div class="history-row-menu-panel">${menuButtons}</div>
          </details>
        </div>
      </td>
    `;
    tr.querySelector('.history-compare-checkbox')?.addEventListener('change', (event) => {
      toggleHistoryCompareSelection(convId, !!event.target.checked);
    });
    tbody.appendChild(tr);
  });
  updateHistoryCompareActions();
  const allBox = $('history-select-all');
  if (allBox) {
    const visibleIds = convs.map(c => c.id || c.conversation_id).filter(Boolean);
    const sel = state.historyCompareSelection || [];
    const checkedCount = visibleIds.filter(id => sel.includes(id)).length;
    allBox.checked = visibleIds.length > 0 && checkedCount === visibleIds.length;
    allBox.indeterminate = checkedCount > 0 && checkedCount < visibleIds.length;
  }
  renderSidebarHistory(state.historyItems || []);
}

function formatConversationEventDetail(detail) {
  if (!detail || typeof detail !== 'object') return '';
  return Object.entries(detail)
    .filter(([, value]) => value !== '' && value !== null && value !== undefined)
    .map(([key, value]) => {
      if (typeof value === 'object') {
        try {
          return `${key}=${JSON.stringify(value)}`;
        } catch (_) {
          return `${key}=[object]`;
        }
      }
      return `${key}=${String(value)}`;
    })
    .join(' · ');
}

function renderConversationEvents() {
  const panel = $('history-events-panel');
  const content = $('history-events-content');
  const meta = $('history-events-meta');
  if (!panel || !content || !meta) return;
  if (!state.historyEventConvId) {
    panel.style.display = 'none';
    return;
  }
  const conversation = (state.historyItems || []).find(item => String(item.id || item.conversation_id || '') === String(state.historyEventConvId || ''));
  const label = conversation ? getConversationDisplayLabel(conversation) : state.historyEventConvId;
  meta.textContent = `${label} · ${state.historyEvents.length} 条日志`;
  if (!state.historyEvents.length) {
    content.innerHTML = '<div style="color:var(--text-tertiary)">暂无匹配日志</div>';
  } else {
    content.innerHTML = state.historyEvents.map(event => {
      const detailText = formatConversationEventDetail(event.detail);
      return `
        <div style="padding:10px 0;border-bottom:1px solid var(--border-light)">
          <div style="display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap">
            <strong>${escapeHtml(String(event.event_type || 'event'))}</strong>
            <span style="color:var(--text-tertiary)">${escapeHtml(formatBeijingDateTime(event.created_at || Date.now()) || '')}</span>
          </div>
          <div style="margin-top:4px;color:var(--text-secondary)">${escapeHtml(`${event.scope || 'generation'} · ${event.level || 'info'}`)}</div>
          ${detailText ? `<div style="margin-top:6px;color:var(--text-secondary);white-space:pre-wrap">${escapeHtml(detailText)}</div>` : ''}
        </div>
      `;
    }).join('');
  }
  panel.style.display = 'block';
}

async function refreshConversationEvents() {
  const convId = String(state.historyEventConvId || '').trim();
  if (!convId) {
    showToast('请先选择一条会话日志', 'warning');
    return;
  }
  const params = new URLSearchParams();
  const scope = getInputValue('history-events-scope').trim();
  const level = getInputValue('history-events-level').trim();
  if (scope) params.set('scope', scope);
  if (level) params.set('level', level);
  const suffix = params.toString();
  const response = await fetch(`/api/conversations/${encodeURIComponent(convId)}/events${suffix ? `?${suffix}` : ''}`);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || response.statusText || '读取执行日志失败');
  state.historyEvents = Array.isArray(data.events) ? data.events : [];
  renderConversationEvents();
}

async function showConversationEvents(convId, options = {}) {
  const normalizedConvId = String(convId || '').trim();
  if (!normalizedConvId) return;
  state.historyEventConvId = normalizedConvId;
  if ($('history-events-scope')) $('history-events-scope').value = String(options.scope || '').trim();
  if ($('history-events-level')) $('history-events-level').value = String(options.level || '').trim();
  switchPage('history');
  await loadHistory();
  try {
    await refreshConversationEvents();
    $('history-events-panel')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (e) {
    showToast('读取日志失败: ' + e.message, 'error');
  }
}

function closeConversationEvents() {
  state.historyEventConvId = '';
  state.historyEvents = [];
  if ($('history-events-panel')) $('history-events-panel').style.display = 'none';
  if ($('history-events-content')) $('history-events-content').innerHTML = '';
  if ($('history-events-meta')) $('history-events-meta').textContent = '';
}

function exportConversationEvents() {
  if (!state.historyEvents.length) {
    showToast('当前没有可导出的日志', 'warning');
    return;
  }
  const lines = state.historyEvents.map(item => JSON.stringify(item));
  const blob = new Blob([`${lines.join('\n')}\n`], { type: 'application/x-ndjson;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `conversation_events_${state.historyEventConvId || 'export'}.jsonl`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
  showToast('日志已导出', 'success');
}

async function toggleConversationArchive(id, archived) {
  try {
    const response = await fetch(`/api/conversations/${encodeURIComponent(id)}/archive?archived=${archived ? 'true' : 'false'}`, {
      method: 'PUT',
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || response.statusText || '归档操作失败');
    if (String(state.historyEventConvId || '') === String(id || '') && archived) closeConversationEvents();
    showToast(archived ? '已归档' : '已取消归档', 'success');
    await loadHistory();
  } catch (e) {
    showToast('更新归档状态失败: ' + e.message, 'error');
  }
}

function applyHistoryFilters() {
  renderHistoryWithCurrentFilters();
}

function resetHistoryFilters() {
  [
    'history-filter-role',
    'history-filter-model',
    'history-filter-prompt',
    'history-filter-status',
    'history-filter-date-from',
    'history-filter-date-to',
    'history-filter-score-min',
    'history-filter-score-max',
  ].forEach(id => { const el = $(id); if (el) el.value = ''; });
  if ($('history-filter-include-archived')) $('history-filter-include-archived').checked = false;
  setScoreQuickFilter('');
  closeConversationEvents();
  if (Array.isArray(state.historyItems) && state.historyItems.length) {
    renderHistoryWithCurrentFilters();
    return;
  }
  loadHistory().catch(err => console.warn('重置历史筛选失败:', err));
}

async function loadHistory() {
  try {
    const params = buildHistoryQueryParams();
    const suffix = params.toString();
    const r = await fetch(`/api/conversations${suffix ? `?${suffix}` : ''}`); const data = await r.json();
    state.historyItems = data.conversations || data || [];
    syncHistoryCompareSelection();
    renderHistoryWithCurrentFilters();
    refreshSPPreview();
  } catch (e) { console.warn('历史加载失败:', e); }
}

async function viewConversation(id) {
  try {
    if (state.ws) {
      try { state.ws.close(); } catch (_) { /* ignore */ }
      state.ws = null;
    }
    const r = await fetch(`/api/conversations/${id}`); const data = await r.json();
    state.convId = id; state.turns = data.turns || data.results || [];
    state.expectedTurnCount = data.total_turns || state.turns.length;
    state.scoreMeta = {
      model_id: data.model_id || '',
      prompt_version: data.prompt_version || data.prompt_file || '',
      summary_prompt_version: data.summary_prompt_version || '',
      scoring_prompt_version: data.scoring_prompt_version || '',
      scoring_model_id: data.scoring_model_id || '',
      dialogue_summary: [...(data.results || [])].reverse().find(item => item.dialogue_summary)?.dialogue_summary || '',
    };
    state.scoreData = null;
    state.chatSessionMode = 'history';
    state.interactiveConfigSignature = '';
    setActiveConversationStatus(data.status || '');
    setFormConfig(buildConversationFormConfig(data));
    syncChatHistoryFromTurns();
    state.debugData = state.turns.map(t => buildTurnDebugEntry(t, { modelId: data.model_id || '' }));
    const chatEmpty = $('chat-empty');
    if (chatEmpty) chatEmpty.style.display = 'none';
    const chatArea = $('chat-area');
    if (chatArea) chatArea.innerHTML = '';
    state.turns.forEach((t, i) => renderTurnBubbles(t, i + 1));
    void runConversationInlineScoreBackfill();
    const chatNav = $('chat-nav');
    if (chatNav) chatNav.style.display = 'flex';
    const chatProgress = $('chat-progress');
    if (chatProgress) chatProgress.style.display = 'flex';
    updateProgress(state.turns.length, state.expectedTurnCount || state.turns.length || 1);
    renderSidebarHistory(state.historyItems || []);
    switchPage('chat');
    if (['running', 'queued', 'pending'].includes(String(data.status || '').toLowerCase())) {
      connectWebSocket(id);
      showToast('已进入会话：实时跟进中', 'info');
    } else if (String(data.status || '').toLowerCase() === 'paused') {
      if ($('chat-status-text')) $('chat-status-text').textContent = '已暂停';
      showToast('已加载暂停中的会话', 'info');
    } else {
      showToast('已加载历史对话', 'info');
    }
  } catch (e) { showToast('加载对话失败: ' + e.message, 'error'); }
}

async function resumeConversation(id) {
  try {
    if (state.ws) {
      try { state.ws.close(); } catch (_) { }
      state.ws = null;
    }
    const detailResponse = await fetch(`/api/conversations/${id}`);
    const detail = await detailResponse.json().catch(() => ({}));
    if (!detailResponse.ok) throw new Error(detail.detail || '读取会话详情失败');

    state.convId = id;
    state.turns = detail.results || [];
    state.debugData = state.turns.map(t => buildTurnDebugEntry(t, { modelId: detail.model_id || '' }));
    state.scoreData = null;
    state.scoreMeta = {
      model_id: detail.model_id || '',
      prompt_version: detail.prompt_version || detail.prompt_file || '',
      summary_prompt_version: detail.summary_prompt_version || '',
      scoring_prompt_version: detail.scoring_prompt_version || '',
      scoring_model_id: detail.scoring_model_id || '',
      dialogue_summary: [...(detail.results || [])].reverse().find(item => item.dialogue_summary)?.dialogue_summary || '',
    };
    state.expectedTurnCount = detail.total_turns || (detail.results || []).length || 0;
    state.chatSessionMode = 'batch';
    state.interactiveConfigSignature = '';
    setActiveConversationStatus(detail.status || '');
    setFormConfig(buildConversationFormConfig(detail));
    const _rChatEmpty = $('chat-empty');
    if (_rChatEmpty) _rChatEmpty.style.display = 'none';
    const _rChatArea = $('chat-area');
    if (_rChatArea) _rChatArea.innerHTML = '';
    state.turns.forEach((turn, index) => renderTurnBubbles(turn, index + 1));
    void runConversationInlineScoreBackfill();
    const _rChatProgress = $('chat-progress');
    if (_rChatProgress) _rChatProgress.style.display = 'flex';
    const _rChatNav = $('chat-nav');
    if (_rChatNav) _rChatNav.style.display = 'none';
    const _rChatTyping = $('chat-typing');
    if (_rChatTyping) _rChatTyping.style.display = 'flex';
    const _rStatusText = $('chat-status-text');
    if (_rStatusText) _rStatusText.textContent = '准备恢复';
    updateProgress(Math.min(detail.next_turn_index || state.turns.length, state.expectedTurnCount || state.turns.length || 0), state.expectedTurnCount || 1);

    const response = await fetch(`/api/conversations/${id}/resume`, { method: 'POST' });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || '恢复任务失败');

    switchPage('chat');
    state.running = true;
    setActiveConversationStatus(payload.status || 'queued');
    const startBtn = $('btn-start');
    if (startBtn) {
      startBtn.disabled = true;
      startBtn.textContent = '⏳ 测试中...';
    }
    connectWebSocket(id);
    loadHistory();
    showToast(payload.status === 'queued' ? '任务已进入队列，等待继续执行' : '已恢复批量任务', 'success');
  } catch (e) {
    setActiveConversationStatus('');
    resetTestUI();
    showToast('恢复任务失败: ' + e.message, 'error');
  }
}

async function deleteConversation(id, btn) {
  if (!confirm('确定删除此对话记录?')) return;
  try {
    await fetch(`/api/conversations/${id}`, { method: 'DELETE' });
    const row = btn?.closest?.('tr');
    if (row) row.remove();
    state.historyCompareSelection = (state.historyCompareSelection || []).filter(item => item !== id);
    if (state.convId === id) {
      state.convId = null;
      state.interactiveConfigSignature = '';
      setActiveConversationStatus('');
      resetChatCanvas();
    }
    showToast('已删除', 'success'); loadHistory();
  } catch (e) { showToast('删除失败', 'error'); }
}

async function toggleConversationPin(id, pinned) {
  try {
    const r = await fetch(`/api/conversations/${id}/pin?pinned=${pinned ? 'true' : 'false'}`, {
      method: 'PUT',
    });
    if (!r.ok) throw new Error('置顶操作失败');
    showToast(pinned ? '已置顶' : '已取消置顶', 'success');
    await loadHistory();
  } catch (e) {
    showToast('更新置顶状态失败: ' + e.message, 'error');
  }
}

const EXCEL_DOWNLOAD_MIME_TYPES = [
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  'application/vnd.ms-excel',
];

function resolveDownloadFilenameFromHeaders(headers, fallbackName) {
  const headerValue = String(
    headers?.get('Content-Disposition')
    || headers?.get('content-disposition')
    || '',
  ).trim();
  if (!headerValue) return fallbackName;
  const utf8Match = headerValue.match(/filename\*\s*=\s*UTF-8''([^;]+)/i);
  if (utf8Match && utf8Match[1]) {
    try {
      return decodeURIComponent(String(utf8Match[1]).replace(/^"(.*)"$/, '$1'));
    } catch (_) {
      return String(utf8Match[1]).replace(/^"(.*)"$/, '$1');
    }
  }
  const plainMatch = headerValue.match(/filename\s*=\s*"([^"]+)"|filename\s*=\s*([^;]+)/i);
  const rawName = plainMatch ? (plainMatch[1] || plainMatch[2] || '') : '';
  return String(rawName || '').trim() || fallbackName;
}

async function readResponseErrorDetail(response, fallbackMessage) {
  const contentType = String(response?.headers?.get('content-type') || '').toLowerCase();
  if (contentType.includes('application/json')) {
    const payload = await response.json().catch(() => ({}));
    return payload.detail || payload.message || response.statusText || fallbackMessage;
  }
  const text = await response.text().catch(() => '');
  return String(text || '').trim() || response?.statusText || fallbackMessage;
}

async function assertExcelDownloadResponse(response, fallbackMessage = '导出失败') {
  const contentType = String(response?.headers?.get('content-type') || '').toLowerCase();
  const isExcel = EXCEL_DOWNLOAD_MIME_TYPES.some(type => contentType.includes(type));
  if (isExcel) return;
  const detail = await readResponseErrorDetail(response, `${fallbackMessage}：服务端未返回 Excel 文件`);
  throw new Error(detail);
}

async function exportConversation(id) {
  try {
    const opts = (typeof id === 'object' && id !== null) ? id : {};
    const cid = opts.id || (typeof id === 'string' ? id : state.convId);
    if (!cid && opts.mode !== 'compare') { showToast('无可导出的对话', 'warning'); return; }
    let downloadUrl = '';
    let fallbackFilename = `conversation_${cid}.xlsx`;
    if (opts.mode === 'scoring') {
      downloadUrl = `/api/scoring/${cid}/export${opts.summary ? '?summary=true' : ''}`;
      fallbackFilename = opts.summary ? `scoring_${cid}_summary.xlsx` : `scoring_${cid}.xlsx`;
    } else if (opts.mode === 'compare') {
      downloadUrl = `/api/reports/compare/${encodeURIComponent(opts.reportId || '')}/export${opts.summary ? '?summary=true' : ''}`;
      fallbackFilename = opts.summary ? 'compare_summary.xlsx' : 'compare_full.xlsx';
    } else {
      downloadUrl = `/api/conversations/${cid}/export`;
    }
    const r = await fetch(downloadUrl);
    if (!r.ok) throw new Error(await readResponseErrorDetail(r, '导出失败'));
    await assertExcelDownloadResponse(r, '导出失败');
    const filename = resolveDownloadFilenameFromHeaders(r.headers, fallbackFilename);
    const blob = await r.blob();
    const objectUrl = URL.createObjectURL(blob); const a = document.createElement('a');
    a.href = objectUrl;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(objectUrl);
    showToast('导出成功', 'success');
  } catch (e) { showToast('导出失败: ' + e.message, 'error'); }
}

/* ═══ 打分 ═══ */
async function triggerScoring({ forceFullRescore = false } = {}) {
  if (!state.convId) { showToast('请先运行一次对话测试', 'warning'); return; }
  await requestTaskNotificationPermission();
  showModal('modal-scoring');
  $('scoring-empty').style.display = 'none'; $('scoring-content').style.display = 'block';
  $('scoring-progress').style.display = 'block'; $('score-cards').innerHTML = '';
  state.scoreData = [];
  state.scoreSummary = null;
  renderScoringMeta();
  refreshScoreSummary();

  const convId = state.convId;
  let progressTotalTurns = Math.max(Number(state.turns?.length || 0), 1);
  const progressCount = $('scoring-progress-count');
  const progressFill = $('scoring-progress-fill');
  const progressText = $('scoring-progress-text');
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const ws = new WebSocket(`${proto}//${location.host}/api/scoring/ws/${state.convId}`);
  const seenTurns = new Set();
  let finalized = false;
  let fallbackStarted = false;
  let wsWarningShown = false;

  const setScoringProgressText = (text) => {
    if (progressText && text) progressText.textContent = text;
  };

  const updateScoringProgress = (current, total, failed = 0) => {
    const safeTotal = Math.max(Number(total || progressTotalTurns), 1);
    progressTotalTurns = safeTotal;
    const safeCurrent = Math.max(0, Math.min(Number(current || 0), safeTotal));
    const safeFailed = Math.max(0, Number(failed || 0));
    if (progressCount) progressCount.textContent = `${safeCurrent}/${safeTotal}`;
    if (progressFill) progressFill.style.width = `${(safeCurrent / safeTotal) * 100}%`;
    // 失败计数显示（scoring modal 内）
    const failedBadge = $('scoring-failed-badge');
    if (failedBadge) {
      if (safeFailed > 0) {
        failedBadge.style.display = 'inline';
        failedBadge.textContent = `失败 ${safeFailed}`;
      } else {
        failedBadge.style.display = 'none';
      }
    }
  };

  const closeScoringSocket = () => {
    if (ws.readyState <= 1) {
      try { ws.close(); } catch (_) { /* ignore */ }
    }
  };

  const applyScoreProgress = (payload) => {
    if (!payload || typeof payload !== 'object') return;
    const turnNumber = Number.parseInt(String(payload.turn || ''), 10);
    if (Number.isFinite(turnNumber) && turnNumber > 0) {
      seenTurns.add(turnNumber);
    }
    const current = Number(payload.current || 0) || seenTurns.size;
    const total = Number(payload.total || 0) || progressTotalTurns;
    const failed = Number(payload.failed_count || payload.failed || 0);
    updateScoringProgress(current, total, failed);
  };

  const finalizeScoring = async (prefetched = null, completionStatus = 'completed') => {
    if (finalized) return;
    finalized = true;
    closeScoringSocket();
    try {
      const ensured = prefetched || await fetchConversationScoreResults(convId);
      const ensuredSummary = ensured?.summary || {};
      updateScoringProgress(
        Number(ensuredSummary.scored_count || 0)
          + Number(ensuredSummary.failed_count || 0)
          + Number(ensuredSummary.skipped_count || 0),
        Number(ensuredSummary.total_count || 0) || progressTotalTurns,
        Number(ensuredSummary.failed_count || 0),
      );
      await syncScoreResults();
      $('scoring-progress').style.display = 'none';
      refreshScoreSummary();
      renderRadarChart();
      renderScoreTrend();
      const completionTitle = completionStatus === 'cancelled' ? '整段评分已取消' : '整段评分已完成';
      showToast(completionTitle, completionStatus === 'cancelled' ? 'warning' : 'success');
      void notifyTaskCompletion(completionTitle, {
        body: `会话 ${convId} 已${completionStatus === 'cancelled' ? '取消评分' : '完成评分'}`,
      });
      // 打分完成后静默预取 AI 摘要（不弹窗，后端去重锁保护）
      if (completionStatus === 'completed') {
        _prefetchedAiSummary = null;
        void _prefetchAiSummary(convId);
      }
    } catch (err) {
      $('scoring-progress').style.display = 'none';
      showToast('打分同步失败: ' + (err && err.message ? err.message : err), 'error');
      void notifyTaskCompletion('整段评分失败', {
        body: err && err.message ? err.message : String(err || '未知错误'),
      });
    }
  };

  const startFallbackSync = () => {
    if (fallbackStarted) return;
    fallbackStarted = true;
    watchConversationScoreRefresh(convId, { allowDelayed: true })
      .then(result => {
        if (result?._sync_delayed) {
          fallbackStarted = false;
          const delayedSummary = result.summary || {};
          updateScoringProgress(
            Number(delayedSummary.scored_count || 0)
              + Number(delayedSummary.failed_count || 0)
              + Number(delayedSummary.skipped_count || 0),
            Number(delayedSummary.total_count || 0) || progressTotalTurns,
            Number(delayedSummary.failed_count || 0),
          );
          setScoringProgressText('同步较慢，后台仍在处理中...');
          showToast('同步较慢，后台仍在处理中', 'info');
          return;
        }
        finalizeScoring(result);
      })
      .catch(err => {
        if (finalized) return;
        finalized = true;
        closeScoringSocket();
        $('scoring-progress').style.display = 'none';
        showToast('打分同步失败: ' + (err && err.message ? err.message : err), 'error');
      });
  };

  updateScoringProgress(0, progressTotalTurns);

  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.type === 'score_progress') {
      applyScoreProgress(msg);
    } else if (msg.type === 'turn_score' || msg.type === 'score') {
      applyScoreProgress(msg.data || msg);
    } else if (msg.type === 'retry') {
      showRetryBadge(msg.turn, msg.attempt, msg.max_retries);
    } else if (msg.type === 'score_updated') {
      applyLiveScoreUpdate(msg);
    } else if (msg.type === 'cancelled') {
      finalizeScoring(null, 'cancelled');
    } else if (msg.type === 'paused') {
      showToast('评分任务已暂停', 'info');
    } else if (msg.type === 'resumed') {
      showToast('评分任务已恢复', 'success');
    } else if (msg.type === 'report_status') {
      setConversationAiReportState(msg.conversation_id || convId, msg.report_status || '', {
        ai_report_label: msg.report_label || '',
        ai_report_ready: !!msg.report_ready,
        ai_report_updated_at: msg.report_updated_at || '',
        ai_report_event: msg.report_event || '',
      });
    } else if (msg.type === 'task_status') {
      const status = String(msg.status || '').trim().toLowerCase();
      if (msg.report_status) {
        setConversationAiReportState(msg.conversation_id || convId, msg.report_status || '', {
          ai_report_label: msg.report_label || '',
          ai_report_ready: !!msg.report_ready,
          ai_report_updated_at: msg.report_updated_at || '',
          ai_report_event: msg.report_event || '',
        });
      }
      if (status === 'cancelled') {
        finalizeScoring(null, 'cancelled');
      } else if (status === 'paused') {
        showToast('评分任务已暂停', 'info');
      }
    } else if (msg.type === 'completed' || msg.type === 'done') {
      const summary = msg.summary || {};
      updateScoringProgress(
        Number(summary.scored_count || 0)
          + Number(summary.failed_count || 0)
          + Number(summary.skipped_count || 0),
        Number(summary.total_count || 0) || progressTotalTurns,
      );
      finalizeScoring(null, 'completed');
    } else if (msg.type === 'error') {
      finalized = true;
      closeScoringSocket();
      $('scoring-progress').style.display = 'none';
      showToast('打分错误: ' + (msg.message || ''), 'error');
      void notifyTaskCompletion('整段评分失败', {
        body: msg.message || '未知错误',
      });
    }
  };
  ws.onerror = () => {
    if (!wsWarningShown) {
      wsWarningShown = true;
      showToast('实时进度连接异常，已切换轮询同步', 'warning');
    }
  };
  const existingResult = await fetchConversationScoreResults(convId).catch(() => null);
  if (existingResult) {
    applyConversationScoreResults(existingResult);
  }
  let actionMeta = getConversationScoringActionMeta(existingResult, { forceFullRescore });
  setScoringProgressText(actionMeta.progressText);

  let payload = null;
  try {
    payload = await runConversationScoringAction(convId, actionMeta.action, { preferLatestPrompt: true });
  } catch (error) {
    closeScoringSocket();
    $('scoring-progress').style.display = 'none';
    showToast(error?.message || '触发打分失败', 'error');
    return;
  }
  if (payload?.summary?.recommended_action && !forceFullRescore) {
    actionMeta = getConversationScoringActionMeta(payload);
    setScoringProgressText(actionMeta.progressText);
  }
  const triggerTurnCount = Number(payload.turns_to_score || 0);
  if (triggerTurnCount > 0) {
    updateScoringProgress(0, triggerTurnCount);
  }
  if (payload.status === 'already_scored' && actionMeta.action === 'repair_summary') {
    try {
      payload = await runConversationScoringAction(convId, 'repair_summary', { preferLatestPrompt: true });
      actionMeta = getConversationScoringActionMeta(payload);
      setScoringProgressText(actionMeta.progressText);
    } catch (error) {
      closeScoringSocket();
      $('scoring-progress').style.display = 'none';
      showToast(error?.message || '汇总评分失败', 'error');
      return;
    }
  }
  if (actionMeta.action === 'repair_summary') {
    closeScoringSocket();
    await syncScoreResults();
    $('scoring-progress').style.display = 'none';
    refreshScoreSummary();
    renderRadarChart();
    renderScoreTrend();
    if (payload?.report?.error) {
      showToast(`汇总完成，但报告生成失败: ${payload.report.error}`, 'warning');
    } else {
      showToast('汇总评分已完成', 'success');
    }
    return;
  }
  if (payload.status === 'already_scored' || actionMeta.action === 'view_results') {
    closeScoringSocket();
    await syncScoreResults();
    $('scoring-progress').style.display = 'none';
    refreshScoreSummary();
    renderRadarChart();
    renderScoreTrend();
    showToast(actionMeta.startedText, 'info');
    return;
  }
  const scoringActive = !!(
    payload?.summary?.scoring_active
    || payload?.meta?.scoring_active
    || payload?.action?.scoring_active
  );
  if (actionMeta.action === 'resume_sync' && !scoringActive) {
    closeScoringSocket();
    await syncScoreResults();
    $('scoring-progress').style.display = 'none';
    refreshScoreSummary();
    renderRadarChart();
    renderScoreTrend();
    showToast('已同步最新评分结果', 'success');
    return;
  }
  if (actionMeta.action === 'repair_summary') {
    setConversationAiReportState(convId, 'generating', {
      ai_report_label: '报告生成中',
      ai_report_ready: false,
      ai_report_count: 0,
      ai_report_updated_at: '',
    });
  } else {
    setConversationAiReportState(convId, 'waiting_scoring', {
      ai_report_label: '待评分完成',
      ai_report_ready: false,
      ai_report_count: 0,
      ai_report_updated_at: '',
    });
  }
  showToast(actionMeta.startedText, 'info');
  startFallbackSync();
}

/* ═══ 仅重试失败轮次 ═══ */
async function retryFailedScoring() {
  if (!state.convId) { showToast('请先运行一次对话测试', 'warning'); return; }

  // 从 scoreData 或服务端结果找出失败/未完成的轮次
  const retryableTurns = (state.scoreData || [])
    .map((s, idx) => ({ ...s, _idx: idx + 1 }))
    .filter(isRetryableScoringTurn);

  if (!retryableTurns.length) {
    // 没有本地缓存时从服务端拉取
    const r = await fetch(`/api/scoring/${state.convId}/results`).catch(() => null);
    if (r && r.ok) {
      const data = await r.json().catch(() => ({}));
      const serverRetryable = (data.turns || []).filter(isRetryableScoringTurn);
      if (!serverRetryable.length) { showToast('没有需要重试的失败/未完成项', 'info'); return; }
      await _retryTurnList(serverRetryable.map(t => t.turn));
    } else {
      showToast('获取打分结果失败', 'error');
    }
    return;
  }

  await _retryTurnList(retryableTurns.map(s => s._idx));
}

async function _retryTurnList(turnNumbers) {
  if (!turnNumbers.length) { showToast('没有需要重试的失败/未完成项', 'info'); return; }
  const convId = state.convId;
  const scoringPayload = buildScoringRuntimeRequest({ preferLatestPrompt: true });

  // 确保 modal 可见并显示进度
  showModal('modal-scoring');
  $('scoring-empty').style.display = 'none';
  $('scoring-content').style.display = 'block';
  $('scoring-progress').style.display = 'block';

  const progressCount = $('scoring-progress-count');
  const progressFill = $('scoring-progress-fill');
  const total = turnNumbers.length;
  let done = 0;
  let failed = 0;

  const updateProgress = () => {
    if (progressCount) progressCount.textContent = `${done}/${total}`;
    if (progressFill) progressFill.style.width = `${(done / Math.max(total, 1)) * 100}%`;
    const badge = $('scoring-failed-badge');
    if (badge) {
      badge.style.display = failed > 0 ? 'inline' : 'none';
      if (failed > 0) badge.textContent = `失败 ${failed}`;
    }
  };

  updateProgress();
  showToast(`开始重试 ${total} 个失败/未完成轮次...`, 'info');

  for (const turn of turnNumbers) {
    try {
      const r = await fetch(`/api/scoring/${convId}/turn/${turn}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(scoringPayload),
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        console.warn(`Turn ${turn} 重试失败:`, err.detail || r.statusText);
        failed++;
      }
    } catch (e) {
      console.warn(`Turn ${turn} 重试异常:`, e.message);
      failed++;
    }
    done++;
    await syncScoreResults().catch(() => null);
    updateProgress();
  }

  $('scoring-progress').style.display = 'none';
  await syncScoreResults();
  refreshScoreSummary();
  renderRadarChart();
  renderScoreTrend();

  if (failed === 0) {
    showToast(`重试完成，${total} 项均已成功`, 'success');
  } else {
    showToast(`重试完成：${total - failed} 项成功，${failed} 项仍失败`, 'warning');
  }
}

// 批量中心工具栏：跨多个 conv 重试失败的打分轮次
async function retryFailedScoringItems() {
  const convIds = (state._lastBatchConvIds || []).slice();
  if (!convIds.length) {
    showToast('当前没有可重试的批量任务，请先运行批量测试', 'warning');
    return;
  }
  const toolbarBtn = $('btn-retry-failed-scoring');
  if (toolbarBtn) { toolbarBtn.disabled = true; toolbarBtn.textContent = '🔁 检测失败/未完成轮次...'; }

  try {
    // Step 1: 并发拉取每个 conv 的打分状态，筛出 failed / unscored 轮次
    const jobs = [];
    await _mapPool(convIds, 4, async (convId) => {
      try {
        const r = await fetch(`/api/scoring/${convId}/results`);
        if (!r.ok) return;
        const data = await r.json().catch(() => ({}));
        const retryableTurns = (data.turns || []).filter(isRetryableScoringTurn).map(t => t.turn);
        if (retryableTurns.length) jobs.push({ convId, turns: retryableTurns });
      } catch (e) {
        console.warn(`[batch-retry] 拉取 ${convId} 失败:`, e.message);
      }
    });

    const totalTurns = jobs.reduce((acc, j) => acc + j.turns.length, 0);
    if (!totalTurns) {
      showToast('没有需要重试的失败/未完成打分项', 'info');
      return;
    }

    const confirmed = await openActionConfirmDialog({
      title: '确认批量重试失败/未完成打分项',
      message: `共 ${jobs.length} 个对话、${totalTurns} 个失败/未完成轮次，确定全部重打吗？`,
      note: '系统会按最新打分提示词重新补齐这些失败/未完成轮次，并在完成后重建评分摘要。',
      confirmText: '确认重试',
    });
    if (!confirmed) return;

    const progressFill = $('batch-progress-fill');
    let done = 0;
    let failCount = 0;
    const flat = jobs.flatMap(j => j.turns.map(t => ({ convId: j.convId, turn: t })));
    if (toolbarBtn) toolbarBtn.textContent = `🔁 重打分 0/${totalTurns}`;
    if (progressFill) progressFill.style.width = '0%';

    await _mapPool(flat, 3, async (item) => {
      try {
        const r = await fetch(`/api/scoring/${item.convId}/turn/${item.turn}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(buildScoringRuntimeRequest({ preferLatestPrompt: true })),
        });
        if (!r.ok) failCount++;
      } catch (e) {
        failCount++;
      }
      done++;
      if (toolbarBtn) toolbarBtn.textContent = `🔁 重打分 ${done}/${totalTurns}`;
      if (progressFill) progressFill.style.width = `${(done / totalTurns * 100).toFixed(1)}%`;
    });

    const summaryResults = await Promise.all(
      [...new Set(flat.map(item => item.convId).filter(Boolean))]
        .map(convId => regenerateConversationAiSummarySilently(convId))
    );
    const summaryFailCount = summaryResults.filter(item => !item.success).length;

    showToast(
      `批量重打分完成：${totalTurns - failCount} 成功 / ${failCount} 失败；摘要更新 ${summaryResults.length - summaryFailCount}/${summaryResults.length}`,
      failCount === 0 && summaryFailCount === 0 ? 'success' : 'warning',
    );

    // 刷新历史列表与汇总
    if (typeof loadHistory === 'function') loadHistory();
  } finally {
    if (toolbarBtn) { toolbarBtn.disabled = false; toolbarBtn.textContent = '🔁 重试失败/未完成项'; }
  }
}

// 轻量并发池：limit 并发处理 items 数组
async function _mapPool(items, limit, worker) {
  const queue = items.slice();
  const runners = Array.from({ length: Math.min(limit, queue.length) }, async () => {
    while (queue.length) {
      const item = queue.shift();
      if (item === undefined) break;
      await worker(item);
    }
  });
  await Promise.all(runners);
}

// 单 conv 级别重打分（用于历史列表每行按钮）
async function retryFailedScoringForConv(convId, btnEl) {
  if (!convId) return;
  const originalText = btnEl ? btnEl.textContent : '';
  if (btnEl) { btnEl.disabled = true; btnEl.textContent = '检测中...'; }
  try {
    const data = await fetchConversationScoreResults(convId);
    const actionMeta = getConversationScoringActionMeta(data);
    if (btnEl) btnEl.textContent = `${actionMeta.label}中...`;
    if (actionMeta.action === 'repair_summary') {
      setConversationAiReportState(convId, 'generating', {
        ai_report_label: '报告生成中',
        ai_report_ready: false,
        ai_report_count: 0,
        ai_report_updated_at: '',
      });
    } else if (actionMeta.action !== 'view_results') {
      setConversationAiReportState(convId, 'waiting_scoring', {
        ai_report_label: '待评分完成',
        ai_report_ready: false,
        ai_report_count: 0,
        ai_report_updated_at: '',
      });
    }

    const payload = await runConversationScoringAction(convId, actionMeta.action, { preferLatestPrompt: true });
    if (typeof loadHistory === 'function') await loadHistory();

    if (btnEl) btnEl.textContent = '同步中...';
    if (actionMeta.action === 'repair_summary') {
      const latest = await fetchConversationScoreResults(convId).catch(() => null);
      const avgTotal = Number(latest?.summary?.avg_total);
      if (Number.isFinite(avgTotal)) {
        showToast(`汇总评分完成，最新综合评分 ${avgTotal.toFixed(1)}`, payload?.report?.error ? 'warning' : 'success');
      } else {
        showToast(payload?.report?.error ? `汇总完成，但报告生成失败: ${payload.report.error}` : '汇总评分已完成', payload?.report?.error ? 'warning' : 'success');
      }
      return;
    }

    if (actionMeta.action === 'view_results' || payload.status === 'already_scored') {
      const latest = await fetchConversationScoreResults(convId).catch(() => null);
      const avgTotal = Number(latest?.summary?.avg_total);
      if (Number.isFinite(avgTotal)) {
        showToast(`当前综合评分 ${avgTotal.toFixed(1)}`, 'info');
      } else {
        showToast('当前会话已有可用评分结果', 'info');
      }
      return;
    }

    try {
      const latest = await watchConversationScoreRefresh(convId, { allowDelayed: true });
      if (latest?._sync_delayed) {
        showToast('同步较慢，后台仍在处理中', 'info');
        return;
      }
      const avgTotal = Number(latest?.summary?.avg_total);
      if (Number.isFinite(avgTotal)) {
        showToast(`最新综合评分 ${avgTotal.toFixed(1)}`, 'success');
      } else {
        showToast(`${actionMeta.label}已触发`, 'success');
      }
    } catch (err) {
      console.warn(`[history-rescore] ${convId} 同步刷新失败:`, err?.message || err);
      showToast(`${actionMeta.label}已触发，刷新结果时稍后重试`, 'warning');
    }
  } finally {
    if (typeof loadHistory === 'function') await loadHistory().catch(() => null);
    if (btnEl) { btnEl.disabled = false; btnEl.textContent = originalText || '重打分'; }
  }
}

// 批量中心工具栏占位：查看未完成打分
function showIncompleteScoringItems() {
  showToast('请在历史记录页筛选「未打分」状态的对话查看', 'info');
}

/* ═══ AI 摘要报告 ═══ */
let _aiSummaryModalState = null;
let _prefetchedAiSummary = null;

/**
 * 打分完成后静默预取摘要报告。
 * 不弹窗、不阻塞主流程；预取成功后高亮按钮提示用户。
 * 后端已有去重锁，与后端预热不会产生重复 LLM 调用。
 */
async function _prefetchAiSummary(convId) {
  setConversationAiReportState(convId, 'generating', {
    ai_report_label: '报告生成中',
    ai_report_ready: false,
    ai_report_count: 0,
  });
  try {
    const summary = await fetchConversationAiSummary(convId);
    if (summary && summary.markdown) {
      _prefetchedAiSummary = { convId, ...summary };
      setConversationAiReportState(convId, 'ready', {
        ai_report_label: '报告就绪',
        ai_report_ready: true,
        ai_report_count: 1,
        ai_report_updated_at: new Date().toISOString(),
      });
      const btn = $('btn-ai-summary');
      if (btn) {
        btn.textContent = '📊 AI报告就绪';
        btn.style.borderColor = 'var(--success-color, #22c55e)';
        btn.style.color = 'var(--success-color, #22c55e)';
        btn.style.fontWeight = '600';
      }
    }
  } catch (e) {
    console.warn('[prefetch] 预取摘要失败:', e.message || e);
    _prefetchedAiSummary = null;
    setConversationAiReportState(convId, 'failed', {
      ai_report_label: '报告生成失败',
      ai_report_ready: false,
      ai_report_count: 0,
    });
  }
}

function setAiSummaryDownloadState(enabled) {
  const btn = $('ai-summary-download-btn');
  if (!btn) return;
  btn.disabled = !enabled;
}

function openAiSummaryModal(title) {
  const modal = $('modal-ai-summary');
  if (!modal) throw new Error('摘要弹窗未找到');
  $('modal-ai-summary-title').textContent = title || '🤖 AI 摘要';
  $('ai-summary-loading').style.display = 'block';
  $('ai-summary-content').style.display = 'none';
  $('ai-summary-error').style.display = 'none';
  if ($('ai-summary-meta')) $('ai-summary-meta').textContent = '';
  if ($('ai-summary-markdown')) $('ai-summary-markdown').textContent = '';
  modal.style.display = 'flex';
  modal.setAttribute('aria-hidden', 'false');
  _aiSummaryModalState = null;
  setAiSummaryDownloadState(false);
}

function renderAiSummaryMarkdown({ markdown, meta = '', filename = '' }) {
  if ($('ai-summary-meta')) $('ai-summary-meta').textContent = meta;
  if ($('ai-summary-markdown')) $('ai-summary-markdown').textContent = markdown || '';
  $('ai-summary-loading').style.display = 'none';
  $('ai-summary-content').style.display = 'block';
  $('ai-summary-error').style.display = 'none';
  _aiSummaryModalState = { markdown: markdown || '', filename: filename || 'ai_summary.md' };
  setAiSummaryDownloadState(Boolean(markdown));
}

function renderAiSummaryError(message) {
  $('ai-summary-loading').style.display = 'none';
  $('ai-summary-content').style.display = 'none';
  $('ai-summary-error-text').textContent = message || '摘要生成失败';
  $('ai-summary-error').style.display = 'block';
  _aiSummaryModalState = null;
  setAiSummaryDownloadState(false);
}

function buildAiSummaryDownloadFilename(summary = {}, fallbackPrefix = 'ai_summary') {
  const titlePart = sanitizeDownloadFilenamePart(summary.report_title || summary.role_name || fallbackPrefix, fallbackPrefix);
  return `${titlePart}.md`;
}

function buildLocalSummaryFallback(summary) {
  return {
    markdown: [
      '# 本地摘要 / 未经 AI 分析',
      '',
      '> 说明: 后端 AI 摘要生成失败，以下内容由前端本地回退模板生成。',
      '',
      summary.markdown || '',
    ].join('\n'),
    filename: summary.filename || 'local_scoring_summary.md',
    meta: '回退模式 · 未调用 qwen-plus',
  };
}

async function fetchConversationAiSummary(convId, { modelId = DEFAULT_AI_SUMMARY_REPORT_MODEL_ID, promptVersion = '' } = {}) {
  const params = new URLSearchParams();
  if (modelId) params.set('model_id', modelId);
  if (promptVersion) params.set('prompt_version', promptVersion);
  const suffix = params.toString() ? `?${params.toString()}` : '';
  const response = await fetch(`/api/scoring/${encodeURIComponent(convId)}/ai-summary${suffix}`, { method: 'POST' });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || response.statusText || 'AI 摘要生成失败');
  }
  const summary = data.summary || {};
  if (summary.error) throw new Error(summary.error);
  return {
    markdown: summary.markdown || '',
    filename: buildAiSummaryDownloadFilename(summary, `scoring_report_${convId}`),
    meta: `模型: ${summary.model_id || modelId || DEFAULT_AI_SUMMARY_REPORT_MODEL_ID} · 提示词: ${summary.prompt_version || '-'}${summary.cached ? ' · 已命中缓存' : ''}`,
  };
}

async function regenerateConversationAiSummarySilently(convId) {
  const conversationId = String(convId || '').trim();
  if (!conversationId) return { success: false, error: '缺少 conversation_id' };
  setConversationAiReportState(conversationId, 'generating', {
    ai_report_label: '报告生成中',
    ai_report_ready: false,
    ai_report_count: 0,
  });
  try {
    const summary = await fetchConversationAiSummary(conversationId);
    setConversationAiReportState(conversationId, 'ready', {
      ai_report_label: '报告就绪',
      ai_report_ready: true,
      ai_report_count: 1,
      ai_report_updated_at: new Date().toISOString(),
    });
    return { success: true, cached: !!summary.cached };
  } catch (error) {
    console.warn(`[rescore-summary] ${conversationId} 生成摘要失败:`, error?.message || error);
    setConversationAiReportState(conversationId, 'failed', {
      ai_report_label: '报告生成失败',
      ai_report_ready: false,
      ai_report_count: 0,
    });
    return { success: false, error: error?.message || '摘要生成失败' };
  }
}

async function retryConversationAiReport(convId, btnEl) {
  if (!convId) return;
  const conversation = (state.historyItems || []).find(item => String(item.id || item.conversation_id || '') === String(convId || ''));
  const conversationLabel = conversation ? getConversationDisplayLabel(conversation) : `会话 ${convId}`;
  const originalText = btnEl ? btnEl.textContent : '';
  if (btnEl) {
    btnEl.disabled = true;
    btnEl.textContent = '生成中...';
  }
  try {
    await requestTaskNotificationPermission();
    setHistorySummaryTaskProgress({
      title: '🧠 AI评分摘要生成中',
      current: 0,
      total: 1,
      detail: `正在为 ${conversationLabel} 生成 AI 摘要`,
      spinning: true,
      allowDismiss: false,
    });
    const summary = await fetchConversationAiSummary(convId);
    setConversationAiReportState(convId, 'ready', {
      ai_report_label: '报告就绪',
      ai_report_ready: true,
      ai_report_count: 1,
      ai_report_updated_at: new Date().toISOString(),
    });
    if (summary && summary.markdown) {
      _prefetchedAiSummary = { convId, ...summary };
    }
    completeHistorySummaryTaskProgress({
      title: '✅ AI评分摘要已完成',
      current: 1,
      total: 1,
      detail: `${conversationLabel} 的 AI 摘要已就绪`,
    });
    showToast('AI报告已更新', 'success');
    void notifyTaskCompletion('AI评分摘要已完成', {
      body: `${conversationLabel} 的 AI 摘要已就绪`,
    });
  } catch (error) {
    setConversationAiReportState(convId, 'failed', {
      ai_report_label: '报告生成失败',
      ai_report_ready: false,
      ai_report_count: 0,
    });
    failHistorySummaryTaskProgress({
      title: '❌ AI评分摘要生成失败',
      current: 0,
      total: 1,
      detail: error?.message || '未知错误',
    });
    showToast(`AI报告生成失败: ${error?.message || error}`, 'error');
    void notifyTaskCompletion('AI评分摘要生成失败', {
      body: error?.message || '未知错误',
    });
  } finally {
    if (btnEl) {
      btnEl.disabled = false;
      btnEl.textContent = originalText || '重试报告';
    }
  }
}

async function fetchCompareAiSummary(reportId, { modelId = DEFAULT_AI_SUMMARY_REPORT_MODEL_ID, promptVersion = '' } = {}) {
  const params = new URLSearchParams();
  if (modelId) params.set('model_id', modelId);
  if (promptVersion) params.set('prompt_version', promptVersion);
  const suffix = params.toString() ? `?${params.toString()}` : '';
  const response = await fetch(`/api/reports/compare/${encodeURIComponent(reportId)}/ai-summary${suffix}`, { method: 'POST' });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || response.statusText || 'AI 对比摘要生成失败');
  }
  const summary = data.summary || {};
  if (summary.error) throw new Error(summary.error);
  return {
    markdown: summary.markdown || '',
    filename: buildAiSummaryDownloadFilename(summary, `compare_report_${reportId}`),
    meta: `模型: ${summary.model_id || modelId || DEFAULT_AI_SUMMARY_REPORT_MODEL_ID} · 提示词: ${summary.prompt_version || '-'}${summary.cached ? ' · 已命中缓存' : ''}`,
  };
}

async function showScoringSummary(convId) {
  // 优先使用预取缓存（同一 convId 且有 markdown）—— 秒出
  if (_prefetchedAiSummary && _prefetchedAiSummary.convId === convId && _prefetchedAiSummary.markdown) {
    openAiSummaryModal('🤖 AI 评分摘要报告');
    renderAiSummaryMarkdown(_prefetchedAiSummary);
    _prefetchedAiSummary = null;
    _resetAiSummaryButton();
    return;
  }
  const conversation = (state.historyItems || []).find(item => String(item.id || item.conversation_id || '') === String(convId || ''));
  const conversationLabel = conversation ? getConversationDisplayLabel(conversation) : `会话 ${convId}`;
  await requestTaskNotificationPermission();
  setHistorySummaryTaskProgress({
    title: '🧠 AI评分摘要生成中',
    current: 0,
    total: 1,
    detail: `正在整理 ${conversationLabel} 的评分摘要`,
    spinning: true,
    allowDismiss: false,
  });
  openAiSummaryModal('🤖 AI 评分摘要报告');
  try {
    const aiSummary = await fetchConversationAiSummary(convId);
    renderAiSummaryMarkdown(aiSummary);
    completeHistorySummaryTaskProgress({
      title: '✅ AI评分摘要已完成',
      current: 1,
      total: 1,
      detail: `${conversationLabel} 的 AI 摘要已展示`,
    });
    void notifyTaskCompletion('AI评分摘要已完成', {
      body: `${conversationLabel} 的 AI 摘要已展示`,
    });
  } catch (aiError) {
    try {
      const resp = await fetch(`/api/conversations/${encodeURIComponent(convId)}`);
      if (!resp.ok) throw new Error('获取对话数据失败');
      const conv = await resp.json();
      const localSummary = buildScoringSummaryMarkdown(conv);
      if (!localSummary) throw aiError;
      renderAiSummaryMarkdown(buildLocalSummaryFallback(localSummary));
      completeHistorySummaryTaskProgress({
        title: '⚠️ 已回退本地评分摘要',
        current: 1,
        total: 1,
        detail: `${conversationLabel} 的 AI 摘要生成失败，已切换为本地摘要`,
      });
      showToast('AI 摘要生成失败，已回退为本地摘要', 'warning');
    } catch (fallbackError) {
      failHistorySummaryTaskProgress({
        title: '❌ AI评分摘要生成失败',
        current: 0,
        total: 1,
        detail: fallbackError.message || aiError.message || '摘要生成失败',
      });
      renderAiSummaryError(fallbackError.message || aiError.message || '摘要生成失败');
    }
  }
  _resetAiSummaryButton();
}

async function showCompareAiSummary(reportId) {
  if (!reportId) { showToast('请先生成历史对比报告', 'warning'); return; }
  const panelTitle = $('history-report-title')?.textContent || '🤖 AI 历史对比分析';
  await requestTaskNotificationPermission();
  setHistorySummaryTaskProgress({
    title: '🧠 历史摘要生成中',
    current: 0,
    total: 1,
    detail: '正在生成历史报告的 AI 摘要分析',
    spinning: true,
    allowDismiss: false,
  });
  openAiSummaryModal(panelTitle.replace(/^📊\s*/, '🤖 '));
  try {
    const summary = await fetchCompareAiSummary(reportId);
    renderAiSummaryMarkdown(summary);
    completeHistorySummaryTaskProgress({
      title: '✅ 历史摘要已完成',
      current: 1,
      total: 1,
      detail: '历史报告的 AI 摘要分析已生成',
    });
    void notifyTaskCompletion('历史摘要已完成', {
      body: '历史报告的 AI 摘要分析已生成',
    });
  } catch (error) {
    failHistorySummaryTaskProgress({
      title: '❌ 历史摘要生成失败',
      current: 0,
      total: 1,
      detail: error.message || 'AI 对比摘要生成失败',
    });
    renderAiSummaryError(error.message || 'AI 对比摘要生成失败');
  }
}

async function triggerAiSummary() {
  if (!state.convId) { showToast('请先运行一次对话测试', 'warning'); return; }
  await showScoringSummary(state.convId);
}

function _resetAiSummaryButton() {
  const btn = $('btn-ai-summary');
  if (btn) {
    btn.textContent = '🤖 AI生成摘要';
    btn.style.borderColor = 'var(--primary-color, #6366f1)';
    btn.style.color = 'var(--primary-color, #6366f1)';
    btn.style.fontWeight = '';
  }
}



function computeAvgScore() {
  const summary = state.scoreSummary || {};
  const summaryAvg = Number(summary.avg_total);
  if (Number(summary.scored_count || 0) > 0 && Number.isFinite(summaryAvg)) {
    return summaryAvg;
  }
  if (!state.scoreData || !state.scoreData.length) return null;
  const scored = state.scoreData.filter(s => getScoringTurnStatus(s) === 'scored');
  if (!scored.length) return null;
  const sum = scored.reduce((a, s) => a + (s.total_score || s.total || 0), 0);
  return sum / scored.length;
}

function isRetryableScoringTurn(turn) {
  const status = getScoringTurnStatus(turn);
  return status === 'failed' || status === 'unscored';
}

const DIM_NAMES = ['人设忠实度', '叙事沉浸感', '情感张力', '边界记忆', '格式合规', '上下文衔接度'];
const DIM_KEYS = ['persona_fidelity', 'narrative_immersion', 'emotional_tension', 'boundary_memory', 'format_compliance', 'context_coherence'];

function renderScoreCard(score, idx) {
  const card = document.createElement('div');
  const lowScoreThreshold = getLowScoreThreshold();
  const scoreStatus = getScoringTurnStatus(score);
  const totalValue = getScoringTurnTotal(score);
  const safeTotal = Number.isFinite(Number(totalValue)) ? Number(totalValue) : 0;
  const isUnscored = scoreStatus === 'unscored';
  const isFailed = scoreStatus === 'failed';
  const showNumericScore = scoreStatus === 'scored';
  const isLowScore = scoreStatus === 'scored' && safeTotal < lowScoreThreshold;
  card.className = `score-turn-card${isLowScore ? ' low-score-turn' : ''}`;
  card.dataset.turn = String(idx);
  card.style.position = 'relative';
  const totalText = showNumericScore ? safeTotal.toFixed(1) : '--';
  let dimsHtml = '<div class="score-dims">';
  DIM_KEYS.forEach((k, i) => {
    const v = showNumericScore ? (score[k] || (score.dimensions && score.dimensions[k]) || 0) : null;
    const color = v === null
      ? 'var(--text-tertiary)'
      : (v >= 8 ? 'var(--success-color)' : v >= 6 ? 'var(--warning-color)' : 'var(--danger-color)');
    dimsHtml += `<div class="score-dim"><div class="dim-val" style="color:${color}">${v === null ? '--' : v}</div><div class="dim-label">${DIM_NAMES[i]}</div></div>`;
  });
  dimsHtml += '</div>';
  const reasoning = score.reasoning || score.explanation || '';
  const manualScore = score.manual_star_score;
  const manualComment = score.manual_comment || '';
  const popoverRows = DIM_KEYS.map((key, i) => {
    const value = score[key] || (score.dimensions && score.dimensions[key]) || 0;
    return `<div style="display:flex;justify-content:space-between;gap:12px;font-size:12px"><span>${DIM_NAMES[i]}</span><strong>${value}</strong></div>`;
  }).join('');
  const manualHtml = manualScore === undefined || manualScore === null || manualScore === ''
    ? ''
    : `<div style="margin-top:10px;padding:10px;border:1px solid var(--border-light);border-radius:8px;background:var(--bg-hover)">
            <div style="font-size:12px;color:var(--text-secondary)">人工评分</div>
            <div style="font-size:14px;font-weight:600;color:var(--primary-color)">${toFixedScore(manualScore)}</div>
            ${manualComment ? `<div style="margin-top:6px;font-size:12px;color:var(--text-secondary)">${escapeHtml(manualComment)}</div>` : ''}
          </div>`;
  const popoverHtml = `<div class="score-popover" style="display:none;position:absolute;top:44px;right:12px;z-index:5;width:240px;padding:12px;border:1px solid var(--border-light);border-radius:10px;background:var(--bg-body);box-shadow:0 10px 24px rgba(0,0,0,.12)">
        <div style="font-size:12px;font-weight:600;margin-bottom:8px">评分详情</div>
        <div style="display:grid;gap:6px">${popoverRows}</div>
        <div style="margin-top:10px;padding-top:10px;border-top:1px solid var(--border-light);font-size:12px;color:var(--text-secondary)">人工分: ${manualScore === undefined || manualScore === null || manualScore === '' ? '-' : toFixedScore(manualScore)}</div>
      </div>`;
  const totalColor = isUnscored
    ? 'var(--text-tertiary)'
    : (isFailed || isLowScore ? 'var(--danger-color)' : 'var(--primary-color)');
  const lowScoreBadge = isLowScore
    ? `<span style="font-size:11px;padding:2px 8px;border-radius:999px;background:rgba(245,63,63,.12);color:var(--danger-color);font-weight:600">低于阈值 ${lowScoreThreshold.toFixed(1)}</span>`
    : '';
  const statusBadge = isUnscored
    ? `<span style="font-size:11px;padding:2px 8px;border-radius:999px;background:rgba(255,125,0,.12);color:var(--warning-color,#ff7d00);font-weight:600">未完成打分</span>`
    : (isFailed
      ? `<span style="font-size:11px;padding:2px 8px;border-radius:999px;background:rgba(245,63,63,.12);color:var(--danger-color);font-weight:600">打分失败</span>`
      : '');
  const reasoningHtml = reasoning
    ? escapeHtml(reasoning)
    : '<span style="color:var(--text-tertiary)">暂无评分依据</span>';
  card.innerHTML = `<div class="score-turn-header" onclick="this.parentElement.classList.toggle('expanded')"><span class="score-turn-title">Turn ${idx}</span><div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">${statusBadge}${lowScoreBadge}<button class="score-turn-total score-popover-trigger" type="button" style="border:none;background:transparent;color:${totalColor};font-weight:700;cursor:pointer">${totalText}</button></div><button class="score-toggle" style="font-size:12px;color:var(--primary-color);background:rgba(22,100,255,.08);padding:4px 10px;border-radius:4px;border:none;cursor:pointer">🔍 查看AI打分依据</button></div>${popoverHtml}${dimsHtml}${manualHtml}<div class="score-reasoning"><div style="font-weight:600;margin-bottom:6px;color:var(--text-primary)">💡 AI 打分依据</div>${reasoningHtml}</div>`;
  const trigger = card.querySelector('.score-popover-trigger');
  const popover = card.querySelector('.score-popover');
  if (trigger && popover) {
    trigger.addEventListener('click', (event) => {
      event.stopPropagation();
      const shouldOpen = popover.style.display !== 'block';
      closeAllScorePopovers();
      popover.style.display = shouldOpen ? 'block' : 'none';
    });
  }
  $('score-cards').appendChild(card);
}

/* ═══ 雷达图 ═══ */
function renderRadarChart() {
  const scoredRows = (state.scoreData || []).filter(item => getScoringTurnStatus(item) === 'scored');
  const svg = $('radar-svg');
  if (!scoredRows.length) {
    if (svg) svg.innerHTML = '';
    return;
  }
  const avgDims = DIM_KEYS.map(k => {
    const sum = scoredRows.reduce((a, s) => a + (s[k] || (s.dimensions && s.dimensions[k]) || 0), 0);
    return sum / scoredRows.length;
  });
  svg.innerHTML = '';
  const cx = 160, cy = 160, R = 120, n = 5;
  const angles = DIM_KEYS.map((_, i) => (Math.PI * 2 * i / n) - Math.PI / 2);
  // Grid
  [0.25, 0.5, 0.75, 1].forEach(s => {
    const pts = angles.map(a => `${cx + R * s * Math.cos(a)},${cy + R * s * Math.sin(a)}`).join(' ');
    svg.innerHTML += `<polygon points="${pts}" fill="none" stroke="var(--border-light)" stroke-width="1"/>`;
  });
  // Axes
  angles.forEach(a => { svg.innerHTML += `<line x1="${cx}" y1="${cy}" x2="${cx + R * Math.cos(a)}" y2="${cy + R * Math.sin(a)}" stroke="var(--border-light)" stroke-width="1"/>`; });
  // Data polygon
  const dataPts = avgDims.map((v, i) => { const r = (v / 10) * R; return `${cx + r * Math.cos(angles[i])},${cy + r * Math.sin(angles[i])}`; }).join(' ');
  svg.innerHTML += `<polygon points="${dataPts}" fill="rgba(22,100,255,0.15)" stroke="var(--primary-color)" stroke-width="2"/>`;
  // Labels
  DIM_NAMES.forEach((name, i) => {
    const lx = cx + (R + 24) * Math.cos(angles[i]), ly = cy + (R + 24) * Math.sin(angles[i]);
    svg.innerHTML += `<text x="${lx}" y="${ly}" text-anchor="middle" dominant-baseline="middle" font-size="11" fill="var(--text-secondary)">${name}</text>`;
  });
  // Data points
  avgDims.forEach((v, i) => { const r = (v / 10) * R; svg.innerHTML += `<circle cx="${cx + r * Math.cos(angles[i])}" cy="${cy + r * Math.sin(angles[i])}" r="4" fill="var(--primary-color)"/>`; });
}

/* ═══ 雷达图 ═══ */
function renderRadarChart() {
  if (!state.scoreData || !state.scoreData.length) return;
  const avgDims = DIM_KEYS.map(k => {
    const sum = state.scoreData.reduce((a, s) => a + (s[k] || (s.dimensions && s.dimensions[k]) || 0), 0);
    return sum / state.scoreData.length;
  });
  const svg = $('radar-svg'); svg.innerHTML = '';
  const cx = 160, cy = 160, R = 120, n = 5;
  const angles = DIM_KEYS.map((_, i) => (Math.PI * 2 * i / n) - Math.PI / 2);
  // Grid
  [0.25, 0.5, 0.75, 1].forEach(s => {
    const pts = angles.map(a => `${cx + R * s * Math.cos(a)},${cy + R * s * Math.sin(a)}`).join(' ');
    svg.innerHTML += `<polygon points="${pts}" fill="none" stroke="var(--border-light)" stroke-width="1"/>`;
  });
  // Axes
  angles.forEach(a => { svg.innerHTML += `<line x1="${cx}" y1="${cy}" x2="${cx + R * Math.cos(a)}" y2="${cy + R * Math.sin(a)}" stroke="var(--border-light)" stroke-width="1"/>`; });
  // Data polygon
  const dataPts = avgDims.map((v, i) => { const r = (v / 10) * R; return `${cx + r * Math.cos(angles[i])},${cy + r * Math.sin(angles[i])}`; }).join(' ');
  svg.innerHTML += `<polygon points="${dataPts}" fill="rgba(22,100,255,0.15)" stroke="var(--primary-color)" stroke-width="2"/>`;
  // Labels
  DIM_NAMES.forEach((name, i) => {
    const lx = cx + (R + 24) * Math.cos(angles[i]), ly = cy + (R + 24) * Math.sin(angles[i]);
    svg.innerHTML += `<text x="${lx}" y="${ly}" text-anchor="middle" dominant-baseline="middle" font-size="11" fill="var(--text-secondary)">${name}</text>`;
  });
  // Data points
  avgDims.forEach((v, i) => { const r = (v / 10) * R; svg.innerHTML += `<circle cx="${cx + r * Math.cos(angles[i])}" cy="${cy + r * Math.sin(angles[i])}" r="4" fill="var(--primary-color)"/>`; });
}

/* ═══ 关系阶段联动 ═══ */
const RELATIONSHIP_PRESETS = {
  '熟人': { intimacy: '仅礼节性接触（握手、点头）', calling: '「你」、正式称谓', info: '刚认识不久，保持礼貌和适度距离' },
  '朋友': { intimacy: '友好接触（拍肩、并肩行走）', calling: '直呼名字', info: '关系熟络，可以开玩笑但不越界' },
  '暧昧': { intimacy: '试探性接触（拉手腕、掖头发、近距离对视）', calling: '名字、可谨慎接受特定昵称', info: '互有好感，心照不宣的暧昧期' },
  '恋人': { intimacy: '亲密接触（拥抱、轻吻、牵手、依偎）', calling: '专属昵称（宝贝/亲爱的）', info: '确定恋爱关系，感情甜蜜稳定' },
  '结婚': { intimacy: '深度日常亲昵（亲吻、拥抱均日常化）', calling: '老公/老婆/宝贝', info: '婚姻关系，日常生活的柴米油盐' },
};
function getResolvedRelationshipVars() {
  const rel = getInputValue('f-relationship').trim();
  const preset = RELATIONSHIP_PRESETS[rel] || {};
  const linked = window._linkedRelationshipVars || {};
  const sameRelationship = linked.relationship === rel;
  return {
    intimacy: sameRelationship && linked.intimacy_boundary ? linked.intimacy_boundary : (preset.intimacy || ''),
    calling: sameRelationship && linked.relation_calling ? linked.relation_calling : (preset.calling || ''),
    info: sameRelationship && linked.relation_info ? linked.relation_info : (preset.info || ''),
  };
}
function updateRelLinkage() {
  const relVars = getResolvedRelationshipVars();
  const preview = $('rel-linkage-preview');
  if (relVars.intimacy || relVars.calling || relVars.info) {
    $('rel-linkage-text').innerHTML = `亲密边界: ${escapeHtml(relVars.intimacy)}<br>称呼: ${escapeHtml(relVars.calling)}<br>关系描述: ${escapeHtml(relVars.info)}`;
    preview.style.display = 'block';
  } else { preview.style.display = 'none'; }
}

async function syncLongformModules(silent = true) {
  const personality = getInputValue('f-personality').trim();
  const relationship = getInputValue('f-relationship').trim();
  const gender = getInputValue('f-gender').trim();
  if (!personality) {
    clearAutoFieldRefreshPending();
    return;
  }
  markAutoFieldRefreshPending();
  try {
    const response = await fetch(`/api/presets/${encodeURIComponent(personality)}/variables?gender=${encodeURIComponent(gender || '男')}&relationship=${encodeURIComponent(relationship || '暧昧')}`);
    if (!response.ok) throw new Error(response.statusText || '联动失败');
    const data = await response.json();

    const updateModule = (id, value, badgeLabel = '自动匹配') => {
      const el = $(id);
      if (el) {
        el.value = value || '';
        const badge = $('badge-' + id.replace('f-', ''));
        if (badge) {
          badge.textContent = badgeLabel;
          badge.style.background = 'var(--bg-hover)';
          badge.style.color = 'var(--text-secondary)';
        }
      }
    };

    updateModule('f-sys-persona', data.longform_persona);
    updateModule('f-sys-style', data.longform_narrative_style);
    updateModule('f-sys-dialogue-guideline', data.longform_dialogue_guideline);
    updateModule('f-sys-fewshot', data.longform_few_shot);
    updateModule('f-voice-forbidden', data.voice_forbidden || DEFAULT_VOICE_FORBIDDEN, '自动填充');
    window._linkedRelationshipVars = {
      relationship: relationship || '暧昧',
      intimacy_boundary: data.intimacy_boundary || '',
      relation_calling: data.relation_calling || '',
      relation_info: data.relation_info || '',
    };

    updateRelLinkage();
    refreshSPPreview();
  } catch (e) {
    if (!silent) showToast('系统模块联动失败: ' + e.message, 'warning');
  } finally {
    clearAutoFieldRefreshPending();
  }
}

/* ═══ Excel 配置导入/导出 ═══ */
const FORM_CONFIG_REQUIRED_HEADERS = ['nickname', 'relationship'];
// Excel 表头别名映射：兼容 Role_Nickname / nick_name 等变体
const HEADER_ALIAS_MAP = {
  'Role_Nickname': 'nickname',
  'role_nickname': 'nickname',
  'nick_name': 'nickname',
  'Role_info_works': 'role_info_works',
  'current_scene': 'scene',
  'timeperiod': 'time_period',
  'user_Nickname': 'user_nickname',
  'prompt_file': 'prompt_version',
  '测试对应提示词': 'prompt_version',
  '用户输入': 'user_message',
  '轮次': 'turn_order',
};

function getExcelRuntime() {
  if (typeof XLSX === 'undefined') {
    throw new Error('Excel 组件未加载，请刷新页面后重试');
  }
  return XLSX;
}

function readFirstWorksheet(arrayBuffer) {
  const excel = getExcelRuntime();
  const workbook = excel.read(arrayBuffer, { type: 'array' });
  const firstSheetName = workbook.SheetNames && workbook.SheetNames[0];
  if (!firstSheetName) throw new Error('Excel 中未找到工作表');
  return { excel, worksheet: workbook.Sheets[firstSheetName] };
}

function normalizeExcelHeaders(headers) {
  return (headers || []).map(h => {
    const raw = String(h || '').trim();
    return HEADER_ALIAS_MAP[raw] || raw;
  });
}

function normalizeRowKeys(row) {
  const out = {};
  for (const [key, value] of Object.entries(row || {})) {
    const rawKey = String(key || '').trim();
    if (!rawKey || rawKey.startsWith('__EMPTY')) continue;
    const mapped = HEADER_ALIAS_MAP[rawKey] || rawKey;
    if (!mapped || mapped.startsWith('__EMPTY')) continue;
    out[mapped] = normalizeImportedCellValue(value);
  }
  return out;
}

async function enrichBatchConfigsWithAutoModules(configs = []) {
  const items = Array.isArray(configs) ? configs : [];
  if (!items.length) return items;
  const cache = new Map();
  let presetCatalogPromise = null;

  const fetchAutoModules = async (personalType, relationship, gender) => {
    const cacheKey = [personalType, relationship, gender].join('::');
    if (!cache.has(cacheKey)) {
      cache.set(
        cacheKey,
        fetch(
          `/api/presets/variables?personality=${encodeURIComponent(personalType)}&gender=${encodeURIComponent(gender || '男')}&relationship=${encodeURIComponent(relationship || '暧昧')}`
        )
          .then(async (response) => {
            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
              throw new Error(data.detail || response.statusText || '自动模块补齐失败');
            }
            return data;
          })
          .catch((error) => {
            console.warn('批量自动模块补齐失败', personalType, relationship, gender, error);
            return {};
          })
      );
    }
    return cache.get(cacheKey);
  };

  const fetchPresetCatalog = async () => {
    if (!presetCatalogPromise) {
      presetCatalogPromise = fetch('/api/presets')
        .then(async (response) => {
          const data = await response.json().catch(() => ({}));
          if (!response.ok) {
            throw new Error(data.detail || response.statusText || '批量类型归一失败');
          }
          return Array.isArray(data.presets) ? data.presets : [];
        })
        .catch((error) => {
          console.warn('批量类型归一失败', error);
          return [];
        });
    }
    return presetCatalogPromise;
  };

  const presetCatalog = await fetchPresetCatalog();

  return Promise.all(items.map(async (cfg) => {
    const resolvedModuleType = resolveBatchModulePersonalityType(cfg, presetCatalog);
    const relationship = normalizeImportedCellValue(cfg.relationship || '') || '暧昧';
    const gender = normalizeImportedCellValue(cfg.gender || '') || '男';
    const autoModules = resolvedModuleType
      ? await fetchAutoModules(resolvedModuleType, relationship, gender)
      : {};

    return {
      ...cfg,
      _resolved_personal_type: resolvedModuleType,
      personal_type: resolvedModuleType || normalizeImportedCellValue(cfg.personal_type || '') || normalizeImportedCellValue(cfg.personality || ''),
      longform_persona: normalizeImportedCellValue(cfg.longform_persona || cfg.sys_persona || '') || normalizeImportedCellValue(autoModules.longform_persona || ''),
      longform_narrative_style: normalizeImportedCellValue(cfg.longform_narrative_style || cfg.sys_style || '') || normalizeImportedCellValue(autoModules.longform_narrative_style || ''),
      longform_dialogue_guideline: normalizeImportedCellValue(cfg.longform_dialogue_guideline || '') || normalizeImportedCellValue(autoModules.longform_dialogue_guideline || ''),
      longform_few_shot: normalizeImportedCellValue(cfg.longform_few_shot || cfg.sys_fewshot || cfg.few_shot_file || '') || normalizeImportedCellValue(autoModules.longform_few_shot || ''),
      few_shot_file: normalizeImportedCellValue(cfg.few_shot_file || cfg.longform_few_shot || '') || normalizeImportedCellValue(autoModules.longform_few_shot || ''),
      voice_forbidden: normalizeImportedCellValue(cfg.voice_forbidden || '') || normalizeImportedCellValue(autoModules.voice_forbidden || '') || DEFAULT_VOICE_FORBIDDEN,
      intimacy_boundary: normalizeImportedCellValue(cfg.intimacy_boundary || '') || normalizeImportedCellValue(autoModules.intimacy_boundary || ''),
      relation_calling: normalizeImportedCellValue(cfg.relation_calling || '') || normalizeImportedCellValue(autoModules.relation_calling || ''),
      relation_info: normalizeImportedCellValue(cfg.relation_info || '') || normalizeImportedCellValue(autoModules.relation_info || ''),
      dialogue_summary: normalizeImportedCellValue(cfg.dialogue_summary || ''),
      system_module8: normalizeImportedCellValue(cfg.system_module8 || ''),
    };
  }));
}

function assertConfigHeaders(headers, sceneLabel) {
  const normalized = normalizeExcelHeaders(headers).filter(Boolean);
  const missing = FORM_CONFIG_REQUIRED_HEADERS.filter(name => !normalized.includes(name));
  if (missing.length) {
    throw new Error(`${sceneLabel}缺少必要表头: ${missing.join(', ')}`);
  }
}

function getFormConfig() {
  const sampling = getGenerationSamplingConfig();
  const dialogueThinking = getDialogueThinkingState(getPrimaryModelId());
  const scoringThinking = getScoringThinkingState(getInputValue('f-scoring-model').trim() || getPrimaryModelId());
  return {
    nickname: $('f-nickname').value, gender: $('f-gender').value, age: $('f-age').value,
    occupation: $('f-occupation').value, personality: $('f-personality').value,
    role_info_works: getInputValue('f-role-info-works').trim(),
    speaking_style: $('f-speaking-style').value, background: $('f-background').value,
    hobby: $('f-hobby').value, relationship: $('f-relationship').value,
    scene: $('f-scene').value, time_period: $('f-timeperiod').value, season: $('f-season').value,
    user_nickname: $('f-user-nickname').value, user_gender: $('f-user-gender').value,
    user_identity: $('f-user-identity').value, turns: $('f-turns') ? $('f-turns').value : '',
    prompt_version: $('f-prompt-version').value,
    summary_prompt_version: getInputValue('f-summary-prompt-version').trim(),
    scoring_prompt_version: getInputValue('f-scoring-prompt-version').trim(),
    summary_interval: $('f-summary-interval').value || DEFAULT_SUMMARY_INTERVAL,
    injection_depth: normalizeInjectionDepthValue($('f-injection-depth').value),
    temperature: sampling.temperature,
    top_p: sampling.top_p,
    model_pro: getPrimaryModelId(), model_mini: getInputValue('f-model-mini').trim(),
    scoring_model_id: getInputValue('f-scoring-model').trim(),
    profile_model_id: getInputValue('f-profile-model').trim(),
    profile_prompt_version: getInputValue('f-profile-prompt-version').trim(),
    thinking_enabled: dialogueThinking.enabled,
    thinking_effort: dialogueThinking.effort,
    scoring_thinking_enabled: scoringThinking.enabled,
    scoring_thinking_effort: scoringThinking.effort,
    scoring_max_workers: normalizeScoringConcurrency(getInputValue('tc-scoring-concurrency')),
    scoring_retry_count: normalizeScoringRetryCount(getInputValue('tc-scoring-retry')),
    sys_persona: getInputValue('f-sys-persona').trim(), sys_style: getInputValue('f-sys-style').trim(),
    sys_fewshot: getInputValue('f-sys-fewshot').trim(), sys_startprompt: getInputValue('f-sys-startprompt').trim(),
    sys_summary: getInputValue('f-sys-summary').trim(), sys_module8: getInputValue('f-sys-module8').trim(),
    weekly_schedule: getInputValue('f-sys-schedule').trim(), sys_role_acting: (getInputValue('f-sys-role-acting').trim() || getInputValue('f-sys-role-acting-module').trim()),
    voice_forbidden: getInputValue('f-voice-forbidden').trim() || DEFAULT_VOICE_FORBIDDEN,
    system_prompt: getInputValue('f-system-prompt').trim(),
  };
}
function setFormConfig(cfg) {
  window.runtimePromptBaseValues = { ...(cfg.prompt_base_values || {}) };
  window.customVarOverrides = { ...(cfg.custom_variables || {}) };
  const map = {
    'f-nickname': cfg.nickname, 'f-gender': cfg.gender, 'f-age': cfg.age,
    'f-occupation': cfg.occupation, 'f-personality': cfg.personality,
    'f-role-info-works': cfg.role_info_works,
    'f-speaking-style': cfg.speaking_style, 'f-background': cfg.background,
    'f-hobby': cfg.hobby, 'f-relationship': cfg.relationship,
    'f-scene': cfg.scene, 'f-timeperiod': cfg.time_period, 'f-season': cfg.season,
    'f-user-nickname': cfg.user_nickname, 'f-user-gender': cfg.user_gender,
    'f-user-identity': cfg.user_identity,
    'f-prompt-version': cfg.prompt_version,
    'f-summary-prompt-version': cfg.summary_prompt_version,
    'f-scoring-prompt-version': cfg.scoring_prompt_version,
    'f-profile-prompt-version': cfg.profile_prompt_version,
    'f-summary-interval': cfg.summary_interval,
    'f-injection-depth': cfg.injection_depth,
    'f-model-pro': normalizeModelId(cfg.model_pro), 'f-model-mini': normalizeModelId(cfg.model_mini, DEFAULT_SUMMARY_MODEL_ID), 'f-scoring-model': normalizeModelId(cfg.scoring_model_id), 'f-profile-model': normalizeModelId(cfg.profile_model_id, DEFAULT_PROFILE_MODEL_ID),
    'f-sys-persona': cfg.sys_persona, 'f-sys-style': cfg.sys_style,
    'f-sys-fewshot': cfg.sys_fewshot, 'f-sys-startprompt': cfg.sys_startprompt,
    'f-sys-summary': cfg.sys_summary, 'f-sys-schedule': cfg.weekly_schedule, 'f-sys-module8': cfg.sys_module8,
    'f-sys-role-acting': cfg.sys_role_acting, 'f-sys-role-acting-module': cfg.sys_role_acting,
    'f-voice-forbidden': cfg.voice_forbidden || DEFAULT_VOICE_FORBIDDEN,
    'f-system-prompt': cfg.system_prompt,
  };
  Object.entries(map).forEach(([id, v]) => { const el = $(id); if (el && v !== undefined && v !== null) el.value = v; });
  if (cfg.model_pro) setPrimaryModelId(cfg.model_pro);
  syncDialogueThinkingControls({
    enabled: coerceOptionalBoolean(cfg.thinking_enabled) ?? DEFAULT_THINKING_ENABLED,
    effort: cfg.thinking_effort || getDefaultThinkingEffortForModel(cfg.model_pro || getPrimaryModelId()),
    modelId: cfg.model_pro || getPrimaryModelId(),
    force: true,
  });
  syncScoringThinkingControls({
    enabled: coerceOptionalBoolean(cfg.scoring_thinking_enabled) ?? DEFAULT_SCORING_THINKING_ENABLED,
    effort: cfg.scoring_thinking_effort || DEFAULT_SCORING_THINKING_EFFORT,
    modelId: cfg.scoring_model_id || cfg.model_pro || getPrimaryModelId(),
    force: true,
  });
  const scoringConcurrency = normalizeScoringConcurrency(cfg.scoring_max_workers);
  if ($('tc-scoring-concurrency')) $('tc-scoring-concurrency').value = String(scoringConcurrency);
  if ($('tc-scoring-concurrency-display')) $('tc-scoring-concurrency-display').textContent = String(scoringConcurrency);
  if ($('tc-scoring-retry')) $('tc-scoring-retry').value = String(normalizeScoringRetryCount(cfg.scoring_retry_count));
  syncGenerationControlsFromConfig(cfg);
  updateRelLinkage();
  syncLongformModules(true);
  syncSelectedChatPrompt({ refreshPreview: true }).catch(err => console.warn('同步主提示词失败', err));
  refreshScoringDefaultsStatus();
}
function importConfigExcel() { $('excel-import-input').click(); }
function handleExcelImport(event) {
  const file = event.target.files[0]; if (!file) return;
  const reader = new FileReader();
  reader.onload = (e) => {
    try {
      const { excel, worksheet } = readFirstWorksheet(e.target.result);
      const rows = excel.utils.sheet_to_json(worksheet, { header: 1, defval: '' });
      if (rows.length < 2) { showToast('Excel 格式不正确', 'error'); return; }
      assertConfigHeaders(rows[0], '配置导入 Excel ');
      const headers = rows[0], vals = rows[1], cfg = {};
      headers.forEach((h, i) => { cfg[h] = vals[i] || ''; });
      setFormConfig(cfg);
      showToast('✅ 配置已导入', 'success');
    } catch (err) { showToast('导入失败: ' + err.message, 'error'); }
  };
  reader.readAsArrayBuffer(file);
  event.target.value = '';
}
function exportConfigExcel() {
  const cfg = getFormConfig();
  const headers = Object.keys(cfg), values = Object.values(cfg);
  const excel = getExcelRuntime();
  const ws = excel.utils.aoa_to_sheet([headers, values]);
  const wb = excel.utils.book_new(); excel.utils.book_append_sheet(wb, ws, '配置');
  excel.writeFile(wb, `config_${$('f-nickname').value || 'export'}_${Date.now()}.xlsx`);
  showToast('✅ 配置已导出', 'success');
}

function isTerminalOrchestrationStatus(status) {
  return ['completed', 'failed', 'cancelled'].includes(String(status || '').trim().toLowerCase());
}

function stopBatchRunPolling() {
  if (_batchRunPollTimer) {
    clearTimeout(_batchRunPollTimer);
    _batchRunPollTimer = null;
  }
}

function stopCompareRunPolling() {
  if (_compareRunPollTimer) {
    clearTimeout(_compareRunPollTimer);
    _compareRunPollTimer = null;
  }
}

function stopABBatchRunPolling() {
  if (_abBatchRunPollTimer) {
    clearTimeout(_abBatchRunPollTimer);
    _abBatchRunPollTimer = null;
  }
}

function getOrchestrationConnectionGuidance(actionLabel = '访问编排接口') {
  if (window.location.protocol === 'file:') {
    return `${actionLabel}失败：当前页面是直接打开的本地 HTML，请改用 launcher.py / start.bat 启动，并访问 http://127.0.0.1:8000`;
  }
  return `${actionLabel}失败：后端不可达，请确认服务仍在运行，并从 http://127.0.0.1:8000 打开当前页面`;
}

function renderOrchestrationEnvironmentNotice() {
  const notice = $('orchestration-env-notice');
  if (!notice) return;
  const message = String(_orchestrationEnvironmentState.message || '').trim();
  if (!message) {
    notice.style.display = 'none';
    notice.innerHTML = '';
    return;
  }
  const blockedByFile = !!_orchestrationEnvironmentState.blockedByFileProtocol;
  const title = blockedByFile ? '测试中心入口错误' : '测试中心暂时无法连接后端';
  notice.style.display = 'flex';
  notice.innerHTML = `
    <div style="min-width:0">
      <div style="font-size:13px;font-weight:700;margin-bottom:4px">${escapeHtml(title)}</div>
      <div style="font-size:12px;line-height:1.6;color:var(--text-secondary)">${escapeHtml(message)}</div>
    </div>
    ${blockedByFile ? '' : `
      <button class="btn btn-secondary btn-sm" type="button" onclick="retryOrchestrationEnvironmentProbe()" style="flex-shrink:0">
        重新检测
      </button>
    `}
  `;
}

function updateOrchestrationActionButtonState() {
  const shouldBlock = _orchestrationEnvironmentState.blockedByFileProtocol || _orchestrationEnvironmentState.reachable === false;
  const message = String(_orchestrationEnvironmentState.message || '').trim();
  ORCHESTRATION_ACTION_BUTTON_IDS.forEach(id => {
    const button = $(id);
    if (!button) return;
    if (shouldBlock) {
      if (button.dataset.orchestrationGuardPrevDisabled === undefined) {
        button.dataset.orchestrationGuardPrevDisabled = button.disabled ? '1' : '0';
        button.dataset.orchestrationGuardPrevTitle = button.getAttribute('title') || '';
      }
      button.disabled = true;
      if (message) {
        button.title = message;
      }
      return;
    }
    if (button.dataset.orchestrationGuardPrevDisabled !== undefined) {
      button.disabled = button.dataset.orchestrationGuardPrevDisabled === '1';
      const previousTitle = button.dataset.orchestrationGuardPrevTitle || '';
      if (previousTitle) {
        button.title = previousTitle;
      } else {
        button.removeAttribute('title');
      }
      delete button.dataset.orchestrationGuardPrevDisabled;
      delete button.dataset.orchestrationGuardPrevTitle;
    }
  });
}

function syncOrchestrationEnvironmentUi() {
  renderOrchestrationEnvironmentNotice();
  updateOrchestrationActionButtonState();
}

function scheduleOrchestrationHealthProbe(delayMs = ORCHESTRATION_HEALTHCHECK_TTL_MS) {
  if (_orchestrationEnvironmentState.blockedByFileProtocol || _orchestrationHealthProbeTimer) return;
  _orchestrationHealthProbeTimer = window.setTimeout(() => {
    _orchestrationHealthProbeTimer = null;
    void probeOrchestrationEnvironment({ silent: true, force: true, bootstrapRecovery: true });
  }, delayMs);
}

function clearOrchestrationHealthProbe() {
  if (_orchestrationHealthProbeTimer) {
    clearTimeout(_orchestrationHealthProbeTimer);
    _orchestrationHealthProbeTimer = null;
  }
}

function setOrchestrationEnvironmentState({ reachable, blockedByFileProtocol = false, message = '', lastCheckedAt = Date.now() }) {
  _orchestrationEnvironmentState.reachable = reachable;
  _orchestrationEnvironmentState.blockedByFileProtocol = blockedByFileProtocol;
  _orchestrationEnvironmentState.message = String(message || '').trim();
  _orchestrationEnvironmentState.lastCheckedAt = lastCheckedAt;
  if (_orchestrationEnvironmentState.reachable === true && !_orchestrationEnvironmentState.blockedByFileProtocol) {
    clearOrchestrationHealthProbe();
  } else {
    scheduleOrchestrationHealthProbe();
  }
  syncOrchestrationEnvironmentUi();
}

async function probeOrchestrationEnvironment({ silent = true, force = false, bootstrapRecovery = false } = {}) {
  const now = Date.now();
  if (
    !force
    && _orchestrationEnvironmentState.reachable === true
    && !_orchestrationEnvironmentState.blockedByFileProtocol
    && now - Number(_orchestrationEnvironmentState.lastCheckedAt || 0) < ORCHESTRATION_HEALTHCHECK_TTL_MS
  ) {
    return true;
  }
  if (window.location.protocol === 'file:') {
    const message = getOrchestrationConnectionGuidance('测试中心初始化');
    setOrchestrationEnvironmentState({
      reachable: false,
      blockedByFileProtocol: true,
      message,
      lastCheckedAt: now,
    });
    if (!silent) {
      showOrchestrationFetchErrorToast('orchestration-bootstrap', message);
    }
    return false;
  }
  try {
    const response = await fetch('/api/app-config', {
      method: 'GET',
      cache: 'no-store',
      headers: { Accept: 'application/json' },
    });
    if (!response.ok) {
      throw new Error(response.statusText || 'app-config unavailable');
    }
    setOrchestrationEnvironmentState({
      reachable: true,
      blockedByFileProtocol: false,
      message: '',
      lastCheckedAt: now,
    });
    if (bootstrapRecovery && !_orchestrationEnvironmentState.recoveryBootstrapped) {
      _orchestrationEnvironmentState.recoveryBootstrapped = true;
      void recoverActiveOrchestrationRuns();
    }
    return true;
  } catch (_) {
    const message = getOrchestrationConnectionGuidance('测试中心初始化');
    setOrchestrationEnvironmentState({
      reachable: false,
      blockedByFileProtocol: false,
      message,
      lastCheckedAt: now,
    });
    if (!silent) {
      showOrchestrationFetchErrorToast('orchestration-bootstrap', message);
    }
    return false;
  }
}

async function ensureOrchestrationEnvironmentReady(actionLabel = '访问编排接口') {
  if (window.location.protocol === 'file:') {
    const message = getOrchestrationConnectionGuidance(actionLabel);
    setOrchestrationEnvironmentState({
      reachable: false,
      blockedByFileProtocol: true,
      message,
      lastCheckedAt: Date.now(),
    });
    throw new Error(message);
  }
  const needsProbe = _orchestrationEnvironmentState.reachable !== true
    || (Date.now() - Number(_orchestrationEnvironmentState.lastCheckedAt || 0)) >= ORCHESTRATION_HEALTHCHECK_TTL_MS;
  if (!needsProbe) return true;
  const ok = await probeOrchestrationEnvironment({ silent: true, force: true, bootstrapRecovery: true });
  if (ok) return true;
  throw new Error(_orchestrationEnvironmentState.message || getOrchestrationConnectionGuidance(actionLabel));
}

async function retryOrchestrationEnvironmentProbe() {
  const ok = await probeOrchestrationEnvironment({ silent: false, force: true, bootstrapRecovery: true });
  if (ok) {
    showToast('测试中心后端连接已恢复', 'success');
  }
}

async function initializeOrchestrationEnvironmentGuard() {
  await probeOrchestrationEnvironment({ silent: false, force: true, bootstrapRecovery: true });
}

async function fetchOrchestrationRun(runId) {
  return requestOrchestrationJson(
    `/api/orchestrations/${encodeURIComponent(runId)}`,
    {},
    '读取编排任务',
  );
}

async function fetchActiveOrchestrationRun(kind) {
  const data = await requestOrchestrationJson(
    `/api/orchestrations/active?kind=${encodeURIComponent(kind)}`,
    {},
    '读取活动任务',
  );
  return data.run || null;
}

async function fetchLatestOrchestrationRun(kind) {
  const data = await requestOrchestrationJson(
    `/api/orchestrations/latest?kind=${encodeURIComponent(kind)}`,
    {},
    '读取最近任务',
  );
  return data.run || null;
}

async function createOrchestrationRun(payload) {
  return requestOrchestrationJson(
    '/api/orchestrations',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    '创建编排任务',
  );
}

async function controlOrchestrationRun(runId, action) {
  return requestOrchestrationJson(
    `/api/orchestrations/${encodeURIComponent(runId)}/control`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action }),
    },
    '控制编排任务',
  );
}

function explainOrchestrationFetchError(actionLabel, error) {
  const rawMessage = String(error?.message || error || '').trim() || `${actionLabel}失败`;
  if (!/failed to fetch/i.test(rawMessage)) {
    return rawMessage;
  }
  return getOrchestrationConnectionGuidance(actionLabel);
}

async function requestOrchestrationJson(url, options = {}, actionLabel = '访问编排接口') {
  try {
    await ensureOrchestrationEnvironmentReady(actionLabel);
    const response = await fetch(url, options);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.detail || response.statusText || `${actionLabel}失败`);
    }
    return data;
  } catch (error) {
    throw new Error(explainOrchestrationFetchError(actionLabel, error));
  }
}

function showOrchestrationFetchErrorToast(key, message) {
  const now = Date.now();
  const previous = _orchestrationFetchErrorToastState.get(key) || { message: '', ts: 0 };
  if (previous.message === message && now - previous.ts < 6000) {
    return;
  }
  _orchestrationFetchErrorToastState.set(key, { message, ts: now });
  showToast(message, 'error');
}

async function recoverBatchOrchestrationRun() {
  const run = (await fetchActiveOrchestrationRun('batch')) || (await fetchLatestOrchestrationRun('batch'));
  if (!run) return null;
  applyBatchOrchestrationRun(run);
  if (!isTerminalOrchestrationStatus(run.status)) {
    pollBatchRun(run.id);
  }
  return run;
}

async function recoverCompareOrchestrationRun() {
  const run = (await fetchActiveOrchestrationRun('compare')) || (await fetchLatestOrchestrationRun('compare'));
  if (!run) return null;
  applyCompareOrchestrationRun(run);
  if (!isTerminalOrchestrationStatus(run.status)) {
    pollCompareRun(run.id);
  }
  return run;
}

async function recoverABBatchOrchestrationRun() {
  const run = (await fetchActiveOrchestrationRun('ab')) || (await fetchLatestOrchestrationRun('ab'));
  if (!run) return null;
  applyABBatchOrchestrationRun(run);
  if (!isTerminalOrchestrationStatus(run.status)) {
    pollABBatchRun(run.id);
  }
  return run;
}

async function recoverActiveOrchestrationRuns() {
  const results = await Promise.allSettled([
    recoverBatchOrchestrationRun(),
    recoverCompareOrchestrationRun(),
    recoverABBatchOrchestrationRun(),
  ]);
  const batchRun = results[0].status === 'fulfilled' ? results[0].value : null;
  const compareRun = results[1].status === 'fulfilled' ? results[1].value : null;
  const abRun = results[2].status === 'fulfilled' ? results[2].value : null;
  if (results[0].status === 'rejected') {
    console.warn('恢复批量编排任务失败:', results[0].reason);
  }
  if (results[1].status === 'rejected') {
    console.warn('恢复模型对比任务失败:', results[1].reason);
  }
  if (results[2].status === 'rejected') {
    console.warn('恢复 Prompt A/B 批量任务失败:', results[2].reason);
  }
  const recoveredModes = [
    batchRun ? 'batch' : '',
    compareRun ? 'compare' : '',
    abRun ? 'prompt-ab' : '',
  ].filter(Boolean);
  if (recoveredModes.length) {
    const persisted = readPersistedTestCenterNavigation();
    const preferredMode = recoveredModes.includes(persisted.testMode)
      ? persisted.testMode
      : recoveredModes[0];
    focusRecoveredTestCenter(preferredMode, {
      abMode: preferredMode === 'prompt-ab' ? 'batch' : null,
    });
  }
  const recoveredKinds = [
    batchRun ? '批量任务' : '',
    compareRun ? '模型对比' : '',
    abRun ? 'Prompt A/B 批量' : '',
  ].filter(Boolean);
  if (recoveredKinds.length) {
    showToast(`已恢复进行中的${recoveredKinds.join(' / ')}`, 'info', 3600);
  }
}

function getOrchestrationManifest(run) {
  return run && typeof run === 'object' && run.manifest && typeof run.manifest === 'object'
    ? run.manifest
    : {};
}

function getOrchestrationGroupManifest(run, groupIndex) {
  const manifest = getOrchestrationManifest(run);
  return Array.isArray(manifest.groups) ? (manifest.groups[groupIndex] || {}) : {};
}

function getOrchestrationItemManifest(run, groupIndex, itemIndex) {
  const group = getOrchestrationGroupManifest(run, groupIndex);
  return Array.isArray(group.items) ? (group.items[itemIndex] || {}) : {};
}

/* ═══ 批量测试 ═══ */
let batchConfigs = [];
let _batchActiveWebSockets = new Set();
let _batchResultRows = [];
let _batchLastTerminalRunId = '';

function registerBatchWebSocket(ws) {
  if (!ws) return;
  _batchActiveWebSockets.add(ws);
}

function unregisterBatchWebSocket(ws) {
  try { _batchActiveWebSockets.delete(ws); } catch (_) { /* ignore */ }
}

function closeAllBatchWebSockets() {
  const sockets = Array.from(_batchActiveWebSockets);
  _batchActiveWebSockets.clear();
  sockets.forEach(ws => {
    try { ws.close(); } catch (_) { /* ignore */ }
  });
}

function resetBatchControlState() {
  state.batchPaused = false;
  state.batchStopRequested = false;
  state.batchRunId = '';
  state.batchRunStatus = '';
  state.batchAutoScoringEnabled = false;
  _batchLastTerminalRunId = '';
  stopBatchRunPolling();
  closeAllBatchWebSockets();
  renderBatchControlRow();
}

function renderBatchControlRow() {
  const row = $('batch-control-row');
  if (!row) return;
  const normalizedStatus = String(state.batchRunStatus || '').trim().toLowerCase();
  const isActive = !!state.batchRunId && !isTerminalOrchestrationStatus(normalizedStatus);
  const isCancelling = normalizedStatus === 'cancelling';
  row.style.display = isActive ? 'flex' : 'none';
  const pauseBtn = $('btn-batch-pause');
  const resumeBtn = $('btn-batch-resume');
  const stopBtn = $('btn-batch-stop');
  const isPaused = ['paused', 'interrupted'].includes(normalizedStatus);
  if (pauseBtn) pauseBtn.style.display = isActive && !isPaused && !isCancelling ? 'inline-flex' : 'none';
  if (resumeBtn) resumeBtn.style.display = isActive && isPaused && !isCancelling ? 'inline-flex' : 'none';
  if (stopBtn) {
    stopBtn.style.display = isActive ? 'inline-flex' : 'none';
    stopBtn.disabled = isCancelling;
    stopBtn.textContent = isCancelling ? '⏳ 停止中...' : '⏹ 停止';
  }
  updateOrchestrationActionButtonState();
}

async function waitForBatchResumeOrStop() {
  while (state.batchPaused && !state.batchStopRequested) {
    await delay(200);
  }
}

function getBatchConfigTurns(cfg) {
  if (Array.isArray(cfg.turns)) return cfg.turns.filter(item => String(item || '').trim());
  return String(cfg.turns || '').split('\n').map(item => String(item || '').trim()).filter(Boolean);
}

function getBatchConcurrency() {
  const el = $('batch-concurrency');
  return normalizeBatchConcurrency(el ? el.value : '', 1);
}

function getABBatchConcurrency() {
  const el = $('ab-batch-concurrency');
  return normalizeABBatchRoleConcurrency(el ? el.value : '', DEFAULT_AB_BATCH_ROLE_CONCURRENCY);
}

function syncABBatchConcurrencyInput(value) {
  const el = $('ab-batch-concurrency');
  if (!el) return;
  el.value = String(normalizeABBatchRoleConcurrency(value, DEFAULT_AB_BATCH_ROLE_CONCURRENCY));
}

function getABBatchItemConcurrency(roleConcurrency = DEFAULT_AB_BATCH_ROLE_CONCURRENCY) {
  return normalizeABBatchRoleConcurrency(roleConcurrency, DEFAULT_AB_BATCH_ROLE_CONCURRENCY) * AB_BATCH_BRANCHES_PER_ROLE;
}

function getABBatchRoleConcurrencyFromRun(run) {
  const branchConcurrency = normalizeBatchConcurrency(run?.concurrency, AB_BATCH_BRANCHES_PER_ROLE);
  return normalizeABBatchRoleConcurrency(
    Math.ceil(branchConcurrency / AB_BATCH_BRANCHES_PER_ROLE),
    DEFAULT_AB_BATCH_ROLE_CONCURRENCY,
  );
}

function getBatchRunLimit(totalCount = batchConfigs.length) {
  const el = $('batch-run-limit');
  const raw = el ? Number.parseInt(String(el.value || '').trim(), 10) : 0;
  if (!Number.isFinite(raw) || raw <= 0) return 0;
  return Math.min(raw, Math.max(0, Number(totalCount) || 0));
}

function getBatchRoleFilterNames() {
  const el = $('batch-role-filter');
  const raw = String(el && el.value ? el.value : '').trim();
  if (!raw) return [];
  return [...new Set(
    raw
      .split(/[\r\n,，、;；]+/)
      .map(item => String(item || '').trim())
      .filter(Boolean)
  )];
}

function isBatchRandomSampleEnabled() {
  return !!($('batch-random-sample') && $('batch-random-sample').checked);
}

function createSeededRandom(seedText = '') {
  let hash = 2166136261;
  const text = String(seedText || '');
  for (let i = 0; i < text.length; i++) {
    hash ^= text.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  let state = (hash >>> 0) || 0x9e3779b9;
  return () => {
    state += 0x6D2B79F5;
    let temp = state;
    temp = Math.imul(temp ^ (temp >>> 15), temp | 1);
    temp ^= temp + Math.imul(temp ^ (temp >>> 7), temp | 61);
    return ((temp ^ (temp >>> 14)) >>> 0) / 4294967296;
  };
}

function shuffleBatchConfigs(list = [], seedText = '') {
  const items = Array.isArray(list) ? [...list] : [];
  const random = createSeededRandom(seedText);
  for (let i = items.length - 1; i > 0; i--) {
    const j = Math.floor(random() * (i + 1));
    [items[i], items[j]] = [items[j], items[i]];
  }
  return items;
}

function getBatchSelectionState(configs = batchConfigs) {
  const loadedConfigs = Array.isArray(configs) ? configs : [];
  const roleNames = getBatchRoleFilterNames();
  const roleNameSet = new Set(roleNames);
  const matchedConfigs = roleNames.length
    ? loadedConfigs.filter(cfg => roleNameSet.has(String(cfg && cfg.nickname || '').trim()))
    : loadedConfigs;
  const matchedNameSet = new Set(matchedConfigs.map(cfg => String(cfg && cfg.nickname || '').trim()).filter(Boolean));
  const missingRoleNames = roleNames.filter(name => !matchedNameSet.has(name));
  const randomSampleEnabled = isBatchRandomSampleEnabled();
  const runLimit = getBatchRunLimit(matchedConfigs.length);
  const seedText = [
    roleNames.join('|'),
    runLimit,
    loadedConfigs.map(cfg => String(cfg && (cfg.session_id || cfg.nickname || '')).trim()).join('|'),
    matchedConfigs.length,
  ].join('::');
  const orderedConfigs = randomSampleEnabled ? shuffleBatchConfigs(matchedConfigs, seedText) : matchedConfigs;
  const activeConfigs = runLimit > 0 ? orderedConfigs.slice(0, runLimit) : orderedConfigs;
  return {
    loadedConfigs,
    matchedConfigs,
    activeConfigs,
    roleNames,
    missingRoleNames,
    randomSampleEnabled,
    runLimit,
  };
}

function getActiveBatchConfigs(configs = batchConfigs) {
  return getBatchSelectionState(configs).activeConfigs;
}

function getBatchTurnLimit(turnCount = 0) {
  const el = $('batch-turn-limit');
  const raw = el ? Number.parseInt(String(el.value || '').trim(), 10) : 0;
  if (!Number.isFinite(raw) || raw <= 0) return 0;
  return Math.min(raw, Math.max(0, Number(turnCount) || 0));
}

function getLimitedBatchConfigTurns(cfg) {
  const turns = getBatchConfigTurns(cfg);
  const limit = getBatchTurnLimit(turns.length);
  return limit > 0 ? turns.slice(0, limit) : turns;
}

function getBatchRunTurns(cfg) {
  const batchTurnsEl = $('batch-turns');
  if (batchTurnsEl && batchTurnsEl.value.trim()) {
    const overrideTurns = batchTurnsEl.value.trim().split('\n').map(item => String(item || '').trim()).filter(Boolean);
    const limit = getBatchTurnLimit(overrideTurns.length);
    return limit > 0 ? overrideTurns.slice(0, limit) : overrideTurns;
  }
  return getLimitedBatchConfigTurns(cfg);
}

function createBatchResultRow(container, cfg) {
  const tr = document.createElement('tr');
  tr.innerHTML = `
        <td>${escapeHtml(cfg.nickname || '')}</td>
        <td>${escapeHtml(cfg.relationship || '')}</td>
        <td class="batch-turn-count">-</td>
        <td class="batch-avg-chars">-</td>
        <td class="batch-score-cell" data-conv-id="">-</td>
        <td class="batch-status-cell"><span class="status-badge status-pending">pending</span></td>
        <td class="batch-action-cell"><span style="color:var(--text-tertiary)">-</span></td>`;
  container.appendChild(tr);
  return {
    tr,
    turnCountEl: tr.querySelector('.batch-turn-count'),
    avgCharsEl: tr.querySelector('.batch-avg-chars'),
    scoreCell: tr.querySelector('.batch-score-cell'),
    statusCell: tr.querySelector('.batch-status-cell'),
    actionCell: tr.querySelector('.batch-action-cell'),
    started: false,
    finished: false,
  };
}

function setBatchRowBadge(row, statusText, badgeCls = 'status-pending', title = '') {
  if (!row || !row.statusCell) return;
  row.statusCell.innerHTML = `<span class="status-badge ${badgeCls}">${escapeHtml(statusText)}</span>`;
  const badge = row.statusCell.querySelector('.status-badge');
  if (badge && title) badge.title = title;
}

function renderBatchConfigAll() {
  const container = $('batch-config-all');
  if (!container) return;
  const selection = getBatchSelectionState(batchConfigs);
  const targetConfigs = selection.activeConfigs;
  if (!targetConfigs.length) {
    container.innerHTML = `<div style="padding:12px;color:var(--text-secondary)">当前筛选条件下没有可执行会话组。</div>`;
    return;
  }
  const rowsHtml = targetConfigs.map((cfg, idx) => {
    const turns = getBatchConfigTurns(cfg);
    const limitedTurns = getLimitedBatchConfigTurns(cfg);
    const conflictFields = Array.isArray(cfg._conflict_fields) ? cfg._conflict_fields : [];
    const conflictBadge = conflictFields.length
      ? `<span title="${escapeHtml(conflictFields.join(', '))}" style="color:var(--danger-color);font-weight:600">⚠冲突</span>`
      : '';
    const sessionId = String(cfg.session_id || '').trim() || String(idx + 1);
    const model = String(cfg.model_pro || '').trim() || '-';
    const promptVersion = String(cfg.prompt_version || '').trim() || '-';
    const previewText = limitedTurns.map((t, i) => `${i + 1}. ${t}`).join('\n');
    const turnLabel = limitedTurns.length < turns.length ? `${limitedTurns.length}/${turns.length}` : `${turns.length}`;
    return `
      <tr>
        <td>${escapeHtml(sessionId)}</td>
        <td>${escapeHtml(cfg.nickname || '')}</td>
        <td>${escapeHtml(cfg.relationship || '')}</td>
        <td>${turnLabel}</td>
        <td>${escapeHtml(model)}</td>
        <td>${escapeHtml(promptVersion)}</td>
        <td>${conflictBadge}</td>
        <td>
          <details>
            <summary style="cursor:pointer;color:var(--primary-color)">预览 turns</summary>
            <pre style="white-space:pre-wrap;margin:8px 0 0;font-family:var(--font-mono);font-size:12px;background:var(--bg-hover);padding:8px;border-radius:8px;border:1px solid var(--border-light);">${escapeHtml(previewText || '(空)')}</pre>
          </details>
        </td>
      </tr>`;
  }).join('');

  const metaParts = [
    `已加载 ${selection.loadedConfigs.length} 组`,
    selection.roleNames.length ? `角色命中 ${selection.matchedConfigs.length} 组` : '',
    selection.randomSampleEnabled ? '随机抽样已开启' : '',
    `本次执行 ${targetConfigs.length} 组`,
  ].filter(Boolean);

  container.innerHTML = `
    <div style="margin-bottom:8px;font-size:12px;color:var(--text-secondary)">${escapeHtml(metaParts.join('｜'))}</div>
    <table class="history-table" style="margin:0;border:0">
      <thead>
        <tr>
          <th>session_id</th>
          <th>角色</th>
          <th>关系</th>
          <th>turns</th>
          <th>主模型</th>
          <th>提示词版本</th>
          <th>冲突</th>
          <th>预览</th>
        </tr>
      </thead>
      <tbody>${rowsHtml}</tbody>
    </table>`;
}

function renderBatchConfigSummary() {
  const summary = $('batch-config-summary');
  const detail = $('batch-config-detail');
  if (!summary || !detail) return;
  if (!batchConfigs.length) { summary.style.display = 'none'; const _be = $('batch-right-empty'); if (_be) _be.style.display = ''; return; }

  const selection = getBatchSelectionState(batchConfigs);
  const conflictCount = batchConfigs.filter(cfg => Array.isArray(cfg._conflict_fields) && cfg._conflict_fields.length).length;
  const activeBatchConfigs = selection.activeConfigs;
  const matchedConfigs = selection.matchedConfigs;
  const roleNames = selection.roleNames;
  const missingRoleNames = selection.missingRoleNames;
  const randomSampleEnabled = selection.randomSampleEnabled;
  const runLimit = selection.runLimit;
  const turnLimit = getBatchTurnLimit(Number.MAX_SAFE_INTEGER);
  const preview = activeBatchConfigs.slice(0, 3).map(cfg => {
    const turns = getBatchConfigTurns(cfg);
    const limitedTurns = getLimitedBatchConfigTurns(cfg);
    const conflictMark = (Array.isArray(cfg._conflict_fields) && cfg._conflict_fields.length) ? ' ⚠' : '';
    const turnLabel = limitedTurns.length < turns.length
      ? `${limitedTurns.length}/${turns.length}轮`
      : `${turns.length}轮`;
    return `• ${escapeHtml(cfg.nickname || '')} / ${escapeHtml(cfg.relationship || '')}（${turnLabel}）${conflictMark}`;
  }).join('<br>');
  const extra = activeBatchConfigs.length > 3 ? `<br>… 还有 ${activeBatchConfigs.length - 3} 组` : '';
  const roleNotice = roleNames.length
    ? `<br>指定角色：<strong>${escapeHtml(roleNames.join('、'))}</strong>（命中 ${matchedConfigs.length} 组）`
    : '';
  const missingNotice = missingRoleNames.length
    ? `<br>未匹配角色：<span style="color:var(--warning-color)">${escapeHtml(missingRoleNames.join('、'))}</span>`
    : '';
  const randomNotice = randomSampleEnabled
    ? `<br>${runLimit > 0 ? `随机抽样 <strong>${activeBatchConfigs.length}</strong> 组` : '随机顺序执行全部命中组'}`
    : '';
  const runNotice = !randomSampleEnabled && runLimit > 0 && activeBatchConfigs.length < matchedConfigs.length
    ? `<br>本次将执行 <strong>${activeBatchConfigs.length}</strong> / ${matchedConfigs.length} 组`
    : '';
  const turnNotice = turnLimit > 0
    ? `<br>每组仅执行前 <strong>${turnLimit}</strong> 轮`
    : '';
  const firstCfg = activeBatchConfigs[0] || batchConfigs[0] || {};
  const scoringThinkingText = firstCfg.scoring_thinking_enabled === false
    ? '关闭'
    : (firstCfg.scoring_thinking_effort || 'high');
  const scoringNotice = [
    firstCfg.scoring_model_id ? `打分模型: <strong>${escapeHtml(firstCfg.scoring_model_id)}</strong>` : '',
    firstCfg.scoring_prompt_version ? `打分提示词: <strong>${escapeHtml(firstCfg.scoring_prompt_version)}</strong>` : '',
    `打分思考: <strong>${escapeHtml(scoringThinkingText)}</strong>`,
  ].filter(Boolean).join(' ｜ ');
  const emptyNotice = !activeBatchConfigs.length
    ? '<br><span style="color:var(--warning-color)">当前筛选条件下没有可执行会话组</span>'
    : '';
  detail.innerHTML = `<strong>${batchConfigs.length}</strong> 组配置已加载${conflictCount ? `（⚠${conflictCount} 组字段冲突）` : ''}${roleNotice}${missingNotice}${randomNotice}${runNotice}${turnNotice}${scoringNotice ? `<br>${scoringNotice}` : ''}${emptyNotice}${preview ? `<br>${preview}${extra}` : ''}`;
  summary.style.display = 'block';
  const batchRightEmpty = $('batch-right-empty'); if (batchRightEmpty) batchRightEmpty.style.display = 'none';

  const toggleBtn = $('btn-batch-config-toggle');
  if (toggleBtn) {
    toggleBtn.style.display = 'inline-flex';
    const expanded = $('batch-config-all') && $('batch-config-all').style.display !== 'none';
    toggleBtn.textContent = expanded ? '收起' : '查看全部';
  }
  if ($('batch-config-all') && $('batch-config-all').style.display !== 'none') renderBatchConfigAll();
}

function toggleBatchConfigAll() {
  const container = $('batch-config-all');
  const btn = $('btn-batch-config-toggle');
  if (!container) return;
  const nextVisible = container.style.display === 'none' || container.style.display === '';
  container.style.display = nextVisible ? 'block' : 'none';
  if (btn) btn.textContent = nextVisible ? '收起' : '查看全部';
  if (nextVisible) renderBatchConfigAll();
}

function loadCurrentConfigToBatch() {
  batchConfigs = [getFormConfig()];
  renderBatchConfigSummary();
  refreshTestCenterShell();
  showToast('已加载当前配置到批量测试', 'success');
}

function hydrateBatchConfigsFromRun(run) {
  const manifestGroups = Array.isArray(getOrchestrationManifest(run).groups)
    ? getOrchestrationManifest(run).groups
    : [];
  const stateGroups = Array.isArray(run?.groups) ? run.groups : [];
  return stateGroups.map((group, groupIndex) => {
    const manifestGroup = manifestGroups[groupIndex] || {};
    const stateItem = Array.isArray(group.items) ? group.items[0] || {} : {};
    const manifestItem = Array.isArray(manifestGroup.items) ? manifestGroup.items[0] || {} : {};
    const payload = manifestItem.payload || {};
    const turns = Array.isArray(payload.turns)
      ? payload.turns.filter(item => String(item || '').trim())
      : Array.from({ length: Number(group.planned_turns || stateItem.planned_turns || 0) }, (_, index) => `第${index + 1}轮`);
    return {
      session_id: group.key || manifestGroup.key || `group:${groupIndex + 1}`,
      nickname: group.label || manifestGroup.label || payload.character?.Role_Nickname || '',
      relationship: group.relationship || manifestGroup.relationship || payload.context?.relationship || '',
      turns,
      model_pro: stateItem.model_id || manifestItem.model_id || payload.model_id || '',
      prompt_version: payload.prompt_version || '',
      scoring_model_id: payload.scoring_model_id || '',
      scoring_prompt_version: payload.scoring_prompt_version || '',
      scoring_thinking_enabled: payload.scoring_thinking_enabled,
      scoring_thinking_effort: payload.scoring_thinking_effort || '',
    };
  });
}

function getBatchRunExecutionContext(run) {
  const firstItem = getOrchestrationItemManifest(run, 0, 0);
  const payload = firstItem.payload || {};
  return {
    isDryRun: !!payload.dry_run,
    autoScoringEnabled: !!payload.auto_scoring,
  };
}

function rebuildBatchRowsFromRun(run) {
  const tbody = $('batch-results-tbody');
  if (!tbody) return;
  const groups = Array.isArray(run?.groups) ? run.groups : [];
  const shouldRebuild = groups.length !== _batchResultRows.length || groups.some((group, index) => {
    const row = _batchResultRows[index];
    return !row || row._groupKey !== group.key;
  });
  if (!shouldRebuild) return;

  tbody.innerHTML = '';
  const fragment = document.createDocumentFragment();
  _batchResultRows = groups.map((group, index) => {
    const cfg = batchConfigs[index] || {
      nickname: group.label || `配置${index + 1}`,
      relationship: group.relationship || '',
    };
    const row = createBatchResultRow(fragment, cfg);
    row._groupKey = group.key || `group:${index + 1}`;
    row._cfg = cfg;
    return row;
  });
  tbody.appendChild(fragment);
}

function updateBatchRunProgress(run) {
  const summary = run?.summary || {};
  const total = Number(summary.total_items || 0);
  const terminal = Number(summary.terminal_items || 0);
  const failed = Number(summary.failed_items || 0);
  let generating = 0;
  const scoring = Number(summary.scoring_items || 0);
  const pendingScoring = Number(summary.pending_scoring_items || 0);
  (run?.groups || []).forEach((group, groupIndex) => {
    (group.items || []).forEach((item, itemIndex) => {
      const manifestItem = getOrchestrationItemManifest(run, groupIndex, itemIndex);
      const plannedTurns = Number(item.planned_turns || group.planned_turns || manifestItem.planned_turns || 0);
      const turnCount = Number(item.turn_count || 0);
      const normalizedStatus = String(item.status || '').trim().toLowerCase();
      if (['pending', 'queued', 'running', 'paused', 'interrupted'].includes(normalizedStatus) && (plannedTurns <= 0 || turnCount < plannedTurns || normalizedStatus !== 'completed')) {
        generating += 1;
      }
    });
  });
  const progressText = $('batch-progress-text');
  if (progressText) {
    const statusText = getConversationStatusLabel(run?.status || '');
    const stageParts = [];
    if (generating > 0) stageParts.push(`生成中 ${generating}`);
    if (scoring > 0) stageParts.push(`评分活跃 ${scoring}`);
    if (pendingScoring > 0) stageParts.push(`待打分 ${pendingScoring}`);
    progressText.textContent = `${run?.title || '批量任务'} · ${statusText} · 已完成 ${terminal}/${total || 0}${stageParts.length ? ` · ${stageParts.join(' · ')}` : ''}`;
  }
  if ($('batch-progress-count')) $('batch-progress-count').textContent = `${terminal}/${total || 0}`;
  if ($('batch-progress-fill')) $('batch-progress-fill').style.width = total ? `${((terminal / total) * 100).toFixed(1)}%` : '0%';
  const failedBadge = $('batch-progress-failed');
  const failedNum = $('batch-failed-num');
  if (failedBadge && failedNum) {
    failedBadge.style.display = failed > 0 ? 'inline-flex' : 'none';
    failedNum.textContent = String(failed);
  }
}

function applyBatchRunItemToRow(row, item, { isDryRun, autoScoringEnabled } = {}) {
  if (!row || !item) return;
  const normalizedStatus = String(item.status || 'pending').trim().toLowerCase();
  row.started = normalizedStatus !== 'pending';
  row.finished = isTerminalOrchestrationStatus(normalizedStatus);

  if (row.turnCountEl) row.turnCountEl.textContent = String(item.turn_count || 0);
  if (row.avgCharsEl) row.avgCharsEl.textContent = String(item.avg_chars || 0);

  const statusLabel = getConversationStatusLabel(item.status || '');
  const statusCls = getCompareStatusBadgeClass(normalizedStatus);
  const errorHtml = item.error
    ? `<div style="margin-top:6px;color:var(--danger-color);font-size:12px;line-height:1.4">${escapeHtml(item.error)}</div>`
    : '';
  if (row.statusCell) {
    row.statusCell.innerHTML = `<span class="status-badge ${statusCls}">${escapeHtml(statusLabel)}</span>${errorHtml}`;
  }

  const convId = String(item.conversation_id || '').trim();
  if (row.actionCell) {
    const actions = [];
    if (convId) {
      actions.push(`<button class="btn btn-secondary" onclick="viewConversation('${convId}')">查看</button>`);
    }
    if (convId && normalizedStatus === 'completed' && !isDryRun && !autoScoringEnabled) {
      actions.push(`<button class="btn btn-secondary" onclick="triggerConversationScoringFromBatch('${convId}', this)">补评分</button>`);
    }
    row.actionCell.innerHTML = actions.length ? actions.join(' ') : '<span style="color:var(--text-tertiary)">-</span>';
  }

  if (row.scoreCell) {
    row.scoreCell.dataset.convId = convId;
    const avgScore = Number.parseFloat(item.avg_score);
    const settledScoreTurns = Number(item.scored_turns || 0) + Number(item.failed_turns || 0) + Number(item.skipped_turns || 0);
    const turnCount = Number(item.turn_count || 0);
    if (isDryRun) {
      row.scoreCell.textContent = '-';
      row.scoreCell.title = '演练模式不执行评分';
      row.scoreCell.style.color = '';
      row.scoreCell.style.fontWeight = '';
    } else if (Number.isFinite(avgScore)) {
      row.scoreCell.innerHTML = autoScoringEnabled && turnCount > 0
        ? `<div style="font-weight:600;color:${getScoreColor(avgScore)}">${avgScore.toFixed(1)}</div><div style="margin-top:2px;font-size:11px;color:var(--text-tertiary)">已打分 ${settledScoreTurns}/${turnCount}</div>`
        : avgScore.toFixed(1);
      row.scoreCell.style.fontWeight = '600';
      row.scoreCell.style.color = getScoreColor(avgScore);
      row.scoreCell.title = '';
    } else if (convId && autoScoringEnabled && turnCount > 0) {
      row.scoreCell.innerHTML = `<div>已打分 ${settledScoreTurns}/${turnCount}</div><div style="margin-top:2px;font-size:11px;color:var(--text-tertiary)">等待均分</div>`;
      row.scoreCell.style.color = '';
      row.scoreCell.style.fontWeight = '';
      row.scoreCell.title = 'live scoring 进行中';
    } else {
      row.scoreCell.textContent = '-';
      row.scoreCell.style.color = '';
      row.scoreCell.style.fontWeight = '';
      row.scoreCell.title = '';
    }
  }
}

function applyBatchOrchestrationRun(run) {
  if (!run) return;
  state.batchRunId = run.id || '';
  state.batchRunStatus = String(run.status || '').trim().toLowerCase();
  state.batchPaused = ['paused', 'interrupted'].includes(state.batchRunStatus);
  state.batchStopRequested = ['cancelling', 'cancelled'].includes(state.batchRunStatus);
  const context = getBatchRunExecutionContext(run);
  state.batchAutoScoringEnabled = context.autoScoringEnabled;
  batchConfigs = hydrateBatchConfigsFromRun(run);
  if (batchConfigs.length) {
    renderBatchConfigSummary();
    refreshTestCenterShell();
  }
  if ($('batch-progress')) $('batch-progress').style.display = 'block';
  if ($('batch-results')) $('batch-results').style.display = 'block';
  const batchRightEmpty = $('batch-right-empty');
  if (batchRightEmpty) batchRightEmpty.style.display = 'none';
  updateBatchRunProgress(run);
  rebuildBatchRowsFromRun(run);
  (run.groups || []).forEach((group, index) => {
    const row = _batchResultRows[index];
    const item = Array.isArray(group.items) ? group.items[0] || null : null;
    applyBatchRunItemToRow(row, item, context);
  });
  state._lastBatchConvIds = (run.groups || [])
    .flatMap(group => (group.items || []).map(item => String(item.conversation_id || '').trim()).filter(Boolean));
  const startBtn = $('btn-batch-start');
  if (startBtn) {
    const isActive = !isTerminalOrchestrationStatus(run.status);
    startBtn.disabled = isActive;
    startBtn.textContent = isActive ? '⏳ 批量测试中...' : '🚀 开始批量生成并落盘';
  }
  renderBatchControlRow();
}

function finalizeBatchOrchestrationRun(run) {
  applyBatchOrchestrationRun(run);
  stopBatchRunPolling();
  renderBatchControlRow();
  if (_batchLastTerminalRunId === run.id) return;
  _batchLastTerminalRunId = run.id;
  const status = String(run.status || '').trim().toLowerCase();
  showToast(
    status === 'cancelled' ? '批量任务已取消' : '批量任务已完成',
    status === 'cancelled' ? 'warning' : 'success',
  );
  void notifyTaskCompletion(status === 'cancelled' ? '批量任务已取消' : '批量任务已完成', {
    body: `${run.summary?.terminal_items || 0}/${run.summary?.total_items || 0} 组已收口`,
  });
  const context = getBatchRunExecutionContext(run);
  const createdAt = Date.parse(run.created_at || '');
  const updatedAt = Date.parse(run.updated_at || '');
  if (_batchResultRows.length > 0 && !context.isDryRun) {
    showBatchSummaryModal(_batchResultRows, batchConfigs, _batchResultRows, {
      total: Number(run.summary?.total_items || _batchResultRows.length),
      completed: Number(run.summary?.terminal_items || 0),
      stoppedEarly: status === 'cancelled',
      durationMs: Number.isFinite(createdAt) && Number.isFinite(updatedAt) && updatedAt >= createdAt
        ? updatedAt - createdAt
        : 0,
    });
  }
}

function pollBatchRun(runId) {
  stopBatchRunPolling();
  const tick = async () => {
    try {
      const run = await fetchOrchestrationRun(runId);
      if (isTerminalOrchestrationStatus(run.status)) {
        finalizeBatchOrchestrationRun(run);
        return;
      }
      applyBatchOrchestrationRun(run);
      _batchRunPollTimer = setTimeout(tick, 1200);
    } catch (e) {
      showOrchestrationFetchErrorToast('batch-poll', '批量任务状态轮询失败: ' + e.message);
      _batchRunPollTimer = setTimeout(tick, 2500);
    }
  };
  _batchRunPollTimer = setTimeout(tick, 1200);
}

async function pauseBatchTest() {
  if (!state.batchRunId || isTerminalOrchestrationStatus(state.batchRunStatus) || state.batchRunStatus === 'cancelling') return;
  try {
    const run = await controlOrchestrationRun(state.batchRunId, 'pause');
    applyBatchOrchestrationRun(run);
    pollBatchRun(run.id);
    showToast('已暂停批量任务', 'info');
  } catch (e) {
    showToast('暂停批量任务失败: ' + e.message, 'error');
  }
}

async function resumeBatchTest() {
  if (!state.batchRunId || isTerminalOrchestrationStatus(state.batchRunStatus) || state.batchRunStatus === 'cancelling') return;
  try {
    const run = await controlOrchestrationRun(state.batchRunId, 'resume');
    applyBatchOrchestrationRun(run);
    pollBatchRun(run.id);
    showToast('已继续批量任务', 'success');
  } catch (e) {
    showToast('继续批量任务失败: ' + e.message, 'error');
  }
}

async function stopBatchTest() {
  if (!state.batchRunId || isTerminalOrchestrationStatus(state.batchRunStatus)) return;
  if (state.batchRunStatus === 'cancelling') {
    showToast('批量任务正在停止中，请等待当前轮次收口', 'info');
    return;
  }
  try {
    const run = await controlOrchestrationRun(state.batchRunId, 'cancel');
    applyBatchOrchestrationRun(run);
    if (isTerminalOrchestrationStatus(run.status)) {
      finalizeBatchOrchestrationRun(run);
      return;
    }
    pollBatchRun(run.id);
    showToast('已发送停止请求，等待批量任务收口', 'info');
  } catch (e) {
    showToast('停止批量任务失败: ' + e.message, 'error');
  }
}

function getScoreColor(score) {
  const value = Number.parseFloat(score);
  if (!Number.isFinite(value)) return 'var(--text-tertiary)';
  if (value >= 7) return 'var(--success-color)';
  if (value >= 5) return 'var(--warning-color)';
  return 'var(--text-tertiary)';
}

function computeConversationScoreAvg(conv) {
  const direct = Number.parseFloat(conv && conv.score_avg);
  if (Number.isFinite(direct)) return direct;
  const results = Array.isArray(conv && conv.results) ? conv.results : [];
  const scored = results.filter(row => row && row.score_status === 'scored' && Number.isFinite(Number.parseFloat(row.score_total)));
  if (!scored.length) return null;
  const sum = scored.reduce((acc, row) => acc + Number.parseFloat(row.score_total), 0);
  return sum / scored.length;
}

async function pollConversationScoreAvg(convId, { timeoutMs = 30000, intervalMs = 1000 } = {}) {
  const startAt = Date.now();
  while (Date.now() - startAt < timeoutMs) {
    const r = await fetch(`/api/conversations/${encodeURIComponent(convId)}`);
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.detail || r.statusText || `HTTP ${r.status}`);
    const avg = computeConversationScoreAvg(data);
    if (avg !== null && avg !== undefined) return avg;
    await delay(intervalMs);
  }
  return null;
}

async function triggerConversationScoringFromBatch(convId, btnEl) {
  const id = String(convId || '').trim();
  if (!id) {
    showToast('缺少 conversation_id', 'error');
    return;
  }
  const btn = btnEl && btnEl.tagName ? btnEl : null;
  const scoreCell = document.querySelector(`.batch-score-cell[data-conv-id="${id}"]`);
  if (btn) {
    btn.disabled = true;
    btn.textContent = '评分中…';
  }
  if (scoreCell) {
    scoreCell.textContent = '打分中 0/?';
    scoreCell.title = '';
  }

  // P3: 建立 WS 连接获取实时进度
  let ws = null;
  let lastSummary = null;
  try {
    const wsProtocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${wsProtocol}//${location.host}/api/scoring/ws/${id}`);
    ws.onmessage = (evt) => {
      try {
        const msg = JSON.parse(evt.data);
        if (msg.type === 'score_progress' && scoreCell) {
          scoreCell.textContent = `打分中 ${msg.current}/${msg.total}`;
        }
        if (msg.type === 'completed') {
          lastSummary = msg.summary || null;
        }
      } catch (_) {}
    };
  } catch (_) {}

  try {
    const scoreData = await ensureConversationScored(id);
    const summary = lastSummary || scoreData?.summary;
    const avg = Number(summary?.avg_total);
    const scored = summary?.scored_count || 0;
    const failed = summary?.failed_count || 0;
    const total = summary?.total_count || 0;
    if (scoreCell) {
      if (!Number.isFinite(avg)) {
        scoreCell.textContent = '-';
        scoreCell.title = '评分完成但未返回均分';
      } else {
        scoreCell.textContent = avg.toFixed(1);
        scoreCell.style.fontWeight = '600';
        scoreCell.style.color = getScoreColor(avg);
        scoreCell.title = failed > 0 ? `已评分 ${scored}/${total}，失败 ${failed} 轮` : '';
      }
    }
    if (btn) {
      btn.textContent = failed > 0 ? `部分失败 ${scored}/${total}` : '已评分';
    }
    showToast(failed > 0 ? `补评分完成（${failed} 轮失败）` : '补评分完成', failed > 0 ? 'warning' : 'success');
  } catch (e) {
    const msg = e && e.message ? e.message : String(e || '补评分失败');
    if (scoreCell) {
      scoreCell.textContent = '-';
      scoreCell.title = msg;
    }
    if (btn) {
      btn.disabled = false;
      btn.textContent = '补评分';
    }
    showToast('补评分失败: ' + msg, 'error');
  } finally {
    if (ws && ws.readyState <= 1) try { ws.close(); } catch (_) {}
  }
}

const SCORING_SUMMARY_DIMENSIONS = [
  { key: 'persona_fidelity', label: '人设忠实度', short: '人设' },
  { key: 'narrative_immersion', label: '叙事沉浸感', short: '叙事' },
  { key: 'emotional_tension', label: '情感张力', short: '情感' },
  { key: 'boundary_memory', label: '边界记忆', short: '边界' },
  { key: 'format_compliance', label: '格式合规', short: '格式' },
  { key: 'context_coherence', label: '上下文衔接度', short: '衔接' },
];

function sanitizeDownloadFilenamePart(value, fallback = 'download') {
  const cleaned = String(value || '')
    .replace(/[\\/:*?"<>|]/g, '_')
    .replace(/\s+/g, ' ')
    .trim();
  return cleaned || fallback;
}

function getScoringTurnNumber(turn, index = 0) {
  const parsed = Number.parseInt(String(turn?.turn || turn?.turn_order || ''), 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : index + 1;
}

function getScoringTurnStatus(turn) {
  const raw = String(turn?.status || turn?.score_status || '').trim().toLowerCase();
  if (raw) return raw;
  return Number.isFinite(Number.parseFloat(turn?.score_total || turn?.total || turn?.mapped_total))
    ? 'scored'
    : 'unscored';
}

function getScoringTurnTotal(turn) {
  const candidates = [turn?.total, turn?.score_total, turn?.total_score, turn?.mapped_total];
  for (const value of candidates) {
    const parsed = Number.parseFloat(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return null;
}

function getScoringDimensionValue(turn, key) {
  const candidates = [
    turn?.scores?.[key],
    turn?.[`score_${key}`],
    turn?.[key],
  ];
  for (const value of candidates) {
    const parsed = Number.parseFloat(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return null;
}

function getScoringReasoning(turn) {
  return String(turn?.reasoning || turn?.score_reasoning || '').trim();
}

function formatScoringMarkdownScore(value) {
  const parsed = Number.parseFloat(value);
  return Number.isFinite(parsed) ? parsed.toFixed(1) : '-';
}

function compactScoringReasoning(reasoning) {
  const normalized = String(reasoning || '')
    .replace(/\s+/g, ' ')
    .replace(/^\[打分异常\]\s*/g, '打分异常：')
    .trim();
  if (!normalized) return '无补充点评';
  return normalized.length > 90 ? `${normalized.slice(0, 90)}...` : normalized;
}

function buildScoringOverallJudgement(avgTotal, strongestDim, weakestDim, failedCount) {
  const level = avgTotal >= 8.5
    ? '整体表现稳，角色和叙事控制都在线。'
    : avgTotal >= 7
      ? '整体可用，但仍有局部维度波动。'
      : avgTotal >= 5
        ? '整体不稳定，关键体验维度存在明显短板。'
        : '整体偏弱，建议优先回看提示词和打分失败轮次。';
  const strongest = strongestDim
    ? `当前最稳的是${strongestDim.label}（${formatScoringMarkdownScore(strongestDim.avg)}/10）。`
    : '';
  const weakest = weakestDim
    ? `最需要回看的维度是${weakestDim.label}（${formatScoringMarkdownScore(weakestDim.avg)}/10）。`
    : '';
  const failure = failedCount > 0 ? `另有 ${failedCount} 轮评分失败，结论需结合失败轮次一起判断。` : '当前无评分失败轮次。';
  return [level, strongest, weakest, failure].filter(Boolean).join(' ');
}

function buildScoringSummaryMarkdown(conv) {
  const results = Array.isArray(conv?.results)
    ? conv.results
    : Array.isArray(conv?.turns)
      ? conv.turns
      : [];
  const config = conv?.config || {};
  const char = config.character || {};
  const ctx = config.context || {};
  const nickname = char.Role_Nickname || conv?.nickname || conv?.character_name || '未知角色';
  const model = conv?.model_id || conv?.model || conv?.model_pro || '-';
  const promptVersion = conv?.prompt_version || config?.prompt_file || '-';
  const relationship = ctx.relationship || ctx.relationship_stage || '-';

  const normalizedTurns = results.map((turn, index) => {
    const dimScores = {};
    SCORING_SUMMARY_DIMENSIONS.forEach(dim => {
      dimScores[dim.key] = getScoringDimensionValue(turn, dim.key);
    });
    return {
      raw: turn,
      turn: getScoringTurnNumber(turn, index),
      status: getScoringTurnStatus(turn),
      total: getScoringTurnTotal(turn),
      reasoning: getScoringReasoning(turn),
      manual: Number.parseFloat(turn?.manual_star_score),
      dimScores,
    };
  });

  const scoredTurns = normalizedTurns.filter(turn => turn.status === 'scored' && Number.isFinite(turn.total));
  if (!scoredTurns.length) return null;
  const failedTurns = normalizedTurns.filter(turn => turn.status === 'failed');
  const totalTurns = normalizedTurns.length;
  const manualScores = normalizedTurns
    .map(turn => turn.manual)
    .filter(value => Number.isFinite(value));
  const avgTotal = scoredTurns.reduce((sum, turn) => sum + turn.total, 0) / scoredTurns.length;
  const avgManual = manualScores.length
    ? manualScores.reduce((sum, value) => sum + value, 0) / manualScores.length
    : null;

  const dimStats = SCORING_SUMMARY_DIMENSIONS.map(dim => {
    const values = scoredTurns
      .map(turn => turn.dimScores[dim.key])
      .filter(value => Number.isFinite(value));
    return {
      ...dim,
      avg: values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null,
      max: values.length ? Math.max(...values) : null,
      min: values.length ? Math.min(...values) : null,
    };
  });

  const bestTurn = scoredTurns.reduce((best, current) => current.total > best.total ? current : best, scoredTurns[0]);
  const worstTurn = scoredTurns.reduce((worst, current) => current.total < worst.total ? current : worst, scoredTurns[0]);
  const dimsWithAvg = dimStats.filter(dim => Number.isFinite(dim.avg));
  const strongestDim = dimsWithAvg.length
    ? dimsWithAvg.reduce((best, current) => current.avg > best.avg ? current : best, dimsWithAvg[0])
    : null;
  const weakestDim = dimsWithAvg.length
    ? dimsWithAvg.reduce((worst, current) => current.avg < worst.avg ? current : worst, dimsWithAvg[0])
    : null;

  const markdownLines = [
    `# 打分摘要 — ${nickname}`,
    '',
    '## 总览仪表盘',
    `- 角色: ${nickname}`,
    `- 模型: ${model}`,
    `- 提示词: ${promptVersion}`,
    `- 关系阶段: ${relationship}`,
    `- 总轮数: ${totalTurns}`,
    `- 已评分轮数: ${scoredTurns.length}`,
    `- 失败轮数: ${failedTurns.length}`,
    `- AI均分: ${formatScoringMarkdownScore(avgTotal)}/10`,
    `- 人工均分: ${avgManual === null ? '-' : `${formatScoringMarkdownScore(avgManual)}/10`}`,
    '',
    '## 维度分析',
    '| 维度 | 均分 | 最高 | 最低 |',
    '|------|------|------|------|',
    ...dimStats.map(dim => `| ${dim.label} | ${formatScoringMarkdownScore(dim.avg)} | ${formatScoringMarkdownScore(dim.max)} | ${formatScoringMarkdownScore(dim.min)} |`),
    '',
    '## 关键结论',
    `- 最高分轮次: Turn ${bestTurn.turn}，${formatScoringMarkdownScore(bestTurn.total)}/10`,
    `- 最低分轮次: Turn ${worstTurn.turn}，${formatScoringMarkdownScore(worstTurn.total)}/10`,
    `- 最强维度: ${strongestDim ? `${strongestDim.label}，${formatScoringMarkdownScore(strongestDim.avg)}/10` : '-'}`,
    `- 最弱维度: ${weakestDim ? `${weakestDim.label}，${formatScoringMarkdownScore(weakestDim.avg)}/10` : '-'}`,
    `- 失败轮次概况: ${failedTurns.length ? `共 ${failedTurns.length} 轮失败（${failedTurns.map(turn => `Turn ${turn.turn}`).join('、')}）` : '无失败轮次'}`,
    `- 整体判断: ${buildScoringOverallJudgement(avgTotal, strongestDim, weakestDim, failedTurns.length)}`,
    '',
    '## 逐轮概览',
    ...normalizedTurns.map(turn => {
      if (turn.status === 'failed') {
        return `- Turn ${turn.turn} | 失败 | ${compactScoringReasoning(turn.reasoning || turn.raw?.error || '评分失败')}`;
      }
      const dimText = SCORING_SUMMARY_DIMENSIONS
        .map(dim => `${dim.short}${formatScoringMarkdownScore(turn.dimScores[dim.key])}`)
        .join(' ');
      const totalText = Number.isFinite(turn.total) ? `${formatScoringMarkdownScore(turn.total)}/10` : '未出分';
      return `- Turn ${turn.turn} | ${totalText} | ${dimText} | ${compactScoringReasoning(turn.reasoning)}`;
    }),
  ];

  return {
    nickname,
    filename: `local_scoring_summary_${sanitizeDownloadFilenamePart(`${nickname}_${conv?.id || conv?.conversation_id || 'conversation'}`)}.md`,
    markdown: markdownLines.join('\n'),
  };
}

function isPerTurnExcelTemplate(rawHeaders = []) {
  const raw = (rawHeaders || []).map(item => String(item || '').trim()).filter(Boolean);
  if (raw.includes('用户输入')) return true;
  if (raw.includes('user_message') || raw.includes('turn_order') || raw.includes('session_id')) return true;
  const normalized = normalizeExcelHeaders(rawHeaders).map(item => String(item || '').trim());
  return normalized.includes('user_message') || normalized.includes('turn_order') || normalized.includes('session_id');
}

function buildBatchConfigsFromPerTurnTemplate(rows = [], { sourceFilename = '' } = {}) {
  const groups = new Map();
  let hasMissingSessionId = false;

  rows.forEach((row, idx) => {
    const sessionId = String(row.session_id || '').trim();
    const nickname = String(row.nickname || '').trim();
    const relationship = String(row.relationship || '').trim();
    const userNickname = String(row.user_nickname || '').trim();
    const compositeKey = [nickname, relationship, userNickname].filter(Boolean).join('::');
    const key = sessionId || compositeKey || `__row_${idx + 1}`;
    if (!sessionId) hasMissingSessionId = true;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push({ ...row, _row_index: idx });
  });

  const configs = [];
  for (const [key, items] of groups.entries()) {
    const sorted = [...items].sort((a, b) => {
      const aOrder = Number.parseInt(String(a.turn_order || '').trim(), 10);
      const bOrder = Number.parseInt(String(b.turn_order || '').trim(), 10);
      const aHas = Number.isFinite(aOrder);
      const bHas = Number.isFinite(bOrder);
      if (aHas && bHas && aOrder !== bOrder) return aOrder - bOrder;
      if (aHas && !bHas) return -1;
      if (!aHas && bHas) return 1;
      return (a._row_index || 0) - (b._row_index || 0);
    });

    const turns = sorted
      .map(item => String(item.user_message || item.turns || '').trim())
      .filter(Boolean);
    if (!turns.length) {
      throw new Error(`turns 不能为空：session_id=${key} 的 user_message 全为空`);
    }

    const base = { ...sorted[0] };
    delete base.user_message;
    delete base.turns;
    delete base.turn_order;
    base.session_id = String(base.session_id || '').trim() || key;
    if (sourceFilename && base.session_id === key && !String(sorted[0].session_id || '').trim()) {
      base.session_id = `${sourceFilename}::${String(base.nickname || '').trim() || key}`;
    }
    base.turns = turns;
    base._turns_count = turns.length;

    const conflictFields = [];
    const ignoreKeys = new Set(['user_message', 'turn_order', '_row_index']);
    const keys = new Set();
    sorted.forEach(row => Object.keys(row || {}).forEach(k => keys.add(k)));
    for (const field of keys) {
      if (ignoreKeys.has(field)) continue;
      const first = String(sorted[0][field] ?? '').trim();
      const conflict = sorted.some(row => String(row[field] ?? '').trim() !== first);
      if (conflict) conflictFields.push(field);
    }
    if (conflictFields.length) base._conflict_fields = conflictFields;

    configs.push(base);
  }

  return { configs, hasMissingSessionId };
}

function assertBatchConfigsTurnsNonEmpty(configs = [], { allowArray = false } = {}) {
  for (let i = 0; i < configs.length; i++) {
    const cfg = configs[i] || {};
    if (allowArray && Array.isArray(cfg.turns)) {
      if (cfg.turns.filter(item => String(item || '').trim()).length) continue;
      throw new Error(`turns 不能为空：第 ${i + 1} 组 turns 为空`);
    }
    if (String(cfg.turns || '').trim()) continue;
    throw new Error(`turns 不能为空：第 ${i + 1} 组 turns 为空`);
  }
}

function handleBatchExcelImport(event) {
  const file = event.target.files[0]; if (!file) return;
  const reader = new FileReader();
  reader.onload = async (e) => {
    try {
      const { excel, worksheet } = readFirstWorksheet(e.target.result);
      const rawRows = excel.utils.sheet_to_json(worksheet, { defval: '' });
      if (!rawRows.length) throw new Error('Excel 未包含任何配置行');
      const rawHeaders = Object.keys(rawRows[0] || {});
      assertConfigHeaders(rawHeaders, '批量配置 Excel ');
      const rows = rawRows
        .map(normalizeRowKeys)
        .filter(row => Object.values(row || {}).some(value => String(value || '').trim()));
      if (!rows.length) throw new Error('Excel 未包含任何有效配置行');

      if (isPerTurnExcelTemplate(rawHeaders)) {
        const { configs, hasMissingSessionId } = buildBatchConfigsFromPerTurnTemplate(rows, { sourceFilename: file.name || '' });
        if (!configs.length) throw new Error('Excel 未生成任何有效会话，请检查 session_id 与 user_message');
        if (hasMissingSessionId) {
          showToast('⚠️ 检测到 session_id 为空：已按角色(角色名+关系+用户昵称)自动合并多轮；建议补齐 session_id 以显式控制会话分组', 'warning', 5200);
        }
        batchConfigs = configs;
        assertBatchConfigsTurnsNonEmpty(batchConfigs, { allowArray: true });
      } else {
        batchConfigs = rows;
        assertBatchConfigsTurnsNonEmpty(batchConfigs, { allowArray: false });
      }

      batchConfigs = await enrichBatchConfigsWithAutoModules(batchConfigs);

      renderBatchConfigSummary();
      refreshTestCenterShell();
      showToast(`✅ 已加载 ${batchConfigs.length} 组批量配置`, 'success');
    } catch (err) { showToast('导入失败: ' + err.message, 'error'); }
  };
  reader.readAsArrayBuffer(file);
  event.target.value = '';
}
async function handleBatchOutputScoring(event) {
  const file = event.target.files[0];
  if (!file) return;
  const summary = $('batch-output-summary');
  const detail = $('batch-output-detail');
  try {
    if (summary) summary.style.display = 'block';
    { const _be = $('batch-right-empty'); if (_be) _be.style.display = 'none'; }
    if (detail) detail.innerHTML = '正在上传并执行评分...';
    const form = new FormData();
    const scoringThinking = getScoringThinkingState(getInputValue('f-scoring-model').trim() || getPrimaryModelId());
    form.append('file', file);
    form.append('scoring_model_id', getInputValue('f-scoring-model').trim() || getPrimaryModelId());
    form.append('scoring_prompt_version', getInputValue('f-scoring-prompt-version').trim());
    form.append('scoring_thinking_enabled', scoringThinking.enabled ? 'true' : 'false');
    form.append('scoring_thinking_effort', scoringThinking.thinking_effort);
    const response = await fetch('/api/scoring/upload', { method: 'POST', body: form });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || response.statusText || '上传评分失败');
    const downloadUrl = data.download_url || '';
    if (detail) {
      detail.innerHTML = `
            <div>文件: ${escapeHtml(file.name)}</div>
            <div>已评分行数: <strong>${data.rows_scored || 0}</strong></div>
            <div style="margin-top:8px">
              ${downloadUrl ? `<a href="${downloadUrl}" style="color:var(--primary-color)">下载评分结果</a>` : '暂无下载链接'}
            </div>`;
    }
    showToast(`输出评分完成: ${data.rows_scored || 0} 行`, 'success');
  } catch (e) {
    if (summary) summary.style.display = 'block';
    if (detail) detail.innerHTML = `<span style="color:var(--danger-color)">失败: ${escapeHtml(e.message)}</span>`;
    showToast('上传已有输出评分失败: ' + e.message, 'error');
  } finally {
    event.target.value = '';
  }
}
function finalizeBatchResultRow(row, cfg, result, { isDryRun, scoringAvailable, scoringError } = {}) {
  if (!row || !result) return;
  row.finished = true;
  if (row.turnCountEl) row.turnCountEl.textContent = String(result.turnCount ?? 0);
  if (row.avgCharsEl) row.avgCharsEl.textContent = String(result.avgChars ?? 0);

  const normalizedStatus = String(result.status || '').trim().toLowerCase();
  const statusCls = normalizedStatus === 'completed'
    ? 'status-completed'
    : (['failed', 'error'].includes(normalizedStatus) ? 'status-failed' : 'status-pending');
  const errorHtml = result.error
    ? `<div style="margin-top:6px;color:var(--danger-color);font-size:12px;line-height:1.4">${escapeHtml(result.error)}</div>`
    : '';
  if (row.statusCell) {
    row.statusCell.innerHTML = `<span class="status-badge ${statusCls}">${escapeHtml(result.status || '')}</span>${errorHtml}`;
  }

  if (row.actionCell) {
    if (result.convId) {
      const viewBtn = `<button class="btn btn-secondary" onclick="viewConversation('${result.convId}')">查看</button>`;
      const scoreBtn = (!isDryRun && scoringAvailable && String(result.status || '') === 'completed' && !state.batchAutoScoringEnabled)
        ? ` <button class="btn btn-secondary" onclick="triggerConversationScoringFromBatch('${result.convId}', this)">补评分</button>`
        : '';
      row.actionCell.innerHTML = `${viewBtn}${scoreBtn}`;
    } else {
      row.actionCell.innerHTML = '<span style="color:var(--text-tertiary)">-</span>';
    }
  }

  const scoreCell = row.scoreCell;
  if (scoreCell) {
    scoreCell.dataset.convId = result.convId || '';
    if (isDryRun) {
      scoreCell.textContent = '-';
      scoreCell.title = '演练模式不执行评分';
    } else if (!scoringAvailable) {
      scoreCell.textContent = '评分不可用';
      scoreCell.title = scoringError || '评分服务不可用';
    } else if (result.status === 'completed' && result.convId) {
      if (state.batchAutoScoringEnabled) {
        scoreCell.textContent = '打分中…';
        pollConversationScoreAvg(result.convId, { timeoutMs: 30000, intervalMs: 1000 })
          .then(avg => {
            if (!scoreCell) return;
            if (avg === null || avg === undefined) {
              scoreCell.textContent = '-';
              scoreCell.title = '打分超时，可稍后在历史列表查看';
              return;
            }
            scoreCell.textContent = Number(avg).toFixed(1);
            scoreCell.style.fontWeight = '600';
            scoreCell.style.color = getScoreColor(avg);
            scoreCell.title = '';
          })
          .catch(err => {
            scoreCell.textContent = '-';
            scoreCell.title = err && err.message ? err.message : '打分失败';
          });
      } else {
        scoreCell.textContent = '-';
        scoreCell.title = '批量阶段已关闭自动评分，可跑完后点击"补评分"';
      }
    } else {
      scoreCell.textContent = '-';
    }
  }
}

async function runSingleBatchConversation(cfg, row, { batchModel, isDryRun, autoScoringEnabled } = {}) {
  const turns = getBatchRunTurns(cfg);
  const resolvedBatchModelId = batchModel !== '使用配置面板模型'
    ? batchModel
    : getPrimaryModelId();
  const payload = buildConversationRunPayload(cfg, {
    modelId: resolvedBatchModelId,
    turns,
    dryRun: isDryRun,
  });
  payload.auto_scoring = !!autoScoringEnabled;
  let convId = '';
  try {
    row.started = true;
    setBatchRowBadge(row, 'starting', 'status-pending');
    if (row.turnCountEl) row.turnCountEl.textContent = '0';
    if (row.avgCharsEl) row.avgCharsEl.textContent = '-';

    const r = await fetch('/api/conversations', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.detail || r.statusText || `HTTP ${r.status}`);
    convId = data.conversation_id || data.id;
    if (!convId) throw new Error('缺少 conversation_id');

    if (row.scoreCell) row.scoreCell.dataset.convId = convId;
    if (row.actionCell) {
      row.actionCell.innerHTML = `<button class="btn btn-secondary" onclick="viewConversation('${convId}')">查看</button>`;
    }

    if (state.batchStopRequested) {
      return { turnCount: 0, avgChars: 0, status: 'stopped', convId, error: '用户停止' };
    }

    return await new Promise((resolve) => {
      const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
      const MAX_TOTAL_WAIT_MS = 2 * 60 * 60 * 1000; // 2h：避免长会话被前端 5min 硬切
      const QUEUED_IDLE_TIMEOUT_MS = 60 * 60 * 1000; // queued 阶段允许更长等待
      const RUNNING_IDLE_TIMEOUT_MS = 10 * 60 * 1000; // running 阶段按"消息闲置超时"判断
      const MAX_RECONNECTS = 3;

      let ws = null;
      let done = false;
      let stage = 'starting';
      let reconciling = false;
      let reconnects = 0;
      const startedAt = Date.now();
      const seenTurns = new Map(); // turn -> ai_output length
      let totalChars = 0;
      let idleTimer = null;
      let totalTimer = null;

      const applyTurn = (turn) => {
        const num = Number.parseInt(String(turn?.turn || turn?.turn_order || ''), 10);
        if (!Number.isFinite(num) || num <= 0) return;
        const len = String(turn?.ai_output || turn?.assistant_reply || '').length;
        const prev = seenTurns.get(num);
        if (prev === undefined) {
          seenTurns.set(num, len);
          totalChars += len;
        } else if (prev !== len) {
          seenTurns.set(num, len);
          totalChars += (len - prev);
        }
        if (row.turnCountEl) row.turnCountEl.textContent = String(seenTurns.size);
      };

      const computeStats = () => {
        const turnCount = seenTurns.size;
        return {
          turnCount,
          avgChars: turnCount ? Math.round(totalChars / turnCount) : 0,
        };
      };

      const cleanup = () => {
        try { if (idleTimer) clearTimeout(idleTimer); } catch (_) { /* ignore */ }
        try { if (totalTimer) clearTimeout(totalTimer); } catch (_) { /* ignore */ }
        try { if (ws) unregisterBatchWebSocket(ws); } catch (_) { /* ignore */ }
      };

      const finalize = (payload) => {
        if (done) return;
        done = true;
        cleanup();
        resolve(payload);
      };

      const scheduleIdleCheck = () => {
        if (done) return;
        try { if (idleTimer) clearTimeout(idleTimer); } catch (_) { /* ignore */ }
        const ms = (stage === 'queued' || stage === 'starting') ? QUEUED_IDLE_TIMEOUT_MS : RUNNING_IDLE_TIMEOUT_MS;
        idleTimer = setTimeout(() => {
          reconcile('idle-timeout');
        }, ms);
      };

      const absorbConversationResults = (conv) => {
        const results = Array.isArray(conv && (conv.results || conv.turns)) ? (conv.results || conv.turns) : [];
        results.forEach(t => applyTurn(t));
      };

      const fetchConversationDetail = async () => {
        const r2 = await fetch(`/api/conversations/${encodeURIComponent(convId)}`);
        const d2 = await r2.json().catch(() => ({}));
        if (!r2.ok) throw new Error(d2.detail || r2.statusText || `HTTP ${r2.status}`);
        return d2;
      };

      const reconcile = async (reason) => {
        if (done || reconciling) return;
        reconciling = true;
        try {
          const conv = await fetchConversationDetail();
          absorbConversationResults(conv);
          const status = String(conv.status || '').trim().toLowerCase();
          const stats = computeStats();

          if (state.batchStopRequested) {
            try { if (ws) ws.close(); } catch (_) { /* ignore */ }
            finalize({ ...stats, status: 'stopped', convId, error: '用户停止' });
            return;
          }

          if (status === 'completed') {
            try { if (ws) ws.close(); } catch (_) { /* ignore */ }
            finalize({ ...stats, status: 'completed', convId });
            return;
          }
          if (status === 'failed') {
            try { if (ws) ws.close(); } catch (_) { /* ignore */ }
            finalize({ ...stats, status: 'failed', convId, error: '任务执行失败' });
            return;
          }

          // 仍在排队/运行：不误判为失败，继续等待或尝试重连
          if (Date.now() - startedAt > MAX_TOTAL_WAIT_MS) {
            try { if (ws) ws.close(); } catch (_) { /* ignore */ }
            finalize({
              ...stats,
              status: '后台继续运行',
              convId,
              error: `前端等待超时（${reason}），后端状态：${status || 'unknown'}。可在历史记录中继续查看/导出`,
            });
            return;
          }

          if (status === 'queued') {
            stage = 'queued';
            setBatchRowBadge(row, 'queued', 'status-pending', conv.queue_position ? `队列位置 ${conv.queue_position}` : '');
          } else {
            stage = 'running';
            setBatchRowBadge(row, 'running', 'status-pending');
          }

          const wsClosed = !ws || ws.readyState === WebSocket.CLOSED || ws.readyState === WebSocket.CLOSING;
          if (wsClosed && reconnects < MAX_RECONNECTS) {
            reconnects++;
            setTimeout(() => {
              connectWebSocketOnce();
            }, Math.min(2000, 400 * reconnects));
          }
          scheduleIdleCheck();
        } catch (err) {
          if (Date.now() - startedAt > MAX_TOTAL_WAIT_MS) {
            const stats = computeStats();
            finalize({
              ...stats,
              status: 'timeout',
              convId,
              error: `等待超时且状态复核失败：${err && err.message ? err.message : '未知错误'}`,
            });
            return;
          }
          scheduleIdleCheck();
        } finally {
          reconciling = false;
        }
      };

      const connectWebSocketOnce = () => {
        if (done) return;
        try { if (ws) unregisterBatchWebSocket(ws); } catch (_) { /* ignore */ }
        const currentWs = new WebSocket(`${proto}//${location.host}/ws/conversations/${convId}`);
        ws = currentWs;
        registerBatchWebSocket(currentWs);

        currentWs.onmessage = (e) => {
          const msg = JSON.parse(e.data);
          if (msg.type === 'turn_result' || msg.type === 'turn') {
            stage = 'running';
            const t = msg.data || msg;
            applyTurn(t);
            setBatchRowBadge(row, 'running', 'status-pending');
          } else if (msg.type === 'queued') {
            stage = 'queued';
            setBatchRowBadge(row, 'queued', 'status-pending', msg.message || '');
          } else if (msg.type === 'started') {
            stage = 'running';
            setBatchRowBadge(row, 'running', 'status-pending', msg.message || '');
          } else if (msg.type === 'completed' || msg.type === 'done') {
            const stats = computeStats();
            try { currentWs.close(); } catch (_) { /* ignore */ }
            finalize({ ...stats, status: 'completed', convId });
          } else if (msg.type === 'error') {
            const stats = computeStats();
            try { currentWs.close(); } catch (_) { /* ignore */ }
            finalize({
              ...stats,
              status: 'failed',
              convId,
              error: msg.error || msg.message || '执行失败',
            });
          }
          scheduleIdleCheck();
        };
        currentWs.onerror = () => {
          // 不直接判死：交给 onclose + 状态复核
        };
        currentWs.onclose = () => {
          try { unregisterBatchWebSocket(currentWs); } catch (_) { /* ignore */ }
          if (done) return;
          if (state.batchStopRequested) {
            const stats = computeStats();
            finalize({ ...stats, status: 'stopped', convId, error: '用户停止' });
            return;
          }
          reconcile('ws-closed');
        };
      };

      totalTimer = setTimeout(() => {
        reconcile('total-timeout');
      }, MAX_TOTAL_WAIT_MS);
      connectWebSocketOnce();
      scheduleIdleCheck();
    });
  } catch (err) {
    return {
      turnCount: 0,
      avgChars: 0,
      status: state.batchStopRequested ? 'stopped' : 'failed',
      convId: convId || null,
      error: err && err.message ? err.message : String(err || '未知错误'),
    };
  }
}

function buildBatchOrchestrationPayload(activeBatchConfigs, {
  batchModel,
  isDryRun,
  autoScoringEnabled,
  concurrency,
} = {}) {
  return {
    kind: 'batch',
    title: `批量测试 ${new Date().toLocaleString('zh-CN', { hour12: false })}`,
    concurrency,
    groups: activeBatchConfigs.map((cfg, index) => {
      const turns = getBatchRunTurns(cfg);
      const resolvedBatchModelId = batchModel !== '使用配置面板模型'
        ? batchModel
        : getPrimaryModelId();
      const payload = buildConversationRunPayload(cfg, {
        modelId: resolvedBatchModelId,
        turns,
        dryRun: isDryRun,
      });
      payload.auto_scoring = !!autoScoringEnabled;
      const groupKey = String(cfg.session_id || cfg.nickname || '').trim() || `group:${index + 1}`;
      return {
        key: groupKey,
        label: String(cfg.nickname || '').trim(),
        relationship: String(cfg.relationship || '').trim(),
        planned_turns: turns.length,
        items: [{
          key: `${groupKey}:primary`,
          label: String(cfg.nickname || '').trim(),
          relationship: String(cfg.relationship || '').trim(),
          model_id: payload.model_id || '',
          planned_turns: turns.length,
          payload,
        }],
      };
    }),
  };
}

async function startBatchTest() {
  if (batchConfigs.length === 0) { showToast('请先加载测试配置', 'warning'); return; }
  if (state.batchRunId && !isTerminalOrchestrationStatus(state.batchRunStatus)) {
    showToast('当前已有进行中的批量任务，请先暂停/停止或等待完成', 'warning');
    return;
  }
  await requestTaskNotificationPermission();
  const selection = getBatchSelectionState(batchConfigs);
  const activeBatchConfigs = selection.activeConfigs;
  if (!activeBatchConfigs.length) {
    showToast(selection.roleNames.length ? '指定角色未命中任何会话组' : '会话组数上限无效，当前没有可执行配置', 'warning');
    return;
  }
  const turnLimit = getBatchTurnLimit(Number.MAX_SAFE_INTEGER);
  resetBatchControlState();
  const batchModel = $('batch-model').value;
  const isDryRun = $('batch-dryrun').checked;
  state.batchAutoScoringEnabled = !!($('batch-auto-scoring') && $('batch-auto-scoring').checked);
  const concurrency = getBatchConcurrency();
  _batchResultRows = [];
  const tbody = $('batch-results-tbody');
  if (tbody) tbody.innerHTML = '';
  if ($('batch-progress')) $('batch-progress').style.display = 'block';
  if ($('batch-results')) $('batch-results').style.display = 'block';
  const batchRightEmpty = $('batch-right-empty');
  if (batchRightEmpty) batchRightEmpty.style.display = 'none';
  const startBtn = $('btn-batch-start');
  if (startBtn) {
    startBtn.disabled = true;
    startBtn.textContent = '⏳ 批量测试中...';
  }
  const batchTurnsOverride = $('batch-turns') && $('batch-turns').value.trim();
  if (batchTurnsOverride) {
    showToast('⚠️ 批量输入区有内容：将覆盖 Excel 每个会话的 turns（用于临时快速替换）', 'warning', 5200);
  }
  if (selection.roleNames.length) {
    showToast(`角色筛选命中 ${selection.matchedConfigs.length} 组，本次执行 ${activeBatchConfigs.length} 组`, 'warning', 4200);
  } else if (activeBatchConfigs.length < batchConfigs.length) {
    showToast(`本次仅执行前 ${activeBatchConfigs.length} 组配置（共加载 ${batchConfigs.length} 组）`, 'warning', 4200);
  }
  if (selection.missingRoleNames.length) {
    showToast(`以下角色未命中：${selection.missingRoleNames.join('、')}`, 'warning', 5200);
  }
  if (selection.randomSampleEnabled) {
    showToast(`已按会话组随机抽样 ${activeBatchConfigs.length} 组`, 'warning', 4200);
  }
  if (!batchTurnsOverride && turnLimit > 0) {
    showToast(`本次按角色-用户会话分组执行，每组仅跑前 ${turnLimit} 轮`, 'warning', 4200);
  }

  try {
    const run = await createOrchestrationRun(buildBatchOrchestrationPayload(activeBatchConfigs, {
      batchModel,
      isDryRun,
      autoScoringEnabled: state.batchAutoScoringEnabled,
      concurrency,
    }));
    applyBatchOrchestrationRun(run);
    if (isTerminalOrchestrationStatus(run.status)) {
      finalizeBatchOrchestrationRun(run);
      return;
    }
    pollBatchRun(run.id);
    showToast(`批量任务已创建：${activeBatchConfigs.length} 组，后端并发 ${concurrency}`, 'success');
  } catch (e) {
    const errorMessage = e && e.message ? e.message : '创建批量任务失败';
    showToast('启动失败: ' + errorMessage, 'error');
    resetBatchControlState();
    if (startBtn) {
      startBtn.disabled = false;
      startBtn.textContent = '🚀 开始批量生成并落盘';
    }
  }
}

/* ═══ Phase2-D: 批量测试摘要弹窗 ═══ */
function showBatchSummaryModal(finishedRows, configs, rowRefs, { total, completed, stoppedEarly, durationMs }) {
  const successRows = finishedRows.filter(r => {
    const badge = r.statusCell?.querySelector('.status-badge');
    return badge && badge.classList.contains('status-completed');
  });
  const failedRows = finishedRows.filter(r => {
    const badge = r.statusCell?.querySelector('.status-badge');
    return badge && (badge.classList.contains('status-failed'));
  });

  // 统计面板
  $('bs-total').textContent = String(total);
  $('bs-success').textContent = String(successRows.length);
  $('bs-failed').textContent = String(failedRows.length + (total - completed));
  const mins = Math.floor(durationMs / 60000);
  const secs = Math.floor((durationMs % 60000) / 1000);
  $('bs-duration').textContent = mins > 0 ? `${mins}m${secs}s` : `${secs}s`;

  // 收集打分数据
  const scoreValues = [];
  const dimSums = { persona_fidelity: 0, narrative_immersion: 0, emotional_tension: 0, boundary_memory: 0, format_compliance: 0, context_coherence: 0 };
  let dimCount = 0;
  finishedRows.forEach(r => {
    const cell = r.scoreCell;
    if (!cell) return;
    const text = cell.textContent || '';
    const match = text.match(/([\d.]+)/);
    if (match) {
      const v = parseFloat(match[1]);
      if (Number.isFinite(v) && v > 0) scoreValues.push(v);
    }
  });

  // 平均分
  const avgScore = scoreValues.length
    ? (scoreValues.reduce((a, b) => a + b, 0) / scoreValues.length).toFixed(2)
    : '-';
  $('bs-avg-score').textContent = avgScore;

  // 各维度卡片（暂用占位，因批量表格只有总分）
  const dimNames = { persona_fidelity: '人设一致', narrative_immersion: '叙事沉浸', emotional_tension: '情感张力', boundary_memory: '边界记忆', format_compliance: '格式合规', context_coherence: '上下文衔接' };
  const dimContainer = $('bs-dim-cards');
  if (dimContainer) {
    dimContainer.innerHTML = Object.entries(dimNames).map(([k, label]) => `
      <div style="text-align:center;padding:10px;background:var(--bg-hover);border-radius:8px">
        <div style="font-size:18px;font-weight:700;color:var(--primary-color)">-</div>
        <div style="font-size:11px;color:var(--text-tertiary);margin-top:2px">${label}</div>
      </div>`).join('');
  }

  // 分数分布
  const dist = { excellent: 0, good: 0, fair: 0, poor: 0 };
  scoreValues.forEach(v => {
    if (v >= 8) dist.excellent++;
    else if (v >= 6) dist.good++;
    else if (v >= 4) dist.fair++;
    else dist.poor++;
  });
  const distEl = $('bs-distribution');
  if (distEl) {
    distEl.innerHTML = [
      { label: '优秀 ≥8', count: dist.excellent, color: 'var(--success-color)' },
      { label: '良好 6-8', count: dist.good, color: 'var(--primary-color)' },
      { label: '一般 4-6', count: dist.fair, color: 'var(--warning-color)' },
      { label: '较差 <4', count: dist.poor, color: 'var(--danger-color)' },
    ].map(d => `
      <div style="text-align:center;padding:10px;background:var(--bg-hover);border-radius:8px">
        <div style="font-size:20px;font-weight:700;color:${d.color}">${d.count}</div>
        <div style="font-size:11px;color:var(--text-tertiary);margin-top:2px">${d.label}</div>
      </div>`).join('');
  }

  showModal('modal-batch-summary');
}

/* ═══ Phase2-C: 批量测试一键汇总导出 ═══ */
async function exportBatchResults() {
  const convIds = state._lastBatchConvIds || [];
  if (!convIds.length) { showToast('无可导出的批量测试结果', 'warning'); return; }
  try {
    const btn = $('btn-batch-export-all');
    if (btn) { btn.disabled = true; btn.textContent = '⏳ 导出中...'; }
    const url = `/api/scoring/multi-model/export?conv_ids=${encodeURIComponent(convIds.join(','))}&summary=false`;
    const r = await fetch(url);
    if (!r.ok) throw new Error('导出失败');
    const blob = await r.blob();
    const objectUrl = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = objectUrl;
    a.download = `batch_results_${new Date().toISOString().slice(0,10).replace(/-/g,'')}.xlsx`;
    a.click();
    URL.revokeObjectURL(objectUrl);
    showToast(`导出成功: ${convIds.length} 个会话`, 'success');
  } catch (e) {
    showToast('批量导出失败: ' + e.message, 'error');
  } finally {
    const btn = $('btn-batch-export-all');
    if (btn) { btn.disabled = false; btn.textContent = '📥 导出全部结果'; }
  }
}

/* ═══ 模型对比页 ═══ */
let compareConfig = null;
let compareExcelConfigs = null;  // Excel 批量角色模式；非空时优先使用
let abBatchConfig = null;
let abBatchExcelConfigs = null;
let _compareLastTerminalRunId = '';

function countCompareRetryableItems(run) {
  return (run?.groups || []).reduce((count, group) => {
    const items = Array.isArray(group?.items) ? group.items : [];
    return count + items.filter(item => String(item?.status || 'pending').trim().toLowerCase() !== 'completed').length;
  }, 0);
}

function countConfigTurns(configs = []) {
  return (configs || []).reduce((acc, cfg) => {
    const turns = Array.isArray(cfg?.turns)
      ? cfg.turns.filter(item => String(item || '').trim())
      : String(cfg?.turns || '').split('\n').filter(item => item.trim());
    return acc + turns.length;
  }, 0);
}

async function loadConfigsFromWorkbookFile(file, { labelPrefix = 'Excel ' } = {}) {
  const reader = new FileReader();
  return new Promise((resolve, reject) => {
    reader.onerror = () => reject(new Error(`${labelPrefix}读取失败`));
    reader.onload = async (event) => {
      try {
        const { excel, worksheet } = readFirstWorksheet(event.target.result);
        const rawRows = excel.utils.sheet_to_json(worksheet, { defval: '' });
        if (!rawRows.length) throw new Error('Excel 未包含任何配置行');
        const rawHeaders = Object.keys(rawRows[0] || {});
        assertConfigHeaders(rawHeaders, labelPrefix);
        const rows = rawRows
          .map(normalizeRowKeys)
          .filter(row => Object.values(row || {}).some(value => String(value || '').trim()));
        if (!rows.length) throw new Error('Excel 未包含任何有效配置行');

        let configs;
        let hasMissingSessionId = false;
        if (isPerTurnExcelTemplate(rawHeaders)) {
          const built = buildBatchConfigsFromPerTurnTemplate(rows, { sourceFilename: file.name || '' });
          configs = built.configs;
          hasMissingSessionId = !!built.hasMissingSessionId;
          if (!configs.length) throw new Error('Excel 未生成任何有效会话');
          assertBatchConfigsTurnsNonEmpty(configs, { allowArray: true });
        } else {
          configs = rows;
          assertBatchConfigsTurnsNonEmpty(configs, { allowArray: false });
        }

        const enrichedConfigs = await enrichBatchConfigsWithAutoModules(configs);
        resolve({ configs: enrichedConfigs, hasMissingSessionId });
      } catch (error) {
        reject(error);
      }
    };
    reader.readAsArrayBuffer(file);
  });
}

function renderCompareControlRow() {
  const row = $('compare-control-row');
  if (!row) return;
  const normalizedStatus = String(state.compareRunStatus || '').trim().toLowerCase();
  const isActive = !!state.compareRunId && !isTerminalOrchestrationStatus(normalizedStatus);
  const isCancelling = normalizedStatus === 'cancelling';
  const showRetry = !!state.compareRunId && !isActive && Number(state.compareRetryableItems || 0) > 0;
  row.style.display = isActive || showRetry ? 'flex' : 'none';
  const isPaused = ['paused', 'interrupted'].includes(normalizedStatus);
  if ($('btn-compare-pause')) $('btn-compare-pause').style.display = isActive && !isPaused && !isCancelling ? 'inline-flex' : 'none';
  if ($('btn-compare-resume')) $('btn-compare-resume').style.display = isActive && isPaused && !isCancelling ? 'inline-flex' : 'none';
  if ($('btn-compare-stop')) {
    $('btn-compare-stop').style.display = isActive ? 'inline-flex' : 'none';
    $('btn-compare-stop').disabled = isCancelling;
    $('btn-compare-stop').textContent = isCancelling ? '⏳ 停止中...' : '⏹ 停止';
  }
  if ($('btn-compare-retry')) $('btn-compare-retry').style.display = showRetry ? 'inline-flex' : 'none';
  updateOrchestrationActionButtonState();
}

function closeCompareScoreSocket(convId, { clearState = true } = {}) {
  const normalized = String(convId || '').trim();
  if (!normalized) return;
  const ws = _compareScoreSockets.get(normalized);
  if (ws) {
    try { ws.close(); } catch (_) { }
  }
  _compareScoreSockets.delete(normalized);
  if (clearState) {
    _compareLiveScoreState.delete(normalized);
  }
}

function closeAllCompareScoreSockets({ clearState = true } = {}) {
  Array.from(_compareScoreSockets.keys()).forEach(convId => {
    closeCompareScoreSocket(convId, { clearState });
  });
  if (clearState) {
    _compareLiveScoreState.clear();
  }
}

function refreshCompareRunViewFromSnapshot() {
  if (!_compareRunSnapshot) return;
  updateCompareRunProgress(_compareRunSnapshot);
  const { models, matrix } = buildCompareMatrixFromRun(_compareRunSnapshot);
  renderCompareMatrix(matrix, models);
  renderCompareControlRow();
}

function mergeCompareCellLiveScoreState(cell) {
  const convId = String(cell?.convId || '').trim();
  if (!convId) return cell;
  const live = _compareLiveScoreState.get(convId);
  if (!live) return cell;
  const merged = { ...cell };
  const totalCount = Number(live.total_count || 0);
  if (Number.isFinite(totalCount) && totalCount > 0) {
    merged.turnCount = Math.max(Number(merged.turnCount || 0), totalCount);
  }
  const scoredCount = Number(live.scored_count);
  const avgScore = Number(live.avg_total);
  if (Number.isFinite(scoredCount) && scoredCount > 0 && Number.isFinite(avgScore)) {
    merged.avgScore = avgScore;
  }
  ['scored_count', 'failed_count', 'skipped_count'].forEach(key => {
    const value = Number(live[key]);
    if (!Number.isFinite(value)) return;
    if (key === 'scored_count') merged.scoredTurns = Math.max(0, value);
    if (key === 'failed_count') merged.failedTurns = Math.max(0, value);
    if (key === 'skipped_count') merged.skippedTurns = Math.max(0, value);
  });
  if (live.scoring_active !== undefined) {
    merged.scoringActive = !!live.scoring_active;
  }
  return merged;
}

function ensureCompareScoreSocket(convId) {
  const normalized = String(convId || '').trim();
  if (!normalized || _compareScoreSockets.has(normalized)) return;
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const ws = new WebSocket(`${proto}//${location.host}/api/scoring/ws/${normalized}`);
  _compareScoreSockets.set(normalized, ws);
  ws.onmessage = (event) => {
    let msg = {};
    try {
      msg = JSON.parse(event.data);
    } catch (_) {
      return;
    }
    if (msg.type === 'score_updated') {
      _compareLiveScoreState.set(normalized, {
        avg_total: Number(msg.avg_total || msg.summary?.avg_total || 0),
        scored_count: Number(msg.scored_count || msg.summary?.scored_count || 0),
        failed_count: Number(msg.failed_count || msg.summary?.failed_count || 0),
        skipped_count: Number(msg.skipped_count || msg.summary?.skipped_count || 0),
        total_count: Number(msg.total_count || msg.summary?.total_count || 0),
        scoring_active: false,
      });
      refreshCompareRunViewFromSnapshot();
    } else if (msg.type === 'score_progress') {
      const previous = _compareLiveScoreState.get(normalized) || {};
      const failedCount = Number(msg.failed_count || previous.failed_count || 0);
      const skippedCount = Number(msg.skipped_count || previous.skipped_count || 0);
      const current = Number(msg.current || 0);
      _compareLiveScoreState.set(normalized, {
        ...previous,
        total_count: Number(msg.total || previous.total_count || 0),
        failed_count: failedCount,
        skipped_count: skippedCount,
        scored_count: Math.max(0, current - failedCount - skippedCount),
        scoring_active: true,
      });
      refreshCompareRunViewFromSnapshot();
    } else if (['score_enqueued', 'score_started', 'score_attempt', 'score_waiting_retry'].includes(msg.type)) {
      const previous = _compareLiveScoreState.get(normalized) || {};
      _compareLiveScoreState.set(normalized, {
        ...previous,
        scoring_active: true,
      });
      refreshCompareRunViewFromSnapshot();
    }
  };
  ws.onclose = () => {
    if (_compareScoreSockets.get(normalized) === ws) {
      _compareScoreSockets.delete(normalized);
    }
  };
  ws.onerror = () => {
    if (_compareScoreSockets.get(normalized) === ws) {
      _compareScoreSockets.delete(normalized);
    }
  };
}

function syncCompareScoreSockets(run) {
  const targetConvIds = new Set();
  if (run && !isTerminalOrchestrationStatus(run.status)) {
    (run.groups || []).forEach((group, groupIndex) => {
      (group.items || []).forEach((item, itemIndex) => {
        const manifestItem = getOrchestrationItemManifest(run, groupIndex, itemIndex);
        const autoScoringEnabled = (manifestItem.payload || {}).auto_scoring !== false;
        const convId = String(item.conversation_id || '').trim();
        if (!autoScoringEnabled || !convId) return;
        const settled = Number(item.scored_turns || 0) + Number(item.failed_turns || 0) + Number(item.skipped_turns || 0);
        const turnCount = Number(item.turn_count || 0);
        const status = String(item.status || '').trim().toLowerCase();
        if (
          turnCount > settled
          || ['pending', 'queued', 'running', 'paused', 'interrupted', 'scoring'].includes(status)
        ) {
          targetConvIds.add(convId);
        }
      });
    });
  }
  Array.from(_compareScoreSockets.keys()).forEach(convId => {
    if (!targetConvIds.has(convId)) {
      closeCompareScoreSocket(convId, { clearState: true });
    }
  });
  targetConvIds.forEach(convId => ensureCompareScoreSocket(convId));
}

function hydrateCompareConfigsFromRun(run) {
  const manifestGroups = Array.isArray(getOrchestrationManifest(run).groups)
    ? getOrchestrationManifest(run).groups
    : [];
  const stateGroups = Array.isArray(run?.groups) ? run.groups : [];
  return stateGroups.map((group, groupIndex) => {
    const manifestGroup = manifestGroups[groupIndex] || {};
    const payload = ((manifestGroup.items || [])[0] || {}).payload || {};
    const turns = Array.isArray(payload.turns)
      ? payload.turns.filter(item => String(item || '').trim())
      : Array.from({ length: Number(group.planned_turns || manifestGroup.planned_turns || 0) }, (_, index) => `第${index + 1}轮`);
    return {
      nickname: group.label || manifestGroup.label || payload.character?.Role_Nickname || '',
      relationship: group.relationship || manifestGroup.relationship || payload.context?.relationship || '',
      turns,
    };
  });
}

function buildCompareMatrixFromRun(run) {
  const groups = Array.isArray(run?.groups) ? run.groups : [];
  const manifestGroups = Array.isArray(getOrchestrationManifest(run).groups)
    ? getOrchestrationManifest(run).groups
    : [];
  const firstManifestGroup = manifestGroups[0] || {};
  const firstStateGroup = groups[0] || {};
  const modelItems = Array.isArray(firstManifestGroup.items) && firstManifestGroup.items.length
    ? firstManifestGroup.items
    : (firstStateGroup.items || []);
  const models = modelItems.map((item, index) => {
    const fallback = (firstStateGroup.items || [])[index] || {};
    return {
      id: item.model_id || fallback.model_id || '',
      name: item.label || fallback.label || item.model_id || fallback.model_id || `模型${index + 1}`,
    };
  });
  const matrix = groups.map((group, groupIndex) => {
    const manifestGroup = manifestGroups[groupIndex] || {};
    return {
      label: String(group.label || manifestGroup.label || `配置${groupIndex + 1}`).trim() || `配置${groupIndex + 1}`,
      relationship: String(group.relationship || manifestGroup.relationship || '').trim(),
      turnsPlanned: Number(group.planned_turns || manifestGroup.planned_turns || 0),
      cells: models.map((model, modelIndex) => {
        const stateItem = (group.items || [])[modelIndex] || {};
        const manifestItem = (manifestGroup.items || [])[modelIndex] || {};
        const payload = manifestItem.payload || {};
        return mergeCompareCellLiveScoreState({
          model,
          convId: String(stateItem.conversation_id || '').trim(),
          plannedTurns: Number(stateItem.planned_turns || manifestItem.planned_turns || group.planned_turns || 0),
          turnCount: Number(stateItem.turn_count || 0),
          avgChars: Number(stateItem.avg_chars || 0),
          avgScore: stateItem.avg_score,
          status: stateItem.status || 'pending',
          scoredTurns: Number(stateItem.scored_turns || 0),
          failedTurns: Number(stateItem.failed_turns || 0),
          skippedTurns: Number(stateItem.skipped_turns || 0),
          pendingScoringTurns: Number(stateItem.pending_scoring_turns || 0),
          hasPendingScores: !!stateItem.has_pending_scores,
          scoringActive: !!stateItem.scoring_active,
          updatedAt: stateItem.updated_at || '',
          autoScoringEnabled: payload.auto_scoring !== false,
          message: '',
          error: stateItem.error || '',
        });
      }),
    };
  });
  return { models, matrix };
}

function getCompareCellSettledScoreTurns(cell) {
  return Number(cell.scoredTurns || 0) + Number(cell.failedTurns || 0) + Number(cell.skippedTurns || 0);
}

function getCompareCellStage(cell) {
  const normalizedStatus = String(cell?.status || '').trim().toLowerCase();
  const plannedTurns = Number(cell?.plannedTurns || 0);
  const turnCount = Number(cell?.turnCount || 0);
  const autoScoringEnabled = cell?.autoScoringEnabled !== false;
  const settledScoreTurns = getCompareCellSettledScoreTurns(cell);
  const pendingScoringTurns = Math.max(
    Number(cell?.pendingScoringTurns || 0),
    Math.max(turnCount - settledScoreTurns, 0),
  );
  const scoringActive = !!cell?.scoringActive;

  if (normalizedStatus === 'pending') return 'pending';
  if (normalizedStatus === 'queued') return 'queued';
  if (normalizedStatus === 'paused') return 'paused';
  if (normalizedStatus === 'cancelled') return 'cancelled';
  if (normalizedStatus === 'interrupted') return 'interrupted';
  if (normalizedStatus === 'failed' || normalizedStatus === 'timeout') return normalizedStatus;
  if (normalizedStatus === 'scoring') return scoringActive ? 'scoring' : 'pending_score';
  if (plannedTurns > 0 && turnCount < plannedTurns) return 'generating';
  if (autoScoringEnabled && turnCount > 0 && pendingScoringTurns > 0) return scoringActive ? 'scoring' : 'pending_score';
  if (normalizedStatus === 'completed') return 'completed';
  if (normalizedStatus === 'running') return 'generating';
  return normalizedStatus || 'pending';
}

function getCompareCellStageLabel(cell) {
  const stage = getCompareCellStage(cell);
  return {
    generating: '生成中',
    scoring: '打分中',
    pending_score: '待打分',
    queued: '排队中',
    paused: '已暂停',
    cancelled: '已取消',
    completed: '已完成',
    failed: '已失败',
    interrupted: '已中断',
    timeout: '等待超时',
    pending: '等待中',
  }[stage] || getCompareStatusLabel(cell.status);
}

function getCompareCellBadgeClass(cell) {
  const stage = getCompareCellStage(cell);
  if (stage === 'generating' || stage === 'scoring') return 'status-running';
  if (stage === 'pending_score') return 'status-pending';
  if (stage === 'timeout') return 'status-failed';
  return getCompareStatusBadgeClass(stage);
}

function summarizeCompareRunActivity(run) {
  let generating = 0;
  const scoring = Number(run?.summary?.scoring_items || 0);
  const pendingScoring = Number(run?.summary?.pending_scoring_items || 0);
  (run?.groups || []).forEach((group, groupIndex) => {
    (group.items || []).forEach((item, itemIndex) => {
      const manifestItem = getOrchestrationItemManifest(run, groupIndex, itemIndex);
      const cell = mergeCompareCellLiveScoreState({
        convId: String(item.conversation_id || '').trim(),
        status: item.status || 'pending',
        plannedTurns: Number(item.planned_turns || group.planned_turns || manifestItem.planned_turns || 0),
        turnCount: Number(item.turn_count || 0),
        scoredTurns: Number(item.scored_turns || 0),
        failedTurns: Number(item.failed_turns || 0),
        skippedTurns: Number(item.skipped_turns || 0),
        pendingScoringTurns: Number(item.pending_scoring_turns || 0),
        scoringActive: !!item.scoring_active,
        autoScoringEnabled: (manifestItem.payload || {}).auto_scoring !== false,
      });
      const stage = getCompareCellStage(cell);
      if (stage === 'generating') generating += 1;
    });
  });
  return { generating, scoring, pendingScoring };
}

function updateCompareRunProgress(run) {
  const summary = run?.summary || {};
  const total = Number(summary.total_items || 0);
  const terminal = Number(summary.terminal_items || 0);
  const failed = Number(summary.failed_items || 0) + Number(summary.cancelled_items || 0);
  const activity = summarizeCompareRunActivity(run);
  const progressText = $('compare-progress-text');
  if (progressText) {
    const stageParts = [];
    if (activity.generating > 0) stageParts.push(`生成中 ${activity.generating}`);
    if (activity.scoring > 0) stageParts.push(`评分活跃 ${activity.scoring}`);
    if (activity.pendingScoring > 0) stageParts.push(`待打分 ${activity.pendingScoring}`);
    progressText.textContent = `${run?.title || '模型对比'} · ${getConversationStatusLabel(run?.status || '')} · 已完成 ${terminal}/${total || 0}${stageParts.length ? ` · ${stageParts.join(' · ')}` : ''}`;
  }
  if ($('compare-progress-count')) $('compare-progress-count').textContent = `${terminal}/${total || 0}`;
  if ($('compare-progress-fill')) $('compare-progress-fill').style.width = total ? `${((terminal / total) * 100).toFixed(1)}%` : '0%';
  const failedBadge = $('compare-progress-failed');
  const failedNum = $('compare-failed-num');
  if (failedBadge && failedNum) {
    failedBadge.style.display = failed > 0 ? 'inline-flex' : 'none';
    failedNum.textContent = String(failed);
  }
}

function applyCompareOrchestrationRun(run) {
  if (!run) return;
  _compareRunSnapshot = run;
  state.compareRunId = run.id || '';
  state.compareRunStatus = String(run.status || '').trim().toLowerCase();
  state.compareRetryableItems = countCompareRetryableItems(run);
  syncCompareScoreSockets(run);
  const recoveredConfigs = hydrateCompareConfigsFromRun(run);
  compareExcelConfigs = recoveredConfigs.length > 1 ? recoveredConfigs : null;
  compareConfig = recoveredConfigs.length === 1 ? recoveredConfigs[0] : compareConfig;
  _updateCompareExcelSummary();
  const infoEl = $('compare-config-info');
  if (infoEl) {
    const roleCount = Number(run.groups?.length || 0);
    const modelCount = Number(run.groups?.[0]?.items?.length || 0);
    infoEl.style.display = 'block';
    infoEl.innerHTML = `🧪 ${roleCount} 组角色 × ${modelCount} 个模型 · 当前状态：<strong>${escapeHtml(getConversationStatusLabel(run.status || ''))}</strong>`;
  }
  if ($('compare-progress')) $('compare-progress').style.display = 'block';
  if ($('compare-results')) $('compare-results').style.display = 'block';
  const emptyEl = $('compare-right-empty');
  if (emptyEl) emptyEl.style.display = 'none';
  updateCompareRunProgress(run);
  const { models, matrix } = buildCompareMatrixFromRun(run);
  renderCompareMatrix(matrix, models);
  const startBtn = $('btn-compare-start');
  if (startBtn) {
    const isActive = !isTerminalOrchestrationStatus(run.status);
    startBtn.disabled = isActive;
    startBtn.textContent = isActive ? '⏳ 对比测试中...' : '🚀 开始横向对比测试';
  }
  renderCompareControlRow();
}

function finalizeCompareOrchestrationRun(run) {
  applyCompareOrchestrationRun(run);
  closeAllCompareScoreSockets({ clearState: false });
  stopCompareRunPolling();
  const status = String(run.status || '').trim().toLowerCase();
  const successCount = Number(run.summary?.completed_items || 0);
  const failCount = Number(run.summary?.failed_items || 0) + Number(run.summary?.cancelled_items || 0);
  if ($('compare-progress')) $('compare-progress').style.display = failCount > 0 ? 'block' : 'none';
  renderCompareControlRow();
  if (_compareLastTerminalRunId === run.id) return;
  _compareLastTerminalRunId = run.id;
  showToast(
    status === 'cancelled'
      ? '模型对比已取消'
      : `模型对比已完成：成功 ${successCount}/${run.summary?.total_items || 0}${failCount ? `（未完成 ${failCount}）` : ''}`,
    status === 'cancelled' || failCount > 0 ? 'warning' : 'success',
  );
  void notifyTaskCompletion(status === 'cancelled' ? '模型对比已取消' : '模型对比已完成', {
    body: `成功 ${successCount}/${run.summary?.total_items || 0}${failCount ? `，未完成 ${failCount}` : ''}`,
  });
}

function pollCompareRun(runId) {
  stopCompareRunPolling();
  const tick = async () => {
    try {
      const run = await fetchOrchestrationRun(runId);
      if (isTerminalOrchestrationStatus(run.status)) {
        finalizeCompareOrchestrationRun(run);
        return;
      }
      applyCompareOrchestrationRun(run);
      _compareRunPollTimer = setTimeout(tick, 1200);
    } catch (e) {
      showOrchestrationFetchErrorToast('compare-poll', '模型对比状态轮询失败: ' + e.message);
      _compareRunPollTimer = setTimeout(tick, 2500);
    }
  };
  _compareRunPollTimer = setTimeout(tick, 1200);
}

function buildCompareOrchestrationPayload(configs, models, { dryRun } = {}) {
  const autoScoringEnabled = !dryRun;
  return {
    kind: 'compare',
    title: `模型对比 ${new Date().toLocaleString('zh-CN', { hour12: false })}`,
    concurrency: Math.max(1, Math.min(models.length, MAX_BATCH_CONCURRENCY)),
    groups: configs.map((cfg, rowIndex) => {
      const turns = Array.isArray(cfg.turns)
        ? cfg.turns.filter(item => String(item || '').trim())
        : String(cfg.turns || '').split('\n').filter(item => item.trim());
      const groupKey = String(cfg.session_id || cfg.nickname || '').trim() || `compare:${rowIndex + 1}`;
      return {
        key: groupKey,
        label: String(cfg.nickname || cfg.session_id || `配置${rowIndex + 1}`).trim(),
        relationship: String(cfg.relationship || '').trim(),
        planned_turns: turns.length,
        items: models.map((model, modelIndex) => {
          const payload = buildConversationRunPayload(cfg, {
            modelId: model.id,
            turns,
            dryRun: !!dryRun,
          });
          payload.auto_scoring = autoScoringEnabled;
          return {
            key: `${groupKey}:${model.id || modelIndex + 1}`,
            label: model.name || model.id,
            relationship: String(cfg.relationship || '').trim(),
            model_id: model.id,
            planned_turns: turns.length,
            payload,
          };
        }),
      };
    }),
  };
}

function _updateCompareExcelSummary() {
  const el = $('compare-excel-summary');
  if (!el) return;
  if (!Array.isArray(compareExcelConfigs) || !compareExcelConfigs.length) {
    el.textContent = '';
    return;
  }
  const totalTurns = countConfigTurns(compareExcelConfigs);
  el.innerHTML = `✅ 已加载 <strong>${compareExcelConfigs.length}</strong> 组角色 · 共 <strong>${totalTurns}</strong> 轮对话（上传 Excel 优先，会覆盖"同步当前配置"）`;
}

async function handleCompareExcelImport(event) {
  const file = event.target.files[0];
  if (!file) return;
  try {
    const { configs, hasMissingSessionId } = await loadConfigsFromWorkbookFile(file, { labelPrefix: '模型对比 Excel ' });
    compareExcelConfigs = configs;
    if (hasMissingSessionId) {
      showToast('⚠️ 检测到 session_id 为空：已按角色(nickname+relationship+user_nickname)自动合并多轮', 'warning', 4500);
    }
    _updateCompareExcelSummary();
    const infoEl = $('compare-config-info');
    if (infoEl) {
      infoEl.style.display = 'block';
      infoEl.innerHTML = `📥 Excel 模式 · <strong>${compareExcelConfigs.length}</strong> 组角色（${compareExcelConfigs.map(c => c.nickname || c.session_id || '未命名').slice(0, 6).join('、')}${compareExcelConfigs.length > 6 ? '…' : ''}）`;
    }
    const emptyEl = $('compare-right-empty');
    if (emptyEl) emptyEl.style.display = 'none';
    refreshTestCenterShell();
    showToast(`✅ 已加载 ${compareExcelConfigs.length} 组对比配置`, 'success');
  } catch (err) {
    showToast('导入失败: ' + err.message, 'error');
  } finally {
    event.target.value = '';
  }
}

function clearCompareExcelConfigs() {
  compareExcelConfigs = null;
  _updateCompareExcelSummary();
  const infoEl = $('compare-config-info');
  if (infoEl && !compareConfig) {
    infoEl.style.display = 'none';
    infoEl.innerHTML = '';
  }
  showToast('已清空 Excel 配置', 'info');
}

function checkProviderConflicts() {
  const box = $('compare-model-checkboxes');
  if (!box) return;
  const checked = [...box.querySelectorAll('input:checked')];
  const providerGroups = {};
  checked.forEach(input => {
    const p = input.dataset.provider || 'unknown';
    providerGroups[p] = providerGroups[p] || [];
    providerGroups[p].push(input.dataset.name || input.value);
  });
  const warnings = [];
  for (const [provider, models] of Object.entries(providerGroups)) {
    if (models.length >= 3) {
      warnings.push(`\u26a0\ufe0f ${models.length} \u4e2a\u6a21\u578b\u5171\u7528 ${provider} API\uff0c\u53ef\u80fd\u89e6\u53d1\u9650\u6d41`);
    }
  }
  let warn = $('compare-provider-warning');
  if (!warn) {
    warn = document.createElement('div');
    warn.id = 'compare-provider-warning';
    warn.style.cssText = 'margin-top:8px;display:flex;flex-direction:column;gap:4px';
    box.parentNode.insertBefore(warn, box.nextSibling);
  }
  if (warnings.length) {
    warn.innerHTML = warnings.map(w =>
      `<span style="display:inline-block;padding:4px 10px;background:#fff3cd;color:#856404;border-radius:4px;font-size:12px">${escapeHtml(w)}</span>`
    ).join('');
    warn.style.display = 'flex';
  } else {
    warn.innerHTML = '';
    warn.style.display = 'none';
  }
}

async function initComparePage() {
  const box = $('compare-model-checkboxes'); box.innerHTML = '';
  try {
    const r = await fetch('/api/models?tier=pro'); const data = await r.json();
    (data.models || data || []).forEach(m => {
      const label = document.createElement('label');
      label.style.cssText = 'display:flex;align-items:center;gap:6px;padding:8px 12px;background:var(--bg-hover);border-radius:6px;font-size:13px;cursor:pointer';
      label.innerHTML = `<input type="checkbox" value="${escapeHtml(m.id || m)}" data-name="${escapeHtml(m.name || m.id || m)}" data-provider="${escapeHtml(m.provider || '')}"> ${escapeHtml(m.name || m.id || m)}`;
      label.querySelector('input')?.addEventListener('change', () => { refreshTestCenterShell(); checkProviderConflicts(); syncToggleAllBtnText(); });
      box.appendChild(label);
    });
    syncToggleAllBtnText();
  } catch (e) { console.warn('\u6a21\u578b\u5217\u8868\u52a0\u8f7d\u5931\u8d25:', e); }
}

function loadConfigToCompare() {
  compareConfig = getFormConfig();
  const info = $('compare-config-info');
  info.style.display = 'block';
  { const _ce = $('compare-right-empty'); if (_ce) _ce.style.display = 'none'; }
  info.textContent = `✅ 已加载: ${compareConfig.nickname || '未命名'} / ${compareConfig.relationship || '暧昧'} / ${(compareConfig.turns || '').split('\n').filter(l => l.trim()).length}轮`;
  refreshTestCenterShell();
  showToast('已加载当前配置到对比测试', 'success');
}

function getABBatchTurnsFromConfig(cfg = {}) {
  return Array.isArray(cfg.turns)
    ? cfg.turns.filter(item => String(item || '').trim())
    : String(cfg.turns || '').split('\n').filter(item => item.trim());
}

function _updateABBatchExcelSummary() {
  const el = $('ab-batch-excel-summary');
  if (!el) return;
  if (!Array.isArray(abBatchExcelConfigs) || !abBatchExcelConfigs.length) {
    el.textContent = '';
    return;
  }
  const totalTurns = countConfigTurns(abBatchExcelConfigs);
  el.innerHTML = `✅ 已加载 <strong>${abBatchExcelConfigs.length}</strong> 组角色 · 共 <strong>${totalTurns}</strong> 轮对话（上传 Excel 优先，会覆盖"同步当前配置"）`;
}

function loadConfigToABBatch() {
  abBatchConfig = getFormConfig();
  const info = $('ab-batch-config-info');
  if (info) {
    info.style.display = 'block';
    info.textContent = `✅ 已加载: ${abBatchConfig.nickname || '未命名'} / ${abBatchConfig.relationship || '暧昧'} / ${getABBatchTurnsFromConfig(abBatchConfig).length}轮`;
  }
  const emptyEl = $('ab-batch-right-empty');
  if (emptyEl) emptyEl.style.display = 'none';
  switchABMode('batch', { refreshShell: false });
  refreshTestCenterShell();
  showToast('已加载当前配置到 Prompt A/B 批量测试', 'success');
}

async function handleABBatchExcelImport(event) {
  const file = event.target.files[0];
  if (!file) return;
  try {
    const { configs, hasMissingSessionId } = await loadConfigsFromWorkbookFile(file, { labelPrefix: 'Prompt A/B Excel ' });
    abBatchExcelConfigs = configs;
    if (hasMissingSessionId) {
      showToast('⚠️ 检测到 session_id 为空：已按角色(nickname+relationship+user_nickname)自动合并多轮', 'warning', 4500);
    }
    _updateABBatchExcelSummary();
    const infoEl = $('ab-batch-config-info');
    if (infoEl) {
      infoEl.style.display = 'block';
      infoEl.innerHTML = `📥 Excel 模式 · <strong>${abBatchExcelConfigs.length}</strong> 组角色（${abBatchExcelConfigs.map(c => c.nickname || c.session_id || '未命名').slice(0, 6).join('、')}${abBatchExcelConfigs.length > 6 ? '…' : ''}）`;
    }
    const emptyEl = $('ab-batch-right-empty');
    if (emptyEl) emptyEl.style.display = 'none';
    switchABMode('batch', { refreshShell: false });
    refreshTestCenterShell();
    showToast(`✅ 已加载 ${abBatchExcelConfigs.length} 组 A/B 配置`, 'success');
  } catch (err) {
    showToast('导入失败: ' + err.message, 'error');
  } finally {
    event.target.value = '';
  }
}

function clearABBatchExcelConfigs() {
  abBatchExcelConfigs = null;
  _updateABBatchExcelSummary();
  refreshTestCenterShell();
}

function resolveABBatchConfigs() {
  if (Array.isArray(abBatchExcelConfigs) && abBatchExcelConfigs.length) {
    return abBatchExcelConfigs;
  }
  if (!abBatchConfig) return [];
  const overrideTurns = getInputValue('ab-batch-turns')
    .split('\n')
    .map(item => item.trim())
    .filter(Boolean);
  const merged = { ...abBatchConfig };
  if (overrideTurns.length) {
    merged.turns = overrideTurns;
  }
  return [merged];
}

function buildABBatchBranchItem(cfg, {
  groupKey,
  variant,
  label,
  modelId,
  promptVersion,
  turns,
  dryRun,
} = {}) {
  const payload = buildConversationRunPayload(cfg, {
    modelId,
    turns,
    dryRun: !!dryRun,
  });
  payload.prompt_version = String(promptVersion || payload.prompt_version || '').trim();
  payload.auto_scoring = !dryRun;
  return {
    key: `${groupKey}:${variant}`,
    label,
    relationship: String(cfg.relationship || '').trim(),
    model_id: modelId,
    planned_turns: turns.length,
    payload,
  };
}

function buildABBatchOrchestrationPayload(configs, { dryRun, roleConcurrency = DEFAULT_AB_BATCH_ROLE_CONCURRENCY } = {}) {
  const baseModel = getInputValue('ab-base-model').trim();
  const compareModel = getInputValue('ab-compare-model').trim();
  const basePrompt = getInputValue('ab-base-prompt').trim();
  const comparePrompt = getInputValue('ab-compare-prompt').trim();
  const normalizedRoleConcurrency = normalizeABBatchRoleConcurrency(roleConcurrency, DEFAULT_AB_BATCH_ROLE_CONCURRENCY);
  const runConcurrency = getABBatchItemConcurrency(normalizedRoleConcurrency);
  return {
    kind: 'ab',
    title: `Prompt A/B ${new Date().toLocaleString('zh-CN', { hour12: false })}`,
    concurrency: runConcurrency,
    groups: configs.map((cfg, rowIndex) => {
      const turns = getABBatchTurnsFromConfig(cfg);
      const groupKey = String(cfg.session_id || cfg.nickname || '').trim() || `ab:${rowIndex + 1}`;
      return {
        key: groupKey,
        label: String(cfg.nickname || cfg.session_id || `配置${rowIndex + 1}`).trim(),
        relationship: String(cfg.relationship || '').trim(),
        planned_turns: turns.length,
        items: [
          buildABBatchBranchItem(cfg, {
            groupKey,
            variant: 'base',
            label: '控制组',
            modelId: baseModel,
            promptVersion: basePrompt,
            turns,
            dryRun,
          }),
          buildABBatchBranchItem(cfg, {
            groupKey,
            variant: 'compare',
            label: '实验组',
            modelId: compareModel,
            promptVersion: comparePrompt,
            turns,
            dryRun,
          }),
        ],
      };
    }),
  };
}

function renderABBatchControlRow() {
  const row = $('ab-batch-control-row');
  if (!row) return;
  const normalizedStatus = String(state.abBatchRunStatus || '').trim().toLowerCase();
  const isActive = !!state.abBatchRunId && !isTerminalOrchestrationStatus(normalizedStatus);
  const isPaused = ['paused', 'interrupted'].includes(normalizedStatus);
  const isCancelling = normalizedStatus === 'cancelling';
  row.style.display = isActive ? 'flex' : 'none';
  if ($('btn-ab-batch-pause')) $('btn-ab-batch-pause').style.display = isActive && !isPaused && !isCancelling ? 'inline-flex' : 'none';
  if ($('btn-ab-batch-resume')) $('btn-ab-batch-resume').style.display = isActive && isPaused && !isCancelling ? 'inline-flex' : 'none';
  if ($('btn-ab-batch-stop')) {
    $('btn-ab-batch-stop').style.display = isActive ? 'inline-flex' : 'none';
    $('btn-ab-batch-stop').disabled = isCancelling;
    $('btn-ab-batch-stop').textContent = isCancelling ? '⏳ 停止中...' : '⏹ 停止';
  }
  updateOrchestrationActionButtonState();
}

function hydrateABBatchConfigsFromRun(run) {
  const manifestGroups = Array.isArray(getOrchestrationManifest(run).groups)
    ? getOrchestrationManifest(run).groups
    : [];
  const stateGroups = Array.isArray(run?.groups) ? run.groups : [];
  return stateGroups.map((group, groupIndex) => {
    const manifestGroup = manifestGroups[groupIndex] || {};
    const firstPayload = ((manifestGroup.items || [])[0] || {}).payload || {};
    return {
      nickname: group.label || manifestGroup.label || firstPayload.character?.Role_Nickname || '',
      relationship: group.relationship || manifestGroup.relationship || firstPayload.context?.relationship || '',
      turns: Array.isArray(firstPayload.turns) ? firstPayload.turns.filter(item => String(item || '').trim()) : [],
    };
  });
}

function summarizeABBatchRunActivity(run) {
  const summary = run?.summary || {};
  return {
    generating: Number(summary.running_items || 0),
    scoring: Number(summary.scoring_items || 0),
    pendingScoring: Number(summary.pending_scoring_items || 0),
    queued: Number(summary.queued_items || 0),
  };
}

function updateABBatchProgress(run) {
  const summary = run?.summary || {};
  const total = Number(summary.total_items || 0);
  const terminal = Number(summary.terminal_items || 0);
  const activity = summarizeABBatchRunActivity(run);
  const parts = [];
  if (activity.generating > 0) parts.push(`生成中 ${activity.generating}`);
  if (activity.scoring > 0) parts.push(`评分活跃 ${activity.scoring}`);
  if (activity.pendingScoring > 0) parts.push(`待打分 ${activity.pendingScoring}`);
  if (activity.queued > 0) parts.push(`排队中 ${activity.queued}`);
  if ($('ab-batch-progress-text')) {
    $('ab-batch-progress-text').textContent = `${run?.title || 'Prompt A/B 批量'} · ${getConversationStatusLabel(run?.status || '')} · 已完成 ${terminal}/${total || 0}${parts.length ? ` · ${parts.join(' · ')}` : ''}`;
  }
  if ($('ab-batch-progress-count')) $('ab-batch-progress-count').textContent = `${terminal}/${total || 0}`;
  if ($('ab-batch-progress-fill')) $('ab-batch-progress-fill').style.width = total ? `${((terminal / total) * 100).toFixed(1)}%` : '0%';
}

function renderABBatchResults(run) {
  const container = $('ab-batch-cards');
  if (!container) return;
  const groups = Array.isArray(run?.groups) ? run.groups : [];
  if (!groups.length) {
    container.innerHTML = '';
    return;
  }
  container.innerHTML = groups.map((group, groupIndex) => {
    const manifestGroup = getOrchestrationGroupManifest(run, groupIndex);
    const itemsHtml = (group.items || []).map((item, itemIndex) => {
      const manifestItem = getOrchestrationItemManifest(run, groupIndex, itemIndex);
      const avgScore = Number.parseFloat(item.avg_score);
      const itemColor = itemIndex === 0 ? 'var(--text-primary)' : '#10b981';
      return `<div style="background:${itemIndex === 0 ? 'var(--bg-hover)' : '#10b9810d'};border:1px solid ${itemIndex === 0 ? 'var(--border-light)' : '#10b98140'};border-radius:12px;display:flex;flex-direction:column">
        <div style="padding:12px;border-bottom:1px solid ${itemIndex === 0 ? 'var(--border-light)' : '#10b98140'};display:flex;justify-content:space-between;gap:8px;align-items:flex-start">
          <div>
            <div style="font-weight:600;color:${itemColor}">${escapeHtml(item.label || (itemIndex === 0 ? '控制组' : '实验组'))}</div>
            <div style="font-size:11px;color:var(--text-tertiary);margin-top:4px">${escapeHtml(manifestItem.payload?.model_id || item.model_id || '未选择模型')} · ${escapeHtml(manifestItem.payload?.prompt_version || '默认提示词')}</div>
          </div>
          <span class="status-badge ${getCompareStatusBadgeClass(item.status || 'pending')}">${escapeHtml(getConversationStatusLabel(item.status || 'pending'))}</span>
        </div>
        <div style="padding:12px;display:grid;grid-template-columns:repeat(3,1fr);gap:8px">
          <div style="text-align:center;padding:10px;background:var(--bg-surface);border-radius:8px"><div style="font-size:18px;font-weight:700">${Number(item.turn_count || 0)}</div><div style="font-size:11px;color:var(--text-tertiary)">完成轮次</div></div>
          <div style="text-align:center;padding:10px;background:var(--bg-surface);border-radius:8px"><div style="font-size:18px;font-weight:700">${Number(item.avg_chars || 0)}</div><div style="font-size:11px;color:var(--text-tertiary)">平均字数</div></div>
          <div style="text-align:center;padding:10px;background:var(--bg-surface);border-radius:8px"><div style="font-size:18px;font-weight:700;color:${Number.isFinite(avgScore) ? getScoreColor(avgScore) : 'var(--text-tertiary)'}">${Number.isFinite(avgScore) ? avgScore.toFixed(1) : '--'}</div><div style="font-size:11px;color:var(--text-tertiary)">AI均分</div></div>
        </div>
        <div style="padding:0 12px 12px;font-size:11px;color:var(--text-tertiary);display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap">
          <span>计划 ${Number(item.planned_turns || group.planned_turns || manifestGroup.planned_turns || 0)} 轮</span>
          <span>已打分 ${Number(item.scored_turns || 0)} / 失败 ${Number(item.failed_turns || 0)} / 跳过 ${Number(item.skipped_turns || 0)}</span>
        </div>
        ${item.error ? `<div style="padding:0 12px 12px;font-size:12px;line-height:1.6;color:var(--danger-color)">${escapeHtml(item.error)}</div>` : ''}
        ${item.conversation_id ? `<div style="padding:0 12px 12px"><button class="btn btn-secondary" type="button" style="width:100%;justify-content:center" onclick="viewConversation('${item.conversation_id}')">📖 查看对话详情</button></div>` : ''}
      </div>`;
    }).join('');
    return `<div style="background:var(--bg-surface);border:1px solid var(--border-light);border-radius:14px;padding:16px;display:flex;flex-direction:column;gap:12px">
      <div style="display:flex;justify-content:space-between;gap:12px;align-items:flex-start">
        <div>
          <div style="font-size:15px;font-weight:600;color:var(--text-primary)">${escapeHtml(group.label || manifestGroup.label || `配置${groupIndex + 1}`)}</div>
          <div style="font-size:12px;color:var(--text-tertiary);margin-top:4px">${escapeHtml(group.relationship || manifestGroup.relationship || '未填写关系')} · ${Number(group.planned_turns || manifestGroup.planned_turns || 0)} 轮</div>
        </div>
        <span class="status-badge ${getCompareStatusBadgeClass(group.status || 'pending')}">${escapeHtml(getConversationStatusLabel(group.status || 'pending'))}</span>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">${itemsHtml}</div>
    </div>`;
  }).join('');
}

function applyABBatchOrchestrationRun(run) {
  if (!run) return;
  _abBatchRunSnapshot = run;
  state.abBatchRunId = run.id || '';
  state.abBatchRunStatus = String(run.status || '').trim().toLowerCase();
  const roleConcurrency = getABBatchRoleConcurrencyFromRun(run);
  const branchConcurrency = getABBatchItemConcurrency(roleConcurrency);
  syncABBatchConcurrencyInput(roleConcurrency);
  const recoveredConfigs = hydrateABBatchConfigsFromRun(run);
  abBatchExcelConfigs = recoveredConfigs.length > 1 ? recoveredConfigs : null;
  abBatchConfig = recoveredConfigs.length === 1 ? recoveredConfigs[0] : null;
  _updateABBatchExcelSummary();
  const infoEl = $('ab-batch-config-info');
  if (infoEl) {
    const roleCount = Number(run.groups?.length || 0);
    infoEl.style.display = 'block';
    infoEl.innerHTML = `🧪 ${roleCount} 组角色 × 2 个分支 · 角色并发 <strong>${roleConcurrency}</strong> · 总分支并发 <strong>${branchConcurrency}</strong> · 当前状态：<strong>${escapeHtml(getConversationStatusLabel(run.status || ''))}</strong>`;
  }
  if ($('ab-batch-right-empty')) $('ab-batch-right-empty').style.display = 'none';
  if ($('ab-batch-progress')) $('ab-batch-progress').style.display = 'block';
  if ($('ab-batch-results')) $('ab-batch-results').style.display = 'block';
  updateABBatchProgress(run);
  renderABBatchResults(run);
  const startBtn = $('btn-ab-batch-start');
  if (startBtn) {
    const isActive = !isTerminalOrchestrationStatus(run.status);
    startBtn.disabled = isActive;
    startBtn.textContent = isActive ? '⏳ 批量测试中...' : '🚀 开始 Prompt A/B 批量测试';
  }
  switchABMode('batch', { refreshShell: false });
  refreshTestCenterShell();
  renderABBatchControlRow();
}

function finalizeABBatchOrchestrationRun(run) {
  applyABBatchOrchestrationRun(run);
  stopABBatchRunPolling();
  renderABBatchControlRow();
  if (_abBatchLastTerminalRunId === run.id) return;
  _abBatchLastTerminalRunId = run.id;
  const status = String(run.status || '').trim().toLowerCase();
  const successCount = Number(run.summary?.completed_items || 0);
  const totalItems = Number(run.summary?.total_items || 0);
  const failCount = Number(run.summary?.failed_items || 0) + Number(run.summary?.cancelled_items || 0);
  showToast(
    status === 'cancelled'
      ? 'Prompt A/B 批量测试已取消'
      : `Prompt A/B 批量测试已完成：成功 ${successCount}/${totalItems}${failCount ? `（未完成 ${failCount}）` : ''}`,
    status === 'cancelled' || failCount > 0 ? 'warning' : 'success',
  );
  void notifyTaskCompletion(status === 'cancelled' ? 'Prompt A/B 批量测试已取消' : 'Prompt A/B 批量测试已完成', {
    body: `成功 ${successCount}/${totalItems}${failCount ? `，未完成 ${failCount}` : ''}`,
  });
}

function pollABBatchRun(runId) {
  stopABBatchRunPolling();
  const tick = async () => {
    try {
      const run = await fetchOrchestrationRun(runId);
      if (isTerminalOrchestrationStatus(run.status)) {
        finalizeABBatchOrchestrationRun(run);
        return;
      }
      applyABBatchOrchestrationRun(run);
      _abBatchRunPollTimer = setTimeout(tick, 1200);
    } catch (error) {
      showOrchestrationFetchErrorToast('ab-poll', 'Prompt A/B 批量状态轮询失败: ' + error.message);
      _abBatchRunPollTimer = setTimeout(tick, 2500);
    }
  };
  _abBatchRunPollTimer = setTimeout(tick, 1200);
}

async function startABBatchTest() {
  if (state.abBatchRunId && !isTerminalOrchestrationStatus(state.abBatchRunStatus)) {
    showToast('当前已有进行中的 Prompt A/B 批量任务，请先暂停/停止或等待完成', 'warning');
    return;
  }
  const configs = resolveABBatchConfigs();
  if (!configs.length) {
    showToast('请先同步当前配置或上传 Excel', 'warning');
    return;
  }
  const turnsMissing = configs.some(cfg => !getABBatchTurnsFromConfig(cfg).length);
  if (turnsMissing) {
    showToast('存在 turns 为空的配置，请先补齐多轮输入', 'warning');
    return;
  }
  const baseModel = getInputValue('ab-base-model').trim();
  const compareModel = getInputValue('ab-compare-model').trim();
  if (!baseModel || !compareModel) {
    showToast('请选择控制组和实验组模型', 'warning');
    return;
  }
  await requestTaskNotificationPermission();
  switchABMode('batch', { refreshShell: false });
  const dryRun = !!$('ab-batch-dryrun')?.checked;
  const roleConcurrency = getABBatchConcurrency();
  const branchConcurrency = getABBatchItemConcurrency(roleConcurrency);
  try {
    const run = await createOrchestrationRun(buildABBatchOrchestrationPayload(configs, { dryRun, roleConcurrency }));
    applyABBatchOrchestrationRun(run);
    if (isTerminalOrchestrationStatus(run.status)) {
      finalizeABBatchOrchestrationRun(run);
      return;
    }
    pollABBatchRun(run.id);
    showToast(`Prompt A/B 批量任务已创建：${configs.length} 组角色 × 2 个分支，角色并发 ${roleConcurrency}（总分支并发 ${branchConcurrency}）`, 'success');
  } catch (error) {
    showToast('启动 Prompt A/B 批量测试失败: ' + error.message, 'error');
    _abBatchRunSnapshot = null;
    state.abBatchRunId = '';
    state.abBatchRunStatus = '';
    renderABBatchControlRow();
    const startBtn = $('btn-ab-batch-start');
    if (startBtn) {
      startBtn.disabled = false;
      startBtn.textContent = '🚀 开始 Prompt A/B 批量测试';
    }
  }
}

async function pauseABBatchTest() {
  if (!state.abBatchRunId || isTerminalOrchestrationStatus(state.abBatchRunStatus) || state.abBatchRunStatus === 'cancelling') return;
  try {
    const run = await controlOrchestrationRun(state.abBatchRunId, 'pause');
    applyABBatchOrchestrationRun(run);
    pollABBatchRun(run.id);
    showToast('已暂停 Prompt A/B 批量任务', 'info');
  } catch (error) {
    showToast('暂停 Prompt A/B 批量测试失败: ' + error.message, 'error');
  }
}

async function resumeABBatchTest() {
  if (!state.abBatchRunId || isTerminalOrchestrationStatus(state.abBatchRunStatus) || state.abBatchRunStatus === 'cancelling') return;
  try {
    const run = await controlOrchestrationRun(state.abBatchRunId, 'resume');
    applyABBatchOrchestrationRun(run);
    pollABBatchRun(run.id);
    showToast('已继续 Prompt A/B 批量任务', 'success');
  } catch (error) {
    showToast('继续 Prompt A/B 批量测试失败: ' + error.message, 'error');
  }
}

async function stopABBatchTest() {
  if (!state.abBatchRunId || isTerminalOrchestrationStatus(state.abBatchRunStatus)) return;
  if (state.abBatchRunStatus === 'cancelling') {
    showToast('Prompt A/B 批量任务正在停止中，请等待当前轮次收口', 'info');
    return;
  }
  try {
    const run = await controlOrchestrationRun(state.abBatchRunId, 'cancel');
    applyABBatchOrchestrationRun(run);
    if (isTerminalOrchestrationStatus(run.status)) {
      finalizeABBatchOrchestrationRun(run);
      return;
    }
    pollABBatchRun(run.id);
    showToast('已发送停止请求，等待 Prompt A/B 批量任务收口', 'info');
  } catch (error) {
    showToast('停止 Prompt A/B 批量测试失败: ' + error.message, 'error');
  }
}
// 单个 config × N 模型，创建 N 个子对话并 Promise.all 等待完成，返回 [{model, status, convId, ...}]
async function _runCompareCellsForConfig(cfg, models, { dryRun, tracker, onCellUpdate, onCellDone }) {
  const turns = Array.isArray(cfg.turns)
    ? cfg.turns.filter(item => String(item || '').trim())
    : String(cfg.turns || '').split('\n').filter(l => l.trim());
  const plannedTurns = turns.length;
  const notifyImmediateCells = (payloads) => {
    payloads.forEach(payload => {
      onCellUpdate && onCellUpdate(payload);
      onCellDone && onCellDone(payload);
    });
    return payloads;
  };
  if (!turns.length) {
    return notifyImmediateCells(models.map(m => ({
      model: m,
      plannedTurns: 0,
      turnCount: 0,
      avgChars: 0,
      avgScore: null,
      status: 'failed',
      convId: null,
      error: 'turns 为空',
    })));
  }

  const body = buildConversationRunPayload({ ...cfg, model_pro: models[0].id }, {
    modelId: models[0].id,
    modelIds: models.map(m => m.id),
    turns,
    dryRun: !!dryRun,
    compareMode: 'model',
  });

  let convItems;
  try {
    const r = await fetch('/api/conversations', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.detail || r.statusText || '创建对比任务失败');
    convItems = Array.isArray(data.conversations) ? data.conversations : [];
  } catch (err) {
    // 整个 config 的 POST 就失败了 → 所有模型标 failed
    return notifyImmediateCells(models.map(m => ({
      model: m,
      plannedTurns,
      turnCount: 0,
      avgChars: 0,
      avgScore: null,
      status: 'failed',
      convId: null,
      error: err.message,
    })));
  }

  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  return Promise.all(models.map((model, index) => {
    const convId = (convItems[index] || {}).id;
    if (!convId) {
      const cell = {
        model,
        plannedTurns,
        turnCount: 0,
        avgChars: 0,
        avgScore: null,
        status: 'failed',
        convId: null,
        error: '缺少子会话 ID',
      };
      onCellUpdate && onCellUpdate(cell);
      onCellDone && onCellDone(cell);
      return Promise.resolve(cell);
    }
    return new Promise((resolve) => {
      const MAX_TOTAL_WAIT_MS = 2 * 60 * 60 * 1000;
      const QUEUED_IDLE_TIMEOUT_MS = 60 * 60 * 1000;
      const RUNNING_IDLE_TIMEOUT_MS = 10 * 60 * 1000;
      const MAX_RECONNECTS = 3;

      let ws = null;
      let stage = 'queued';
      let latestMessage = '';
      let latestAvgScore = null;
      let reconciling = false;
      let reconnects = 0;
      let totalChars = 0;
      let finalized = false;
      let idleTimer = null;
      let totalTimer = null;
      const startedAt = Date.now();
      const seenTurns = new Map();

      const computeStats = () => {
        const turnCount = seenTurns.size;
        return {
          turnCount,
          avgChars: turnCount ? Math.round(totalChars / turnCount) : 0,
        };
      };

      const buildCellPayload = (overrides = {}) => {
        const stats = computeStats();
        return {
          model,
          convId,
          plannedTurns,
          turnCount: stats.turnCount,
          avgChars: stats.avgChars,
          avgScore: latestAvgScore,
          status: stage,
          message: latestMessage,
          error: '',
          ...overrides,
        };
      };

      const publishCell = (overrides = {}) => {
        const payload = buildCellPayload(overrides);
        onCellUpdate && onCellUpdate(payload);
        return payload;
      };

      const cleanup = () => {
        try { if (idleTimer) clearTimeout(idleTimer); } catch (_) { /* ignore */ }
        try { if (totalTimer) clearTimeout(totalTimer); } catch (_) { /* ignore */ }
      };

      const enrichCompletedCellScore = async () => {
        try {
          const avgScore = await pollConversationScoreAvg(convId, { timeoutMs: 20000, intervalMs: 1000 });
          if (avgScore === null || avgScore === undefined) return;
          latestAvgScore = Number(avgScore.toFixed(2));
          publishCell({ status: 'completed', avgScore: latestAvgScore });
        } catch (_) {
          // 分数可能还没落库，保持已完成即可
        }
      };

      const finalize = (overrides = {}, { enrichScore = false } = {}) => {
        if (finalized) return;
        finalized = true;
        cleanup();
        const payload = buildCellPayload(overrides);
        onCellUpdate && onCellUpdate(payload);
        onCellDone && onCellDone(payload);
        resolve(payload);
        if (enrichScore && convId) {
          void enrichCompletedCellScore();
        }
      };

      const applyTurn = (turnData) => {
        const turnNumber = Number.parseInt(String(turnData?.turn || turnData?.turn_order || ''), 10);
        if (!Number.isFinite(turnNumber) || turnNumber <= 0) return;
        const charLength = String(turnData?.ai_output || turnData?.assistant_reply || '').length;
        const prevLength = seenTurns.get(turnNumber);
        if (prevLength === undefined) {
          seenTurns.set(turnNumber, charLength);
          totalChars += charLength;
        } else if (prevLength !== charLength) {
          seenTurns.set(turnNumber, charLength);
          totalChars += (charLength - prevLength);
        }
      };

      const absorbConversationResults = (conversation) => {
        const results = Array.isArray(conversation && (conversation.results || conversation.turns))
          ? (conversation.results || conversation.turns)
          : [];
        results.forEach(item => applyTurn(item));
      };

      const fetchConversationDetail = async () => {
        const r2 = await fetch(`/api/conversations/${encodeURIComponent(convId)}`);
        const data = await r2.json().catch(() => ({}));
        if (!r2.ok) throw new Error(data.detail || r2.statusText || `HTTP ${r2.status}`);
        return data;
      };

      const scheduleIdleCheck = () => {
        if (finalized) return;
        try { if (idleTimer) clearTimeout(idleTimer); } catch (_) { /* ignore */ }
        const timeoutMs = stage === 'queued' ? QUEUED_IDLE_TIMEOUT_MS : RUNNING_IDLE_TIMEOUT_MS;
        idleTimer = setTimeout(() => {
          reconcile('idle-timeout');
        }, timeoutMs);
      };

      const reconcile = async (reason) => {
        if (finalized || reconciling) return;
        reconciling = true;
        try {
          const conversation = await fetchConversationDetail();
          absorbConversationResults(conversation);
          const conversationStatus = String(conversation.status || '').trim().toLowerCase();
          if (conversationStatus === 'completed') {
            stage = 'completed';
            latestMessage = '';
            try { if (ws) ws.close(); } catch (_) { /* ignore */ }
            finalize({ status: 'completed' }, { enrichScore: true });
            return;
          }
          if (conversationStatus === 'failed') {
            stage = 'failed';
            latestMessage = '';
            try { if (ws) ws.close(); } catch (_) { /* ignore */ }
            finalize({ status: 'failed', error: '任务执行失败' });
            return;
          }
          if (conversationStatus === 'cancelled') {
            stage = 'cancelled';
            latestMessage = '';
            try { if (ws) ws.close(); } catch (_) { /* ignore */ }
            finalize({ status: 'cancelled', error: '任务已取消' });
            return;
          }
          if (Date.now() - startedAt > MAX_TOTAL_WAIT_MS) {
            stage = 'timeout';
            latestMessage = '';
            try { if (ws) ws.close(); } catch (_) { /* ignore */ }
            finalize({
              status: 'timeout',
              error: `前端等待超时（${reason}），后端状态：${conversationStatus || 'unknown'}。可在历史记录中继续查看`,
            });
            return;
          }
          if (conversationStatus === 'queued' || conversationStatus === 'pending') {
            stage = 'queued';
            latestMessage = conversation.queue_position ? `队列位置 ${conversation.queue_position}` : '';
            tracker && tracker.setStage('排队中');
            publishCell({ status: 'queued' });
          } else {
            stage = 'running';
            latestMessage = '';
            tracker && tracker.setStage('模型处理中');
            publishCell({ status: 'running' });
          }
          const wsClosed = !ws || ws.readyState === WebSocket.CLOSED || ws.readyState === WebSocket.CLOSING;
          if (wsClosed && reconnects < MAX_RECONNECTS) {
            reconnects++;
            setTimeout(() => {
              connectWebSocketOnce();
            }, Math.min(2000, 400 * reconnects));
          }
          scheduleIdleCheck();
        } catch (err) {
          if (Date.now() - startedAt > MAX_TOTAL_WAIT_MS) {
            stage = 'timeout';
            latestMessage = '';
            finalize({
              status: 'timeout',
              error: `等待超时且状态复核失败：${err && err.message ? err.message : '未知错误'}`,
            });
            return;
          }
          scheduleIdleCheck();
        } finally {
          reconciling = false;
        }
      };

      const connectWebSocketOnce = () => {
        if (finalized) return;
        ws = new WebSocket(`${proto}//${location.host}/ws/conversations/${convId}`);
        ws.onmessage = (e) => {
          const msg = JSON.parse(e.data);
          if (msg.type === 'turn_result' || msg.type === 'turn') {
            stage = 'running';
            latestMessage = '';
            tracker && tracker.setStage('结果整理中');
            applyTurn(msg.data || msg);
            publishCell({ status: 'running' });
          } else if (msg.type === 'queued') {
            stage = 'queued';
            latestMessage = msg.message || '';
            tracker && tracker.setStage('排队中');
            publishCell({ status: 'queued' });
          } else if (msg.type === 'started' || msg.type === 'resumed') {
            stage = 'running';
            latestMessage = msg.message || '';
            tracker && tracker.setStage('模型处理中');
            publishCell({ status: 'running' });
          } else if (msg.type === 'turn_started') {
            stage = 'running';
            const turnNum = msg.turn || 0;
            const totalTurns = msg.total_turns || plannedTurns;
            latestMessage = `正在生成第 ${turnNum}/${totalTurns} 轮`;
            tracker && tracker.setStage(`第 ${turnNum}/${totalTurns} 轮`);
            publishCell({ status: 'running', message: latestMessage });
          } else if (msg.type === 'completed' || msg.type === 'done') {
            stage = 'completed';
            latestMessage = '';
            try { ws.close(); } catch (_) { /* ignore */ }
            finalize({ status: 'completed' }, { enrichScore: true });
          } else if (msg.type === 'cancelled') {
            stage = 'cancelled';
            latestMessage = '';
            try { ws.close(); } catch (_) { /* ignore */ }
            finalize({ status: 'cancelled', error: msg.message || '任务已取消' });
          } else if (msg.type === 'error') {
            stage = 'failed';
            latestMessage = '';
            try { ws.close(); } catch (_) { /* ignore */ }
            finalize({ status: 'failed', error: msg.error || msg.message || '执行失败' });
          }
          scheduleIdleCheck();
        };
        ws.onerror = () => {
          // 交给 onclose + 状态复核兜底，避免把暂时性断连直接判死
        };
        ws.onclose = () => {
          if (finalized) return;
          reconcile('ws-closed');
        };
      };

      onCellUpdate && onCellUpdate({
        model,
        convId,
        plannedTurns,
        turnCount: 0,
        avgChars: 0,
        avgScore: null,
        status: 'queued',
        message: '',
        error: '',
      });
      totalTimer = setTimeout(() => {
        reconcile('total-timeout');
      }, MAX_TOTAL_WAIT_MS);
      connectWebSocketOnce();
      scheduleIdleCheck();
    });
  }));
}

async function startModelCompare() {
  if (state.compareRunId && !isTerminalOrchestrationStatus(state.compareRunStatus)) {
    showToast('当前已有进行中的模型对比任务，请先暂停/停止或等待完成', 'warning');
    return;
  }
  const checked = [...$('compare-model-checkboxes').querySelectorAll('input:checked')];
  if (checked.length < 2) { showToast('请至少选择 2 个模型进行对比', 'warning'); return; }
  await requestTaskNotificationPermission();

  // 优先使用 Excel 配置；否则退回到单角色 compareConfig
  const excelMode = Array.isArray(compareExcelConfigs) && compareExcelConfigs.length > 0;
  let configs;
  if (excelMode) {
    configs = compareExcelConfigs;
  } else if (compareConfig) {
    // 单角色：使用 textarea 里的 turns 覆盖（如果有）
    const compareTurnsEl = $('compare-turns');
    const overrideTurns = compareTurnsEl && compareTurnsEl.value.trim()
      ? compareTurnsEl.value.trim().split('\n').filter(l => l.trim())
      : null;
    const mergedCfg = { ...compareConfig };
    if (overrideTurns) mergedCfg.turns = overrideTurns;
    configs = [mergedCfg];
  } else {
    showToast('请先点击「🔄 同步当前对话配置」或「📥 上传 Excel」加载配置', 'warning');
    return;
  }

  const models = checked.map(c => ({ id: c.value, name: c.dataset.name }));
  const dryRun = !!$('compare-dryrun').checked;
  try {
    const run = await createOrchestrationRun(buildCompareOrchestrationPayload(configs, models, { dryRun }));
    applyCompareOrchestrationRun(run);
    if (isTerminalOrchestrationStatus(run.status)) {
      finalizeCompareOrchestrationRun(run);
      return;
    }
    pollCompareRun(run.id);
    showToast(
      excelMode
        ? `模型对比任务已创建：${configs.length} 组角色 × ${models.length} 个模型`
        : `模型对比任务已创建：${models.length} 个模型`,
      'success',
    );
  } catch (e) {
    showToast('启动模型对比失败: ' + e.message, 'error');
    _compareRunSnapshot = null;
    closeAllCompareScoreSockets({ clearState: true });
    state.compareRunId = '';
    state.compareRunStatus = '';
    state.compareRetryableItems = 0;
    renderCompareControlRow();
    const startBtn = $('btn-compare-start');
    if (startBtn) {
      startBtn.disabled = false;
      startBtn.textContent = '🚀 开始横向对比测试';
    }
  }
}

async function pauseCompareTest() {
  if (!state.compareRunId || isTerminalOrchestrationStatus(state.compareRunStatus) || state.compareRunStatus === 'cancelling') return;
  try {
    const run = await controlOrchestrationRun(state.compareRunId, 'pause');
    applyCompareOrchestrationRun(run);
    pollCompareRun(run.id);
    showToast('已暂停模型对比任务', 'info');
  } catch (e) {
    showToast('暂停模型对比失败: ' + e.message, 'error');
  }
}

async function resumeCompareTest() {
  if (!state.compareRunId || isTerminalOrchestrationStatus(state.compareRunStatus) || state.compareRunStatus === 'cancelling') return;
  try {
    const run = await controlOrchestrationRun(state.compareRunId, 'resume');
    applyCompareOrchestrationRun(run);
    pollCompareRun(run.id);
    showToast('已继续模型对比任务', 'success');
  } catch (e) {
    showToast('继续模型对比失败: ' + e.message, 'error');
  }
}

async function stopCompareTest() {
  if (!state.compareRunId || isTerminalOrchestrationStatus(state.compareRunStatus)) return;
  if (state.compareRunStatus === 'cancelling') {
    showToast('模型对比任务正在停止中，请等待当前轮次收口', 'info');
    return;
  }
  try {
    const run = await controlOrchestrationRun(state.compareRunId, 'cancel');
    applyCompareOrchestrationRun(run);
    if (isTerminalOrchestrationStatus(run.status)) {
      finalizeCompareOrchestrationRun(run);
      return;
    }
    pollCompareRun(run.id);
    showToast('已发送停止请求，等待模型对比任务收口', 'info');
  } catch (e) {
    showToast('停止模型对比失败: ' + e.message, 'error');
  }
}

function buildCompareRetryPayloadFromRun(run) {
  const manifestGroups = Array.isArray(getOrchestrationManifest(run).groups)
    ? getOrchestrationManifest(run).groups
    : [];
  const retryGroups = [];
  (run?.groups || []).forEach((group, groupIndex) => {
    const manifestGroup = manifestGroups[groupIndex] || {};
    const items = [];
    (manifestGroup.items || []).forEach((manifestItem, itemIndex) => {
      const stateItem = (group.items || [])[itemIndex] || {};
      const status = String(stateItem.status || 'pending').trim().toLowerCase();
      if (status === 'completed') return;
      items.push({
        key: manifestItem.key || stateItem.key || `${group.key || `compare:${groupIndex + 1}`}:retry:${itemIndex + 1}`,
        label: manifestItem.label || stateItem.label || manifestItem.model_id || stateItem.model_id || `模型${itemIndex + 1}`,
        relationship: manifestItem.relationship || stateItem.relationship || group.relationship || '',
        model_id: manifestItem.model_id || stateItem.model_id || '',
        planned_turns: Number(manifestItem.planned_turns || stateItem.planned_turns || group.planned_turns || 0),
        payload: { ...(manifestItem.payload || {}) },
      });
    });
    if (!items.length) return;
    retryGroups.push({
      key: manifestGroup.key || group.key || `compare:retry:${groupIndex + 1}`,
      label: manifestGroup.label || group.label || `配置${groupIndex + 1}`,
      relationship: manifestGroup.relationship || group.relationship || '',
      planned_turns: Number(manifestGroup.planned_turns || group.planned_turns || 0),
      items,
    });
  });
  const concurrency = retryGroups.reduce((maxValue, group) => Math.max(maxValue, group.items.length), 1);
  return {
    kind: 'compare',
    title: `模型对比重试 ${new Date().toLocaleString('zh-CN', { hour12: false })}`,
    concurrency: Math.max(1, Math.min(concurrency, MAX_BATCH_CONCURRENCY)),
    groups: retryGroups,
  };
}

async function retryIncompleteCompareItems() {
  if (!state.compareRunId) {
    showToast('当前没有可重试的模型对比任务', 'warning');
    return;
  }
  if (!isTerminalOrchestrationStatus(state.compareRunStatus)) {
    showToast('请先等待当前模型对比任务结束后再重试未完成项', 'warning');
    return;
  }
  const btn = $('btn-compare-retry');
  const originalText = btn ? btn.textContent : '';
  if (btn) {
    btn.disabled = true;
    btn.textContent = '重试中...';
  }
  try {
    const latestRun = await fetchOrchestrationRun(state.compareRunId);
    const retryableCount = countCompareRetryableItems(latestRun);
    if (!retryableCount) {
      showToast('当前没有未完成的模型对比项', 'info');
      return;
    }
    const payload = buildCompareRetryPayloadFromRun(latestRun);
    if (!payload.groups.length) {
      showToast('未找到可重试的模型对比项', 'warning');
      return;
    }
    const retryRun = await createOrchestrationRun(payload);
    applyCompareOrchestrationRun(retryRun);
    if (isTerminalOrchestrationStatus(retryRun.status)) {
      finalizeCompareOrchestrationRun(retryRun);
      return;
    }
    pollCompareRun(retryRun.id);
    showToast(`已重新发起 ${retryableCount} 个未完成的模型对比项`, 'success');
  } catch (e) {
    showToast('重试未完成项失败: ' + e.message, 'error');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = originalText || '🔁 重试未完成项';
    }
  }
}

// 矩阵渲染：1 个 config 时退化为原 card 视图；多 config 时渲染表格
function renderCompareMatrix(matrix, models) {
  const container = $('compare-cards');
  if (!container) return;
  if (!matrix.length) { container.innerHTML = ''; return; }

  // 单 config + 所有完成 → 沿用旧 card 视图（兼容原 UX）
  if (matrix.length === 1) {
    renderCompareCards(matrix[0].cells);
    return;
  }

  // 多 config → 矩阵表格
  const existingScrollWrap = $('compare-matrix-scroll');
  const previousScrollLeft = existingScrollWrap ? existingScrollWrap.scrollLeft : 0;
  const rows = matrix.map(row => `
    <tr>
      <td style="min-width:120px">
        <strong>${escapeHtml(row.label)}</strong>
        ${row.relationship ? `<br><span style="color:var(--text-tertiary);font-size:11px">${escapeHtml(row.relationship)}</span>` : ''}
        <br><span style="color:var(--text-tertiary);font-size:11px">${row.turnsPlanned} 轮</span>
      </td>
      ${row.cells.map(renderCompareCell).join('')}
    </tr>`).join('');
  container.innerHTML = `
    <div id="compare-matrix-scroll" style="overflow-x:auto">
      <table class="history-table" style="min-width:${120 + models.length * 180}px">
        <thead><tr>
          <th>测试角色</th>
          ${models.map(m => `<th>${escapeHtml(m.name)}</th>`).join('')}
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
  const nextScrollWrap = $('compare-matrix-scroll');
  if (nextScrollWrap) {
    nextScrollWrap.scrollLeft = previousScrollLeft;
  }
}

function getCompareStatusLabel(status) {
  const normalized = String(status || '').trim().toLowerCase();
  if (normalized === 'timeout') return '等待超时';
  return getConversationStatusLabel(status);
}

function getCompareStatusBadgeClass(status) {
  const normalized = String(status || '').trim().toLowerCase();
  if (normalized === 'queued') return 'status-queued';
  if (normalized === 'running') return 'status-running';
  if (normalized === 'scoring') return 'status-running';
  if (normalized === 'paused') return 'status-paused';
  if (normalized === 'completed') return 'status-completed';
  if (normalized === 'cancelled') return 'status-cancelled';
  if (normalized === 'interrupted') return 'status-interrupted';
  if (normalized === 'failed' || normalized === 'timeout') return 'status-failed';
  return 'status-pending';
}

function renderCompareCell(cell) {
  const normalizedStatus = String(cell.status || '').trim().toLowerCase();
  const stage = getCompareCellStage(cell);
  const statusLabel = getCompareCellStageLabel(cell);
  const progressParts = [];
  const settledScoreTurns = getCompareCellSettledScoreTurns(cell);
  const avgScore = Number.parseFloat(cell.avgScore);
  const liveAvgScoreHtml = Number.isFinite(avgScore)
    ? `<div style="margin-top:4px;font-size:12px;font-weight:600;color:${getScoreColor(avgScore)}">${avgScore.toFixed(1)} 分</div>`
    : '';
  if (Number.isFinite(Number(cell.turnCount)) && Number(cell.turnCount) > 0) {
    const plannedTurns = Number(cell.plannedTurns);
    if (Number.isFinite(plannedTurns) && plannedTurns > 0) {
      progressParts.push(`${cell.turnCount}/${plannedTurns} 轮`);
    } else {
      progressParts.push(`${cell.turnCount} 轮`);
    }
  } else if (Number.isFinite(Number(cell.plannedTurns)) && Number(cell.plannedTurns) > 0) {
    progressParts.push(`0/${cell.plannedTurns} 轮`);
  }
  if (cell.autoScoringEnabled && Number(cell.turnCount) > 0) {
    progressParts.push(`已打分 ${settledScoreTurns}/${cell.turnCount}`);
    const pendingScoringTurns = Math.max(
      Number(cell.pendingScoringTurns || 0),
      Math.max(Number(cell.turnCount) - settledScoreTurns, 0),
    );
    if (pendingScoringTurns > 0) {
      progressParts.push(`${cell.scoringActive ? '评分活跃' : '待打分'} ${pendingScoringTurns}`);
    }
  }
  if (Number.isFinite(Number(cell.avgChars)) && Number(cell.avgChars) > 0) {
    progressParts.push(`均字数 ${cell.avgChars}`);
  }
  const relativeUpdatedAt = formatRelativeTime(cell.updatedAt);
  if (relativeUpdatedAt) {
    progressParts.push(`${relativeUpdatedAt}更新`);
  }
  const progressHtml = progressParts.length
    ? `<div style="margin-top:6px;font-size:11px;color:var(--text-tertiary)">${escapeHtml(progressParts.join(' · '))}</div>`
    : '';
  const messageHtml = cell.message
    ? `<div style="margin-top:6px;font-size:11px;color:var(--text-tertiary);line-height:1.4;max-width:240px;word-break:break-all">${escapeHtml(cell.message)}</div>`
    : '';
  if (cell.status === 'pending') return `<td><span style="color:var(--text-tertiary)">等待中</span></td>`;
  if (stage === 'queued' || stage === 'generating' || stage === 'scoring' || normalizedStatus === 'running') {
    return `<td><span class="status-badge ${getCompareCellBadgeClass(cell)}">${statusLabel}</span>${liveAvgScoreHtml}${progressHtml}${messageHtml}</td>`;
  }
  if (normalizedStatus === 'failed' || normalizedStatus === 'cancelled' || normalizedStatus === 'timeout') {
    const errorText = cell.error ? `<div style="margin-top:4px;font-size:11px;color:var(--danger-color);line-height:1.4;max-width:240px;word-break:break-all">${escapeHtml(String(cell.error).slice(0, 220))}</div>` : '';
    const viewBtn = cell.convId ? `<br><button class="btn btn-secondary" style="margin-top:4px;padding:2px 8px;font-size:11px" onclick="viewConversation('${cell.convId}')">查看</button>` : '';
    return `<td><span class="status-badge ${getCompareCellBadgeClass(cell)}">${statusLabel}</span>${progressHtml}${errorText}${viewBtn}</td>`;
  }
  // completed
  const avgScoreHtml = Number.isFinite(avgScore)
    ? `<div style="margin-top:4px;font-size:12px;font-weight:600;color:${getScoreColor(avgScore)}">${avgScore.toFixed(1)} 分</div>`
    : '<div style="margin-top:4px;font-size:12px;color:var(--text-tertiary)">AI 均分 --</div>';
  return `<td>
    <div><span class="status-badge ${getCompareCellBadgeClass(cell)}">${statusLabel}</span></div>
    <div style="font-size:13px"><strong>${cell.turnCount}</strong> 轮 · <strong>${cell.avgChars}</strong> 字</div>
    ${cell.autoScoringEnabled ? `<div style="margin-top:4px;font-size:11px;color:var(--text-tertiary)">已打分 ${settledScoreTurns}/${Math.max(Number(cell.turnCount) || 0, 0)}</div>` : ''}
    ${avgScoreHtml}
    ${cell.convId ? `<button class="btn btn-secondary" style="margin-top:4px;padding:2px 8px;font-size:11px" onclick="viewConversation('${cell.convId}')">查看</button>` : ''}
  </td>`;
}
function renderCompareCards(results) {
  const cards = $('compare-cards'); cards.innerHTML = '';
  const colors = ['#1664ff', '#00b42a', '#ff7d00', '#f53f3f', '#722ed1'];
  results.forEach((r, i) => {
    const card = document.createElement('div');
    card.style.cssText = 'padding:20px;background:var(--bg-surface);border-radius:12px;border:1px solid var(--border-light)';
    const normalizedStatus = String(r.status || '').trim().toLowerCase();
    const statusLabel = getCompareStatusLabel(r.status);
    const statusColor = normalizedStatus === 'completed'
      ? 'var(--success-color)'
      : (normalizedStatus === 'failed' || normalizedStatus === 'timeout' || normalizedStatus === 'cancelled'
        ? 'var(--danger-color)'
        : 'var(--warning-color)');
  const avgScore = Number.parseFloat(r.avgScore);
    card.innerHTML = `<div style="font-weight:600;font-size:15px;margin-bottom:12px;color:${colors[i % colors.length]}">🤖 ${escapeHtml(r.model.name)}</div><div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px"><div style="text-align:center;padding:12px;background:var(--bg-hover);border-radius:8px"><div style="font-size:20px;font-weight:700">${r.turnCount}</div><div style="font-size:11px;color:var(--text-tertiary)">完成轮次</div></div><div style="text-align:center;padding:12px;background:var(--bg-hover);border-radius:8px"><div style="font-size:20px;font-weight:700">${r.avgChars}</div><div style="font-size:11px;color:var(--text-tertiary)">平均字数</div></div><div style="text-align:center;padding:12px;background:var(--bg-hover);border-radius:8px"><div style="font-size:20px;font-weight:700;color:${Number.isFinite(avgScore) ? getScoreColor(avgScore) : 'var(--text-tertiary)'}">${Number.isFinite(avgScore) ? avgScore.toFixed(1) : '--'}</div><div style="font-size:11px;color:var(--text-tertiary)">AI均分</div></div><div style="text-align:center;padding:12px;background:var(--bg-hover);border-radius:8px"><div style="font-size:20px;font-weight:700;color:${statusColor}">${statusLabel}</div><div style="font-size:11px;color:var(--text-tertiary)">状态</div></div></div>${r.error ? `<div style="margin-top:12px;font-size:12px;line-height:1.6;color:var(--danger-color)">${escapeHtml(r.error)}</div>` : ''}${r.convId ? `<button class="btn btn-secondary" style="width:100%;margin-top:12px;justify-content:center" onclick="viewConversation('${r.convId}')">📖 查看对话详情</button>` : ''}`;
    cards.appendChild(card);
  });
}

/* ═══ Prompt A/B 对比测试（后端会话化） ═══ */
function getABSideState(variant) {
  return abSessionState.sides[variant];
}

function closeABSideSockets(variant) {
  const side = getABSideState(variant);
  try {
    if (side.ws) side.ws.close();
  } catch (_) { }
  try {
    if (side.scoreWs) side.scoreWs.close();
  } catch (_) { }
  side.ws = null;
  side.scoreWs = null;
}

function closeAllABSockets() {
  closeABSideSockets('base');
  closeABSideSockets('compare');
}

function resetABSessionState({ preserveUi = false } = {}) {
  closeAllABSockets();
  abSessionState = {
    id: '',
    status: '',
    currentTurn: 0,
    baseConversationId: '',
    compareConversationId: '',
    sharedConfig: {},
    baseConfig: {},
    compareConfig: {},
    sides: {
      base: {
        convId: '',
        ws: null,
        scoreWs: null,
        awaitingTurn: 0,
        latestTurn: 0,
        latestReply: '',
        scoreSummary: null,
        generationStatus: '',
        error: '',
      },
      compare: {
        convId: '',
        ws: null,
        scoreWs: null,
        awaitingTurn: 0,
        latestTurn: 0,
        latestReply: '',
        scoreSummary: null,
        generationStatus: '',
        error: '',
      },
    },
  };
  if (!preserveUi) {
    if ($('ab-history')) $('ab-history').innerHTML = '';
    if ($('ab-base-content')) $('ab-base-content').textContent = '';
    if ($('ab-compare-content')) $('ab-compare-content').textContent = '';
    if ($('ab-base-status')) $('ab-base-status').textContent = '等待...';
    if ($('ab-compare-status')) $('ab-compare-status').textContent = '等待...';
    if ($('ab-results')) $('ab-results').style.display = 'none';
  }
}

function buildABSessionRequestPayload() {
  const baseModel = getInputValue('ab-base-model').trim();
  const basePrompt = getInputValue('ab-base-prompt').trim();
  const compareModel = getInputValue('ab-compare-model').trim();
  const comparePrompt = getInputValue('ab-compare-prompt').trim();
  return {
    shared_config: buildConfigSnapshotRequest('Prompt A/B', 'ab_session').config || {},
    base: buildABConversationPayload({ modelId: baseModel, promptVersion: basePrompt, variant: 'base' }),
    compare: buildABConversationPayload({ modelId: compareModel, promptVersion: comparePrompt, variant: 'compare' }),
  };
}

function normalizeABSessionPayloadForSignature(payload = {}) {
  const normalizeConfig = (config = {}) => {
    const normalized = { ...(config || {}) };
    delete normalized.ab_session_id;
    return normalized;
  };
  return {
    shared_config: payload.shared_config || {},
    base: normalizeConfig(payload.base || payload.base_config || {}),
    compare: normalizeConfig(payload.compare || payload.compare_config || {}),
  };
}

function getABSelectionSignature() {
  return stableSerializeForSignature(
    normalizeABSessionPayloadForSignature(buildABSessionRequestPayload())
  );
}

function getStoredABSelectionSignature() {
  return stableSerializeForSignature(
    normalizeABSessionPayloadForSignature({
      shared_config: abSessionState.sharedConfig || {},
      base: abSessionState.baseConfig || {},
      compare: abSessionState.compareConfig || {},
    })
  );
}

function getABHistoryBubbleHtml(turnNumber, text) {
  return `<div class="chat-bubble user" style="margin:8px 0;padding:10px 14px;align-self:flex-end;max-width:80%;background:var(--primary-color);color:#fff;border-radius:12px;font-size:13px">› Turn ${turnNumber}: ${escapeHtml(text || '')}</div>`;
}

function renderABHistory(results = []) {
  const histArea = $('ab-history');
  if (!histArea) return;
  histArea.innerHTML = (results || []).map(item => getABHistoryBubbleHtml(item.turn || 0, item.user_input || '')).join('');
}

function computeABSettledScoreTurns(summary = {}) {
  return Number(summary.scored_count || 0) + Number(summary.failed_count || 0) + Number(summary.skipped_count || 0);
}

function renderABSideStatus(variant) {
  const side = getABSideState(variant);
  const statusEl = $(variant === 'base' ? 'ab-base-status' : 'ab-compare-status');
  if (!statusEl) return;
  if (side.error) {
    statusEl.textContent = `❌ ${side.error}`;
    return;
  }
  const parts = [];
  if (side.awaitingTurn && side.awaitingTurn > side.latestTurn) {
    parts.push(variant === 'base' ? '生成中...' : '等待...');
  } else if (side.latestTurn > 0) {
    parts.push(`Turn ${side.latestTurn} 完成`);
  } else if (String(side.generationStatus || '').trim().toLowerCase() === 'running') {
    parts.push(variant === 'base' ? '生成中...' : '等待...');
  } else {
    parts.push('等待...');
  }
  const summary = side.scoreSummary || {};
  const total = Number(summary.total_count || 0);
  if (total > 0) {
    const settled = computeABSettledScoreTurns(summary);
    parts.push(`已打分 ${settled}/${total}`);
    const avg = Number(summary.avg_total);
    if (Number.isFinite(avg) && settled > 0) {
      parts.push(`均分 ${avg.toFixed(1)}`);
    }
  }
  statusEl.textContent = parts.join(' · ');
}

function applyABConversationToSide(variant, conversation) {
  const side = getABSideState(variant);
  if (!conversation) return;
  side.convId = String(conversation.id || side.convId || '').trim();
  side.generationStatus = String(conversation.status || side.generationStatus || '').trim().toLowerCase();
  side.error = '';
  const results = Array.isArray(conversation.results) ? conversation.results : [];
  if (variant === 'base') {
    renderABHistory(results);
  }
  if (results.length > 0) {
    const latest = results[results.length - 1] || {};
    side.latestTurn = Number(latest.turn || results.length);
    side.latestReply = String(latest.ai_output || '').trim();
    const contentEl = $(variant === 'base' ? 'ab-base-content' : 'ab-compare-content');
    if (contentEl) contentEl.innerHTML = formatNarration(side.latestReply);
  }
  renderABSideStatus(variant);
}

function applyABScoreSummaryToSide(variant, summary = {}) {
  const side = getABSideState(variant);
  side.scoreSummary = summary || {};
  renderABSideStatus(variant);
}

function connectABConversationSocket(variant) {
  const side = getABSideState(variant);
  const convId = String(side.convId || '').trim();
  if (!convId) return;
  closeABSideSockets(variant);
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const ws = new WebSocket(`${proto}//${location.host}/ws/conversations/${convId}`);
  side.ws = ws;
  ws.onmessage = (event) => {
    let msg = {};
    try {
      msg = JSON.parse(event.data);
    } catch (_) {
      return;
    }
    if (msg.type === 'turn_result' || msg.type === 'turn_complete') {
      const turn = msg.data || msg;
      const turnNumber = Number(turn.turn || 0);
      if (turnNumber > 0) {
        side.latestTurn = Math.max(side.latestTurn || 0, turnNumber);
        side.latestReply = String(turn.ai_output || '').trim();
        side.generationStatus = 'running';
        if (side.awaitingTurn && turnNumber >= side.awaitingTurn) {
          side.awaitingTurn = 0;
          stopWaitingTracker(`ab-${variant}-task`);
        }
        const contentEl = $(variant === 'base' ? 'ab-base-content' : 'ab-compare-content');
        if (contentEl) contentEl.innerHTML = formatNarration(side.latestReply);
      }
      renderABSideStatus(variant);
    } else if (msg.type === 'completed' || msg.type === 'done') {
      side.generationStatus = 'completed';
      renderABSideStatus(variant);
    } else if (msg.type === 'error') {
      side.error = msg.error || msg.message || '生成失败';
      stopWaitingTracker(`ab-${variant}-task`);
      renderABSideStatus(variant);
    }
  };
  ws.onclose = () => {
    if (side.ws === ws) side.ws = null;
  };
  ws.onerror = () => {
    if (side.ws === ws) side.ws = null;
  };
}

function connectABScoreSocket(variant) {
  const side = getABSideState(variant);
  const convId = String(side.convId || '').trim();
  if (!convId) return;
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const ws = new WebSocket(`${proto}//${location.host}/api/scoring/ws/${convId}`);
  side.scoreWs = ws;
  ws.onmessage = (event) => {
    let msg = {};
    try {
      msg = JSON.parse(event.data);
    } catch (_) {
      return;
    }
    if (msg.type === 'score_updated') {
      applyABScoreSummaryToSide(variant, msg.summary || {});
    } else if (msg.type === 'score_progress') {
      const summary = side.scoreSummary || {};
      side.scoreSummary = {
        ...summary,
        total_count: Number(msg.total || summary.total_count || 0),
        failed_count: Number(msg.failed_count || summary.failed_count || 0),
        skipped_count: Number(msg.skipped_count || summary.skipped_count || 0),
        scored_count: Math.max(0, Number(msg.current || 0) - Number(msg.failed_count || 0) - Number(msg.skipped_count || 0)),
      };
      renderABSideStatus(variant);
    }
  };
  ws.onclose = () => {
    if (side.scoreWs === ws) side.scoreWs = null;
  };
  ws.onerror = () => {
    if (side.scoreWs === ws) side.scoreWs = null;
  };
}

async function hydrateABSession(session, { preserveUi = false } = {}) {
  if (!session?.id) return null;
  if (!preserveUi) resetABSessionState({ preserveUi: true });
  abSessionState.id = session.id;
  abSessionState.status = String(session.status || '').trim().toLowerCase();
  abSessionState.currentTurn = Number(session.current_turn || 0);
  abSessionState.baseConversationId = String(session.base_conversation_id || '').trim();
  abSessionState.compareConversationId = String(session.compare_conversation_id || '').trim();
  abSessionState.sharedConfig = session.shared_config || {};
  abSessionState.baseConfig = session.base_config || {};
  abSessionState.compareConfig = session.compare_config || {};
  getABSideState('base').convId = abSessionState.baseConversationId;
  getABSideState('compare').convId = abSessionState.compareConversationId;
  if ($('ab-results')) $('ab-results').style.display = 'block';
  const [baseConversation, compareConversation, baseScore, compareScore] = await Promise.all([
    fetchConversationDetailById(abSessionState.baseConversationId).catch(() => null),
    fetchConversationDetailById(abSessionState.compareConversationId).catch(() => null),
    fetchConversationScoreResults(abSessionState.baseConversationId).catch(() => null),
    fetchConversationScoreResults(abSessionState.compareConversationId).catch(() => null),
  ]);
  if (baseConversation) applyABConversationToSide('base', baseConversation);
  if (compareConversation) applyABConversationToSide('compare', compareConversation);
  if (abSessionState.status === 'running') {
    const baseTurnCount = Array.isArray(baseConversation?.results) ? baseConversation.results.length : 0;
    const compareTurnCount = Array.isArray(compareConversation?.results) ? compareConversation.results.length : 0;
    getABSideState('base').awaitingTurn = baseTurnCount < abSessionState.currentTurn ? abSessionState.currentTurn : 0;
    getABSideState('compare').awaitingTurn = compareTurnCount < abSessionState.currentTurn ? abSessionState.currentTurn : 0;
  }
  if (baseScore?.summary) applyABScoreSummaryToSide('base', baseScore.summary || {});
  if (compareScore?.summary) applyABScoreSummaryToSide('compare', compareScore.summary || {});
  connectABConversationSocket('base');
  connectABConversationSocket('compare');
  connectABScoreSocket('base');
  connectABScoreSocket('compare');
  return session;
}

async function createABSessionOnServer() {
  const payload = buildABSessionRequestPayload();
  const response = await fetch('/api/ab-sessions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || response.statusText || '创建 A/B 实验失败');
  return data;
}

async function ensureABSession({ forceNew = false } = {}) {
  const selectionChanged = getABSelectionSignature() !== getStoredABSelectionSignature();
  if (!forceNew && abSessionState.id && !selectionChanged) {
    return { createdNew: false, session: abSessionState };
  }
  resetABSessionState();
  const created = await createABSessionOnServer();
  await hydrateABSession(created, { preserveUi: true });
  return { createdNew: true, session: created };
}

async function restoreActiveABSession({ silent = true } = {}) {
  try {
    const response = await fetch('/api/ab-sessions/active');
    const data = await response.json().catch(() => null);
    if (!response.ok) throw new Error((data && data.detail) || response.statusText || '读取活动实验失败');
    if (!data || !data.id) return null;
    await hydrateABSession(data, { preserveUi: true });
    return data;
  } catch (err) {
    if (!silent) showToast('恢复 A/B 实验失败: ' + err.message, 'warning');
    return null;
  }
}

async function startABTest() {
  const input = getInputValue('ab-input');
  if (!input) { showToast('请输入剧情推进文本', 'warning'); return; }
  const baseModel = getInputValue('ab-base-model');
  const compModel = getInputValue('ab-compare-model');
  if (!baseModel || !compModel) { showToast('请选择控制组和实验组模型', 'warning'); return; }
  const button = $('btn-ab-send');
  if (button) button.disabled = true;
  try {
    await ensureABSession();
    const nextTurn = Number(abSessionState.currentTurn || 0) + 1;
    if ($('ab-results')) $('ab-results').style.display = 'block';
    if ($('ab-base-content')) $('ab-base-content').textContent = '';
    if ($('ab-compare-content')) $('ab-compare-content').textContent = '';
    const baseSide = getABSideState('base');
    const compareSide = getABSideState('compare');
    baseSide.awaitingTurn = nextTurn;
    compareSide.awaitingTurn = nextTurn;
    baseSide.error = '';
    compareSide.error = '';
    renderABSideStatus('base');
    renderABSideStatus('compare');
    startWaitingTracker('ab-base-task', {
      forcedStage: '模型处理中',
      onUpdate: ({ elapsedMs, elapsedText }) => {
        if (baseSide.awaitingTurn === nextTurn) $('ab-base-status').textContent = elapsedMs < 5000 ? '生成中...' : `模型处理中 · ${elapsedText}`;
      }
    });
    startWaitingTracker('ab-compare-task', {
      forcedStage: '模型处理中',
      onUpdate: ({ elapsedMs, elapsedText }) => {
        if (compareSide.awaitingTurn === nextTurn) $('ab-compare-status').textContent = elapsedMs < 5000 ? '等待...' : `模型处理中 · ${elapsedText}`;
      }
    });
    const response = await fetch(`/api/ab-sessions/${encodeURIComponent(abSessionState.id)}/turns`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_input: input,
        temperature: getGenerationSamplingConfig().temperature,
        top_p: getGenerationSamplingConfig().top_p,
      }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || response.statusText || '提交 A/B 对话失败');
    abSessionState.currentTurn = Number(data.current_turn || nextTurn);
    abSessionState.status = String(data.status || 'running').trim().toLowerCase();
    const histArea = $('ab-history');
    if (histArea) histArea.innerHTML += getABHistoryBubbleHtml(nextTurn, input);
    $('ab-input').value = '';
  } catch (e) {
    stopWaitingTracker('ab-base-task');
    stopWaitingTracker('ab-compare-task');
    getABSideState('base').error = e.message;
    getABSideState('compare').error = e.message;
    renderABSideStatus('base');
    renderABSideStatus('compare');
    showToast('A/B 对比出错: ' + e.message, 'error');
  } finally {
    if (button) button.disabled = false;
  }
}

/* ═══ Prompt A/B 模式切换 ═══ */
function switchABMode(mode, { refreshShell = true, persist = true } = {}) {
  state.abMode = mode === 'batch' ? 'batch' : 'live';
  if (persist) {
    persistTestCenterNavigationState({ abMode: state.abMode });
  }
  const liveEl = $('ab-live-mode');
  const batchEl = $('ab-batch-mode');
  const btnLive = $('ab-mode-live');
  const btnBatch = $('ab-mode-batch');
  if (liveEl) liveEl.style.display = state.abMode === 'live' ? '' : 'none';
  if (batchEl) batchEl.style.display = state.abMode === 'batch' ? '' : 'none';
  if (btnLive) btnLive.className = state.abMode === 'live' ? 'btn btn-primary' : 'btn btn-secondary';
  if (btnBatch) btnBatch.className = state.abMode === 'batch' ? 'btn btn-primary' : 'btn btn-secondary';
  if (refreshShell) refreshTestCenterShell();
}

async function loadABHistoryConversations() {
  try {
    const r = await fetch('/api/conversations');
    const d = await r.json();
    const list = d.conversations || [];
    const makeOpts = (items) => items.map(c => {
      const labelTime = formatBeijingDateTime(c.created_at || '') || String(c.created_at || '').slice(0, 16);
      const label = `${c.nickname || '未命名'} | ${c.model_id || '?'} | T${c.total_turns || 0} | ${labelTime}`;
      return `<option value="${c.id}">${escapeHtml(label)}</option>`;
    }).join('');
    const opts = '<option value="">-- 选择对话 --</option>' + makeOpts(list);
    if ($('ab-hist-a')) $('ab-hist-a').innerHTML = opts;
    if ($('ab-hist-b')) $('ab-hist-b').innerHTML = opts;
  } catch (e) {
    showToast('加载对话列表失败: ' + e.message, 'error');
  }
}

async function startHistoryCompare() {
  const idA = getInputValue('ab-hist-a');
  const idB = getInputValue('ab-hist-b');
  if (!idA || !idB) { showToast('请选择两个对话记录', 'warning'); return; }
  if (idA === idB) { showToast('请选择不同的对话记录', 'warning'); return; }
  const resultsEl = $('ab-hist-results');
  if (resultsEl) resultsEl.innerHTML = '<p style="color:var(--text-tertiary)">加载中...</p>';
  try {
    const [rA, rB] = await Promise.all([
      fetch(`/api/conversations/${idA}`).then(r => r.json()),
      fetch(`/api/conversations/${idB}`).then(r => r.json())
    ]);
    const turnsA = rA.results || [];
    const turnsB = rB.results || [];
    const maxTurns = Math.max(turnsA.length, turnsB.length);
    if (maxTurns === 0) { resultsEl.innerHTML = '<p>两个对话均无轮次数据</p>'; return; }
    const labelA = `${rA.config?.character?.Role_Nickname || rA.model_id || 'A'}`;
    const labelB = `${rB.config?.character?.Role_Nickname || rB.model_id || 'B'}`;
    let html = `<div class="group-title">历史对比: ${escapeHtml(labelA)} vs ${escapeHtml(labelB)} (共${maxTurns}轮)</div>`;
    for (let i = 0; i < maxTurns; i++) {
      const tA = turnsA[i]; const tB = turnsB[i];
      const scoreA = tA?.scores?.mapped_total;
      const scoreB = tB?.scores?.mapped_total;
      const sBadge = (s) => s != null ? `<span style="margin-left:6px;padding:2px 6px;border-radius:4px;font-size:11px;background:${s >= 7 ? '#10b98133' : '#f5920033'};color:${s >= 7 ? '#10b981' : '#f59e0b'}">${Number(s).toFixed(1)}</span>` : '';
      html += `<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px">`;
      html += `<div style="background:var(--bg-hover);border-radius:8px;padding:12px;border:1px solid var(--border-light)">`;
      html += `<div style="font-size:12px;color:var(--text-tertiary);margin-bottom:6px">🔵 Turn ${i + 1}${sBadge(scoreA)}</div>`;
      html += `<div style="font-size:12px;color:var(--primary-color);margin-bottom:4px">${escapeHtml(tA?.user_input || '—')}</div>`;
      html += `<div style="font-size:13px;line-height:1.5;max-height:200px;overflow-y:auto">${formatNarration(tA?.ai_output || '无数据')}</div></div>`;
      html += `<div style="background:#10b9810d;border-radius:8px;padding:12px;border:1px solid #10b98140">`;
      html += `<div style="font-size:12px;color:var(--text-tertiary);margin-bottom:6px">🟢 Turn ${i + 1}${sBadge(scoreB)}</div>`;
      html += `<div style="font-size:12px;color:#10b981;margin-bottom:4px">${escapeHtml(tB?.user_input || '—')}</div>`;
      html += `<div style="font-size:13px;line-height:1.5;max-height:200px;overflow-y:auto">${formatNarration(tB?.ai_output || '无数据')}</div></div>`;
      html += `</div>`;
    }
    // 汇总评分对比
    const avgScore = (turns) => {
      const scored = turns.filter(t => t?.scores?.mapped_total != null);
      if (!scored.length) return null;
      return scored.reduce((s, t) => s + t.scores.mapped_total, 0) / scored.length;
    };
    const avgA = avgScore(turnsA); const avgB = avgScore(turnsB);
    if (avgA != null || avgB != null) {
      html += `<div style="display:flex;gap:16px;padding:12px;background:var(--bg-surface);border-radius:8px;margin-top:8px">`;
      html += `<span style="font-weight:600;font-size:13px">📊 平均分:</span>`;
      html += `<span>🔵 ${avgA != null ? avgA.toFixed(2) : '无评分'}</span>`;
      html += `<span>🟢 ${avgB != null ? avgB.toFixed(2) : '无评分'}</span>`;
      if (avgA != null && avgB != null) {
        const diff = avgB - avgA;
        html += `<span style="color:${diff >= 0 ? '#10b981' : '#ef4444'}">${diff >= 0 ? '+' : ''}${diff.toFixed(2)}</span>`;
      }
      html += `</div>`;
    }
    resultsEl.innerHTML = html;
    showToast('历史对比完成', 'success');
  } catch (e) {
    resultsEl.innerHTML = `<p style="color:#ef4444">对比失败: ${escapeHtml(e.message)}</p>`;
    showToast('历史对比失败: ' + e.message, 'error');
  }
}

/* ═══ 人工详细打分 Modal ═══ */
let _humanScoreCtx = { convId: null, turnNumber: null };
function openHumanScoreModal(convId, turnNumber, aiText) {
  _humanScoreCtx = { convId, turnNumber };
  if ($('hs-target-text')) $('hs-target-text').textContent = aiText || '';
  const container = $('hs-dimensions-container');
  if (container) {
    container.innerHTML = DIM_NAMES.map((name, i) => `
          <div style="padding:12px;background:var(--bg-hover);border-radius:8px">
            <div style="display:flex;justify-content:space-between;margin-bottom:6px">
              <span style="font-size:13px;font-weight:500">${name}</span>
              <span class="hs-dim-val" style="font-size:12px;color:var(--primary-color)">8.0</span>
            </div>
            <input type="range" class="hs-dim-slider" data-dim="${DIM_KEYS[i]}" min="0" max="10" step="0.1" value="8" style="width:100%">
          </div>`).join('');
    container.querySelectorAll('.hs-dim-slider').forEach(s => {
      s.addEventListener('input', () => {
        s.parentElement.querySelector('.hs-dim-val').textContent = toFixedScore(s.value);
      });
    });
  }
  if ($('hs-comment')) $('hs-comment').value = '';
  showModal('modal-human-score');
}
function closeHumanScoreModal() {
  closeModal('modal-human-score');
}
async function submitHumanScore() {
  const { convId, turnNumber } = _humanScoreCtx;
  if (!convId) { showToast('缺少对话ID', 'warning'); return; }
  const dims = {};
  document.querySelectorAll('.hs-dim-slider').forEach(s => {
    dims[s.dataset.dim] = parseFloat(s.value);
  });
  const comment = getInputValue('hs-comment');
  const weights = [0.25, 0.25, 0.15, 0.10, 0.10, 0.15];
  const starScore = DIM_KEYS.reduce((sum, k, i) => sum + (dims[k] || 8) * weights[i], 0);
  try {
    const r = await fetch(`/api/scoring/${convId}/turn/${turnNumber}/manual`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ star_score: parseFloat(starScore.toFixed(1)), comment, dimensions: dims })
    });
    if (!r.ok) throw new Error(await r.text());
    closeHumanScoreModal();
    showToast('人工打分已保存', 'success');
  } catch (e) {
    showToast('打分保存失败: ' + e.message, 'error');
  }
}

/* ═══ 打分趋势折线图 ═══ */
function renderScoreTrend() {
  if (!state.scoreData || state.scoreData.length < 2) {
    const existing = $('score-trend-canvas');
    if (existing) {
      const ctx = existing.getContext('2d');
      ctx.clearRect(0, 0, existing.width, existing.height);
    }
    return;
  }
  let canvas = $('score-trend-canvas');
  if (!canvas) {
    const container = document.createElement('div');
    container.style.cssText = 'margin-top:24px;text-align:center';
    container.innerHTML = '<div style="font-weight:600;margin-bottom:12px">📈 逐轮总分趋势</div><canvas id="score-trend-canvas" width="600" height="200" style="max-width:100%;background:var(--bg-surface);border-radius:8px;border:1px solid var(--border-light)"></canvas>';
    $('scoring-content').appendChild(container);
    canvas = $('score-trend-canvas');
  }
  const ctx = canvas.getContext('2d');
  const W = canvas.width, H = canvas.height, pad = 40;
  ctx.clearRect(0, 0, W, H);
  const scores = state.scoreData.map(s => (
    getScoringTurnStatus(s) === 'scored'
      ? (getScoringTurnTotal(s) ?? 0)
      : null
  ));
  const manualScores = state.scoreData.map(s => {
    const value = Number.parseFloat(s.manual_star_score);
    return Number.isFinite(value) ? value : null;
  });
  const lowScoreThreshold = getActiveLowScoreThreshold();
  const maxS = 10, minS = 0;
  const xStep = (W - pad * 2) / Math.max(scores.length - 1, 1);
  // Grid
  ctx.strokeStyle = '#e5e6eb'; ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const y = pad + (H - pad * 2) * (1 - i / 4);
    ctx.beginPath(); ctx.moveTo(pad, y); ctx.lineTo(W - pad, y); ctx.stroke();
    ctx.fillStyle = '#86909c'; ctx.font = '11px Inter'; ctx.fillText((minS + (maxS - minS) * i / 4).toFixed(0), 8, y + 4);
  }
  const drawSeries = (series, color, dashed = false) => {
    ctx.save();
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.setLineDash(dashed ? [6, 4] : []);
    ctx.beginPath();
    let started = false;
    series.forEach((s, i) => {
      if (s === null || s === undefined) return;
      const x = pad + i * xStep;
      const y = pad + (H - pad * 2) * (1 - (s - minS) / (maxS - minS));
      if (!started) {
        ctx.moveTo(x, y);
        started = true;
      } else {
        ctx.lineTo(x, y);
      }
    });
    ctx.stroke();
    ctx.restore();
  };
  drawSeries(scores, '#1664ff');
  drawSeries(manualScores, '#ff7d00', true);
  const thresholdY = pad + (H - pad * 2) * (1 - (lowScoreThreshold - minS) / (maxS - minS));
  ctx.save();
  ctx.strokeStyle = '#f53f3f';
  ctx.lineWidth = 1;
  ctx.setLineDash([4, 4]);
  ctx.beginPath();
  ctx.moveTo(pad, thresholdY);
  ctx.lineTo(W - pad, thresholdY);
  ctx.stroke();
  ctx.fillStyle = '#f53f3f';
  ctx.font = '11px Inter';
  ctx.fillText(`低分阈值 ${lowScoreThreshold.toFixed(1)}`, pad + 4, thresholdY - 6);
  ctx.restore();
  scores.forEach((s, i) => {
    if (s === null || s === undefined) return;
    const x = pad + i * xStep, y = pad + (H - pad * 2) * (1 - (s - minS) / (maxS - minS));
    const lowScorePoint = Number.parseFloat(s) < lowScoreThreshold;
    ctx.beginPath(); ctx.arc(x, y, lowScorePoint ? 6 : 4, 0, Math.PI * 2); ctx.fillStyle = lowScorePoint ? '#f53f3f' : '#1664ff'; ctx.fill();
    if (lowScorePoint) {
      ctx.beginPath();
      ctx.arc(x, y, 8, 0, Math.PI * 2);
      ctx.strokeStyle = 'rgba(245,63,63,.25)';
      ctx.lineWidth = 2;
      ctx.stroke();
    }
    ctx.fillStyle = '#1d2129'; ctx.font = '11px Inter'; ctx.fillText(s.toFixed(1), x - 10, y - 10);
  });
  manualScores.forEach((s, i) => {
    if (s === null || s === undefined) return;
    const x = pad + i * xStep, y = pad + (H - pad * 2) * (1 - (s - minS) / (maxS - minS));
    ctx.beginPath(); ctx.arc(x, y, 4, 0, Math.PI * 2); ctx.fillStyle = '#ff7d00'; ctx.fill();
  });
  ctx.fillStyle = '#86909c'; ctx.font = '12px Inter';
  ctx.fillText('AI', W - 110, 20);
  ctx.fillText('人工', W - 55, 20);
  ctx.strokeStyle = '#1664ff'; ctx.lineWidth = 2; ctx.setLineDash([]); ctx.beginPath(); ctx.moveTo(W - 135, 16); ctx.lineTo(W - 118, 16); ctx.stroke();
  ctx.strokeStyle = '#ff7d00'; ctx.setLineDash([6, 4]); ctx.beginPath(); ctx.moveTo(W - 80, 16); ctx.lineTo(W - 63, 16); ctx.stroke();
  ctx.setLineDash([]);
  // X labels
  ctx.fillStyle = '#86909c'; ctx.font = '11px Inter';
  scores.forEach((_, i) => { ctx.fillText(`T${i + 1}`, pad + i * xStep - 6, H - 8); });
}

/* ═══ 提示词管理 ═══ */
const PROMPT_KIND_CONFIG = {
  chat: { label: '主提示词', supportsVersioning: false, supportsActivate: false },
  summary: { label: '摘要提示词', supportsVersioning: true, supportsActivate: true },
  scoring: { label: '打分提示词', supportsVersioning: true, supportsActivate: true },
  profile: { label: '画像提示词', supportsVersioning: true, supportsActivate: true },
};

function buildPromptListUrl(kind) {
  if (kind === 'scoring') return '/api/scoring-prompts';
  return `/api/prompts?kind=${encodeURIComponent(kind)}`;
}
function buildPromptHistoryUrl(kind) {
  if (kind === 'scoring') return '/api/scoring-prompts/history';
  return `/api/prompts/history?kind=${encodeURIComponent(kind)}`;
}
function buildPromptDetailUrl(kind, filename) {
  if (kind === 'scoring') return `/api/scoring-prompts/${encodeURIComponent(filename)}`;
  return `/api/prompts/${encodeURIComponent(filename)}?kind=${encodeURIComponent(kind)}`;
}
function buildPromptDownloadUrl(kind, filename) {
  if (kind === 'scoring') return `/api/scoring-prompts/${encodeURIComponent(filename)}/download`;
  return `/api/prompts/${encodeURIComponent(filename)}/download?kind=${encodeURIComponent(kind)}`;
}
function buildPromptEditUrl(kind, filename) {
  if (kind === 'scoring') return `/api/scoring-prompts/${encodeURIComponent(filename)}`;
  return `/api/prompts/${encodeURIComponent(filename)}?kind=${encodeURIComponent(kind)}`;
}
function buildPromptUploadUrl(kind) {
  if (kind === 'scoring') return '/api/scoring-prompts/upload';
  return `/api/prompts/upload?kind=${encodeURIComponent(kind)}`;
}
function buildPromptCreateVersionUrl(kind) {
  if (kind === 'scoring') return '/api/scoring-prompts/versions';
  return `/api/prompts/versions?kind=${encodeURIComponent(kind)}`;
}
function buildPromptActivateUrl(kind, filename) {
  if (kind === 'scoring') return `/api/scoring-prompts/${encodeURIComponent(filename)}/activate`;
  return `/api/prompts/${encodeURIComponent(filename)}/activate?kind=${encodeURIComponent(kind)}`;
}

function switchPromptKind(kind) {
  _promptManagerKind = kind;
  document.querySelectorAll('.prompt-kind-pill').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.kind === kind);
  });
  $('prompt-new-version-btn').style.display = PROMPT_KIND_CONFIG[kind]?.supportsVersioning ? 'inline-flex' : 'none';
  loadPrompts();
}

async function loadPrompts() {
  const list = $('prompt-list'); list.innerHTML = '加载中...';
  const meta = $('prompt-kind-meta');
  try {
    const r = await fetch(buildPromptListUrl(_promptManagerKind));
    const data = await r.json();
    const prompts = data.prompts || [];
    const activeFilename = data.active_filename || '';
    if (meta) {
      meta.textContent = activeFilename
        ? `${PROMPT_KIND_CONFIG[_promptManagerKind].label}当前生效版本：${activeFilename}`
        : `${PROMPT_KIND_CONFIG[_promptManagerKind].label}当前无可用版本`;
    }
    if (!prompts.length) {
      list.innerHTML = '<div class="empty-state"><div class="title">无提示词文件</div></div>';
      return;
    }
    list.innerHTML = '';
    prompts.forEach(p => {
      const div = document.createElement('div');
      div.style.cssText = 'display:flex;justify-content:space-between;align-items:center;gap:12px;padding:16px;background:var(--bg-surface);border-radius:10px;border:1px solid var(--border-light)';
      const sizeKB = ((p.size || 0) / 1024).toFixed(1);
      const modified = p.modified ? new Date(p.modified * 1000).toLocaleString('zh-CN') : '-';
      const badges = [
        p.is_active ? '<span class="meta-chip">生效中</span>' : '',
        p.is_latest && _promptManagerKind === 'chat' ? '<span class="meta-chip">最新</span>' : '',
      ].filter(Boolean).join('');
      div.innerHTML = `
        <div style="min-width:0;flex:1">
          <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:4px">
            <div style="font-weight:600;font-size:14px;min-width:0;overflow:hidden;text-overflow:ellipsis">📄 ${escapeHtml(p.filename)}</div>
            ${badges}
          </div>
          <div style="font-size:12px;color:var(--text-tertiary)">${sizeKB} KB · ${modified}</div>
        </div>
        <div style="display:flex;gap:8px;flex-wrap:wrap">
          <button class="btn btn-secondary" onclick="previewPrompt('${escapeHtml(p.filename)}', '${_promptManagerKind}')">👁 预览</button>
          <button class="btn btn-secondary" onclick="editPromptInline('${escapeHtml(p.filename)}', '${_promptManagerKind}')">✏️ 编辑</button>
          <button class="btn btn-primary" onclick="downloadPrompt('${escapeHtml(p.filename)}', '${_promptManagerKind}')">📥 下载</button>
        </div>`;
      list.appendChild(div);
    });
  } catch (e) { list.innerHTML = '<div style="color:var(--danger-color)">加载失败</div>'; }
}
async function previewPrompt(filename, kind = _promptManagerKind) {
  try {
    const r = await fetch(buildPromptDetailUrl(kind, filename));
    const data = await r.json();
    _promptEditFilename = filename;
    _promptEditKind = kind;
    $('prompt-preview').style.display = 'block';
    $('prompt-preview-title').textContent = `${filename} (${data.total_lines} 行)`;
    $('prompt-preview-content').textContent = data.content;
    $('prompt-preview-content').style.display = 'block';
    $('prompt-edit-content').style.display = 'none';
    $('prompt-edit-btn').textContent = '✏️ 编辑';
    $('prompt-save-btn').style.display = 'none';
    $('prompt-activate-btn').style.display = PROMPT_KIND_CONFIG[kind]?.supportsActivate ? 'inline-flex' : 'none';
    $('prompt-download-btn').onclick = () => downloadPrompt(filename, kind);
    if (data.truncated) showToast('文件过大，仅显示前 20K 字符', 'warning');
  } catch (e) { showToast('预览失败', 'error'); }
}
function downloadPrompt(filename, kind = _promptManagerKind) {
  window.open(buildPromptDownloadUrl(kind, filename), '_blank');
}
function closePromptPreview() {
  $('prompt-preview').style.display = 'none';
  _promptEditFilename = null;
}
function togglePromptEdit() {
  const pre = $('prompt-preview-content');
  const ta = $('prompt-edit-content');
  if (ta.style.display === 'none') {
    ta.value = pre.textContent;
    ta.style.display = 'block'; pre.style.display = 'none';
    $('prompt-edit-btn').textContent = '\ud83d\udc41 预览';
    $('prompt-save-btn').style.display = 'inline-flex';
  } else {
    ta.style.display = 'none'; pre.style.display = 'block';
    $('prompt-edit-btn').textContent = '\u270f\ufe0f 编辑';
    $('prompt-save-btn').style.display = 'none';
  }
}
async function editPromptInline(filename, kind = _promptManagerKind) {
  await previewPrompt(filename, kind);
  togglePromptEdit();
}
async function savePromptEdit() {
  if (!_promptEditFilename) return;
  const content = $('prompt-edit-content').value;
  try {
    const r = await fetch(buildPromptEditUrl(_promptEditKind, _promptEditFilename), {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content })
    });
    if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
    showToast(`\ud83c\udf89 ${_promptEditFilename} 保存成功`, 'success');
    $('prompt-preview-content').textContent = content;
    togglePromptEdit();
    loadPrompts();
    fetchPromptVersions();
  } catch (e) { showToast('保存失败: ' + e.message, 'error'); }
}
async function activatePromptVersion() {
  if (!_promptEditFilename || !PROMPT_KIND_CONFIG[_promptEditKind]?.supportsActivate) return;
  try {
    const r = await fetch(buildPromptActivateUrl(_promptEditKind, _promptEditFilename), { method: 'POST' });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.detail || r.statusText || '切换失败');
    showToast(`已切换生效版本：${_promptEditFilename}`, 'success');
    loadPrompts();
    fetchPromptVersions();
  } catch (e) {
    showToast('切换生效版本失败: ' + e.message, 'error');
  }
}
async function createPromptVersion() {
  if (!PROMPT_KIND_CONFIG[_promptManagerKind]?.supportsVersioning) {
    showToast('当前提示词类型不支持新建版本', 'warning');
    return;
  }
  const content = $('prompt-edit-content').style.display !== 'none'
    ? $('prompt-edit-content').value
    : $('prompt-preview-content').textContent;
  if (!content.trim()) {
    showToast('请先预览或编辑一个提示词版本', 'warning');
    return;
  }
  try {
    const r = await fetch(buildPromptCreateVersionUrl(_promptManagerKind), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content, activate: true }),
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.detail || r.statusText || '新建版本失败');
    showToast(`已创建新版本：${data.filename}`, 'success');
    await loadPrompts();
    await fetchPromptVersions();
    await previewPrompt(data.filename, _promptManagerKind);
  } catch (e) {
    showToast('新建版本失败: ' + e.message, 'error');
  }
}
async function uploadPrompt(event) {
  const file = event.target.files[0];
  if (!file) return;
  if (!file.name.endsWith('.md')) { showToast('仅支持 .md 文件', 'warning'); return; }
  const form = new FormData(); form.append('file', file);
  try {
    const r = await fetch(buildPromptUploadUrl(_promptManagerKind), { method: 'POST', body: form });
    if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
    showToast(`\u2705 ${file.name} 上传成功`, 'success');
    loadPrompts();
    fetchPromptVersions();
  } catch (e) { showToast('上传失败: ' + e.message, 'error'); }
  event.target.value = '';
}

/* ═══ 普通聊天与模型对比 ═══ */
let _compareModeActive = false;
window.toggleCompareMode = function () {
  _compareModeActive = !_compareModeActive;
  console.log('toggleCompareMode triggered, state:', _compareModeActive);
  if (_compareModeActive) {
    switchPage('freechat');
    initFreeChatPage();
    const btn = document.getElementById('btn-toggle-compare');
    if (btn) {
      btn.style.background = 'var(--primary-color)';
      btn.style.color = 'white';
    }
  } else {
    switchPage('chat');
    const btn = document.getElementById('btn-toggle-compare');
    if (btn) {
      btn.style.background = '';
      btn.style.color = '';
    }
  }
};

let freeChatPrompts = {}; // 独立模型的 Prompt 存储
let freeChatSamplingConfigs = {};
let freeChatSessions = {};
let _freeChatSlotCounter = 0;
let _currentFreeChatModel = null;
let _webSearchEnabled = false;
let _thinkingEffort = _dialogueThinkingEffortDraft;
let _modelCapabilities = {}; // { modelId: { web_search: bool, thinking: bool } }

function toggleWebSearch() {
  _webSearchEnabled = !_webSearchEnabled;
  const btn = $('btn-web-search');
  if (btn) {
    btn.textContent = _webSearchEnabled ? '联网 ✓' : '⊕ 联网';
    btn.style.background = _webSearchEnabled ? 'var(--primary-color)' : '';
    btn.style.color = _webSearchEnabled ? '#fff' : '';
  }
}
function onThinkingChange() {
  const sel = $('sel-thinking');
  if (sel) sel.dataset.userTouched = '1';
  const raw = normalizeThinkingEffortOption(sel ? sel.value : '', _dialogueThinkingEffortDraft);
  syncDialogueThinkingControls({
    enabled: raw !== 'disabled',
    effort: raw === 'disabled' ? _dialogueThinkingEffortDraft : raw,
    modelId: getPrimaryModelId(),
    force: true,
  });
}
function updateControlStates(modelId) {
  const caps = _modelCapabilities[modelId] || {};
  const btnWS = $('btn-web-search');
  if (btnWS) { btnWS.disabled = !caps.web_search; btnWS.title = caps.web_search ? '联网搜索' : '该模型不支持联网'; }
  syncDialogueThinkingControls({ modelId, force: false });
  syncScoringThinkingControls({
    modelId: getInputValue('f-scoring-model').trim() || modelId,
    force: false,
  });
}

function openFreeChatPrompt(modelId, modelName) {
  _currentFreeChatModel = modelId;
  $('freechat-prompt-title').textContent = `⚙️ 编辑 [${modelName}] Prompt & 多样性`;
  $('freechat-prompt-editor').value = freeChatPrompts[modelId] || '';
  _variablePreviewModes['freechat-prompt-vars-body'] = 'related';
  syncFreeChatGenerationControls(modelId);
  renderVariablePreviewTags({
    containerId: 'freechat-prompt-vars-body',
    promptText: freeChatPrompts[modelId] || '',
  });
  showModal('modal-freechat-prompt');
  $('freechat-prompt-editor').focus();
}

function saveFreeChatPrompt() {
  if (!_currentFreeChatModel) return;
  const modelId = _currentFreeChatModel;
  const val = $('freechat-prompt-editor').value;
  const prevPrompt = String(freeChatPrompts[modelId] || '');
  const prevSampling = getStoredFreeChatSamplingConfig(modelId);
  const nextSampling = getFreeChatSamplingDraft();
  const samplingChanged = Math.abs(prevSampling.temperature - nextSampling.temperature) > 0.001
    || Math.abs(prevSampling.top_p - nextSampling.top_p) > 0.001;
  freeChatPrompts[modelId] = val;
  freeChatSamplingConfigs[modelId] = nextSampling;
  closeModal('modal-freechat-prompt');
  refreshFreeChatPromptButtonState(modelId);
  if ((prevPrompt !== val || samplingChanged) && hasAnyFreeChatTurns()) {
    clearFreeChat({ preserveSlots: true }).catch(() => { });
    showToast('专属提示词与多样性已保存，当前模型对比会话已重置', 'success');
  } else {
    showToast('专属提示词与多样性已保存', 'success');
  }
}

function refreshFreeChatPromptButtonState(modelId) {
  const safeId = String(modelId || '').replace(/[^a-zA-Z0-9-]/g, '-');
  const btn = document.getElementById(`btn-fc-prompt-${safeId}`);
  if (!btn) return;
  const hasPrompt = !!String(freeChatPrompts[modelId] || '').trim();
  const sampling = getStoredFreeChatSamplingConfig(modelId);
  const defaultSampling = getGenerationSamplingConfig();
  const isSamplingCustom = Math.abs(sampling.temperature - defaultSampling.temperature) > 0.001
    || Math.abs(sampling.top_p - defaultSampling.top_p) > 0.001;
  if (hasPrompt || isSamplingCustom) {
    btn.style.color = 'var(--primary-color)';
    btn.style.background = '#e6f4ff';
  } else {
    btn.style.color = 'var(--text-tertiary)';
    btn.style.background = 'none';
  }
}

function renderFreeChatEmptyState() {
  const area = $('freechat-area');
  if (!area) return;
  area.innerHTML = '<div class="empty-state" id="freechat-empty"><div class="title">自由聊天</div><p>选择 1-3 个模型，发送消息查看多模型并行输出对比。</p></div>';
}

async function completeConversationById(convId) {
  if (!convId) return;
  try {
    await fetch(`/api/conversations/${convId}/complete`, { method: 'POST' });
  } catch (_) { }
}

async function finalizeFreeChatSessions() {
  const convIds = [...new Set(Object.values(freeChatSessions || {}).map(item => item?.convId).filter(Boolean))];
  await Promise.all(convIds.map(convId => completeConversationById(convId)));
}

function getFreeChatComparableTurnCount() {
  const sessions = Object.values(freeChatSessions || {}).filter(item => item?.convId);
  if (sessions.length < 2) return 0;
  return Math.min(...sessions.map(item => Number(item.lastTurn || 0)));
}

function hasAnyFreeChatTurns() {
  return Object.values(freeChatSessions || {}).some(item => Number(item?.lastTurn || 0) > 0);
}

function updateFreeChatReportState() {
  const actionWrap = $('freechat-report-actions');
  const button = $('btn-freechat-generate-report');
  const hint = $('freechat-report-hint');
  const sessionCount = Object.values(freeChatSessions || {}).filter(item => item?.convId).length;
  const comparableTurns = getFreeChatComparableTurnCount();
  const eligible = sessionCount >= 2 && comparableTurns >= 3;
  if (actionWrap) actionWrap.style.display = eligible ? 'flex' : 'none';
  if (button) button.disabled = !eligible;
  if (hint) {
    hint.textContent = eligible
      ? `当前已有 ${sessionCount} 个模型列完成 ${comparableTurns} 轮，可生成模型对比报告。`
      : '完成至少 3 轮模型对比后，可生成汇总报告并跳转到历史记录页查看。';
  }
}

function buildFreeChatConversationPayload(modelId) {
  const payload = buildInteractiveConversationPayload();
  const sampling = getStoredFreeChatSamplingConfig(modelId);
  payload.model_id = modelId;
  payload.prompt_version = getInputValue('f-prompt-version') || payload.prompt_version;
  payload.temperature = sampling.temperature;
  payload.top_p = sampling.top_p;
  payload.modules = payload.modules || {};
  const customPrompt = String(freeChatPrompts[modelId] || '').trim();
  if (customPrompt) {
    payload.modules.system_prompt = customPrompt;
  } else {
    delete payload.modules.system_prompt;
  }
  return payload;
}

async function ensureFreeChatConversationSession(slot) {
  const slotKey = slot.dataset.slotKey;
  const modelId = slot.dataset.modelId;
  const modelName = slot.dataset.modelName;
  const existing = freeChatSessions[slotKey];
  if (existing?.convId && existing.modelId === modelId) return existing;
  const payload = buildFreeChatConversationPayload(modelId);
  const response = await fetch('/api/conversations/interactive', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || response.statusText || '创建模型对比会话失败');
  const session = {
    convId: data.id,
    modelId,
    modelName,
    promptVersion: payload.prompt_version || '',
    lastTurn: 0,
  };
  freeChatSessions[slotKey] = session;
  slot.dataset.convId = data.id;
  return session;
}

let _freeChatModelList = [];
async function initFreeChatPage() {
  if (_freeChatModelList.length > 0) return;
  try {
    if (_allModelOptions.length === 0) {
      const r = await fetch('/api/models'); const data = await r.json();
      _allModelOptions = (data.models || data || []).map(m => ({ id: m.id || m, name: m.name || m.id || m }));
    }
    _freeChatModelList = _allModelOptions.slice();
    // Auto-add first slot
    if ($('freechat-model-slots').children.length === 0) addModelSlot();
    syncFreeChatThinkingEffortDefault();
  } catch (e) { console.warn('\u6a21\u578b\u52a0\u8f7d\u5931\u8d25:', e); }
}

function addModelSlot() {
  const slots = $('freechat-model-slots');
  if (slots.children.length >= 3) { showToast('\u6700\u591a\u652f\u6301 3 \u4e2a\u6a21\u578b\u5e76\u884c', 'warning'); return; }
  const slotIdx = slots.children.length;
  const colors = ['#1664ff', '#00b42a', '#ff7d00'];
  const color = colors[slotIdx % 3];

  const slot = document.createElement('div');
  slot.className = 'fc-model-slot';
  slot.dataset.slotIdx = slotIdx;
  slot.dataset.slotKey = `fc-slot-${++_freeChatSlotCounter}`;
  slot.style.cssText = `display:flex;align-items:center;gap:0;padding:0 0;border-right:1px solid var(--border-light);position:relative;`;

  const defaultModel = _freeChatModelList[slotIdx] || _freeChatModelList[0] || { id: '', name: '\u9009\u62e9\u6a21\u578b' };
  slot.dataset.modelId = defaultModel.id;
  slot.dataset.modelName = defaultModel.name;
  const pickerWrap = document.createElement('div');
  pickerWrap.className = 'fc-slot-picker';
  pickerWrap.style.cssText = 'padding:4px 0 4px 4px;min-width:220px';

  // \u22ee settings button
  const settingsBtn = document.createElement('button');
  settingsBtn.id = `btn-fc-prompt-${defaultModel.id.replace(/[^a-zA-Z0-9-]/g, '-')}`;
  settingsBtn.style.cssText = 'background:none;border:none;padding:6px 8px;cursor:pointer;color:var(--text-tertiary);font-size:16px;font-weight:bold';
  settingsBtn.title = '\u7f16\u8f91\u72ec\u7acb System Prompt';
  settingsBtn.innerHTML = '\u22ee';
  settingsBtn.onclick = () => openFreeChatPrompt(slot.dataset.modelId, slot.dataset.modelName);

  // x close button
  const closeBtn = document.createElement('button');
  closeBtn.style.cssText = 'background:none;border:none;padding:6px 8px;cursor:pointer;color:var(--text-tertiary);font-size:14px';
  closeBtn.innerHTML = '\u00d7';
  closeBtn.onclick = async () => {
    const slotKey = slot.dataset.slotKey;
    const removedSession = freeChatSessions[slotKey];
    delete freeChatSessions[slotKey];
    slot.remove();
    syncFreeChatThinkingEffortDefault();
    if (removedSession?.convId) await completeConversationById(removedSession.convId);
    const hadTurns = !!removedSession?.lastTurn || hasAnyFreeChatTurns() || !slots.children.length;
    if (hadTurns) {
      await clearFreeChat({ preserveSlots: true });
      showToast('模型列已变更，当前模型对比会话已重置', 'info');
    } else {
      updateFreeChatReportState();
    }
  };

  slot.appendChild(pickerWrap);
  slot.appendChild(settingsBtn);
  slot.appendChild(closeBtn);
  slots.appendChild(slot);
  const rerenderSlotPicker = (selectedId) => {
    renderSharedModelPicker(pickerWrap, {
      options: _freeChatModelList,
      value: selectedId,
      accentColor: color,
      onChange: (item) => {
        const previousModelId = slot.dataset.modelId;
        slot.dataset.modelId = item.id;
        slot.dataset.modelName = item.name;
        settingsBtn.id = `btn-fc-prompt-${item.id.replace(/[^a-zA-Z0-9-]/g, '-')}`;
        delete slot.dataset.convId;
        delete freeChatSessions[slot.dataset.slotKey];
        if (previousModelId && previousModelId !== item.id && hasAnyFreeChatTurns()) {
          clearFreeChat({ preserveSlots: true }).catch(() => { });
          showToast('模型选择已变更，当前模型对比会话已重置', 'info');
        }
        rerenderSlotPicker(item.id);
        refreshFreeChatPromptButtonState(item.id);
        syncFreeChatThinkingEffortDefault();
      },
    });
  };
  rerenderSlotPicker(defaultModel.id);
  refreshFreeChatPromptButtonState(defaultModel.id);
  syncFreeChatThinkingEffortDefault();
  if (hasAnyFreeChatTurns()) {
    clearFreeChat({ preserveSlots: true }).catch(() => { });
    showToast('模型列已变更，当前模型对比会话已重置', 'info');
  } else {
    updateFreeChatReportState();
  }
}
async function sendFreeChat() {
  const input = $('freechat-input').value.trim();
  if (!input) return;
  const slots = [...$('freechat-model-slots').querySelectorAll('.fc-model-slot')];
  if (!slots.length) { showToast('请先添加模型', 'warning'); return; }
  $('freechat-empty')?.remove();
  const area = $('freechat-area');
  // 渲染用户消息
  const userBubble = document.createElement('div');
  userBubble.className = 'chat-bubble user';
  userBubble.style.cssText = 'align-self:flex-end;max-width:70%';
  userBubble.innerHTML = `<div class="chat-label">\ud83d\udc64 你</div><div style="line-height:1.6">${escapeHtml(input)}</div>`;
  area.appendChild(userBubble);
  $('freechat-input').value = '';
  $('btn-freechat-send').disabled = true;
  $('btn-freechat-send').textContent = '\u23f3';
  // Bug#1: 骨架屏等待动画
  const waitingGrid = document.createElement('div');
  waitingGrid.className = 'freechat-waiting-grid';
  waitingGrid.style.cssText = `display:grid;grid-template-columns:repeat(${slots.length},1fr);gap:12px;width:100%`;
  const waitColors = ['#1664ff', '#00b42a', '#ff7d00'];
  slots.forEach((slot, i) => {
    const card = document.createElement('div');
    card.className = 'chat-bubble ai chat-bubble-loading';
    card.style.cssText = 'max-width:100%';
    card.innerHTML = `
      <div class="chat-label" style="color:${waitColors[i % 3]}">🤖 ${escapeHtml(slot.dataset.modelName || '模型')}</div>
      <div class="reply-waiting-shell">
        <div class="reply-waiting-line line-lg"></div>
        <div class="reply-waiting-line line-md"></div>
        <div class="reply-waiting-line line-sm"></div>
        <div class="reply-waiting-dots" aria-hidden="true"><span></span><span></span><span></span></div>
      </div>`;
    waitingGrid.appendChild(card);
  });
  area.appendChild(waitingGrid);
  area.scrollTop = area.scrollHeight;
  try {
    const sessions = await Promise.all(slots.map(slot => ensureFreeChatConversationSession(slot)));
    const results = await Promise.all(sessions.map(async (session, index) => {
      const dialogueThinking = getDialogueThinkingState(session.modelId);
      const response = await fetch(`/api/conversations/${session.convId}/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_input: input,
          model_id: session.modelId,
          web_search: _webSearchEnabled,
          thinking_enabled: dialogueThinking.enabled,
          thinking_effort: dialogueThinking.thinking_effort,
          temperature: getStoredFreeChatSamplingConfig(session.modelId).temperature,
          top_p: getStoredFreeChatSamplingConfig(session.modelId).top_p,
        }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        return {
          success: false,
          error: payload.detail || payload.error || response.statusText || '生成失败',
          model_id: session.modelId,
          modelName: session.modelName,
          convId: session.convId,
          turn: session.lastTurn || 0,
        };
      }
      freeChatSessions[slots[index].dataset.slotKey] = {
        ...session,
        lastTurn: payload.turn || session.lastTurn || 0,
      };
      return {
        ...payload,
        success: true,
        modelName: session.modelName,
        convId: session.convId,
      };
    }));
    const colors = ['#1664ff', '#00b42a', '#ff7d00'];
    const grid = document.createElement('div');
    grid.style.cssText = `display:grid;grid-template-columns:repeat(${results.length},1fr);gap:12px;width:100%`;
    results.forEach((res, i) => {
      const card = document.createElement('div');
      card.className = 'chat-bubble ai';
      card.style.cssText = 'max-width:100%';
      const name = slots[i]?.dataset?.modelName || res.modelName || res.model_id;
      const content = res.success ? (res.ai_output || '(无内容)') : `\u274c ${res.error}`;
      const renderedContent = res.success
        ? (formatNarration ? formatNarration(content) : escapeHtml(content))
        : escapeHtml(content);
      const tokens = res.success ? `${res.input_tokens || 0}+${res.output_tokens || 0} tok · ${(res.latency_s || 0).toFixed(1)}s` : '';
      const extra = res.convId ? `<div style="margin-top:8px"><button class="btn btn-secondary" style="width:100%;justify-content:center" onclick="viewConversation('${res.convId}')">查看对话</button></div>` : '';
      card.innerHTML = `<div class="chat-label" style="color:${colors[i % 3]}">🤖 ${escapeHtml(name)}</div><div style="line-height:1.6;font-size:13px">${renderedContent}</div>${tokens ? `<div style="font-size:11px;color:var(--text-tertiary);margin-top:6px">${tokens}</div>` : ''}${extra}`;
      grid.appendChild(card);
    });
    area.appendChild(grid);
    updateFreeChatReportState();
  } catch (e) { showToast('发送失败: ' + e.message, 'error'); } finally {
    if (waitingGrid && waitingGrid.parentNode) waitingGrid.remove();
  }
  $('btn-freechat-send').disabled = false;
  $('btn-freechat-send').textContent = '发送';
  area.scrollTop = area.scrollHeight;
}
async function clearFreeChat({ preserveSlots = false } = {}) {
  await finalizeFreeChatSessions();
  freeChatSessions = {};
  state.compareReportId = '';
  renderFreeChatEmptyState();
  updateFreeChatReportState();
  if (!preserveSlots && $('freechat-model-slots')?.children.length === 0) {
    addModelSlot();
  }
}

async function generateFreeChatCompareReport() {
  const slots = [...$('freechat-model-slots').querySelectorAll('.fc-model-slot')];
  const sessions = slots
    .map(slot => freeChatSessions[slot.dataset.slotKey])
    .filter(item => item?.convId);
  const comparableTurns = getFreeChatComparableTurnCount();
  if (sessions.length < 2) {
    showToast('请至少保留 2 个模型列', 'warning');
    return;
  }
  if (comparableTurns < 3) {
    showToast('至少完成 3 轮模型对比后才能生成报告', 'warning');
    return;
  }
  const button = $('btn-freechat-generate-report');
  if (button) button.disabled = true;
  try {
    await Promise.all(sessions.map(session => completeConversationById(session.convId)));
    const labelsById = {};
    sessions.forEach(session => {
      labelsById[session.convId] = session.modelName || session.modelId || session.convId;
    });
    const report = await createCompareReportFromConversationIds(
      sessions.map(session => session.convId),
      labelsById,
    );
    await openCompareReportOnHistoryPage(report, sessions.map(session => session.convId));
    showToast('模型对比报告已生成', 'success');
  } catch (e) {
    showToast('生成模型对比报告失败: ' + e.message, 'error');
  } finally {
    updateFreeChatReportState();
  }
}

/* ═══ 保存为模板 ═══ */
function toggleTemplateSaveMenu() {
  const dropdown = $('template-save-dropdown');
  if (!dropdown) return;
  const isVisible = dropdown.style.display !== 'none';
  dropdown.style.display = isVisible ? 'none' : 'flex';
  if (!isVisible) {
    dropdown.style.flexDirection = 'column';
    dropdown.style.gap = '2px';
  }
}

async function saveAsPreset() {
  await saveCurrentTemplate('preset');
}

function buildTemplateSnapshot(templateType) {
  const nickname = getInputValue('f-nickname').trim() || `模板_${Date.now()}`;
  const personality = getInputValue('f-personality').trim() || '自定义';
  const snapshot = buildConfigSnapshotRequest(nickname, 'custom_config').config;
  const runtimeOnlyModules = {
    dialogueStartPrompt: snapshot.modules?.dialogueStartPrompt || '',
    dialogue_summary: snapshot.modules?.dialogue_summary || '',
    weekly_schedule: snapshot.modules?.weekly_schedule || '',
    monthly_schedule: snapshot.modules?.monthly_schedule || '',
    system_module8: snapshot.modules?.system_module8 || '',
    system_Role_acting: snapshot.modules?.system_Role_acting || '',
    voice_forbidden: snapshot.modules?.voice_forbidden || DEFAULT_VOICE_FORBIDDEN,
  };
  if (templateType === 'preset') {
    return {
      endpoint: '/api/presets',
      payload: {
        name: nickname,
        type: personality,
        config: {
          prompt_file: snapshot.prompt_file || '',
          few_shot_file: snapshot.few_shot_file || '',
          character: snapshot.character || {},
          context: snapshot.context || {},
          modules: snapshot.modules || {},
        },
      },
      successMessage: `模板 "${nickname}" 保存成功`,
      shouldRefreshPresets: true,
    };
  }
  if (templateType === 'runtime') {
    return {
      endpoint: '/api/configs',
      payload: {
        name: `${nickname}_参数模板`,
        type: 'runtime_template',
        config: {
          prompt_file: snapshot.prompt_file || '',
          few_shot_file: snapshot.few_shot_file || '',
          runtime: snapshot.runtime || {},
          modules: runtimeOnlyModules,
        },
      },
      successMessage: `参数模板 "${nickname}" 保存成功`,
      shouldRefreshPresets: false,
    };
  }
  return {
    endpoint: '/api/configs',
    payload: {
      name: `${nickname}_完整模板`,
      type: 'full_template',
      config: snapshot,
    },
    successMessage: `完整模板 "${nickname}" 保存成功`,
    shouldRefreshPresets: false,
  };
}

async function saveCurrentTemplate(templateType = 'full') {
  const resolvedType = ['preset', 'runtime', 'full'].includes(String(templateType || '').trim())
    ? String(templateType || '').trim()
    : 'full';
  const { endpoint, payload, successMessage, shouldRefreshPresets } = buildTemplateSnapshot(resolvedType);
  try {
    const r = await fetch(endpoint, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
    showToast(`\u2705 ${successMessage}`, 'success');
    if (shouldRefreshPresets) fetchPresets();
  } catch (e) { showToast('保存失败: ' + e.message, 'error'); }
}

/* ═══ Phase 1: System Prompt 管理 ═══ */
async function fetchPromptVersions() {
  try {
    const [chatRes, summaryRes, scoringRes, profileRes] = await Promise.all([
      fetch('/api/prompts?kind=chat'),
      fetch('/api/prompts?kind=summary'),
      fetch('/api/scoring-prompts'),
      fetch('/api/prompts?kind=profile'),
    ]);
    const [chatData, summaryData, scoringData, profileData] = await Promise.all([
      chatRes.json(),
      summaryRes.json(),
      scoringRes.json(),
      profileRes.json(),
    ]);

    const promptSel = $('f-prompt-version');
    if (promptSel) {
      const currentValue = promptSel.value;
      promptSel.innerHTML = '<option value="">自动加载最新提示词（服务器判定）</option>';
      _chatPromptOptions = (chatData.prompts || []).filter(p => p.is_main_prompt);
      _activeChatPromptFilename = chatData.active_filename || '';
      _chatPromptOptions.forEach(p => {
          const opt = document.createElement('option');
          opt.value = p.filename;
          opt.textContent = p.is_latest ? `${p.filename}（最新）` : p.filename;
          promptSel.appendChild(opt);
        });
      const latestFilename = _chatPromptOptions.find(p => p.is_latest)?.filename || '';
      promptSel.value = currentValue || latestFilename || '';
      await syncSelectedChatPrompt({ refreshPreview: true });
    } else {
      _activeChatPromptFilename = chatData.active_filename || '';
    }

    const fillPromptSelect = (selectId, listing, kind) => {
      const sel = $(selectId);
      if (!sel) return;
      const currentValue = sel.value;
      _runtimePromptListings[kind] = listing || null;
      sel.innerHTML = '<option value="">自动加载最新提示词（服务器判定）</option>';
      (listing.prompts || []).forEach(item => {
        const opt = document.createElement('option');
        opt.value = item.filename;
        opt.textContent = item.is_active
          ? `${item.filename}（生效中）`
          : (item.filename === listing.latest_filename ? `${item.filename}（最新）` : item.filename);
        sel.appendChild(opt);
      });
      sel.value = currentValue || '';
    };

    fillPromptSelect('f-summary-prompt-version', summaryData, 'summary');
    fillPromptSelect('f-scoring-prompt-version', scoringData, 'scoring');
    fillPromptSelect('f-profile-prompt-version', profileData, 'profile');
    populateABPromptSelectors();
    refreshTestCenterShell();
    refreshHeaderModelSettingsButtonState();
  } catch (e) {
    console.warn('获取提示词版本失败', e);
  }
}

function getRuntimePromptSelectId(kind) {
  if (kind === 'chat') return 'f-prompt-version';
  if (kind === 'summary') return 'f-summary-prompt-version';
  if (kind === 'profile') return 'f-profile-prompt-version';
  return 'f-scoring-prompt-version';
}

function getRuntimePromptFallbackFilename(kind) {
  if (kind === 'chat') {
    return _activeChatPromptFilename || (_chatPromptOptions.find(item => item.is_latest)?.filename || '');
  }
  const listing = _runtimePromptListings[kind] || null;
  return String(listing?.latest_filename || listing?.active_filename || '').trim();
}

async function loadRuntimePromptContent(kind, filename, { force = false, syncStorage = false } = {}) {
  const resolvedFilename = String(filename || '').trim();
  if (!resolvedFilename) return '';
  const cacheKey = `${kind}:${resolvedFilename}`;
  let content = '';
  if (!force && _runtimePromptContentCache.has(cacheKey)) {
    content = _runtimePromptContentCache.get(cacheKey) || '';
  } else {
    const response = await fetch(buildPromptDetailUrl(kind, resolvedFilename));
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || response.statusText || '读取提示词失败');
    content = data.content || '';
    _runtimePromptContentCache.set(cacheKey, content);
  }
  if (syncStorage && kind === 'chat') {
    if ($('f-system-prompt')) $('f-system-prompt').value = content;
    if ($('f-system-prompt-shadow')) $('f-system-prompt-shadow').value = content;
  }
  return content;
}

async function syncSelectedChatPrompt({ force = false, refreshPreview = false } = {}) {
  const filename = getInputValue('f-prompt-version').trim();
  if (!filename) {
    if ($('f-system-prompt')) $('f-system-prompt').value = '';
    if ($('f-system-prompt-shadow')) $('f-system-prompt-shadow').value = '';
    refreshHeaderModelSettingsButtonState();
    if (refreshPreview) refreshSPPreview();
    return '';
  }
  const content = await loadRuntimePromptContent('chat', filename, { force, syncStorage: true });
  refreshHeaderModelSettingsButtonState();
  if (refreshPreview) refreshSPPreview();
  return content;
}

function toggleSPInlineEdit() {
  const spInput = $('f-system-prompt');
  if (!spInput) return;
  if (spInput.hasAttribute('readonly')) {
    spInput.removeAttribute('readonly');
    spInput.style.cursor = 'text';
    spInput.style.background = 'var(--bg-body)';
    showToast('已开启内联编辑配置区，可自定义发送的主控 Prompt', 'success');
  } else {
    spInput.setAttribute('readonly', 'true');
    spInput.style.cursor = 'not-allowed';
    spInput.style.background = 'var(--bg-hover)';
    showToast('已锁定配置区', 'info');
  }
}

function openFullscreenSP() {
  openRuntimePromptEditor('chat');
}

async function saveFullscreenSP() {
  if (!_runtimePromptEditorContext) {
    closeModal('modal-sp-edit');
    return;
  }
  const { kind, filename } = _runtimePromptEditorContext;
  try {
    const r = await fetch(buildPromptEditUrl(kind, filename), {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: $('fs-sp-editor').value }),
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.detail || r.statusText || '保存失败');
    _runtimePromptContentCache.set(`${kind}:${filename}`, $('fs-sp-editor').value);
    if (kind === 'chat') {
      if ($('f-system-prompt')) $('f-system-prompt').value = $('fs-sp-editor').value;
      if ($('f-system-prompt-shadow')) $('f-system-prompt-shadow').value = $('fs-sp-editor').value;
      refreshSPPreview();
    }
    closeModal('modal-sp-edit');
    showToast(`${PROMPT_KIND_CONFIG[kind].label}已保存`, 'success');
    await fetchPromptVersions();
    if (getCurrentPageName() === 'prompts') await loadPrompts();
  } catch (e) {
    showToast('保存失败: ' + e.message, 'error');
  }
}

async function importSPVersion() {
  const filename = $('f-sp-import-list') ? $('f-sp-import-list').value : '';
  if (!filename) {
    showToast('请先选择一个提示词版本', 'warning');
    return;
  }
  try {
    await loadRuntimePromptContent('chat', filename, { force: true, syncStorage: true });
    refreshSPPreview();
    showToast(`已成功导入 ${filename}`, 'success');
  } catch (e) {
    showToast(`导入失败: ${e.message}`, 'error');
  }
}

async function openRuntimePromptEditor(kind) {
  const selectId = getRuntimePromptSelectId(kind);
  const filename = getInputValue(selectId).trim() || getRuntimePromptFallbackFilename(kind);
  if (!filename) {
    showToast('请先选择提示词版本', 'warning');
    return;
  }
  try {
    const content = await loadRuntimePromptContent(kind, filename, { syncStorage: kind === 'chat' });
    if (kind === 'chat') refreshSPPreview();
    _runtimePromptEditorContext = { kind, filename };
    if (kind === 'chat') _variablePreviewModes['runtime-prompt-editor-vars-body'] = 'related';
    $('runtime-prompt-editor-title').textContent = `${PROMPT_KIND_CONFIG[kind].label}编辑器`;
    $('fs-sp-editor').value = content || '';
    const editorAside = $('runtime-prompt-editor-aside');
    const editorGeneration = $('runtime-prompt-editor-generation');
    const editorVars = $('runtime-prompt-editor-vars');
    if (editorAside) editorAside.style.display = kind === 'chat' ? 'flex' : 'none';
    if (editorGeneration) editorGeneration.style.display = kind === 'chat' ? 'flex' : 'none';
    if (editorVars) editorVars.style.display = kind === 'chat' ? 'flex' : 'none';
    renderVariablePreviewTags({
      containerId: 'runtime-prompt-editor-vars-body',
      promptText: content || '',
    });
    showModal('modal-sp-edit');
  } catch (e) {
    showToast('读取提示词失败: ' + e.message, 'error');
  }
}

async function previewRuntimePrompt(kind) {
  const selectId = getRuntimePromptSelectId(kind);
  const filename = getInputValue(selectId).trim() || getRuntimePromptFallbackFilename(kind);
  if (!filename) {
    showToast('请先选择提示词版本', 'warning');
    return;
  }
  try {
    const content = await loadRuntimePromptContent(kind, filename, { syncStorage: kind === 'chat' });
    if (kind === 'chat') refreshSPPreview();
    $('runtime-prompt-preview-title').textContent = `${PROMPT_KIND_CONFIG[kind].label}预览`;
    const previewMeta = $('runtime-prompt-preview-meta');
    if (kind === 'chat') {
      if (previewMeta) {
        const variables = extractPromptVariables(content || '').filter(v => v !== 'user_message');
        previewMeta.style.display = 'block';
        previewMeta.innerHTML = `检测到 <strong>${variables.length}</strong> 个变量，占位符将按分类着色；缺失变量会以红色标记，自动生成变量会显示自动来源。`;
      }
      $('sp-preview-content').innerHTML = resolveSystemPromptPreview(content || '');
    } else {
      if (previewMeta) {
        previewMeta.style.display = 'none';
        previewMeta.innerHTML = '';
      }
      $('sp-preview-content').textContent = content || '';
    }
    showModal('modal-sp-preview');
  } catch (e) {
    showToast('预览失败: ' + e.message, 'error');
  }
}

/* ═══ Phase 2: 系统模块编辑弹窗 ═══ */
let _currentEditModuleId = null;

function openModuleEditor(moduleId, moduleName) {
  const ta = $(moduleId);
  const fsInput = $('fs-module-editor');
  const title = $('module-edit-title');

  if (ta && fsInput && title) {
    _currentEditModuleId = moduleId;
    title.textContent = `编辑系统模块: ${moduleName}`;
    fsInput.value = ta.value;
    showModal('modal-module-edit');
  }
}

function saveModuleEdit() {
  if (!_currentEditModuleId) return;
  const ta = $(_currentEditModuleId);
  const fsInput = $('fs-module-editor');

  if (ta && fsInput) {
    ta.value = fsInput.value;
    if (_currentEditModuleId === 'f-sys-role-acting-module' && $('f-sys-role-acting')) {
      $('f-sys-role-acting').value = fsInput.value;
    }
    closeModal('modal-module-edit');

    // 更新标签状态为"手动"
    const badgeId = 'badge-' + _currentEditModuleId.replace('f-', '');
    const badge = $(badgeId);
    if (badge) {
      badge.textContent = '手动';
      badge.style.background = 'var(--primary-color)';
      badge.style.color = '#fff';
    }

    refreshSPPreview();
    showToast('模块内容已手动更新', 'success');
  }
  _currentEditModuleId = null;
}

function buildPromptVariableMap() {
  const cfg = getFormConfig();
  const relationshipPreset = getResolvedRelationshipVars();
  const now = new Date();
  const baseValues = window.runtimePromptBaseValues || {};
  const defaultLastConversationType = resolvePreviousConversationType(cfg.nickname || '');
  const currentTime = baseValues.currentTime || formatPromptPreviewDate(now);
  const weekDay = baseValues.weekDay || getPromptPreviewWeekday(now);
  const timeperiod = cfg.time_period || baseValues.timeperiod || inferPromptPreviewTimeperiod(now.getHours());
  const season = cfg.season || baseValues.season || inferPromptPreviewSeason(now.getMonth() + 1);
  return {
    Role_Nickname: cfg.nickname || '',
    gender: cfg.gender || '',
    age: cfg.age || '',
    occupation: cfg.occupation || '',
    Role_info_works: cfg.role_info_works || '',
    personality: cfg.personality || '',
    speaking_style: cfg.speaking_style || '',
    personal_type: cfg.personality || '',
    background: cfg.background || '',
    hobby: cfg.hobby || '',
    relationship: cfg.relationship || '',
    relation_info: relationshipPreset.info || '',
    intimacy_boundary: relationshipPreset.intimacy || '',
    relation_calling: relationshipPreset.calling || '',
    current_scene: cfg.scene || '',
    currentTime,
    weekDay,
    timeperiod,
    season,
    完整时间信息: baseValues['完整时间信息'] || [currentTime, weekDay, timeperiod, season].filter(Boolean).join(' / '),
    last_cst_type: baseValues.last_cst_type || defaultLastConversationType || '',
    user_Nickname: cfg.user_nickname || '',
    user_gender: cfg.user_gender || '',
    user_identity: cfg.user_identity || '',
    moments: baseValues.moments || '',
    monthly_schedule: baseValues.monthly_schedule || '',
    ...buildSystemModulesPayload(),
  };
}

function extractPromptVariables(promptText) {
  return Array.from(new Set(Array.from((promptText || '').matchAll(/\{\{\s*([a-zA-Z0-9_\u4e00-\u9fa5]+)\s*\}\}/g)).map(match => match[1])));
}

const VAR_ZH_MAP = {
  'Role_Nickname': '昵称',
  'gender': '性别',
  'age': '年龄',
  'occupation': '职业',
  'Role_info_works': '代表作品',
  'background': '背景',
  'personality': '性格',
  'speaking_style': '说话风格',
  'personal_type': '性格类型',
  'hobby': '爱好',
  'system_module8': '兴趣爱好补充',
  'longform_persona': '角色行为画像',
  'longform_narrative_style': '叙事策略包',
  'longform_dialogue_guideline': '对白规范',
  'longform_few_shot': 'Few-shot示例',
  'user_Nickname': '用户昵称',
  'user_gender': '用户性别',
  'user_identity': '用户身份',
  'relation_calling': '称呼规则',
  'relationship': '关系阶段',
  'intimacy_boundary': '亲密边界',
  'currentTime': '当前时间',
  'weekDay': '星期',
  'timeperiod': '时段',
  'season': '季节',
  '完整时间信息': '完整时间信息',
  'last_cst_type': '上一通类型',
  'weekly_schedule': '当前正在做的事情',
  'monthly_schedule': '近期行动（月度）',
  'current_scene': '当前场景',
  'dialogueStartPrompt': '长期记忆用户画像',
  'dialogue_summary': '对话摘要',
  'system_Role_acting': '名人角色设定',
  'voice_forbidden': '语音条禁用规则',
  'moments': '朋友圈动态'
};

const VARIABLE_GROUPS = [
  { id: 'role', title: '角色信息', color: '#7c3aed' },
  { id: 'user', title: '用户信息', color: '#0891b2' },
  { id: 'relation', title: '关系边界', color: '#e11d48' },
  { id: 'scene', title: '时空场景', color: '#ca8a04' },
  { id: 'system', title: '系统模块', color: '#2563eb' },
  { id: 'memory', title: '记忆变量', color: '#16a34a' },
];

const VARIABLE_FIELD_SCHEMA = [
  { key: 'Role_Nickname', zhLabel: '昵称', group: 'role', sourceId: 'f-nickname', controlType: 'text', sourceKind: 'preset', defaultStrategy: 'preset-fill', editableMode: 'inline', summaryMode: 'inline', expandMode: 'none', placeholder: '如：萧璟言', emptyHint: '当前会话未写入角色昵称' },
  { key: 'gender', zhLabel: '性别', group: 'role', sourceId: 'f-gender', controlType: 'select', sourceKind: 'preset', defaultStrategy: 'preset-fill', editableMode: 'inline', summaryMode: 'inline', expandMode: 'none' },
  { key: 'age', zhLabel: '年龄', group: 'role', sourceId: 'f-age', controlType: 'text', sourceKind: 'preset', defaultStrategy: 'preset-fill', editableMode: 'inline', summaryMode: 'inline', expandMode: 'none', placeholder: '25' },
  { key: 'occupation', zhLabel: '职业', group: 'role', sourceId: 'f-occupation', controlType: 'text', sourceKind: 'preset', defaultStrategy: 'preset-fill', editableMode: 'inline', summaryMode: 'inline', expandMode: 'none', placeholder: '金融分析师' },
  { key: 'Role_info_works', zhLabel: '代表作品', group: 'role', sourceId: 'f-role-info-works', controlType: 'text', sourceKind: 'preset', defaultStrategy: 'preset-fill', editableMode: 'inline', summaryMode: 'inline', expandMode: 'none', optional: true, placeholder: '如：代表作 / 代表项目 / 经典经历', emptyHint: '无代表作品时可留空' },
  { key: 'background', zhLabel: '背景', group: 'role', sourceId: 'f-background', controlType: 'text', sourceKind: 'preset', defaultStrategy: 'preset-fill', editableMode: 'inline', summaryMode: 'inline', expandMode: 'none', placeholder: '背景设定' },
  { key: 'personality', zhLabel: '性格', group: 'role', sourceId: 'f-personality', controlType: 'text', sourceKind: 'preset', defaultStrategy: 'preset-fill', editableMode: 'inline', summaryMode: 'inline', expandMode: 'none', placeholder: '角色性格' },
  { key: 'speaking_style', zhLabel: '说话风格', group: 'role', sourceId: 'f-speaking-style', controlType: 'text', sourceKind: 'preset', defaultStrategy: 'preset-fill', editableMode: 'inline', summaryMode: 'inline', expandMode: 'none', placeholder: '说话风格' },
  { key: 'personal_type', zhLabel: '性格类型', group: 'role', controlType: 'readonly', sourceKind: 'derived', defaultStrategy: 'preset-link', editableMode: 'readonly', summaryMode: 'card', expandMode: 'none', readonly: true, valueResolver: () => getInputValue('f-personality').trim(), emptyHint: '根据角色性格自动同步', previewLength: 56 },
  { key: 'hobby', zhLabel: '爱好', group: 'role', sourceId: 'f-hobby', controlType: 'text', sourceKind: 'preset', defaultStrategy: 'preset-fill', editableMode: 'inline', summaryMode: 'inline', expandMode: 'none', placeholder: '兴趣爱好' },

  { key: 'user_Nickname', zhLabel: '用户昵称', group: 'user', sourceId: 'f-user-nickname', controlType: 'text', sourceKind: 'user-profile', defaultStrategy: 'system-default', editableMode: 'inline', summaryMode: 'inline', expandMode: 'none', placeholder: '小鹿', emptyHint: '默认用户昵称为小鹿' },
  { key: 'user_gender', zhLabel: '用户性别', group: 'user', sourceId: 'f-user-gender', controlType: 'select', sourceKind: 'user-profile', defaultStrategy: 'manual', editableMode: 'inline', summaryMode: 'inline', expandMode: 'none' },
  { key: 'user_identity', zhLabel: '用户身份', group: 'user', sourceId: 'f-user-identity', controlType: 'text', sourceKind: 'user-profile', defaultStrategy: 'manual', editableMode: 'inline', summaryMode: 'inline', expandMode: 'none', placeholder: '用户身份' },

  { key: 'relationship', zhLabel: '关系阶段', group: 'relation', sourceId: 'f-relationship', controlType: 'select', sourceKind: 'manual', defaultStrategy: 'manual', editableMode: 'inline', summaryMode: 'inline', expandMode: 'none' },
  { key: 'relation_calling', zhLabel: '称呼规则', group: 'relation', controlType: 'readonly', sourceKind: 'relationship-link', defaultStrategy: 'relationship-link', editableMode: 'readonly', summaryMode: 'card', expandMode: 'none', readonly: true, valueResolver: () => getResolvedRelationshipVars().calling, emptyHint: '切换关系阶段后自动联动', previewLength: 60, pendingEligible: true },
  { key: 'intimacy_boundary', zhLabel: '亲密边界', group: 'relation', controlType: 'readonly', sourceKind: 'relationship-link', defaultStrategy: 'relationship-link', editableMode: 'readonly', summaryMode: 'card', expandMode: 'none', readonly: true, valueResolver: () => getResolvedRelationshipVars().intimacy, emptyHint: '按关系阶段自动联动边界规则', previewLength: 84, pendingEligible: true },
  { key: 'last_cst_type', zhLabel: '上一通类型', group: 'relation', controlType: 'readonly', sourceKind: 'history-auto', defaultStrategy: 'history-auto', editableMode: 'readonly', summaryMode: 'card', expandMode: 'none', readonly: true, valueResolver: () => resolvePreviousConversationType(getInputValue('f-nickname').trim()), emptyHint: '按上一轮对话类型自动推导', previewLength: 36, pendingEligible: true },

  { key: 'current_scene', zhLabel: '当前场景', group: 'scene', sourceId: 'f-scene', controlType: 'text', sourceKind: 'manual', defaultStrategy: 'manual', editableMode: 'inline', summaryMode: 'inline', expandMode: 'none', placeholder: '当前场景' },
  { key: 'timeperiod', zhLabel: '时段', group: 'scene', sourceId: 'f-timeperiod', controlType: 'select', sourceKind: 'time-auto', defaultStrategy: 'time-auto', editableMode: 'inline', summaryMode: 'inline', expandMode: 'none' },
  { key: 'season', zhLabel: '季节', group: 'scene', sourceId: 'f-season', controlType: 'select', sourceKind: 'time-auto', defaultStrategy: 'time-auto', editableMode: 'inline', summaryMode: 'inline', expandMode: 'none' },
  { key: 'currentTime', zhLabel: '当前时间', group: 'scene', controlType: 'readonly', sourceKind: 'time-auto', defaultStrategy: 'time-auto', editableMode: 'readonly', summaryMode: 'card', expandMode: 'none', readonly: true, emptyHint: '按本机时间自动生成', previewLength: 48, pendingEligible: true },
  { key: 'weekDay', zhLabel: '星期', group: 'scene', controlType: 'readonly', sourceKind: 'time-auto', defaultStrategy: 'time-auto', editableMode: 'readonly', summaryMode: 'card', expandMode: 'none', readonly: true, emptyHint: '按本机时间自动生成', previewLength: 24, pendingEligible: true },
  { key: '完整时间信息', zhLabel: '完整时间信息', group: 'scene', controlType: 'readonly', sourceKind: 'time-auto', defaultStrategy: 'time-auto', editableMode: 'readonly', summaryMode: 'card', expandMode: 'none', readonly: true, emptyHint: '每小时刷新一次完整时间信息', previewLength: 84, pendingEligible: true },

  { key: 'longform_persona', zhLabel: '角色行为画像', group: 'system', sourceId: 'f-sys-persona', badgeId: 'badge-sys-persona', controlType: 'longtext', sourceKind: 'preset-auto', defaultStrategy: 'preset-auto', editableMode: 'expandable', summaryMode: 'card', expandMode: 'panel', placeholder: '长文行为画像', emptyHint: '按性格类型 × 性别 × 关系阶段自动匹配', previewLength: 88, pendingEligible: true },
  { key: 'longform_narrative_style', zhLabel: '叙事策略包', group: 'system', sourceId: 'f-sys-style', badgeId: 'badge-sys-style', controlType: 'longtext', sourceKind: 'preset-auto', defaultStrategy: 'preset-auto', editableMode: 'expandable', summaryMode: 'card', expandMode: 'panel', placeholder: '长文叙事风格', emptyHint: '按性格类型自动匹配叙事风格', previewLength: 88, pendingEligible: true },
  { key: 'longform_dialogue_guideline', zhLabel: '对白规范', group: 'system', sourceId: 'f-sys-dialogue-guideline', badgeId: 'badge-sys-dialogue-guideline', controlType: 'longtext', sourceKind: 'preset-auto', defaultStrategy: 'preset-auto', editableMode: 'expandable', summaryMode: 'card', expandMode: 'panel', placeholder: '长文对白规范', emptyHint: '按性格类型自动匹配对白规范', previewLength: 88, pendingEligible: true },
  { key: 'longform_few_shot', zhLabel: 'Few-shot示例', group: 'system', sourceId: 'f-sys-fewshot', badgeId: 'badge-sys-fewshot', controlType: 'longtext', sourceKind: 'preset-auto', defaultStrategy: 'preset-auto', editableMode: 'expandable', summaryMode: 'card', expandMode: 'panel', placeholder: 'Few-shot 示例', emptyHint: '按性格类型与场景标签自动匹配', previewLength: 88, pendingEligible: true },
  { key: 'system_module8', zhLabel: '兴趣爱好补充', group: 'system', sourceId: 'f-sys-module8', badgeId: 'badge-sys-module8', controlType: 'longtext', sourceKind: 'preset-auto', defaultStrategy: 'preset-auto', editableMode: 'expandable', summaryMode: 'card', expandMode: 'panel', placeholder: '兴趣爱好补充', emptyHint: '系统自动扩展兴趣标签', previewLength: 80, pendingEligible: true },
  { key: 'weekly_schedule', zhLabel: '当前正在做的事情', group: 'system', sourceId: 'f-sys-schedule', badgeId: 'badge-sys-schedule', controlType: 'longtext', sourceKind: 'schedule-auto', defaultStrategy: 'schedule-auto', editableMode: 'expandable', summaryMode: 'card', expandMode: 'panel', placeholder: '当前正在做的事情', emptyHint: '每日首次聊天时自动同步', previewLength: 80, pendingEligible: true },
  { key: 'system_Role_acting', zhLabel: '名人角色设定', group: 'system', sourceId: 'f-sys-role-acting-module', controlType: 'longtext', sourceKind: 'manual', defaultStrategy: 'manual', editableMode: 'expandable', summaryMode: 'card', expandMode: 'panel', placeholder: '名人角色设定', emptyHint: '可留空，按需要补充' },
  { key: 'voice_forbidden', zhLabel: '语音条禁用规则', group: 'system', sourceId: 'f-voice-forbidden', badgeId: 'badge-voice-forbidden', controlType: 'longtext', sourceKind: 'system-default', defaultStrategy: 'system-default', editableMode: 'expandable', summaryMode: 'card', expandMode: 'panel', placeholder: '语音条禁用规则', emptyHint: '语音消息发送时自动注入约束', previewLength: 96 },

  { key: 'dialogueStartPrompt', zhLabel: '长期记忆用户画像', group: 'memory', sourceId: 'f-sys-startprompt', badgeId: 'badge-sys-startprompt', controlType: 'longtext', sourceKind: 'memory-auto', defaultStrategy: 'memory-auto', editableMode: 'expandable', summaryMode: 'card', expandMode: 'panel', placeholder: '长期记忆用户画像', emptyHint: '长期记忆画像自动同步写入', previewLength: 96, pendingEligible: true },
  { key: 'dialogue_summary', zhLabel: '对话摘要', group: 'memory', sourceId: 'f-sys-summary', badgeId: 'badge-sys-summary', controlType: 'longtext', sourceKind: 'memory-auto', defaultStrategy: 'memory-auto', editableMode: 'expandable', summaryMode: 'card', expandMode: 'panel', placeholder: '对话摘要', emptyHint: '每 10 轮自动更新摘要', previewLength: 96, pendingEligible: true },
  { key: 'moments', zhLabel: '朋友圈动态', group: 'memory', customKey: 'moments', controlType: 'longtext', sourceKind: 'memory-auto', defaultStrategy: 'memory-auto', editableMode: 'expandable', summaryMode: 'card', expandMode: 'panel', optional: true, placeholder: '朋友圈动态记忆', emptyHint: '系统从朋友圈同步，无内容可留空', previewLength: 88, pendingEligible: true },
  { key: 'monthly_schedule', zhLabel: '近期行动（月度）', group: 'memory', customKey: 'monthly_schedule', controlType: 'longtext', sourceKind: 'schedule-auto', defaultStrategy: 'schedule-auto', editableMode: 'expandable', summaryMode: 'card', expandMode: 'panel', optional: true, placeholder: '近期行动（月度）', emptyHint: '系统月程未同步时可留空', previewLength: 88, pendingEligible: true },
];

const VARIABLE_SCHEMA_MAP = Object.fromEntries(VARIABLE_FIELD_SCHEMA.map(field => [field.key, field]));
const VARIABLE_SCHEMA_KEYS = VARIABLE_FIELD_SCHEMA.map(field => field.key);
const VAR_CATEGORY = Object.fromEntries(VARIABLE_GROUPS.map(group => [group.title, { color: group.color, vars: VARIABLE_FIELD_SCHEMA.filter(field => field.group === group.id).map(field => field.key) }]));
const RIGHT_PANEL_EDITOR_SECTIONS = VARIABLE_GROUPS.map(group => ({ title: group.title, color: group.color, keys: VARIABLE_FIELD_SCHEMA.filter(field => field.group === group.id).map(field => field.key) }));
const RIGHT_PANEL_EDITOR_META = Object.fromEntries(VARIABLE_FIELD_SCHEMA.map(field => [field.key, { ...field, control: field.controlType === 'select' ? 'select' : undefined }]));
const AUTO_PENDING_SYNC_KEYS = [
  'longform_persona',
  'longform_narrative_style',
  'longform_dialogue_guideline',
  'longform_few_shot',
  'voice_forbidden',
];
const _autoFieldPendingKeys = new Set();
const _variablePreviewModes = {};
window.rightPanelExpandedFields = window.rightPanelExpandedFields || {};

function getRightPanelEditorMeta(key) {
  return RIGHT_PANEL_EDITOR_META[key] || {};
}

function getRightPanelEditorValue(key, values = buildPromptVariableMap()) {
  const meta = getRightPanelEditorMeta(key);
  if (typeof meta.valueResolver === 'function') return String(meta.valueResolver(values) || '');
  if (meta.sourceId) return String(getInputValue(meta.sourceId) || '');
  const resolvedKey = meta.customKey || key;
  return String(values[resolvedKey] || values[key] || '');
}

function getVariableGroupMeta(groupId) {
  return VARIABLE_GROUPS.find(group => group.id === groupId) || { id: groupId, title: '其他', color: '#6b7280' };
}

function normalizeRightPanelBadgeStatus(rawText) {
  const badgeText = String(rawText || '').trim();
  if (!badgeText) return null;
  if (/自动填充/.test(badgeText)) return { label: '系统自动填充', tone: 'auto' };
  if (/自动匹配/.test(badgeText)) return { label: '系统自动匹配', tone: 'auto' };
  if (/自动生成/.test(badgeText)) return { label: '系统自动生成', tone: 'auto' };
  if (/手动/.test(badgeText)) return { label: '手动覆盖', tone: 'manual' };
  return {
    label: badgeText,
    tone: /自动|联动|推导|同步/.test(badgeText) ? 'auto' : 'manual',
  };
}

function updateAutoFieldPending(keys = [], pending = true) {
  let changed = false;
  const normalized = Array.isArray(keys) ? keys : Array.from(keys || []);
  normalized.forEach((key) => {
    if (!key) return;
    if (pending) {
      if (!_autoFieldPendingKeys.has(key)) {
        _autoFieldPendingKeys.add(key);
        changed = true;
      }
      return;
    }
    if (_autoFieldPendingKeys.delete(key)) changed = true;
  });
  if (changed) refreshSPPreview();
}

function markAutoFieldRefreshPending(keys = AUTO_PENDING_SYNC_KEYS) {
  updateAutoFieldPending(keys, true);
}

function clearAutoFieldRefreshPending(keys = AUTO_PENDING_SYNC_KEYS) {
  updateAutoFieldPending(keys, false);
}

function isAutoFieldPending(meta, value, key) {
  if (!meta.pendingEligible) return false;
  if (String(value || '').trim()) return false;
  return _autoFieldPendingKeys.has(key);
}

function getFieldSourceText(meta, statusInfo, pending, value) {
  if (pending) return '系统正在联动或生成，稍后会自动刷新。';
  switch (meta.sourceKind) {
    case 'preset':
      return '预设角色基础信息，可直接编辑。';
    case 'user-profile':
      return meta.key === 'user_Nickname'
        ? '用户画像默认值，默认填充为"小鹿"。'
        : '当前会话用户画像，可直接编辑。';
    case 'relationship-link':
      return value ? '关系阶段联动结果。' : '等待关系联动结果。';
    case 'history-auto':
      return value ? '历史会话推导结果。' : '暂无历史可推导。';
    case 'time-auto':
      return value ? '本机时间自动生成。' : '等待本机时间生成。';
    case 'preset-auto':
      return statusInfo.tone === 'manual' ? '已手动覆盖自动匹配结果。' : '按角色、关系、性别自动匹配。';
    case 'schedule-auto':
      return statusInfo.tone === 'manual' ? '已手动覆盖系统日程结果。' : '系统日程同步结果。';
    case 'memory-auto':
      return statusInfo.tone === 'manual' ? '已手动覆盖系统记忆结果。' : '系统记忆同步结果。';
    case 'system-default':
      return statusInfo.tone === 'manual' ? '已手动覆盖系统默认约束。' : '系统默认基线，语音消息发送时自动注入。';
    case 'derived':
      return value ? '由当前字段派生展示。' : '等待上游字段完成。';
    default:
      return '当前会话配置，可直接编辑。';
  }
}

function getRightPanelEditorStatus(key, meta, state, value) {
  if (meta.badgeId) {
    const badgeStatus = normalizeRightPanelBadgeStatus($(`${meta.badgeId}`)?.textContent || '');
    if (badgeStatus) return badgeStatus;
  }
  if (meta.readonly) {
    if (key === 'currentTime' || key === 'weekDay' || key === '完整时间信息') return { label: value ? '系统自动生成' : '等待时间生成', tone: 'auto' };
    if (key === 'relation_calling' || key === 'intimacy_boundary') return { label: value ? '关系自动联动' : '等待关系联动', tone: 'auto' };
    if (key === 'last_cst_type') return { label: value ? '会话自动推导' : '等待会话推导', tone: 'auto' };
    if (key === 'personal_type') return { label: value ? '同步角色类型' : '等待角色同步', tone: 'auto' };
    return { label: value ? '系统只读展示' : '等待系统同步', tone: 'auto' };
  }
  if (state.missing && meta.optional) return { label: '可留空', tone: 'optional' };
  if (state.missing) return { label: '待补充', tone: 'missing' };
  if (state.hasOverride && state.currentVal !== state.originalVal) return { label: '手动覆盖', tone: 'manual' };
  if (state.autoGenerated) return { label: '系统自动生成', tone: 'auto' };
  switch (meta.sourceKind) {
    case 'preset':
      return { label: '预设自动填充', tone: 'auto' };
    case 'user-profile':
      return { label: key === 'user_Nickname' ? '默认已填充' : '资料已填充', tone: 'auto' };
    case 'relationship-link':
      return { label: value ? '关系自动联动' : '等待关系联动', tone: 'auto' };
    case 'history-auto':
      return { label: value ? '历史自动推导' : '等待历史推导', tone: 'auto' };
    case 'time-auto':
      return { label: value ? '时间自动生成' : '等待时间生成', tone: 'auto' };
    case 'preset-auto':
      return { label: value ? '自动匹配结果' : '等待自动匹配', tone: 'auto' };
    case 'schedule-auto':
      return { label: value ? '系统日程同步' : '等待日程同步', tone: 'auto' };
    case 'memory-auto':
      return { label: value ? '系统记忆同步' : '等待记忆同步', tone: 'auto' };
    case 'system-default':
      return { label: value ? '系统自动填充' : '等待系统填充', tone: 'auto' };
    default:
      break;
  }
  return { label: '用户可编辑', tone: 'manual' };
}

function getRightPanelEditorPreviewText(meta, value, missing, pending = false) {
  if (pending) return '系统正在同步默认值或联动结果…';
  if (missing) return meta.emptyHint || meta.placeholder || '可直接填写';
  return truncateText(value, meta.previewLength || 42);
}

function rememberRightPanelEditorFocus(container) {
  const active = document.activeElement;
  if (!container || !active || !container.contains(active) || !active.dataset?.editorKey) return null;
  return {
    key: active.dataset.editorKey,
    start: typeof active.selectionStart === 'number' ? active.selectionStart : null,
    end: typeof active.selectionEnd === 'number' ? active.selectionEnd : null,
  };
}

function restoreRightPanelEditorFocus(container, snapshot) {
  if (!container || !snapshot?.key) return;
  const target = container.querySelector(`[data-editor-key="${snapshot.key}"]`);
  if (!target) return;
  target.focus();
  if (typeof snapshot.start === 'number' && typeof target.setSelectionRange === 'function') {
    target.setSelectionRange(snapshot.start, snapshot.end ?? snapshot.start);
  }
}

function renderRightPanelVariableEditor({ preserveFocus = false } = {}) {
  const container = $('role-variable-editor');
  if (!container) return;
  const focusSnapshot = preserveFocus ? rememberRightPanelEditorFocus(container) : null;
  const values = buildPromptVariableMap();
  const escapeAttr = value => escapeHtml(String(value ?? '')).replace(/"/g, '&quot;');

  let html = '';
  RIGHT_PANEL_EDITOR_SECTIONS.forEach(section => {
    html += `<section class="role-variable-editor-group"><div class="role-variable-editor-group-title" style="color:${section.color}">${section.title}</div>`;
    section.keys.forEach(key => {
      const meta = getRightPanelEditorMeta(key);
      const cat = _getVarCategory(key);
      const groupMeta = getVariableGroupMeta(meta.group);
      const value = getRightPanelEditorValue(key, values);
      const state = getPromptVariableState(meta.customKey || key, values);
      const pending = isAutoFieldPending(meta, value, key);
      const missing = !String(value || '').trim();
      const statusInfo = getRightPanelEditorStatus(key, meta, state, value);
      const previewText = getRightPanelEditorPreviewText(meta, value, missing, pending);
      const chipClasses = [
        'role-variable-editor-chip',
        missing ? 'is-missing' : '',
        statusInfo.tone === 'auto' || meta.readonly || state.autoGenerated ? 'is-auto' : '',
      ].filter(Boolean).join(' ');
      const chipTitle = missing
        ? `${VAR_ZH_MAP[key] || key} ({{${key}}})\n当前值为空`
        : `${VAR_ZH_MAP[key] || key} ({{${key}}})\n当前值：${value}`;

      let controlHtml = '';
      if (meta.control === 'select') {
        const source = $(meta.sourceId);
        const options = source
          ? [...source.options].map(option => `<option value="${escapeAttr(option.value)}" ${String(option.value) === String(value) ? 'selected' : ''}>${escapeHtml(option.textContent || option.value || '')}</option>`).join('')
          : '';
        controlHtml = `<select class="form-control role-variable-editor-select" data-editor-key="${escapeAttr(key)}" onchange="window.handleRightPanelEditorInput('${key}', this.value, 'change')">${options}</select>`;
      } else if (meta.readonly) {
        const summaryClasses = ['role-variable-editor-summary-card', statusInfo.tone === 'auto' ? 'is-auto' : '', missing ? 'is-missing' : '', pending ? 'is-pending' : ''].filter(Boolean).join(' ');
        controlHtml = `<div class="role-variable-editor-readonly">
          <div class="${summaryClasses}">
            <div class="role-variable-editor-summary-value${missing ? ' is-empty' : ''}${pending ? ' is-pending' : ''}">${escapeHtml(previewText)}</div>
          </div>
          ${String(value || '').trim() ? `<button type="button" class="role-variable-editor-inline-btn role-variable-editor-readonly-copy" onclick="window.copyRightPanelFieldValue('${key}')">复制</button>` : ''}
        </div>`;
      } else if (meta.controlType === 'longtext') {
        const expanded = !!window.rightPanelExpandedFields[key];
        const summaryClasses = ['role-variable-editor-summary-card', statusInfo.tone === 'auto' ? 'is-auto' : '', missing ? 'is-missing' : '', pending ? 'is-pending' : ''].filter(Boolean).join(' ');
        controlHtml = `<div class="role-variable-editor-control is-stack">
          <div class="${summaryClasses}">
            <div class="role-variable-editor-summary-value${missing ? ' is-empty' : ''}${pending ? ' is-pending' : ''}">${escapeHtml(previewText)}</div>
            <div class="role-variable-editor-summary-actions">
              <button type="button" class="role-variable-editor-inline-btn" onclick="window.toggleRightPanelFieldExpand('${key}')">${expanded ? '收起编辑' : '展开编辑'}</button>
              ${String(value || '').trim() ? `<button type="button" class="role-variable-editor-inline-btn" onclick="window.copyRightPanelFieldValue('${key}')">复制</button>` : ''}
            </div>
          </div>
          <div class="role-variable-editor-textarea-wrap${expanded ? ' is-open' : ''}">
            <textarea class="role-variable-editor-textarea" data-editor-key="${escapeAttr(key)}" placeholder="${escapeAttr(meta.placeholder || '')}" oninput="window.handleRightPanelEditorInput('${key}', this.value, 'input')" onblur="window.handleRightPanelEditorInput('${key}', this.value, 'blur')">${escapeHtml(value)}</textarea>
          </div>
        </div>`;
      } else {
        controlHtml = `<input type="text" class="form-control role-variable-editor-input" data-editor-key="${escapeAttr(key)}" value="${escapeAttr(value)}" placeholder="${escapeAttr(meta.placeholder || '')}" oninput="window.handleRightPanelEditorInput('${key}', this.value, 'input')">`;
      }

      html += `<div class="role-variable-editor-row">
        <div class="role-variable-editor-row-head">
          <span class="${chipClasses}" style="--chip-color:${groupMeta.color};--chip-bg:${missing ? '#fff1f2' : `${groupMeta.color}12`};--chip-border:${missing ? '#fecaca' : `${groupMeta.color}38`};" title="${escapeAttr(chipTitle)}">
            <span class="role-variable-editor-chip-name">${escapeHtml(meta.zhLabel || VAR_ZH_MAP[key] || key)}</span>
            <code class="role-variable-editor-token">{{${escapeHtml(key)}}}</code>
          </span>
          <span class="role-variable-editor-status ${missing && !pending ? 'is-missing' : ''}">
            <span class="role-variable-editor-status-pill is-${escapeAttr(statusInfo.tone || 'manual')}">${escapeHtml(pending ? '同步中' : (statusInfo.label || '用户可编辑'))}</span>
          </span>
        </div>
        <div class="role-variable-editor-control">${controlHtml}</div>
      </div>`;
    });
    html += '</section>';
  });

  container.innerHTML = html;
  if (focusSnapshot) restoreRightPanelEditorFocus(container, focusSnapshot);
}

window.toggleRightPanelFieldExpand = function (key) {
  window.rightPanelExpandedFields = window.rightPanelExpandedFields || {};
  window.rightPanelExpandedFields[key] = !window.rightPanelExpandedFields[key];
  renderRightPanelVariableEditor({ preserveFocus: false });
};

window.copyRightPanelFieldValue = async function (key) {
  const value = getRightPanelEditorValue(key);
  if (!String(value || '').trim()) {
    showToast('当前字段暂无内容可复制', 'warning');
    return;
  }
  try {
    await navigator.clipboard.writeText(String(value));
    showToast('已复制变量内容', 'success');
  } catch (err) {
    showToast('复制失败: ' + err.message, 'error');
  }
};

window.handleRightPanelEditorInput = function (key, value, mode = 'input') {
  const meta = getRightPanelEditorMeta(key);
  if (!meta || meta.readonly) return;
  if (meta.sourceId) {
    const source = $(meta.sourceId);
    if (!source) return;
    source.value = value;
    source.dispatchEvent(new Event('input', { bubbles: true }));
    if (mode === 'change' || mode === 'blur' || source.tagName === 'SELECT') {
      source.dispatchEvent(new Event('change', { bubbles: true }));
    }
  } else {
    window.updateCustomVar(meta.customKey || key, value);
  }
  refreshSPPreview({ skipMainEditor: meta.controlType === 'longtext' && mode === 'input' });
};

window.openRightPanelEditorExpand = function (el, key, color) {
  const meta = getRightPanelEditorMeta(key);
  if (!el || meta.readonly || document.getElementById('_right-panel-expand-overlay')) return;
  const overlay = document.createElement('div');
  overlay.id = '_right-panel-expand-overlay';
  overlay.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;z-index:9998;background:rgba(0,0,0,0.15)';
  const box = document.createElement('div');
  box.style.cssText = `position:fixed;z-index:9999;left:50%;top:84px;transform:translateX(-50%);width:560px;max-width:92vw;background:#fff;border:2px solid ${color};border-radius:8px;box-shadow:0 8px 32px rgba(0,0,0,0.2);padding:10px;`;
  const label = document.createElement('div');
  label.style.cssText = `font-size:12px;font-weight:700;color:${color};margin-bottom:8px`;
  label.textContent = `${VAR_ZH_MAP[key] || key} · {{${key}}}`;
  const ta = document.createElement('textarea');
  ta.style.cssText = 'width:100%;min-height:120px;max-height:280px;font-size:12px;font-family:monospace;border:1px solid #d0d7de;border-radius:6px;padding:8px;resize:vertical;outline:none;';
  ta.value = el.value || '';
  ta.oninput = function () {
    el.value = ta.value;
    window.handleRightPanelEditorInput(key, ta.value, 'input');
  };
  const close = () => { overlay.remove(); box.remove(); };
  overlay.onclick = close;
  box.appendChild(label);
  box.appendChild(ta);
  document.body.appendChild(overlay);
  document.body.appendChild(box);
  ta.focus();
  ta.select();
};

function _getVarCategory(name) {
  const meta = getRightPanelEditorMeta(name);
  const group = getVariableGroupMeta(meta.group);
  return { label: group.title, color: group.color };
}

function getPromptVariableState(varName, values = buildPromptVariableMap()) {
  const meta = getRightPanelEditorMeta(varName);
  const resolvedKey = meta.customKey || varName;
  const overrides = window.customVarOverrides || {};
  const hasOverride = Object.prototype.hasOwnProperty.call(overrides, resolvedKey)
    || Object.prototype.hasOwnProperty.call(overrides, varName);
  const originalVal = String(values[resolvedKey] ?? values[varName] ?? '');
  const currentVal = hasOverride
    ? String(overrides[resolvedKey] ?? overrides[varName] ?? '')
    : originalVal;
  const hasBaseValue = Object.prototype.hasOwnProperty.call(window.runtimePromptBaseValues || {}, resolvedKey)
    || Object.prototype.hasOwnProperty.call(window.runtimePromptBaseValues || {}, varName);
  const autoGenerated = AUTO_GENERATED_PROMPT_VARS.has(varName) && !hasBaseValue && !hasOverride;
  const missing = !String(currentVal || '').trim();
  return {
    originalVal,
    currentVal,
    hasOverride,
    autoGenerated,
    missing,
    title: autoGenerated ? '系统自动生成' : '请先在角色 Tab 填写',
  };
}

function getPromptTextForPreviewContainer(containerId) {
  if (containerId === 'runtime-prompt-editor-vars-body') return getInputValue('fs-sp-editor') || getInputValue('f-system-prompt');
  if (containerId === 'freechat-prompt-vars-body') return getInputValue('freechat-prompt-editor');
  return getInputValue('f-system-prompt');
}

window.setVariablePreviewMode = function (containerId, mode) {
  _variablePreviewModes[containerId] = mode;
  renderVariablePreviewTags({ containerId, promptText: getPromptTextForPreviewContainer(containerId) });
};

function renderVariablePreviewTags({ containerId = 'sp-variable-preview', promptText = getInputValue('f-system-prompt') } = {}) {
  const container = $(containerId);
  if (!container) return;

  const spText = promptText || '';
  const variables = extractPromptVariables(spText).filter(v => v !== 'user_message');
  const mode = _variablePreviewModes[containerId] || 'related';
  const selectedVariables = mode === 'all' ? VARIABLE_SCHEMA_KEYS : variables;
  const values = buildPromptVariableMap();
  const toolbar = `<div class="variable-preview-toolbar">
      <div class="variable-preview-toolbar-meta">当前 Prompt 引用 <strong>${variables.length}</strong> 个变量，共维护 <strong>${VARIABLE_SCHEMA_KEYS.length}</strong> 个。</div>
      <div class="variable-preview-segmented" role="tablist" aria-label="变量过滤">
        <button type="button" class="variable-preview-segmented-btn ${mode === 'related' ? 'active' : ''}" onclick="window.setVariablePreviewMode('${containerId}', 'related')">相关变量</button>
        <button type="button" class="variable-preview-segmented-btn ${mode === 'all' ? 'active' : ''}" onclick="window.setVariablePreviewMode('${containerId}', 'all')">全部变量</button>
      </div>
    </div>`;

  if (!spText && mode === 'related') {
    container.innerHTML = `${toolbar}<div class="variable-preview-empty">当前 Prompt 为空，暂无可关联变量。切到"全部变量"可直接检查完整变量表。</div>`;
    return;
  }
  if (!selectedVariables.length) {
    container.innerHTML = `${toolbar}<div class="variable-preview-empty">当前 Prompt 中未检测到变量占位符。你可以切换到"全部变量"查看全部变量。</div>`;
    return;
  }

  // 按分类分组
  const grouped = {};
  selectedVariables.forEach(name => {
    const meta = getRightPanelEditorMeta(name);
    const cat = _getVarCategory(name);
    const state = getPromptVariableState(name, values);
    const value = getRightPanelEditorValue(name, values);
    const statusInfo = getRightPanelEditorStatus(name, meta, state, value);
    const pending = isAutoFieldPending(meta, value, name);
    if (!grouped[cat.label]) grouped[cat.label] = { color: cat.color, items: [] };
    grouped[cat.label].items.push({ name, cat, meta, state, value, statusInfo, pending });
  });

  let html = `${toolbar}<div class="variable-preview-list">`;
  for (const [catLabel, catData] of Object.entries(grouped)) {
    html += `<div class="variable-preview-group-title" style="color:${catData.color};border-bottom-color:${catData.color}22">${catLabel}</div>`;
    catData.items.forEach(item => {
      const { name, state, value, meta, statusInfo, pending } = item;
      const zhName = meta.zhLabel || VAR_ZH_MAP[name] || name;
      const previewText = getRightPanelEditorPreviewText(meta, value, state.missing, pending);
      const chipClasses = [
        'variable-preview-chip',
        state.missing ? 'is-missing' : '',
        statusInfo.tone === 'auto' || state.autoGenerated ? 'is-auto' : '',
        state.hasOverride && state.currentVal !== state.originalVal ? 'is-overridden' : '',
      ].filter(Boolean).join(' ');
      const chipStyle = state.missing
        ? '--chip-color:#b91c1c;--chip-bg:#fff1f2;--chip-border:#fecaca;'
        : `--chip-color:${catData.color};--chip-bg:${(state.hasOverride && state.currentVal !== state.originalVal) ? `${catData.color}1d` : `${catData.color}12`};--chip-border:${statusInfo.tone === 'auto' ? `${catData.color}66` : `${catData.color}38`};`;
      const chipTitle = state.missing
        ? `${zhName} ({{${name}}})\n当前状态：缺失，需先在角色 Tab 或系统模块中补齐`
        : `${zhName} ({{${name}}})\n当前值：${value}`;
      const inputStyle = state.missing
        ? 'border-color:#dc2626;background:#fff7f7;color:#991b1b;'
        : (state.hasOverride && state.currentVal !== state.originalVal)
          ? `border-color:${catData.color};background:${catData.color}10;`
          : (statusInfo.tone === 'auto' ? `border-color:${catData.color}66;background:${catData.color}0d;` : '');
      const valueAttr = escapeHtml(state.currentVal).replace(/"/g, '&quot;');
      const rowClass = state.missing ? 'variable-preview-row is-missing' : 'variable-preview-row';
      html += `<div class="${rowClass}">
            <div class="variable-preview-label-wrap">
              <span class="${chipClasses}" style="${chipStyle}" title="${escapeHtml(chipTitle).replace(/"/g, '&quot;')}">
                <span class="variable-preview-chip-name">${escapeHtml(zhName)}</span>
                <code class="variable-preview-chip-token">{{${escapeHtml(name)}}}</code>
              </span>
              <span class="variable-preview-chip-state">${escapeHtml(pending ? '同步中' : (statusInfo.label || '用户可编辑'))}</span>
            </div>
            <input type="text" class="form-control variable-preview-input" data-var="${name}"
                   style="${inputStyle}"
                   value="${valueAttr}"
                   title="${escapeHtml(previewText).replace(/"/g, '&quot;')}"
                   placeholder="${state.missing ? '请先在角色 Tab 填写' : '修改值...'}"
                   oninput="window.updateCustomVar('${meta.customKey || name}', this.value)"
                   ondblclick="window._expandVarInput(this, '${meta.customKey || name}', '${state.missing ? '#b91c1c' : catData.color}')">
          </div>`;
    });
  }
  html += '</div><div class="variable-preview-footer">保留彩色变量标签与可编辑输入行；默认优先显示当前 Prompt 实际引用的变量，双击输入框可放大编辑。</div>';
  container.innerHTML = html;
}

window._expandVarInput = function (el, varName, color) {
  if (document.getElementById('_var-expand-overlay')) return;
  const rect = el.getBoundingClientRect();
  const overlay = document.createElement('div');
  overlay.id = '_var-expand-overlay';
  overlay.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;z-index:9998;background:rgba(0,0,0,0.15)';
  const box = document.createElement('div');
  box.style.cssText = `position:fixed;z-index:9999;left:50%;top:${Math.max(rect.top - 20, 60)}px;transform:translateX(-50%);width:480px;max-width:90vw;background:#fff;border:2px solid ${color};border-radius:8px;box-shadow:0 8px 32px rgba(0,0,0,0.2);padding:8px;`;
  const label = document.createElement('div');
  label.style.cssText = `font-size:11px;font-weight:600;color:${color};margin-bottom:4px`;
  label.textContent = (VAR_ZH_MAP[varName] || varName) + ' : {{' + varName + '}}';
  const ta = document.createElement('textarea');
  ta.style.cssText = 'width:100%;min-height:80px;max-height:200px;font-size:12px;font-family:monospace;border:1px solid #ddd;border-radius:4px;padding:6px;resize:vertical;outline:none;';
  ta.value = el.value;
  ta.oninput = function () { el.value = ta.value; window.updateCustomVar(varName, ta.value); };
  const close = () => { overlay.remove(); box.remove(); };
  overlay.onclick = close;
  box.appendChild(label);
  box.appendChild(ta);
  document.body.appendChild(overlay);
  document.body.appendChild(box);
  ta.focus();
  ta.select();
};

window.updateCustomVar = function (key, val) {
  const baseValues = buildPromptVariableMap();
  window.customVarOverrides = window.customVarOverrides || {};
  if (String(val ?? '') === String(baseValues[key] ?? '')) {
    delete window.customVarOverrides[key];
  } else {
    window.customVarOverrides[key] = val;
  }
  if ($('role-variable-editor')) renderRightPanelVariableEditor({ preserveFocus: true });
  const preview = $('sp-preview-content');
  if (preview && _runtimePromptEditorContext?.kind === 'chat') preview.innerHTML = resolveSystemPromptPreview();
};

function resolveSystemPromptPreview(promptText = getInputValue('f-system-prompt')) {
  const values = buildPromptVariableMap();
  const pattern = /\{\{\s*([a-zA-Z0-9_\u4e00-\u9fa5]+)\s*\}\}/g;
  let html = '';
  let lastIndex = 0;

  for (const match of promptText.matchAll(pattern)) {
    const start = match.index ?? 0;
    const end = start + match[0].length;
    const key = match[1];
    const cat = _getVarCategory(key);
    const state = getPromptVariableState(key, values);
    const bg = cat.color + '18';
    const escapedValue = escapeHtml(state.currentVal);
    const renderedValue = state.missing
      ? `<span title="${state.title}" style="background:#fef2f2;color:#dc2626;padding:0 4px;border-radius:4px;font-weight:600;border:1px solid #fecaca;">未配置:${escapeHtml(VAR_ZH_MAP[key] || key)}</span>`
      : `<span title="${state.title}" style="background:${bg};color:${cat.color};padding:0 4px;border-radius:4px;font-weight:500;${state.autoGenerated ? 'border:1px dashed ' + cat.color + ';' : ''}">${escapedValue}${state.autoGenerated ? '<span style="margin-left:4px;font-size:10px;opacity:0.75">自动生成</span>' : ''}</span>`;
    html += escapeHtml(promptText.slice(lastIndex, start));
    html += renderedValue;
    lastIndex = end;
  }
  html += escapeHtml(promptText.slice(lastIndex));
  return html;
}

function refreshSPPreview({ notify = false, skipMainEditor = false } = {}) {
  if (!skipMainEditor) renderRightPanelVariableEditor({ preserveFocus: true });
  renderVariablePreviewTags();
  if ($('runtime-prompt-editor-vars-body') && _runtimePromptEditorContext?.kind === 'chat') {
    renderVariablePreviewTags({
      containerId: 'runtime-prompt-editor-vars-body',
      promptText: getInputValue('fs-sp-editor') || getInputValue('f-system-prompt'),
    });
  }
  if ($('freechat-prompt-vars-body') && $('modal-freechat-prompt')?.style.display === 'flex') {
    renderVariablePreviewTags({
      containerId: 'freechat-prompt-vars-body',
      promptText: getInputValue('freechat-prompt-editor'),
    });
  }
  const preview = $('sp-preview-content');
  if (preview && _runtimePromptEditorContext?.kind === 'chat') preview.innerHTML = resolveSystemPromptPreview();
  refreshHeaderModelSettingsButtonState();
  if (notify) showToast('变量预览已刷新', 'success');
}

function openSPPreview() {
  const preview = $('sp-preview-content');
  if (preview) preview.innerHTML = resolveSystemPromptPreview();
  showModal('modal-sp-preview');
  refreshSPPreview();
}


/* ═══ 初始化 & 事件绑定 ═══ */
document.addEventListener('DOMContentLoaded', () => {
  fetchPresets(); fetchModels(); loadHistory(); fetchPromptVersions(); initComparePage();
  window.setTimeout(() => {
    restoreActiveABSession({ silent: true }).catch(() => { });
  }, 800);
  switchPromptKind('chat');
  restorePersistedTestCenterNavigation();
  renderConversationControlRow();
  void initializeOrchestrationEnvironmentGuard();
  setLowScoreThreshold(state.lowScoreThreshold);

  $('fs-sp-editor')?.addEventListener('input', () => {
    if (_runtimePromptEditorContext?.kind === 'chat') {
      renderVariablePreviewTags({
        containerId: 'runtime-prompt-editor-vars-body',
        promptText: getInputValue('fs-sp-editor'),
      });
      const preview = $('sp-preview-content');
      if (preview) preview.innerHTML = resolveSystemPromptPreview(getInputValue('fs-sp-editor'));
    }
  });
  $('freechat-prompt-editor')?.addEventListener('input', () => {
    renderVariablePreviewTags({
      containerId: 'freechat-prompt-vars-body',
      promptText: getInputValue('freechat-prompt-editor'),
    });
  });

  // Sidebar toggle
  $('toggleSidebar').onclick = () => {
    const sb = $('sidebar');
    sb.classList.toggle('collapsed');
    const btn = $('toggleSidebar');
    btn.setAttribute('aria-expanded', !sb.classList.contains('collapsed'));
    renderSidebarHistory(state.historyItems || []);
  };

  // Panel toggle
  $('togglePanelBtn').onclick = () => {
    if (state.rightPanelOpen) {
      closeRightPanel();
    } else {
      openRightPanel();
    }
  };
  $('closePanelBtn').onclick = closeRightPanel;
  syncPageChrome(getCurrentPageName());

  // Start test / 开始对话
  $('btn-start').onclick = saveConfigAndStartChat;

  // Chat nav buttons
  $('btn-view-msgs').onclick = () => {
    if (state.debugData.length) {
      switchDebugPanel('messages');
      showModal('modal-debug');
      renderDebugView(0);
    } else {
      showToast('暂无调试数据', 'warning');
    }
  };
  if ($('debug-tab-messages')) $('debug-tab-messages').onclick = () => switchDebugPanel('messages');
  if ($('debug-tab-request')) $('debug-tab-request').onclick = () => switchDebugPanel('request');
  if ($('btn-copy-debug-json')) $('btn-copy-debug-json').onclick = copyCurrentDebugJson;
  $('btn-export-excel').onclick = () => exportConversation({ mode: 'conversation' });
  $('btn-score-conv').onclick = () => triggerScoring();
  $('btn-rescore').onclick = () => triggerScoring({ forceFullRescore: true });
  if ($('btn-retry-failed')) $('btn-retry-failed').onclick = retryFailedScoring;
  $('btn-export-scored').onclick = () => exportConversation({ mode: 'scoring', summary: false });
  if ($('btn-export-summary-scored')) $('btn-export-summary-scored').onclick = () => exportConversation({ mode: 'scoring', summary: true });
  if ($('btn-ai-summary')) $('btn-ai-summary').onclick = triggerAiSummary;
  if ($('ai-summary-download-btn')) $('ai-summary-download-btn').onclick = () => {
    if (!_aiSummaryModalState?.markdown) return;
    const blob = new Blob([_aiSummaryModalState.markdown], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = _aiSummaryModalState.filename || 'ai_summary.md';
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    showToast('摘要已下载', 'success');
  };


  // Model selector update
  $('f-model-pro').onchange = () => {
    setPrimaryModelId($('f-model-pro').value);
  };
  $('f-scoring-model')?.addEventListener('change', () => {
    if ($('tc-scoring-model')) $('tc-scoring-model').value = getInputValue('f-scoring-model').trim();
    syncScoringThinkingControls({
      modelId: getInputValue('f-scoring-model').trim() || getPrimaryModelId(),
      force: false,
    });
    refreshTestCenterShell();
    refreshScoringDefaultsStatus();
  });
  $('tc-scoring-model')?.addEventListener('change', () => {
    const nextModelId = normalizeModelId(getInputValue('tc-scoring-model').trim(), DEFAULT_SCORING_MODEL_ID);
    if ($('f-scoring-model')) $('f-scoring-model').value = nextModelId;
    syncScoringThinkingControls({
      modelId: nextModelId || getPrimaryModelId(),
      force: true,
    });
    refreshTestCenterShell();
    refreshScoringDefaultsStatus();
  });
  $('tc-scoring-thinking-effort')?.addEventListener('change', () => {
    const nextValue = normalizeThinkingEffortOption(getInputValue('tc-scoring-thinking-effort').trim(), _scoringThinkingEffortDraft);
    const enabled = nextValue !== 'disabled';
    if ($('f-scoring-thinking-enabled')) {
      $('f-scoring-thinking-enabled').dataset.userTouched = '1';
      $('f-scoring-thinking-enabled').checked = enabled;
    }
    if (enabled && $('f-scoring-thinking-effort')) {
      $('f-scoring-thinking-effort').dataset.userTouched = '1';
      $('f-scoring-thinking-effort').value = nextValue;
    }
    syncScoringThinkingControls({
      enabled,
      effort: enabled ? nextValue : _scoringThinkingEffortDraft,
      modelId: getInputValue('f-scoring-model').trim() || getPrimaryModelId(),
      force: true,
    });
    refreshTestCenterShell();
    refreshScoringDefaultsStatus();
  });
  $('tc-scoring-concurrency')?.addEventListener('input', (event) => {
    const value = normalizeScoringConcurrency(event?.target?.value);
    if ($('tc-scoring-concurrency-display')) $('tc-scoring-concurrency-display').textContent = String(value);
    refreshTestCenterShell();
    refreshScoringDefaultsStatus();
  });
  $('tc-scoring-concurrency')?.addEventListener('change', async (event) => {
    const value = normalizeScoringConcurrency(event?.target?.value);
    if ($('tc-scoring-concurrency')) $('tc-scoring-concurrency').value = String(value);
    if ($('tc-scoring-concurrency-display')) $('tc-scoring-concurrency-display').textContent = String(value);
    try {
      await syncScoringConfigToServer({ max_workers: value });
    } catch (err) {
      showToast('同步打分并发失败: ' + err.message, 'error');
    }
    refreshTestCenterShell();
    refreshScoringDefaultsStatus();
  });
  $('tc-scoring-retry')?.addEventListener('change', () => {
    if ($('tc-scoring-retry')) $('tc-scoring-retry').value = String(normalizeScoringRetryCount(getInputValue('tc-scoring-retry')));
    refreshTestCenterShell();
    refreshScoringDefaultsStatus();
  });

  // Relationship linkage
  $('f-relationship').onchange = async () => {
    updateRelLinkage();
    await syncLongformModules(false);
  };
  if ($('f-gender')) $('f-gender').onchange = () => {
    syncLongformModules(false);
  };
  if ($('f-personality')) $('f-personality').onchange = () => {
    syncLongformModules(false);
  };
  if ($('f-injection-depth')) $('f-injection-depth').addEventListener('change', () => {
    $('f-injection-depth').value = String(normalizeInjectionDepthValue($('f-injection-depth').value));
  });
  syncGenerationControlsFromConfig();
  updateRelLinkage();
  syncDialogueThinkingControls({ modelId: getPrimaryModelId(), force: true });
  syncScoringThinkingControls({
    modelId: getInputValue('f-scoring-model').trim() || getPrimaryModelId(),
    force: true,
  });

  const previewInputs = [
    'f-system-prompt', 'f-nickname', 'f-gender', 'f-age', 'f-occupation',
    'f-personality', 'f-speaking-style', 'f-background', 'f-hobby',
    'f-relationship', 'f-scene', 'f-timeperiod', 'f-season',
    'f-user-nickname', 'f-user-gender', 'f-user-identity',
    'f-sys-persona', 'f-sys-style', 'f-sys-fewshot', 'f-sys-module8',
    'f-sys-startprompt', 'f-sys-summary', 'f-sys-schedule',
    'f-sys-role-acting', 'f-sys-role-acting-module', 'f-voice-forbidden'
  ];
  previewInputs.forEach(id => {
    const el = $(id);
    // Bind input event to input and select elements
    if (el) el.addEventListener('input', refreshSPPreview);
    if (el && el.tagName === 'SELECT') el.addEventListener('change', refreshSPPreview);
    // For textareas updated by JS explicitly we need explicit dispatch or we just rely on calling refreshSPPreview in logic
  });
  if ($('f-prompt-version')) {
    $('f-prompt-version').addEventListener('change', () => {
      syncSelectedChatPrompt({ force: true, refreshPreview: true }).catch(err => {
        console.warn('切换主提示词失败', err);
        showToast('切换主提示词失败: ' + err.message, 'error');
      });
    });
  }
  if ($('batch-model')) $('batch-model').addEventListener('change', refreshTestCenterShell);
  if ($('ab-lock-model')) $('ab-lock-model').addEventListener('change', () => syncABModelLock());
  if ($('ab-base-model')) $('ab-base-model').addEventListener('change', () => syncABModelLock());
  if ($('ab-compare-model')) $('ab-compare-model').addEventListener('change', refreshTestCenterShell);
  if ($('ab-base-prompt')) $('ab-base-prompt').addEventListener('change', refreshTestCenterShell);
  if ($('ab-compare-prompt')) $('ab-compare-prompt').addEventListener('change', refreshTestCenterShell);
  if ($('fs-sp-editor')) {
    $('fs-sp-editor').addEventListener('input', () => {
      if (_runtimePromptEditorContext?.kind !== 'chat') return;
      renderVariablePreviewTags({
        containerId: 'runtime-prompt-editor-vars-body',
        promptText: getInputValue('fs-sp-editor'),
      });
    });
  }
  refreshSPPreview();

  ['history-filter-role', 'history-filter-model', 'history-filter-prompt', 'history-filter-score-min', 'history-filter-score-max'].forEach(id => {
    const el = $(id);
    if (el) el.addEventListener('input', applyHistoryFilters);
  });
  ['history-filter-status', 'history-filter-date-from', 'history-filter-date-to', 'history-filter-include-archived'].forEach(id => {
    const el = $(id);
    if (el) el.addEventListener('change', applyHistoryFilters);
  });
  $('history-events-export-btn')?.addEventListener('click', exportConversationEvents);
  $('history-events-scope')?.addEventListener('change', () => {
    refreshConversationEvents().catch(err => showToast('刷新日志失败: ' + err.message, 'error'));
  });
  $('history-events-level')?.addEventListener('change', () => {
    refreshConversationEvents().catch(err => showToast('刷新日志失败: ' + err.message, 'error'));
  });
  $('score-low-threshold')?.addEventListener('input', (event) => {
    const nextValue = setLowScoreThreshold(event?.target?.value);
    if ($('score-low-threshold')) $('score-low-threshold').value = String(nextValue);
    if (Array.isArray(state.scoreData) && state.scoreData.length) {
      renderScoreCards();
      renderScoreTrend();
    }
    renderHistory(filterHistoryItems(state.historyItems || []));
  });
  $('btn-next-low-score')?.addEventListener('click', () => {
    const lowScoreCards = [...document.querySelectorAll('#score-cards .score-turn-card.low-score-turn')];
    if (!lowScoreCards.length) {
      showToast('当前没有低于阈值的轮次', 'info');
      return;
    }
    _lowScoreNavCursor = (_lowScoreNavCursor + 1) % lowScoreCards.length;
    document.querySelectorAll('#score-cards .score-turn-card.low-score-active').forEach(node => node.classList.remove('low-score-active'));
    const targetCard = lowScoreCards[_lowScoreNavCursor];
    targetCard.classList.add('low-score-active');
    targetCard.classList.add('expanded');
    targetCard.scrollIntoView({ behavior: 'smooth', block: 'center' });
  });
  $('btn-score-events')?.addEventListener('click', async () => {
    if (!state.convId) {
      showToast('当前没有可查看日志的会话', 'warning');
      return;
    }
    closeModal('modal-scoring');
    await showConversationEvents(state.convId, { scope: 'scoring' });
  });
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) stopTitleFlash();
  });
  window.addEventListener('focus', stopTitleFlash);
  document.addEventListener('click', (event) => {
    if (!event.target.closest('.shared-model-picker')) {
      closeAllModelPickers();
    }
    if (!event.target.closest('.score-popover') && !event.target.closest('.score-popover-trigger')) {
      closeAllScorePopovers();
    }
    if (!event.target.closest('#btn-save-template-menu')) {
      const dropdown = $('template-save-dropdown');
      if (dropdown) dropdown.style.display = 'none';
    }
  });
  ['modal-freechat-prompt', 'modal-scoring', 'modal-debug', 'modal-human-score', 'modal-sp-edit', 'modal-sp-preview', 'modal-module-edit', 'modal-preset-delete', 'modal-action-confirm']
    .forEach(id => {
      const modal = $(id);
      if (!modal) return;
      modal.addEventListener('mousedown', (event) => {
        if (event.target === modal) closeModal(modal);
      });
    });
  // P2-10: Dark Mode 初始化
  if (localStorage.getItem('theme') === 'dark'
    || (!localStorage.getItem('theme')
      && matchMedia('(prefers-color-scheme:dark)').matches)) {
    document.documentElement.dataset.theme = 'dark';
  }
});

/* ═══ P0-2: 模态框焦点陷阱 (WCAG 2.4.3) ═══ */
function trapFocus(modalEl) {
  const focusable = modalEl.querySelectorAll(
    'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
  if (!focusable.length) return;
  const first = focusable[0], last = focusable[focusable.length - 1];
  first.focus();
  modalEl._trapHandler = (e) => {
    if (e.key === 'Escape') {
      closeModal(modalEl);
      return;
    }
    if (e.key !== 'Tab') return;
    if (e.shiftKey) {
      if (document.activeElement === first) { e.preventDefault(); last.focus(); }
    } else {
      if (document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
  };
  modalEl.addEventListener('keydown', modalEl._trapHandler);
}
function releaseFocus(modalEl) {
  if (modalEl._trapHandler) {
    modalEl.removeEventListener('keydown', modalEl._trapHandler);
    delete modalEl._trapHandler;
  }
}

/* P2-10: Dark Mode 切换 */
function toggleDarkMode() {
  const html = document.documentElement;
  const isDark = html.dataset.theme === 'dark';
  html.dataset.theme = isDark ? '' : 'dark';
  localStorage.setItem('theme', isDark ? 'light' : 'dark');
  showToast(isDark ? '已切换到浅色模式' : '已切换到深色模式', 'info');
}
