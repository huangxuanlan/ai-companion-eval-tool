"""
审计修复验证测试 v2 — 全部替换为行为测试，消除静态 grep。

P0 #1: _summarize_state 必须返回 ETA 字段（行为测试）
P0 #2: _public_run 必须复用 state.summary（行为测试）
P0 #3: formatEta 浏览器级测试（在 JS_BEHAVIORAL_TESTS 中）
P1 #4: _refresh_run_state 无二次 DB 遍历（mock + call_count）
P1 #5: XSS 全局扫描（结构化正则扫描 onclick 模板插值）
P1 #6: CSS 变量反向检查（确认无硬编码色值）
三色标签 / normalizeDebugEntry: JS 函数级行为测试
"""
import os
import re
import sys

# === 测试库隔离：强制使用临时数据库 ===
_test_db = os.path.join(os.path.dirname(__file__), "output", "test_audit_fixes.db")
os.makedirs(os.path.dirname(_test_db), exist_ok=True)
os.environ["LONGFORM_DB_PATH"] = _test_db

# 确保 server 目录在 path 中
server_dir = os.path.join(os.path.dirname(__file__), "server")
if server_dir not in sys.path:
    sys.path.insert(0, server_dir)

import pytest


# ═══════════════════════════════════════════════════════════════
# P0 #1: _summarize_state ETA 字段（行为测试 — 保留不动）
# ═══════════════════════════════════════════════════════════════
class TestP0_1_SummarizeStateEtaFields:
    """P0 #1: _summarize_state 必须计算并返回 ETA 相关字段。"""

    @pytest.fixture(autouse=True)
    def _import(self):
        from services.orchestration_service import _summarize_state
        self.fn = _summarize_state

    def test_returns_total_planned_turns(self):
        state = {
            "groups": [{"items": [
                {"planned_turns": 10, "turn_count": 3, "status": "running"},
                {"planned_turns": 8, "turn_count": 8, "status": "completed"},
            ]}],
            "avg_latency": 15.0,
            "concurrency": 2,
        }
        result = self.fn(state)
        assert result["total_planned_turns"] == 18
        assert result["total_completed_turns"] == 11

    def test_returns_eta_seconds(self):
        state = {
            "groups": [{"items": [
                {"planned_turns": 10, "turn_count": 2, "status": "running"},
            ]}],
            "avg_latency": 10.0,
            "concurrency": 2,
        }
        result = self.fn(state)
        assert result["eta_seconds"] == 40.0

    def test_returns_avg_latency(self):
        state = {
            "groups": [{"items": [{"planned_turns": 5, "turn_count": 1, "status": "running"}]}],
            "avg_latency": 7.5,
            "concurrency": 1,
        }
        result = self.fn(state)
        assert result["avg_latency"] == 7.5

    def test_eta_defaults_when_no_latency(self):
        state = {
            "groups": [{"items": [{"planned_turns": 5, "turn_count": 0, "status": "pending"}]}],
        }
        result = self.fn(state)
        assert result["avg_latency"] == 12.0
        assert result["eta_seconds"] == 60.0

    def test_eta_zero_when_all_completed(self):
        state = {
            "groups": [{"items": [
                {"planned_turns": 5, "turn_count": 5, "status": "completed"},
            ]}],
            "avg_latency": 10.0,
            "concurrency": 1,
        }
        result = self.fn(state)
        assert result["eta_seconds"] == 0.0

    def test_preserves_existing_item_counts(self):
        state = {
            "groups": [{"items": [
                {"planned_turns": 5, "turn_count": 5, "status": "completed"},
                {"planned_turns": 3, "turn_count": 1, "status": "failed"},
                {"planned_turns": 4, "turn_count": 0, "status": "pending"},
            ]}],
        }
        result = self.fn(state)
        assert result["total_items"] == 3
        assert result["completed_items"] == 1
        assert result["failed_items"] == 1
        assert result["pending_items"] == 1
        assert result["terminal_items"] == 2


