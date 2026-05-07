from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent
JS_PATH = PROJECT_DIR / "server" / "static" / "js" / "legacy_bundle.js"
CSS_PATH = PROJECT_DIR / "server" / "static" / "css" / "main.css"
HTML_PATH = PROJECT_DIR / "server" / "static" / "index.html"


def _slice(source: str, start_marker: str, end_marker: str) -> str:
    start = source.index(start_marker)
    end = source.index(end_marker, start)
    return source[start:end]


def test_history_table_removes_source_column_and_uses_single_line_actions():
    html = HTML_PATH.read_text(encoding="utf-8")
    js = JS_PATH.read_text(encoding="utf-8")
    css = CSS_PATH.read_text(encoding="utf-8")
    history_body = _slice(js, "function renderHistory(convs)", "function applyHistoryFilters()")

    assert "<th>来源</th>" not in html
    assert 'colspan="9"' in history_body
    assert "sourceLabel" not in history_body
    assert "history-actions-cell" in history_body
    assert "history-row-actions" in history_body
    assert ".history-actions-cell" in css
    assert ".history-row-actions" in css
    assert "flex-wrap: nowrap" in css or "flex-wrap:nowrap" in css
    assert "white-space: nowrap" in css or "white-space:nowrap" in css
    assert "const scoringAction = getHistoryScoringActionMeta(c, stats, reportMeta);" in history_body
    assert 'title="${retryScoringTitle}"' in history_body


def test_history_table_treats_zero_score_as_valid_average():
    js = JS_PATH.read_text(encoding="utf-8")
    history_body = _slice(js, "function renderHistory(convs)", "function applyHistoryFilters()")

    assert "const scoreAvg = Number.parseFloat(c.score_avg);" in history_body
    assert "if (Number.isFinite(scoreAvg))" in history_body
    assert "scoreLabel = scoreAvg.toFixed(1);" in history_body


def test_history_records_table_uses_fixed_columns_and_dropdown_menu_styles():
    html = HTML_PATH.read_text(encoding="utf-8")
    js = JS_PATH.read_text(encoding="utf-8")
    css = CSS_PATH.read_text(encoding="utf-8")
    history_body = _slice(js, "function renderHistory(convs)", "function applyHistoryFilters()")

    assert 'class="history-table history-records-table"' in html
    assert 'class="history-col-role"' in html
    assert 'class="history-col-actions"' in html
    assert 'class="history-select-cell"' in history_body
    assert 'class="history-role-cell"' in history_body
    assert 'class="history-row-menu"' in history_body
    assert 'history-row-menu-trigger' in history_body
    assert ".history-records-table" in css
    assert "table-layout: fixed" in css
    assert ".history-records-table .history-row-menu-panel" in css
    assert "position: absolute" in css
    assert ".history-records-table .history-row-menu > summary.history-row-menu-trigger" in css


def test_export_conversation_prefers_response_filename_and_validates_excel_type():
    source = JS_PATH.read_text(encoding="utf-8")
    export_body = _slice(source, "async function exportConversation(id)", "/* ═══ 打分 ═══ */")

    assert "function resolveDownloadFilenameFromHeaders" in source
    assert "Content-Disposition" in source
    assert "function assertExcelDownloadResponse" in source
    assert "await assertExcelDownloadResponse(r, '导出失败')" in export_body
    assert "resolveDownloadFilenameFromHeaders(r.headers, fallbackFilename)" in export_body


def test_trigger_scoring_handles_score_progress_and_final_sync_fallback():
    source = JS_PATH.read_text(encoding="utf-8")
    scoring_body = _slice(source, "async function triggerScoring({ forceFullRescore = false } = {})", "function computeAvgScore()")

    assert "msg.type === 'score_progress'" in scoring_body
    assert "const ensured = prefetched || await fetchConversationScoreResults(convId);" in scoring_body
    assert "await syncScoreResults();" in scoring_body
    assert "startFallbackSync();" in scoring_body
    assert "watchConversationScoreRefresh(convId, { allowDelayed: true })" in scoring_body


def test_scoring_summary_uses_authoritative_summary_instead_of_fake_zero():
    source = JS_PATH.read_text(encoding="utf-8")
    summary_body = _slice(source, "function refreshScoreSummary()", "async function saveInlineManualScore")
    sync_body = _slice(source, "function buildConversationReportMeta(data = {})", "async function saveInlineManualScore")
    compute_body = _slice(source, "function computeAvgScore()", "function isRetryableScoringTurn")

    assert "avgScore === null ? '--' : avgScore.toFixed(1)" in summary_body
    assert "state.scoreSummary = data.summary || null;" in sync_body
    assert "Number(summary.scored_count || 0) > 0 && Number.isFinite(summaryAvg)" in compute_body
    assert "return null;" in compute_body


