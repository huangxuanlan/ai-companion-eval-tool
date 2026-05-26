from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

PROJECT_DIR = Path(__file__).resolve().parent
SERVER_DIR = PROJECT_DIR / "server"

if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from services.prompt_service import PromptService  # noqa: E402


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).strip() + "\n", encoding="utf-8")


def _few_shot_content(user_text: str, assistant_text: str) -> str:
    return f"""
    ## 【霸道腹黑型 - 暧昧阶段 - 日常场景】
    [User]
    {user_text}
    [Assistant]
    {assistant_text}
    ---
    """


@pytest.fixture
def strict_latest_few_shot_tree(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    few_shot_root = tmp_path / "长文模式叙事变量" / "示例——长文模式"
    latest_dir = few_shot_root / "最新版本"
    archive_dir = few_shot_root / "归档"

    latest_path = latest_dir / "霸道腹黑型男性 Few-shot 示例（精选版）_v15_formatted.md"
    parent_old_path = few_shot_root / "霸道腹黑型男性 Few-shot 示例（精选版）_v14.md"
    archived_path = archive_dir / "霸道腹黑型男性 Few-shot 示例（精选版）_v99_20260522.md"

    _write(latest_path, _few_shot_content("*latest user*", "*latest reply*"))
    _write(parent_old_path, _few_shot_content("*parent old user*", "*parent old reply*"))
    _write(archived_path, _few_shot_content("*archived user*", "*archived reply*"))

    monkeypatch.setattr(PromptService, "FEW_SHOT_LATEST_DIR", latest_dir)
    monkeypatch.setattr(PromptService, "FEW_SHOT_SOURCE_ROOTS", [latest_dir])
    monkeypatch.setattr(PromptService, "FEW_SHOT_SEARCH_PATHS", [latest_dir, few_shot_root])

    return {
        "latest_path": latest_path,
        "parent_old_path": parent_old_path,
        "archived_path": archived_path,
    }


def test_few_shot_auto_resolution_only_scans_latest_dir(strict_latest_few_shot_tree):
    service = PromptService()

    resolved, _ = service.resolve_few_shot_reference(
        "",
        personal_type="霸道腹黑",
        gender="男",
        relationship="暧昧",
    )

    assert resolved == strict_latest_few_shot_tree["latest_path"]
    assert resolved != strict_latest_few_shot_tree["parent_old_path"]
    assert resolved != strict_latest_few_shot_tree["archived_path"]


def test_few_shot_explicit_old_path_redirects_to_latest_when_traits_are_known(
    strict_latest_few_shot_tree,
):
    service = PromptService()

    for requested_path in (
        str(strict_latest_few_shot_tree["archived_path"]),
        "霸道腹黑型男性 Few-shot 示例（精选版）_v14.md",
        "示例——长文模式/霸道腹黑型男性 Few-shot 示例.md",
    ):
        resolved, _ = service.resolve_few_shot_reference(
            requested_path,
            personal_type="霸道腹黑",
            gender="男",
            relationship="暧昧",
        )
        messages = service.load_few_shot_examples(
            requested_path,
            personal_type="霸道腹黑",
            gender="男",
            relationship="暧昧",
        )

        assert resolved == strict_latest_few_shot_tree["latest_path"]
        assert messages[0]["content"] == "*latest user*"
        assert messages[1]["content"] == "*latest reply*"


def test_few_shot_explicit_archive_path_is_blocked_without_traits(
    strict_latest_few_shot_tree,
):
    service = PromptService()

    resolved, display_path = service.resolve_few_shot_reference(
        str(strict_latest_few_shot_tree["archived_path"]),
    )
    messages = service.load_few_shot_examples(
        str(strict_latest_few_shot_tree["archived_path"]),
    )

    assert resolved is None
    assert display_path == ""
    assert messages == []


def test_few_shot_does_not_fallback_to_old_path_when_latest_has_no_match(
    strict_latest_few_shot_tree,
):
    service = PromptService()

    resolved, display_path = service.resolve_few_shot_reference(
        str(strict_latest_few_shot_tree["archived_path"]),
        personal_type="温暖陪伴",
        gender="女",
        relationship="暧昧",
    )
    messages = service.load_few_shot_examples(
        str(strict_latest_few_shot_tree["archived_path"]),
        personal_type="温暖陪伴",
        gender="女",
        relationship="暧昧",
    )

    assert resolved is None
    assert display_path == ""
    assert messages == []
