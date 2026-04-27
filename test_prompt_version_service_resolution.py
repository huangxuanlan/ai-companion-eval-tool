from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
SERVER_DIR = PROJECT_DIR / "server"

if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from services import prompt_version_service  # noqa: E402


def _write_meta(path: Path, active_filename: str) -> None:
    path.write_text(
        json.dumps({"active_filename": active_filename}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def test_versioned_prompt_store_resolve_filename_semantics(tmp_path: Path, monkeypatch):
    summary_dir = tmp_path / "summary"
    scoring_dir = tmp_path / "scoring"
    summary_dir.mkdir()
    scoring_dir.mkdir()

    (summary_dir / "长文模式摘要提示词_v1.0.md").write_text("v1.0", encoding="utf-8")
    (summary_dir / "长文模式摘要提示词_v1.2.md").write_text("v1.2", encoding="utf-8")
    _write_meta(summary_dir / ".prompt_meta.json", "长文模式摘要提示词_v1.0.md")

    (scoring_dir / "长文模式打分提示词_v2.1.md").write_text("v2.1", encoding="utf-8")
    (scoring_dir / "长文模式打分提示词_v2.3.md").write_text("v2.3", encoding="utf-8")
    _write_meta(scoring_dir / ".prompt_meta.json", "长文模式打分提示词_v2.1.md")
    (scoring_dir / "长文模式评分摘要报告提示词_v1.0_20260420.md").write_text("report-v1.0", encoding="utf-8")
    (scoring_dir / "长文模式评分摘要报告提示词_v1.1_20260421.md").write_text("report-v1.1", encoding="utf-8")
    _write_meta(scoring_dir / ".scoring_report_prompt_meta.json", "长文模式评分摘要报告提示词_v1.0_20260420.md")
    (scoring_dir / "长文模式对比摘要报告提示词_v1.0_20260420.md").write_text("compare-v1.0", encoding="utf-8")
    (scoring_dir / "长文模式对比摘要报告提示词_v1.2_20260422.md").write_text("compare-v1.2", encoding="utf-8")
    _write_meta(scoring_dir / ".compare_report_prompt_meta.json", "长文模式对比摘要报告提示词_v1.0_20260420.md")

    monkeypatch.setattr(prompt_version_service, "SUMMARY_PROMPT_DIR", summary_dir)
    monkeypatch.setattr(prompt_version_service, "SCORING_PROMPT_DIR", scoring_dir)

    summary_store = prompt_version_service.VersionedPromptStore(kind="summary")
    scoring_store = prompt_version_service.VersionedPromptStore(kind="scoring")
    scoring_report_store = prompt_version_service.VersionedPromptStore(kind="scoring_report")
    compare_report_store = prompt_version_service.VersionedPromptStore(kind="compare_report")

    assert summary_store.resolve_filename("") == "长文模式摘要提示词_v1.0.md"
    assert summary_store.resolve_filename(None) == "长文模式摘要提示词_v1.0.md"
    assert summary_store.resolve_filename("active") == "长文模式摘要提示词_v1.0.md"
    assert summary_store.resolve_filename("latest") == "长文模式摘要提示词_v1.2.md"
    assert summary_store.resolve_filename("auto") == "长文模式摘要提示词_v1.2.md"
    assert summary_store.resolve_filename("长文模式摘要提示词_v1.2.md") == "长文模式摘要提示词_v1.2.md"

    assert scoring_store.resolve_filename("") == "长文模式打分提示词_v2.1.md"
    assert scoring_store.resolve_filename(None) == "长文模式打分提示词_v2.1.md"
    assert scoring_store.resolve_filename("active") == "长文模式打分提示词_v2.1.md"
    assert scoring_store.resolve_filename("latest") == "长文模式打分提示词_v2.3.md"
    assert scoring_store.resolve_filename("auto") == "长文模式打分提示词_v2.3.md"
    assert scoring_store.resolve_filename("长文模式打分提示词_v2.3.md") == "长文模式打分提示词_v2.3.md"

    assert scoring_report_store.resolve_filename("") == "长文模式评分摘要报告提示词_v1.0_20260420.md"
    assert scoring_report_store.resolve_filename("active") == "长文模式评分摘要报告提示词_v1.0_20260420.md"
    assert scoring_report_store.resolve_filename("latest") == "长文模式评分摘要报告提示词_v1.1_20260421.md"
    assert compare_report_store.resolve_filename("") == "长文模式对比摘要报告提示词_v1.0_20260420.md"
    assert compare_report_store.resolve_filename("latest") == "长文模式对比摘要报告提示词_v1.2_20260422.md"