def test_scoring_summary_builder_has_required_sections_without_raw_boundary_dump():
    source = JS_PATH.read_text(encoding="utf-8")
    summary_body = _slice(source, "function buildScoringSummaryMarkdown(conv)", "function isPerTurnExcelTemplate")

    assert "## 总览仪表盘" in summary_body
    assert "## 维度分析" in summary_body
    assert "## 关键结论" in summary_body
    assert "## 逐轮概览" in summary_body
    assert "最强维度" in summary_body
    assert "最弱维度" in summary_body
    assert "失败轮次概况" in summary_body
    assert "intimacy_boundary" not in summary_body
    assert "relation_calling" not in summary_body


def test_ai_summary_modal_and_shared_markdown_flow():
    html = HTML_PATH.read_text(encoding="utf-8")
    source = JS_PATH.read_text(encoding="utf-8")
    trigger_body = _slice(source, "async function triggerAiSummary()", "function computeAvgScore()")
    scoring_summary_body = _slice(source, "async function showScoringSummary(convId)", "async function showCompareAiSummary(reportId)")

    assert 'id="ai-summary-markdown"' in html
    assert 'id="ai-summary-meta"' in html
    assert 'id="ai-summary-download-btn"' in html
    assert "ai-summary-overall-text" not in html
    assert "ai-summary-strengths" not in html
    assert "function renderAiSummaryMarkdown" in source
    assert "function buildLocalSummaryFallback" in source
    assert "async function fetchConversationAiSummary" in source
    assert "await showScoringSummary(state.convId);" in trigger_body
    assert "fetchConversationAiSummary(convId)" in scoring_summary_body
    assert "buildLocalSummaryFallback(localSummary)" in scoring_summary_body


def test_history_compare_panel_has_ai_compare_summary_entry():
    html = HTML_PATH.read_text(encoding="utf-8")
    source = JS_PATH.read_text(encoding="utf-8")

    assert 'id="history-report-ai-summary-btn"' in html
    assert "showCompareAiSummary(state.compareReportId)" in html
    assert "async function showCompareAiSummary(reportId)" in source
    assert "async function fetchCompareAiSummary(reportId" in source
    assert "/api/reports/compare/${encodeURIComponent(reportId)}/ai-summary" in source


def test_history_filters_include_status_score_and_archived_controls():
    html = HTML_PATH.read_text(encoding="utf-8")
    source = JS_PATH.read_text(encoding="utf-8")
    history_state_body = _slice(source, "function getHistoryFilterState()", "function filterHistoryItems(items)")

    assert 'id="history-filter-status"' in html
    assert 'id="history-filter-score-min"' in html
    assert 'id="history-filter-score-max"' in html
    assert 'id="history-filter-include-archived"' in html
    assert "status: getInputValue('history-filter-status')" in history_state_body
    assert "scoreMin: getInputValue('history-filter-score-min')" in history_state_body
    assert "scoreMax: getInputValue('history-filter-score-max')" in history_state_body
    assert "includeArchived: !!$('history-filter-include-archived')?.checked" in history_state_body


def test_history_filters_apply_locally_without_reloading_every_keystroke():
    source = JS_PATH.read_text(encoding="utf-8")
    apply_body = _slice(source, "function applyHistoryFilters()", "function resetHistoryFilters()")
    load_body = _slice(source, "async function loadHistory()", "async function viewConversation(id)")

    assert "renderHistoryWithCurrentFilters();" in apply_body
    assert "await loadHistory();" not in apply_body
    assert "renderHistoryWithCurrentFilters();" in load_body


def test_history_bulk_toolbar_exposes_rescore_button_and_confirm_modal():
    html = HTML_PATH.read_text(encoding="utf-8")
    source = JS_PATH.read_text(encoding="utf-8")
    actions_body = _slice(source, "function updateHistoryCompareActions()", "function toggleHistoryCompareSelection(convId, checked)")

    assert 'id="history-rescore-selected-btn"' in html
    assert 'id="modal-action-confirm"' in html
    assert 'id="btn-action-confirm"' in html
    assert "function openActionConfirmDialog" in source
    assert "function resolveActionConfirmDialog" in source
    assert "批量重打分选中记录" in actions_body
    assert "history-rescore-selected-btn" in actions_body