# ═══════════════════════════════════════════════════════════════
# P0 #2: _public_run 复用 summary（行为测试 — 保留不动）
# ═══════════════════════════════════════════════════════════════
class TestP0_2_PublicRunReusesSummary:
    """P0 #2: _public_run 必须复用 state 中已计算的 summary，不重新覆盖。"""

    @pytest.fixture(autouse=True)
    def _import(self):
        from services.orchestration_service import _public_run
        self.fn = _public_run

    def test_reuses_precomputed_summary(self):
        pre_summary = {
            "total_items": 2, "terminal_items": 1,
            "total_planned_turns": 20, "total_completed_turns": 15,
            "avg_latency": 8.5, "eta_seconds": 29.4,
            "completed_items": 1, "failed_items": 0, "cancelled_items": 0,
            "pending_items": 1, "queued_items": 0, "running_items": 0,
            "scoring_items": 0, "pending_scoring_items": 0,
            "paused_items": 0, "interrupted_items": 0,
        }
        run = {
            "id": "test-run-001", "kind": "batch", "title": "Test",
            "status": "running", "concurrency": 2,
            "created_at": None, "updated_at": None,
            "manifest": {},
            "state": {
                "groups": [{"items": [
                    {"status": "completed", "conversation_id": "", "turn_count": 10,
                     "planned_turns": 10, "avg_chars": 300, "avg_score": 7.5,
                     "scored_turns": 10, "failed_turns": 0, "skipped_turns": 0,
                     "scoring_active": False, "has_pending_scores": False,
                     "pending_scoring_turns": 0, "updated_at": None, "resume_supported": False},
                    {"status": "running", "conversation_id": "", "turn_count": 5,
                     "planned_turns": 10, "avg_chars": 350, "avg_score": None,
                     "scored_turns": 0, "failed_turns": 0, "skipped_turns": 0,
                     "scoring_active": False, "has_pending_scores": False,
                     "pending_scoring_turns": 0, "updated_at": None, "resume_supported": False},
                ]}],
                "summary": pre_summary,
                "avg_latency": 8.5,
            },
        }
        result = self.fn(run)
        assert result is not None
        assert result["summary"]["eta_seconds"] == 29.4
        assert result["summary"]["total_planned_turns"] == 20
        assert result["summary"]["avg_latency"] == 8.5

    def test_fallback_when_no_summary(self):
        run = {
            "id": "test-run-002", "kind": "batch", "title": "Test",
            "status": "running", "concurrency": 1,
            "created_at": None, "updated_at": None,
            "manifest": {},
            "state": {
                "groups": [{"items": [
                    {"status": "running", "conversation_id": "", "turn_count": 3,
                     "planned_turns": 10, "avg_chars": 0, "avg_score": None,
                     "scored_turns": 0, "failed_turns": 0, "skipped_turns": 0,
                     "scoring_active": False, "has_pending_scores": False,
                     "pending_scoring_turns": 0, "updated_at": None, "resume_supported": False},
                ]}],
                "avg_latency": 15.0,
            },
        }
        result = self.fn(run)
        assert result is not None
        assert result["summary"]["total_planned_turns"] == 10
        assert result["summary"]["total_completed_turns"] == 3
        assert result["summary"]["eta_seconds"] > 0


# ═══════════════════════════════════════════════════════════════
# P1 #4: _refresh_run_state 无二次 DB 遍历（mock call_count）
# 替换旧的 grep 源码字符串计数
# ═══════════════════════════════════════════════════════════════
class TestP1_4_NoDuplicateDBTraversal:
    """P1 #4: _refresh_run_state 中 latency 收集在已有循环内完成，
    不产生额外的 db.get_conversation 调用。"""

    @pytest.mark.asyncio
    async def test_get_conversation_called_once_per_item(self):
        """每个 item 只调用 1 次 db.get_conversation，无二次遍历。"""
        from unittest.mock import patch, MagicMock
        from services import orchestration_service as svc

        fake_conv = {
            "id": "conv-001", "status": "completed",
            "results": [
                {"role": "assistant", "latency_s": 5.0, "text": "hello", "status": "ok"},
                {"role": "assistant", "latency_s": 3.0, "text": "world", "status": "ok"},
            ],
            "resume_supported": False,
        }
        fake_run = {
            "id": "run-001", "kind": "batch", "status": "running",
            "concurrency": 1, "created_at": None, "updated_at": None,
            "manifest": {"groups": [{"items": [{"payload": {}}]}]},
            "state": {
                "groups": [{"items": [
                    {"conversation_id": "conv-001", "planned_turns": 5,
                     "status": "running", "turn_count": 2},
                ]}],
            },
        }

        call_count = {"get_conversation": 0}

        def mock_get_conv(conv_id):
            call_count["get_conversation"] += 1
            return fake_conv

        with patch.object(svc.db, "get_orchestration_run", return_value=fake_run):
            with patch.object(svc.db, "get_conversation", side_effect=mock_get_conv):
                with patch.object(svc.db, "update_orchestration_run", return_value=fake_run):
                    with patch.object(svc, "_get_live_scoring_state", return_value={}):
                        await svc._refresh_run_state("run-001", persist=True)

        # 关键断言：只有 1 个 item，所以 get_conversation 应该只被调用 1 次
        assert call_count["get_conversation"] == 1, (
            f"Expected exactly 1 call to get_conversation, got {call_count['get_conversation']}. "
            "This suggests a second traversal loop exists."
        )

    @pytest.mark.asyncio
    async def test_latencies_collected_in_state(self):
        """验证 avg_latency 被正确计算并写入 state。"""
        from unittest.mock import patch
        from services import orchestration_service as svc

        fake_conv = {
            "id": "conv-002", "status": "completed",
            "results": [
                {"role": "assistant", "latency_s": 6.0, "text": "a", "status": "ok"},
                {"role": "assistant", "latency_s": 4.0, "text": "b", "status": "ok"},
            ],
            "resume_supported": False,
        }
        fake_run = {
            "id": "run-002", "kind": "batch", "status": "running",
            "concurrency": 1, "created_at": None, "updated_at": None,
            "manifest": {"groups": [{"items": [{"payload": {}}]}]},
            "state": {
                "groups": [{"items": [
                    {"conversation_id": "conv-002", "planned_turns": 5,
                     "status": "running", "turn_count": 2},
                ]}],
            },
        }
        captured_state = {}

        def mock_update(run_id, *, status, state):
            captured_state.update(state)
            return {**fake_run, "state": state, "status": status}

        with patch.object(svc.db, "get_orchestration_run", return_value=fake_run):
            with patch.object(svc.db, "get_conversation", return_value=fake_conv):
                with patch.object(svc.db, "update_orchestration_run", side_effect=mock_update):
                    with patch.object(svc, "_get_live_scoring_state", return_value={}):
                        await svc._refresh_run_state("run-002", persist=True)

        assert "avg_latency" in captured_state
        assert captured_state["avg_latency"] == pytest.approx(5.0, rel=0.01), (
            f"Expected avg_latency ~5.0 (mean of 6.0 and 4.0), got {captured_state['avg_latency']}"
        )


