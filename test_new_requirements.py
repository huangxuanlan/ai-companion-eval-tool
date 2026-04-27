from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PROJECT_DIR = Path(__file__).resolve().parent
SERVER_DIR = PROJECT_DIR / "server"

if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from main import app  # noqa: E402
from config import PRESET_CHARACTERS  # noqa: E402
from services.model_adapter import ModelAdapter  # noqa: E402
from services.prompt_service import PromptService  # noqa: E402


PRESET_IDS = [
    "xiaoJingYan",
    "guChenXi",
    "luHanZe",
    "suTangTang",
    "xiaoZhan",
    "chiCheng",
    "yuMianGui",
]


def _resolve_latest_curated_few_shot_path(preset_id: str) -> str:
    preset = PRESET_CHARACTERS[preset_id]
    _, display_path = PromptService().resolve_few_shot_reference(
        "",
        personal_type=str(preset.get("type", "")).strip(),
        gender=str(preset.get("gender", "")).strip(),
    )
    assert display_path, f"未解析到 {preset_id} 的最新 few-shot 路径"
    return display_path


EXPECTED_PRESET_PATHS = {
    preset_id: _resolve_latest_curated_few_shot_path(preset_id)
    for preset_id in PRESET_IDS
}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_minimax_models_registered(client: TestClient):
    response = client.get("/api/models")
    assert response.status_code == 200, response.text

    models = {item["id"]: item for item in response.json()["models"]}
    assert "minimax-m27" in models
    assert "minimax-m25" in models
    assert "minimax-her" in models
    assert "minimax-m27-hs" not in models
    assert "healer-alpha" not in models
    assert "doubao-1.5-character" in models

    m27 = models["minimax-m27"]
    doubao_character = models["doubao-1.5-character"]
    assert m27["display_name"] == "MiniMax M2.7"
    assert m27["capabilities"]["thinking"] is False
    assert m27["capabilities"]["web_search"] is False
    assert m27["provider"] == "minimax"
    assert doubao_character["provider"] == "volcengine"
    assert doubao_character["capabilities"]["thinking"] is False


def test_model_tier_keeps_minimax_in_pro_bucket(client: TestClient):
    pro_response = client.get("/api/models", params={"tier": "pro"})
    mini_response = client.get("/api/models", params={"tier": "mini"})
    assert pro_response.status_code == 200, pro_response.text
    assert mini_response.status_code == 200, mini_response.text

    pro_ids = {item["id"] for item in pro_response.json()["models"]}
    mini_ids = {item["id"] for item in mini_response.json()["models"]}
    assert "minimax-m27" in pro_ids
    assert "minimax-m27" not in mini_ids


def test_doubao_15_character_builtin_uses_chat_completions():
    provider = ModelAdapter()._get_provider("doubao-1.5-character")
    assert provider.interface == "chat_completions"
    assert provider.endpoint_id == "doubao-1-5-pro-32k-character-250715"
    assert provider.supports_thinking() is False


def test_minimax_provider_merges_multiple_system_messages():
    provider = ModelAdapter()._get_provider("minimax-m27")
    converted = provider._convert_messages([
        {"role": "system", "content": "系统约束 A"},
        {"role": "system", "content": "系统约束 B"},
        {"role": "user", "content": "你好"},
    ])

    assert converted[0]["role"] == "system"
    assert converted[0]["content"] == "系统约束 A\n\n系统约束 B"
    assert sum(1 for item in converted if item["role"] == "system") == 1
    assert converted[1]["role"] == "user"
    assert converted[1]["name"] == provider.user_name


@pytest.mark.parametrize("preset_id, expected_path", EXPECTED_PRESET_PATHS.items())
def test_preset_few_shot_paths(
    client: TestClient,
    preset_id: str,
    expected_path: str,
):
    response = client.get(f"/api/presets/{preset_id}")
    assert response.status_code == 200, response.text

    payload = response.json()
    assert payload.get("is_builtin") is True
    actual_path = payload.get("config", {}).get("few_shot_file", "")
    assert actual_path == expected_path
    assert "Role_info_works" in payload.get("config", {}).get("character", {})
    assert "voice_forbidden" in payload.get("config", {}).get("modules", {})


def test_variables_api_uses_new_few_shot_dir(client: TestClient):
    response = client.get(
        "/api/presets/variables",
        params={
            "personality": "霸道腹黑",
            "gender": "男",
            "relationship": "暧昧",
        },
    )
    assert response.status_code == 200, response.text

    payload = response.json()
    assert "示例——长文模式" in payload.get("longform_few_shot", "")
    assert payload.get("voice_forbidden", "").strip()


@pytest.mark.parametrize("preset_id", PRESET_IDS)
def test_builtin_presets_do_not_use_old_few_shot_prefix(
    client: TestClient,
    preset_id: str,
):
    response = client.get(f"/api/presets/{preset_id}")
    assert response.status_code == 200, response.text

    payload = response.json()
    few_shot_file = payload.get("config", {}).get("few_shot_file", "")
    assert "longform_few_shot_" not in few_shot_file