def test_history_actions_include_archive_and_event_log():
    html = HTML_PATH.read_text(encoding="utf-8")
    source = JS_PATH.read_text(encoding="utf-8")
    sidebar_body = _slice(source, "function renderSidebarHistory(convs)", "function syncHistoryCompareSelection()")
    history_body = _slice(source, "function renderHistory(convs)", "function applyHistoryFilters()")

    assert 'id="history-events-panel"' in html
    assert 'id="history-events-content"' in html
    assert 'id="history-events-export-btn"' in html
    assert 'data-action="archive"' in sidebar_body
    assert 'data-action="events"' in sidebar_body
    assert "toggleConversationArchive(convId, !c.archived)" in sidebar_body
    assert "showConversationEvents(convId)" in sidebar_body
    assert "归档" in history_body
    assert "日志" in history_body


def test_scoring_modal_has_low_score_threshold_and_log_actions():
    html = HTML_PATH.read_text(encoding="utf-8")
    source = JS_PATH.read_text(encoding="utf-8")
    score_card_body = _slice(source, "function renderScoreCard(score, idx)", "/* ═══ 雷达图 ═══ */")

    assert 'id="score-low-threshold"' in html
    assert 'id="score-low-threshold-display"' in html
    assert 'id="btn-next-low-score"' in html
    assert 'id="btn-score-events"' in html
    assert "low-score-turn" in score_card_body
    assert "getLowScoreThreshold()" in score_card_body


def test_completion_notification_and_template_menu_exist():
    html = HTML_PATH.read_text(encoding="utf-8")
    source = JS_PATH.read_text(encoding="utf-8")

    assert 'id="btn-save-template-menu"' in html
    assert 'data-template-type="preset"' in html
    assert 'data-template-type="runtime"' in html
    assert 'data-template-type="full"' in html
    assert "async function notifyTaskCompletion(" in source
    assert "Notification.requestPermission()" in source
    assert "document.title" in source
    assert "saveCurrentTemplate(" in source


def test_compare_matrix_streams_live_status_and_reconciles_idle_tasks():
    source = JS_PATH.read_text(encoding="utf-8")
    compare_body = _slice(source, "async function _runCompareCellsForConfig(", "async function startModelCompare()")
    cell_body = _slice(source, "function renderCompareCell(cell)", "function renderCompareCards(results)")
    cards_body = _slice(source, "function renderCompareCards(results)", "/* ═══ Prompt A/B 对比测试（后端会话化） ═══ */")
    matrix_body = _slice(source, "function renderCompareMatrix(matrix, models)", "function getCompareStatusLabel(status)")

    assert "onCellUpdate" in compare_body
    assert "publishCell(" in compare_body
    assert "reconcile('idle-timeout')" in compare_body
    assert "reconcile('ws-closed')" in compare_body
    assert "fetch(`/api/conversations/${encodeURIComponent(convId)}`)" in compare_body
    assert "status: 'queued'" in compare_body
    assert "status: 'running'" in compare_body
    assert "enrichCompletedCellScore" in compare_body
    assert "getCompareCellStageLabel(cell)" in cell_body
    assert "function getCompareCellStage(cell)" in source
    assert "已打分" in cell_body
    assert "formatRelativeTime(cell.updatedAt)" in cell_body
    assert "function getCompareStatusBadgeClass(status)" in source
    assert "status-queued" in source
    assert "queued" in cell_body
    assert "getCompareStatusLabel(r.status)" in cards_body
    assert "compare-matrix-scroll" in matrix_body
    assert "previousScrollLeft" in matrix_body


def test_inline_ai_score_persists_for_any_loaded_conversation():
    source = JS_PATH.read_text(encoding="utf-8")
    inline_body = _slice(source, "async function runInlineAiScore(", "async function sendChatMessage()")

    assert "async function persistInlineAiScoreResult" in source
    assert "if (state.convId) {" in inline_body
    assert "state.chatSessionMode === 'interactive' && state.convId" not in inline_body


def test_history_and_batch_views_backfill_unscored_inline_scores():
    source = JS_PATH.read_text(encoding="utf-8")

    assert "async function runConversationInlineScoreBackfill()" in source
    assert "filter(shouldAutoBackfillInlineScore)" in source
    assert "await triggerInlineAiScoreForTurn(turnNumber, { refreshHistory: false });" in source
    assert source.count("void runConversationInlineScoreBackfill();") >= 2