# ═══════════════════════════════════════════════════════════════
# P1 #5: XSS 全面扫描（结构化正则，替代旧的单点 grep）
# ═══════════════════════════════════════════════════════════════
class TestP1_5_XssComprehensiveScan:
    """P1 #5: 所有 onclick/innerHTML 中的动态 convId 必须经过转义。"""

    def test_no_raw_convid_in_onclick_templates(self):
        """扫描所有 onclick 中出现 convId 的位置，确认不存在未转义的插值。"""
        js_path = os.path.join(os.path.dirname(__file__), "server", "static", "js", "legacy_bundle.js")
        with open(js_path, "r", encoding="utf-8") as f:
            content = f.read()

        # 找所有 onclick="...${...convId...}..." 或 onclick='...${...convId...}...' 模式
        # 危险模式：直接插入 d.convId / item.convId 等而没有 escapeHtml()
        dangerous_pattern = re.compile(
            r"""onclick\s*=\s*['"][^'"]*\$\{(?!.*escapeHtml)[^}]*conv[Ii]d[^}]*\}""",
            re.IGNORECASE,
        )
        dangerous_matches = dangerous_pattern.findall(content)
        assert len(dangerous_matches) == 0, (
            f"Found {len(dangerous_matches)} onclick with unescaped convId:\n"
            + "\n".join(dangerous_matches[:5])
        )


# ═══════════════════════════════════════════════════════════════
# P1 #6: CSS 变量反向检查（确认无硬编码 #DC2626）
# ═══════════════════════════════════════════════════════════════
class TestP1_6_NoBadHardcodedColors:
    """P1 #6: buildDegenerationPanel 中不应存在硬编码的危险色值。"""

    def test_no_hardcoded_dc2626_in_degeneration_panel(self):
        js_path = os.path.join(os.path.dirname(__file__), "server", "static", "js", "legacy_bundle.js")
        with open(js_path, "r", encoding="utf-8") as f:
            content = f.read()
        fn_start = content.find("function buildDegenerationPanel")
        assert fn_start > 0, "buildDegenerationPanel function not found"
        fn_end = content.find("\nfunction ", fn_start + 1)
        fn_body = content[fn_start:fn_end]
        # 去除合法的 CSS var() fallback 后，检查是否还有裸硬编码的 #DC2626
        # var(--color-danger, #DC2626) 中的 #DC2626 是合法 fallback，不算硬编码
        cleaned = re.sub(r"var\(--[\w-]+,\s*#[0-9A-Fa-f]+\)", "", fn_body)
        assert "#DC2626" not in cleaned, (
            "buildDegenerationPanel still contains bare hardcoded #DC2626 outside of CSS var() fallback. "
            "Should use var(--color-danger, #DC2626) pattern."
        )
        # 正向检查：确认使用了 CSS 变量
        assert "var(--color-danger" in fn_body, (
            "buildDegenerationPanel should use var(--color-danger) CSS variable."
        )



# ═══════════════════════════════════════════════════════════════
# 三色标签: buildTurnStatusTags 行为测试（JS 函数级）
# 在 test_ui_completeness.py 的 E2E 中用 Playwright evaluate 测试
# 这里作为结构契约测试：验证函数签名和返回值结构
# ═══════════════════════════════════════════════════════════════
# → 移至 test_ui_completeness.py 中的 Playwright evaluate 测试（S2）


# ═══════════════════════════════════════════════════════════════
# normalizeDebugEntry: 行为测试（JS 函数级）
# → 同样移至 test_ui_completeness.py 中的 Playwright evaluate 测试（S2）


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
