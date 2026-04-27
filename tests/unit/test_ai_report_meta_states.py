from __future__ import annotations

import database


def test_ai_report_meta_marks_ready_when_summary_exists():
    meta = database._derive_ai_report_meta(
        conversation_status="completed",
        total_turns=16,
        scored_turns=16,
        ai_report_count=1,
        ai_report_event="summary_generated",
    )

    assert meta["ai_report_status"] == "ready"
    assert meta["ai_report_label"] == "报告就绪"
    assert meta["ai_report_ready"] is True


def test_ai_report_meta_marks_waiting_scoring_with_progress_fraction():
    meta = database._derive_ai_report_meta(
        conversation_status="completed",
        total_turns=16,
        scored_turns=5,
        failed_turns=0,
        skipped_turns=0,
    )

    assert meta["ai_report_status"] == "waiting_scoring"
    assert meta["ai_report_label"] == "待评分完成 5/16"
    assert meta["scoring_done_turns"] == 5
    assert meta["scoring_complete"] is False


def test_ai_report_meta_marks_blocked_when_no_scored_turns_after_completion():
    meta = database._derive_ai_report_meta(
        conversation_status="completed",
        total_turns=2,
        scored_turns=0,
        failed_turns=2,
        skipped_turns=0,
    )

    assert meta["ai_report_status"] == "blocked_no_score"
    assert meta["ai_report_label"] == "无已评分轮次"


def test_ai_report_meta_marks_pending_after_scoring_completes_without_summary():
    meta = database._derive_ai_report_meta(
        conversation_status="completed",
        total_turns=16,
        scored_turns=16,
        failed_turns=0,
        skipped_turns=0,
    )

    assert meta["ai_report_status"] == "pending"
    assert meta["ai_report_label"] == "等待生成报告"