def test_history_rescore_routes_to_summary_retry_or_sync_instead_of_forced_full_rescore():
    source = JS_PATH.read_text(encoding="utf-8")
    rescore_body = _slice(source, "async function retryFailedScoringForConv(", "/* ═══ AI 摘要报告 ═══ */")
    history_body = _slice(source, "function renderHistory(convs)", "function applyHistoryFilters()")

    assert "const actionMeta = getConversationScoringActionMeta(data);" in rescore_body
    assert "runConversationScoringAction(convId, actionMeta.action" in rescore_body
    assert "watchConversationScoreRefresh(convId, { allowDelayed: true })" in rescore_body
    assert "/api/scoring/${convId}/repair-summary" in source
    assert "/api/scoring/${convId}/retry-failed-turns" in source
    assert "/api/scoring/${convId}/resume-sync" in source
    assert "if (typeof loadHistory === 'function') await loadHistory();" in rescore_body
    assert "function getHistoryScoringActionMeta(item = {}, stats = getHistoryScoringStats(item), reportMeta = getHistoryAiReportMeta(item))" in source
    assert "escapeHtml(scoringAction.label)" in history_body
    assert "const scoringAction = getHistoryScoringActionMeta(c, stats, reportMeta);" in history_body


def test_rescore_requests_force_latest_scoring_prompt_and_refresh_summary():
    source = JS_PATH.read_text(encoding="utf-8")
    scoring_body = _slice(source, "async function triggerScoring({ forceFullRescore = false } = {})", "/* ═══ 仅重试失败轮次 ═══ */")
    retry_body = _slice(source, "async function retryFailedScoringForConv(", "/* ═══ AI 摘要报告 ═══ */")
    ensure_body = _slice(source, "async function ensureConversationScored(convId, { skipTrigger = false, preferLatestPrompt = true } = {})", "function renderCompareReportView(report)")

    assert "function resolveScoringPromptRequestVersion" in source
    assert "preferLatestPrompt = true" in source
    assert "forceFullRescore = false" in scoring_body
    assert "function getConversationScoringActionMeta(scoreData = {}, { forceFullRescore = false } = {})" in source
    assert "function runConversationScoringAction(convId, action, { preferLatestPrompt = true } = {})" in source
    assert "runConversationScoringAction(convId, actionMeta.action, { preferLatestPrompt: true })" in scoring_body
    assert "`/api/scoring/${convId}/rescore-all`" in source
    assert "`/api/scoring/${convId}/retry-failed-turns`" in source
    assert "`/api/scoring/${convId}/repair-summary`" in source
    assert "`/api/scoring/${convId}/resume-sync`" in source
    assert "payload.status === 'already_scored'" in scoring_body
    assert "applyConversationScoreResults(existingResult);" in scoring_body
    assert "await syncScoreResults();" in scoring_body
    assert "`/api/scoring/${convId}`" in ensure_body
    assert "triggerData.status === 'already_scored'" in ensure_body
    assert "buildScoringRuntimeRequest({ preferLatestPrompt: true })" in source
    assert "watchConversationScoreRefresh(convId, { allowDelayed: true })" in retry_body
    assert "$('btn-rescore').onclick = () => triggerScoring({ forceFullRescore: true });" in source


def test_history_bulk_actions_use_confirm_modal_and_regenerate_summaries():
    source = JS_PATH.read_text(encoding="utf-8")
    delete_body = _slice(source, "async function deleteSelectedHistoryConversations()", "function closeHistoryCompareReport()")
    batch_rescore_body = _slice(source, "async function batchRescoreSelectedHistoryConversations()", "function closeHistoryCompareReport()")
    compare_body = _slice(source, "async function startHistoryCompareFromSelection()", "function renderHistory(convs)")

    assert "openActionConfirmDialog" in delete_body
    assert "确认批量删除" in delete_body
    assert "openActionConfirmDialog" in batch_rescore_body
    assert "确认批量重打分" in batch_rescore_body
    assert "/rescore-all" in batch_rescore_body
    assert "buildScoringRuntimeRequest({ preferLatestPrompt: true })" in batch_rescore_body
    assert "watchConversationScoreRefresh(convId)" in batch_rescore_body
    assert "regenerateConversationAiSummarySilently(convId)" in batch_rescore_body
    assert "openActionConfirmDialog" in compare_body
    assert "确认生成历史对比分析" in compare_body


def test_history_summary_toolbar_supports_export_progress_and_ai_summary_generation():
    html = HTML_PATH.read_text(encoding="utf-8")
    source = JS_PATH.read_text(encoding="utf-8")
    summary_body = _slice(source, "async function startHistorySelectionSummaryFromSelection()", "async function startHistoryCompareFromSelection()")
    create_report_body = _slice(source, "async function createHistorySelectionReportFromConversationIds(ids)", "async function createCompareReportFromConversationIds(ids, labelsById = {})")
    retry_body = _slice(source, "async function retryConversationAiReport(convId, btnEl)", "async function fetchCompareAiSummary(reportId")
    scoring_summary_body = _slice(source, "async function showScoringSummary(convId)", "async function showCompareAiSummary(reportId)")
    compare_summary_body = _slice(source, "async function showCompareAiSummary(reportId)", "async function triggerAiSummary()")
    role_body = _slice(source, "function getHistoryRoleLabel(item = {})", "function getHistoryModelLabel(item = {})")
    history_body = _slice(source, "function renderHistory(convs)", "function applyHistoryFilters()")

    assert 'id="history-report-title"' in html
    assert 'id="history-summary-task-progress"' in html
    assert "function exportSelectedHistoryConversations()" in source
    assert "function dismissHistorySummaryTaskProgress()" in source
    assert "function setHistorySummaryTaskProgress(" in source
    assert "function completeHistorySummaryTaskProgress(" in source
    assert "function failHistorySummaryTaskProgress(" in source
    assert "/api/reports/history-selection" in create_report_body
    assert "fetchCompareAiSummary(report.id)" in summary_body
    assert "notifyTaskCompletion" in summary_body
    assert "setHistorySummaryTaskProgress" in retry_body
    assert "setHistorySummaryTaskProgress" in scoring_summary_body
    assert "setHistorySummaryTaskProgress" in compare_summary_body
    assert "未命名角色" in role_body
    assert 'history-row-menu-trigger' in history_body


def test_orchestration_recovery_bootstraps_batch_and_compare_runs():
    source = JS_PATH.read_text(encoding="utf-8")
    init_body = _slice(source, "document.addEventListener('DOMContentLoaded', () => {", "$('fs-sp-editor')?.addEventListener('input'")

    assert "const TEST_CENTER_NAV_STORAGE_KEY = 'longformTestCenterNavState';" in source
    assert "function restorePersistedTestCenterNavigation()" in source
    assert "function focusRecoveredTestCenter(mode, { abMode = null } = {})" in source
    assert "async function recoverBatchOrchestrationRun()" in source
    assert "async function recoverCompareOrchestrationRun()" in source
    assert "async function recoverABBatchOrchestrationRun()" in source
    assert "async function recoverActiveOrchestrationRuns()" in source
    assert "async function initializeOrchestrationEnvironmentGuard()" in source
    assert "async function fetchLatestOrchestrationRun(kind)" in source
    assert "fetchActiveOrchestrationRun('batch')" in source
    assert "fetchLatestOrchestrationRun('batch')" in source
    assert "fetchActiveOrchestrationRun('compare')" in source
    assert "fetchLatestOrchestrationRun('compare')" in source
    assert "fetchActiveOrchestrationRun('ab')" in source
    assert "fetchLatestOrchestrationRun('ab')" in source
    assert "pollBatchRun(run.id)" in source
    assert "pollCompareRun(run.id)" in source
    assert "pollABBatchRun(run.id)" in source
    assert "switchPage('test-center');" in source
    assert "const preferredMode = recoveredModes.includes(persisted.testMode)" in source
    assert "focusRecoveredTestCenter(preferredMode" in source
    assert "switchABMode('batch'" in source
    assert "void initializeOrchestrationEnvironmentGuard();" in init_body
    assert "restorePersistedTestCenterNavigation();" in init_body


def test_orchestration_stop_uses_cancelling_state_until_backend_finalizes():
    source = JS_PATH.read_text(encoding="utf-8")
    status_body = _slice(source, "function getConversationStatusLabel(status)", "function buildHistoryQueryParams()")
    batch_control_body = _slice(source, "function renderBatchControlRow()", "async function waitForBatchResumeOrStop()")
    compare_control_body = _slice(source, "function renderCompareControlRow()", "function hydrateCompareConfigsFromRun(run)")
    ab_control_body = _slice(source, "function renderABBatchControlRow()", "function hydrateABBatchConfigsFromRun(run)")

    assert "cancelling: '停止中'" in status_body
    assert "const isCancelling = normalizedStatus === 'cancelling';" in batch_control_body
    assert "stopBtn.textContent = isCancelling ? '⏳ 停止中...' : '⏹ 停止';" in batch_control_body
    assert "state.batchStopRequested = ['cancelling', 'cancelled'].includes(state.batchRunStatus);" in source
    assert "const isCancelling = normalizedStatus === 'cancelling';" in compare_control_body
    assert "'⏳ 停止中...'" in compare_control_body
    assert "const isCancelling = normalizedStatus === 'cancelling';" in ab_control_body
    assert "'⏳ 停止中...'" in ab_control_body


def test_orchestration_fetch_failures_show_actionable_diagnostics_and_throttled_toasts():
    source = JS_PATH.read_text(encoding="utf-8")
    fetch_body = _slice(source, "async function fetchOrchestrationRun(runId)", "async function recoverBatchOrchestrationRun()")
    batch_poll_body = _slice(source, "function pollBatchRun(runId)", "async function pauseBatchTest()")
    compare_poll_body = _slice(source, "function pollCompareRun(runId)", "async function pauseCompareTest()")
    ab_poll_body = _slice(source, "function pollABBatchRun(runId)", "async function startABBatchTest()")

    assert "function explainOrchestrationFetchError" in source
    assert "window.location.protocol === 'file:'" in source
    assert "http://127.0.0.1:8000" in source
    assert "fetch('/api/app-config'" in source
    assert "async function ensureOrchestrationEnvironmentReady" in source
    assert "function updateOrchestrationActionButtonState" in source
    assert "async function requestOrchestrationJson" in source
    assert "requestOrchestrationJson(" in fetch_body
    assert "await ensureOrchestrationEnvironmentReady(actionLabel);" in source
    assert "showOrchestrationFetchErrorToast('batch-poll'" in batch_poll_body
    assert "showOrchestrationFetchErrorToast('compare-poll'" in compare_poll_body
    assert "showOrchestrationFetchErrorToast('ab-poll'" in ab_poll_body


def test_orchestration_notice_renders_retry_entry_and_cache_busted_bundle():
    html = HTML_PATH.read_text(encoding="utf-8")
    source = JS_PATH.read_text(encoding="utf-8")

    assert 'id="orchestration-env-notice"' in html
    assert "onclick=\"retryOrchestrationEnvironmentProbe()\"" in source
    assert "function renderOrchestrationEnvironmentNotice()" in source
    assert 'legacy_bundle.js?v=95' in html


def test_prompt_ab_batch_mode_reuses_excel_and_orchestration_controls():
    html = HTML_PATH.read_text(encoding="utf-8")
    source = JS_PATH.read_text(encoding="utf-8")
    batch_body = _slice(source, "function getABBatchTurnsFromConfig(cfg = {})", "// 单个 config × N 模型，创建 N 个子对话并 Promise.all 等待完成")
    mode_body = _slice(source, "function switchABMode(mode, { refreshShell = true, persist = true } = {})", "async function loadABHistoryConversations()")

    assert 'id="ab-mode-batch"' in html
    assert 'id="ab-batch-mode"' in html
    assert 'id="ab-batch-excel-input"' in html
    assert 'id="ab-batch-turns"' in html
    assert 'id="ab-batch-concurrency"' in html
    assert "角色并发" in html
    assert 'id="btn-ab-batch-start"' in html
    assert 'id="ab-batch-control-row"' in html
    assert 'id="ab-batch-cards"' in html
    assert "function buildABBatchOrchestrationPayload" in batch_body
    assert "kind: 'ab'" in batch_body
    assert "function normalizeABBatchRoleConcurrency" in source
    assert "function getABBatchItemConcurrency(roleConcurrency = DEFAULT_AB_BATCH_ROLE_CONCURRENCY)" in source
    assert "function getABBatchRoleConcurrencyFromRun(run)" in source
    assert "const normalizedRoleConcurrency = normalizeABBatchRoleConcurrency(roleConcurrency, DEFAULT_AB_BATCH_ROLE_CONCURRENCY);" in batch_body
    assert "concurrency: runConcurrency," in batch_body
    assert "const roleConcurrency = getABBatchConcurrency();" in batch_body
    assert "const branchConcurrency = getABBatchItemConcurrency(roleConcurrency);" in batch_body
    assert "syncABBatchConcurrencyInput(roleConcurrency);" in batch_body
    assert "角色并发 ${roleConcurrency}（总分支并发 ${branchConcurrency}）" in batch_body
    assert "async function startABBatchTest()" in batch_body
    assert "function renderABBatchResults(run)" in batch_body
    assert "async function handleABBatchExcelImport(event)" in batch_body
    assert "state.abMode = mode === 'batch' ? 'batch' : 'live';" in mode_body
    assert "btnBatch.className = state.abMode === 'batch' ? 'btn btn-primary' : 'btn btn-secondary';" in mode_body


def test_prompt_ab_live_session_reuse_signature_uses_full_request_snapshot():
    source = JS_PATH.read_text(encoding="utf-8")
    request_body = _slice(source, "function buildABSessionRequestPayload()", "function normalizeABSessionPayloadForSignature(payload = {})")
    normalize_body = _slice(source, "function normalizeABSessionPayloadForSignature(payload = {})", "function getABSelectionSignature()")
    selection_body = _slice(source, "function getABSelectionSignature()", "function getStoredABSelectionSignature()")
    stored_body = _slice(source, "function getStoredABSelectionSignature()", "function getABHistoryBubbleHtml(turnNumber, text)")
    create_body = _slice(source, "async function createABSessionOnServer()", "async function ensureABSession({ forceNew = false } = {})")

    assert "shared_config: buildConfigSnapshotRequest('Prompt A/B', 'ab_session').config || {}" in request_body
    assert "base: buildABConversationPayload({ modelId: baseModel, promptVersion: basePrompt, variant: 'base' })" in request_body
    assert "compare: buildABConversationPayload({ modelId: compareModel, promptVersion: comparePrompt, variant: 'compare' })" in request_body
    assert "delete normalized.ab_session_id;" in normalize_body
    assert "normalizeABSessionPayloadForSignature(buildABSessionRequestPayload())" in selection_body
    assert "shared_config: abSessionState.sharedConfig || {}" in stored_body
    assert "base: abSessionState.baseConfig || {}" in stored_body
    assert "compare: abSessionState.compareConfig || {}" in stored_body
    assert "const payload = buildABSessionRequestPayload();" in create_body


def test_compare_progress_surfaces_unfinished_counts_and_retry_action():
    html = HTML_PATH.read_text(encoding="utf-8")
    source = JS_PATH.read_text(encoding="utf-8")
    control_body = _slice(source, "function renderCompareControlRow()", "function hydrateCompareConfigsFromRun(run)")
    progress_body = _slice(source, "function updateCompareRunProgress(run)", "function applyCompareOrchestrationRun(run)")

    assert 'id="btn-compare-retry"' in html
    assert 'id="compare-progress-failed"' in html
    assert 'id="compare-failed-num"' in html
    assert "state.compareRetryableItems" in source
    assert "countCompareRetryableItems(run)" in source
    assert "async function retryIncompleteCompareItems()" in source
    assert "buildCompareRetryPayloadFromRun(run)" in source
    assert "function summarizeCompareRunActivity(run)" in source
    assert "showRetry" in control_body
    assert "btn-compare-retry" in control_body
    assert "compare-progress-failed" in progress_body
    assert "compare-failed-num" in progress_body
    assert "生成中" in progress_body
    assert "评分活跃" in progress_body


def test_compare_orchestration_subscribes_live_score_updates_and_renders_partial_avg():
    source = JS_PATH.read_text(encoding="utf-8")
    compare_score_body = _slice(source, "function closeCompareScoreSocket(", "function hydrateCompareConfigsFromRun(run)")
    build_body = _slice(source, "function buildCompareMatrixFromRun(run)", "function getCompareCellSettledScoreTurns(cell)")
    cell_body = _slice(source, "function renderCompareCell(cell)", "function renderCompareCards(results)")
    progress_body = _slice(source, "} else if (msg.type === 'score_progress') {", "} else if (['score_enqueued', 'score_started', 'score_attempt', 'score_waiting_retry'].includes(msg.type)) {")

    assert "function ensureCompareScoreSocket(convId)" in compare_score_body
    assert "/api/scoring/ws/${normalized}" in compare_score_body
    assert "msg.type === 'score_updated'" in compare_score_body
    assert "msg.type === 'score_progress'" in compare_score_body
    assert "function syncCompareScoreSockets(run)" in compare_score_body
    assert "mergeCompareCellLiveScoreState({" in build_body
    assert "const liveAvgScoreHtml = Number.isFinite(avgScore)" in cell_body
    assert "stage === 'queued' || stage === 'generating' || stage === 'scoring'" in cell_body
    assert "${liveAvgScoreHtml}" in cell_body
    assert "scoring_active: true" in progress_body
    assert "scoring_active: false" not in progress_body


def test_scoring_retry_covers_unscored_turns_and_pending_cards_do_not_fake_zero_scores():
    html = HTML_PATH.read_text(encoding="utf-8")
    source = JS_PATH.read_text(encoding="utf-8")
    retry_body = _slice(source, "async function retryFailedScoring()", "async function _retryTurnList(turnNumbers)")
    score_card_body = _slice(source, "function renderScoreCard(score, idx)", "function renderRadarChart()")
    trend_body = _slice(source, "function renderScoreTrend()", "/* ═══ 提示词管理 ═══ */")

    assert "function isRetryableScoringTurn(turn)" in source
    assert "status === 'failed' || status === 'unscored'" in source
    assert "serverRetryable" in retry_body
    assert "没有需要重试的失败/未完成项" in retry_body
    assert "未完成打分" in score_card_body
    assert "const isLowScore = scoreStatus === 'scored'" in score_card_body
    assert "const totalText = showNumericScore ? safeTotal.toFixed(1) : '--';" in score_card_body
    assert "getScoringTurnStatus(s) === 'scored'" in trend_body
    assert '重试失败/未完成项' in html


def test_batch_retry_confirmation_mentions_unfinished_turns():
    source = JS_PATH.read_text(encoding="utf-8")
    retry_items_body = _slice(source, "async function retryFailedScoringItems()", "// 轻量并发池：limit 并发处理 items 数组")

    assert "确认批量重试失败/未完成打分项" in retry_items_body
    assert "失败/未完成轮次" in retry_items_body
    assert "这些失败/未完成轮次" in retry_items_body


def test_batch_and_compare_stop_wait_for_polling_to_finalize():
    source = JS_PATH.read_text(encoding="utf-8")
    batch_stop_body = _slice(source, "async function stopBatchTest()", "function getScoreColor(score)")
    compare_stop_body = _slice(source, "async function stopCompareTest()", "// 矩阵渲染：1 个 config 时退化为原 card 视图；多 config 时渲染表格")
    ab_stop_body = _slice(source, "async function stopABBatchTest()", "// 单个 config × N 模型，创建 N 个子对话并 Promise.all 等待完成")

    assert "applyBatchOrchestrationRun(run);" in batch_stop_body
    assert "pollBatchRun(run.id);" in batch_stop_body
    assert "finalizeBatchOrchestrationRun(run);" in batch_stop_body
    assert "已发送停止请求，等待批量任务收口" in batch_stop_body
    assert "applyCompareOrchestrationRun(run);" in compare_stop_body
    assert "pollCompareRun(run.id);" in compare_stop_body
    assert "finalizeCompareOrchestrationRun(run);" in compare_stop_body
    assert "已发送停止请求，等待模型对比任务收口" in compare_stop_body
    assert "applyABBatchOrchestrationRun(run);" in ab_stop_body
    assert "pollABBatchRun(run.id);" in ab_stop_body
    assert "finalizeABBatchOrchestrationRun(run);" in ab_stop_body
    assert "已发送停止请求，等待 Prompt A/B 批量任务收口" in ab_stop_body


def test_chat_control_row_calls_conversation_control_api():
    html = HTML_PATH.read_text(encoding="utf-8")
    source = JS_PATH.read_text(encoding="utf-8")
    control_body = _slice(source, "function normalizeConversationStatus(status)", "/* ═══ 保存配置并开始对话 ═══ */")

    assert 'id="chat-control-row"' in html
    assert 'id="btn-chat-pause"' in html
    assert 'id="btn-chat-resume"' in html
    assert 'id="btn-chat-cancel"' in html
    assert "function renderConversationControlRow()" in source
    assert "async function controlConversationRun(convId, action)" in source
    assert "/api/conversations/${encodeURIComponent(convId)}/control" in control_body
    assert "async function pauseActiveConversation()" in source
    assert "async function resumeActiveConversation()" in source
    assert "async function cancelActiveConversation()" in source
    assert "state.chatSessionMode !== 'interactive'" in control_body
    assert "isControllableConversationStatus" in control_body
