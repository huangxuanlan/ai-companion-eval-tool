from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
SERVER_DIR = PROJECT_DIR / "server"

if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from services import scoring_service  # noqa: E402


def _clear_score_excel_cache():
    sys.modules.pop(scoring_service._SCORE_EXCEL_MODULE_NAME, None)


def test_scoring_service_loads_score_excel_without_sys_path_pollution(
    tmp_path: Path,
    monkeypatch,
):
    (tmp_path / "score_excel.py").write_text(
        """
SCORING_BASE_URL = "https://example.com/v1"
SCORING_API_KEY = "test-key"
SCORING_MODEL = "score-model"
_active_config = None


def load_scene_config(scoring_dir):
    return {"dimensions": ["a"], "weights": {"a": 1.0}, "column_alias": {}}


def load_scoring_template(scoring_dir):
    return "system-prompt", "user-template"


def validate_scores(data, config):
    return data


def fill_user_prompt(user_template, row, config):
    return user_template
""".strip(),
        encoding="utf-8",
    )

    _clear_score_excel_cache()
    monkeypatch.setattr(scoring_service, "PIPELINE_SCRIPTS", tmp_path)
    path_before = list(sys.path)

    try:
        module = scoring_service._get_score_excel_module()
        service = scoring_service.ScoringService()

        assert module.SCORING_MODEL == "score-model"
        assert service.is_available() is True
        assert sys.path == path_before
        assert str(tmp_path) not in sys.path
    finally:
        _clear_score_excel_cache()


def test_scoring_service_uses_tighter_default_max_tokens(monkeypatch):
    monkeypatch.delenv("SCORING_MAX_TOKENS", raising=False)

    service = scoring_service.ScoringService()

    assert service._max_tokens == 8192


def test_scoring_service_uses_longer_default_request_timeout(monkeypatch):
    monkeypatch.delenv("SCORING_REQUEST_TIMEOUT_S", raising=False)

    service = scoring_service.ScoringService()

    assert service._default_timeout_s == 120


def test_scoring_service_allows_max_tokens_env_override(monkeypatch):
    monkeypatch.setenv("SCORING_MAX_TOKENS", "900")

    service = scoring_service.ScoringService()

    assert service._max_tokens == 900


def test_scoring_service_falls_back_to_26b_after_31b_timeout(monkeypatch):
    service = scoring_service.ScoringService()
    service._config = {"dimensions": ["persona_fidelity"]}
    service._timeout_fallback_model_id = "gemma4-26b"

    attempts: list[str] = []
    sleeps: list[float] = []

    class _FakeCompletions:
        def create(self, *, model, **kwargs):
            attempts.append(model)
            if model == "gemma-4-31b-it":
                raise TimeoutError("Request timed out.")
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content='{"scores":{"persona_fidelity":5},"weighted_total":5,"reasoning":"ok"}'))],
                usage=SimpleNamespace(prompt_tokens=11, completion_tokens=22),
            )

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=_FakeCompletions()))

    monkeypatch.setattr(
        service,
        "_get_client",
        lambda timeout_s=None, model_id=None: fake_client,
    )
    monkeypatch.setattr(
        service,
        "_resolve_scoring_model_id",
        lambda model_id: {
            "gemma4-31b": "gemma-4-31b-it",
            "gemma4-26b": "gemma-4-26b-a4b-it",
        }.get(str(model_id or ""), str(model_id or "")),
    )
    monkeypatch.setattr(
        service,
        "_parse_score_payload",
        lambda text: {
            "scores": {"persona_fidelity": 5},
            "weighted_total": 5,
            "mapped_total": 10,
            "reasoning": "ok",
        },
    )
    monkeypatch.setattr(scoring_service.time, "sleep", lambda seconds: sleeps.append(seconds))

    result = service._call_scoring_api(
        system_prompt="system",
        user_content="user",
        model_id="gemma4-31b",
        retry_delays=(5, 15),
    )

    assert attempts == ["gemma-4-31b-it", "gemma-4-26b-a4b-it"]
    assert sleeps == []
    assert result["success"] is True
    assert result["model_id"] == "gemma-4-26b-a4b-it"
    assert result["mapped_total"] == 10


def test_scoring_service_keeps_original_model_on_non_timeout(monkeypatch):
    service = scoring_service.ScoringService()
    service._config = {"dimensions": ["persona_fidelity"]}
    service._timeout_fallback_model_id = "gemma4-26b"

    attempts: list[str] = []
    sleeps: list[float] = []

    class _FakeCompletions:
        def create(self, *, model, **kwargs):
            attempts.append(model)
            raise RuntimeError("429 too many requests")

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=_FakeCompletions()))

    monkeypatch.setattr(
        service,
        "_get_client",
        lambda timeout_s=None, model_id=None: fake_client,
    )
    monkeypatch.setattr(
        service,
        "_resolve_scoring_model_id",
        lambda model_id: {
            "gemma4-31b": "gemma-4-31b-it",
            "gemma4-26b": "gemma-4-26b-a4b-it",
        }.get(str(model_id or ""), str(model_id or "")),
    )
    monkeypatch.setattr(scoring_service.time, "sleep", lambda seconds: sleeps.append(seconds))

    result = service._call_scoring_api(
        system_prompt="system",
        user_content="user",
        model_id="gemma4-31b",
        retry_delays=(1,),
    )

    assert attempts == ["gemma-4-31b-it", "gemma-4-31b-it"]
    assert sleeps == [1]
    assert result["success"] is False
    assert result["model_id"] == "gemma-4-31b-it"


def test_parse_score_payload_repairs_dirty_json_variants(monkeypatch):
    service = scoring_service.ScoringService()
    service._config = {"dimensions": ["persona_fidelity"]}
    fake_score_excel = SimpleNamespace(validate_scores=lambda data, config: data)
    monkeypatch.setattr(scoring_service, "_get_score_excel_module", lambda: fake_score_excel)

    cases = {
        "plain": '{"scores":{"persona_fidelity":5},"weighted_total":5,"mapped_total":10,"reasoning":"ok"}',
        "fenced": '```json\n{"scores":{"persona_fidelity":5},"weighted_total":5,"mapped_total":10,"reasoning":"ok"}\n```',
        "prefix_suffix": '下面是结果\n{"scores":{"persona_fidelity":5},"weighted_total":5,"mapped_total":10,"reasoning":"ok"}\n评分结束',
        "truncated": '{"scores":{"persona_fidelity":5},"weighted_total":5,"mapped_total":10,"reasoning":"ok"',
        "double_json": '{"debug":1}\n一些说明\n{"scores":{"persona_fidelity":5},"weighted_total":5,"mapped_total":10,"reasoning":"ok"}',
    }

    for raw_text in cases.values():
        parsed = service._parse_score_payload(raw_text)
        assert parsed.get("_parse_failed") is not True
        assert parsed["scores"]["persona_fidelity"] == 5
        assert parsed["mapped_total"] == 10
        assert parsed["reasoning"] == "ok"


def test_call_scoring_api_retries_after_json_parse_failure(monkeypatch):
    service = scoring_service.ScoringService()
    service._config = {"dimensions": ["persona_fidelity"]}
    attempts: list[str] = []
    sleeps: list[float] = []

    def fake_call(**kwargs):
        attempts.append(kwargs.get("candidate_model") or kwargs.get("candidate_alias") or "unknown")
        if len(attempts) == 1:
            raise RuntimeError("JSON 解析失败，触发重试: bad payload")
        return {
            "scores": {"persona_fidelity": 5},
            "weighted_total": 5,
            "mapped_total": 10,
            "reasoning": "ok",
            "raw_response": '{"scores":{"persona_fidelity":5}}',
            "input_tokens": 1,
            "output_tokens": 1,
            "latency": 0.1,
            "success": True,
            "error": None,
            "model_id": "qwen3.6-plus",
        }

    monkeypatch.setattr(service, "_call_scoring_via_openai", fake_call)
    monkeypatch.setattr(service, "_resolve_requested_scoring_alias", lambda model_id: "qwen3.6-plus")
    monkeypatch.setattr(service, "_resolve_scoring_provider", lambda model_id: "aliyun")
    monkeypatch.setattr(service, "_resolve_scoring_model_id", lambda model_id: "qwen3.6-plus")
    monkeypatch.setattr(service, "_is_timeout_error", lambda exc: False)
    monkeypatch.setattr(service, "_is_rate_limit_error", lambda exc: False)
    monkeypatch.setattr(scoring_service.time, "sleep", lambda seconds: sleeps.append(seconds))

    result = service._call_scoring_api(
        system_prompt="system",
        user_content="user",
        model_id="qwen3.6-plus",
        retry_delays=(0,),
    )

    assert attempts == ["qwen3.6-plus", "qwen3.6-plus"]
    assert sleeps == [0]
    assert result["success"] is True
    assert result["mapped_total"] == 10


def test_scoring_service_rejects_embedded_fallback_api_key(tmp_path: Path, monkeypatch):
    (tmp_path / "score_excel.py").write_text(
        """
SCORING_BASE_URL = "https://example.com/v1"
SCORING_API_KEY = "embedded-demo-key"
SCORING_MODEL = "score-model"


def load_scene_config(scoring_dir):
    return {"dimensions": ["a"], "weights": {"a": 1.0}, "column_alias": {}}


def load_scoring_template(scoring_dir):
    return "system-prompt", "user-template"


def validate_scores(data, config):
    return data


def fill_user_prompt(user_template, row, config):
    return user_template
""".strip(),
        encoding="utf-8",
    )

    monkeypatch.setattr(scoring_service, "PIPELINE_SCRIPTS", tmp_path)
    monkeypatch.delenv("SCORING_API_KEY", raising=False)
    monkeypatch.delenv("ARK_API_KEY", raising=False)
    monkeypatch.delenv("VOLCENGINE_API_KEY", raising=False)
    _clear_score_excel_cache()

    try:
        service = scoring_service.ScoringService()

        assert service.is_available() is False
        assert service.get_last_error() == "SCORING_API_KEY 未配置"
    finally:
        _clear_score_excel_cache()


def test_scoring_service_allows_local_model_without_scoring_api_key(
    tmp_path: Path,
    monkeypatch,
):
    (tmp_path / "score_excel.py").write_text(
        """
SCORING_BASE_URL = "https://example.com/v1"
SCORING_API_KEY = ""
SCORING_MODEL = "doubao-pro"


def load_scene_config(scoring_dir):
    return {"dimensions": ["a"], "weights": {"a": 1.0}, "column_alias": {}}


def load_scoring_template(scoring_dir):
    return "system-prompt", "user-template"


def validate_scores(data, config):
    return data


def fill_user_prompt(user_template, row, config):
    return user_template
""".strip(),
        encoding="utf-8",
    )

    monkeypatch.setattr(scoring_service, "PIPELINE_SCRIPTS", tmp_path)
    monkeypatch.delenv("SCORING_API_KEY", raising=False)
    monkeypatch.delenv("ARK_API_KEY", raising=False)
    monkeypatch.delenv("VOLCENGINE_API_KEY", raising=False)
    _clear_score_excel_cache()

    try:
        service = scoring_service.ScoringService()

        assert service.is_available("gemma4-31b-local") is True
        assert service.is_available() is False
        assert service.get_last_error() == "SCORING_API_KEY 未配置"
    finally:
        _clear_score_excel_cache()


def test_scoring_service_allows_google_api_key_fallback_for_google_provider(
    tmp_path: Path,
    monkeypatch,
):
    (tmp_path / "score_excel.py").write_text(
        """
SCORING_BASE_URL = "https://example.com/v1"
SCORING_API_KEY = ""
SCORING_MODEL = "gemma4-31b"
_active_config = None


def load_scene_config(scoring_dir):
    return {"dimensions": ["a"], "weights": {"a": 1.0}, "column_alias": {}}


def load_scoring_template(scoring_dir):
    return "system-prompt", "user-template"


def validate_scores(data, config):
    return data


def fill_user_prompt(user_template, row, config):
    return user_template
""".strip(),
        encoding="utf-8",
    )

    monkeypatch.setattr(scoring_service, "PIPELINE_SCRIPTS", tmp_path)
    monkeypatch.delenv("SCORING_API_KEY", raising=False)
    monkeypatch.delenv("SCORING_API_KEYS", raising=False)
    monkeypatch.delenv("ARK_API_KEY", raising=False)
    monkeypatch.delenv("VOLCENGINE_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "google-single-key")
    monkeypatch.setenv("GOOGLE_API_KEYS", "google-key-a, google-key-b")
    _clear_score_excel_cache()

    try:
        service = scoring_service.ScoringService()
        monkeypatch.setattr(
            service,
            "_get_model_config",
            lambda model_id: {"provider": "google_gemini"} if model_id == "gemma4-31b" else {},
        )

        assert service._resolve_scoring_api_key("gemma4-31b") == "google-single-key"
        assert service._resolve_scoring_api_keys("gemma4-31b") == [
            "google-key-a",
            "google-key-b",
            "google-single-key",
        ]
        assert service.is_available("gemma4-31b") is True
    finally:
        _clear_score_excel_cache()


def test_scoring_service_prefers_model_provider_connection_over_global_scoring_env(
    monkeypatch,
):
    monkeypatch.setenv("SCORING_API_KEY", "google-global-key")
    monkeypatch.setenv("SCORING_API_KEYS", "google-global-a, google-global-b, google-direct-a")
    monkeypatch.setenv("GOOGLE_API_KEY", "google-direct-key")
    monkeypatch.setenv("GOOGLE_API_KEYS", "google-direct-a, google-direct-b")
    monkeypatch.setenv("VOLCENGINE_API_KEY", "volcengine-direct-key")

    service = scoring_service.ScoringService()

    assert service._resolve_requested_scoring_alias("doubao-seed-2-0-pro-260215") == "doubao-pro"
    assert service._resolve_scoring_provider("doubao-seed-2-0-pro-260215") == "volcengine"
    assert service._resolve_scoring_base_url("doubao-pro") == "https://ark.cn-beijing.volces.com/api/v3"
    assert service._resolve_scoring_api_key("doubao-pro") == "volcengine-direct-key"
    assert service._resolve_scoring_api_keys("doubao-pro") == ["volcengine-direct-key"]
    assert service._resolve_scoring_api_key("gemma-4-31b-it") == "google-direct-key"
    assert service._resolve_scoring_api_keys("gemma-4-31b-it") == [
        "google-global-a",
        "google-global-b",
        "google-direct-a",
        "google-global-key",
        "google-direct-b",
        "google-direct-key",
    ]


def test_scoring_service_get_client_tracks_requested_model(monkeypatch):
    service = scoring_service.ScoringService()
    service._config = {"dimensions": ["persona_fidelity"]}

    calls: list[dict] = []

    class _FakeOpenAI:
        def __init__(self, *, base_url, api_key, timeout):
            calls.append(
                {
                    "base_url": base_url,
                    "api_key": api_key,
                    "timeout": timeout,
                }
            )
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs: None))

    monkeypatch.setenv("SCORING_API_KEY", "google-global-key")
    monkeypatch.setenv("SCORING_API_KEYS", "google-global-a, google-global-b")
    monkeypatch.setenv("GOOGLE_API_KEY", "google-direct-key")
    monkeypatch.setenv("GOOGLE_API_KEYS", "google-direct-a, google-direct-b")
    monkeypatch.setenv("VOLCENGINE_API_KEY", "volcengine-direct-key")

    import openai

    monkeypatch.setattr(openai, "OpenAI", _FakeOpenAI)

    service._get_client(model_id="gemma4-31b")
    service._get_client(model_id="doubao-pro")

    assert calls == [
        {
            "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
            "api_key": "google-global-a",
            "timeout": 120,
        },
        {
            "base_url": "https://ark.cn-beijing.volces.com/api/v3",
            "api_key": "volcengine-direct-key",
            "timeout": 120,
        },
    ]


def test_scoring_service_routes_local_model_through_model_adapter(monkeypatch):
    service = scoring_service.ScoringService()
    service._config = {"dimensions": ["persona_fidelity"]}

    class _FakeAdapter:
        _models = {
            "gemma4-31b-local": {
                "provider": "local_openai",
                "api": {"model_name": "gemma4"},
            }
        }

        def __init__(self):
            self.calls = []

        def chat(self, model_id, messages, **kwargs):
            self.calls.append(
                {
                    "model_id": model_id,
                    "messages": messages,
                    "kwargs": kwargs,
                }
            )
            return SimpleNamespace(
                content='{"scores":{"persona_fidelity":5},"weighted_total":5,"mapped_total":10,"reasoning":"ok"}',
                input_tokens=12,
                output_tokens=34,
                latency_s=1.25,
                success=True,
                error="",
            )

    fake_adapter = _FakeAdapter()
    service._model_adapter = fake_adapter
    monkeypatch.setattr(
        service,
        "_parse_score_payload",
        lambda text: {
            "scores": {"persona_fidelity": 5},
            "weighted_total": 5,
            "mapped_total": 10,
            "reasoning": "ok",
        },
    )

    result = service._call_scoring_api(
        system_prompt="system",
        user_content="user",
        model_id="gemma4-31b-local",
        retry_delays=(),
    )

    assert fake_adapter.calls == [
        {
            "model_id": "gemma4-31b-local",
            "messages": [
                {"role": "system", "content": "system"},
                {"role": "user", "content": "user"},
            ],
            "kwargs": {
                "max_tokens": 8192,
                "thinking_effort": "high",
                "temperature": 0,
                "top_p": 1,
            },
        }
    ]
    assert result["success"] is True
    assert result["model_id"] == "gemma4-31b-local"
    assert result["mapped_total"] == 10


# ---------------------------------------------------------------------------
# 回归测试: score_turn / score_conversation / score_rows / get_dimensions
# 走 local_openai 时不应因缺少 SCORING_API_KEY 而 RuntimeError
# ---------------------------------------------------------------------------

import asyncio


def _make_local_ready_service(tmp_path, monkeypatch):
    """构造一个 config 已加载、无远端 API Key、有 local adapter 的 ScoringService。"""
    (tmp_path / "score_excel.py").write_text(
        """\
SCORING_BASE_URL = "https://example.com/v1"
SCORING_API_KEY = ""
SCORING_MODEL = "gemma4-31b-local"
_active_config = None


def load_scene_config(scoring_dir):
    return {
        "dimensions": ["persona_fidelity"],
        "weights": {"persona_fidelity": 1.0},
        "column_alias": {"user_message": "用户输入", "output": "AI输出"},
        "dims_display": {},
    }


def validate_scores(data, config):
    return data


def fill_user_prompt(user_template, row, config):
    return "filled"
""",
        encoding="utf-8",
    )

    monkeypatch.setattr(scoring_service, "PIPELINE_SCRIPTS", tmp_path)
    monkeypatch.delenv("SCORING_API_KEY", raising=False)
    monkeypatch.delenv("ARK_API_KEY", raising=False)
    monkeypatch.delenv("VOLCENGINE_API_KEY", raising=False)
    _clear_score_excel_cache()

    service = scoring_service.ScoringService()

    class _FakeAdapter:
        _models = {
            "gemma4-31b-local": {
                "provider": "local_openai",
                "api": {"model_name": "gemma4"},
            }
        }

        def chat(self, model_id, messages, **kwargs):
            return SimpleNamespace(
                content='{"scores":{"persona_fidelity":8},"weighted_total":8,"mapped_total":16,"reasoning":"good"}',
                input_tokens=10,
                output_tokens=20,
                latency_s=0.5,
                success=True,
                error="",
            )

    service._model_adapter = _FakeAdapter()
    return service


def test_score_turn_local_model_no_api_key_required(tmp_path, monkeypatch):
    """P0 回归: score_turn() 走 local_openai 不应报 SCORING_API_KEY 未配置。"""
    service = _make_local_ready_service(tmp_path, monkeypatch)
    monkeypatch.setattr(
        service,
        "_parse_score_payload",
        lambda text: {
            "scores": {"persona_fidelity": 8},
            "weighted_total": 8,
            "mapped_total": 16,
            "reasoning": "good",
        },
    )

    turn_data = {
        "user_input": "你好",
        "ai_output": "嗨~",
        "turn": 1,
        "role_name": "测试角色",
        "personality": "温柔",
        "relationship": "朋友",
        "prompt_name": "test",
    }

    try:
        result = asyncio.run(
            service.score_turn(turn_data, model_id="gemma4-31b-local")
        )
    finally:
        _clear_score_excel_cache()


def test_score_turn_passes_history_context_into_scoring_row(tmp_path, monkeypatch):
    service = _make_local_ready_service(tmp_path, monkeypatch)
    captured: dict = {}

    def fake_score_one_sync(
        row,
        timeout_s=None,
        retry_delays=None,
        prompt_version=None,
        model_id=None,
        thinking_effort="",
    ):
        captured["row"] = dict(row)
        return {
            "success": True,
            "scores": {"persona_fidelity": 8},
            "weighted_total": 8,
            "mapped_total": 16,
            "reasoning": "ok",
            "latency": 0.1,
            "model_id": model_id,
            "score_status": "scored",
        }

    monkeypatch.setattr(service, "_score_one_sync", fake_score_one_sync)

    try:
        asyncio.run(
            service.score_turn(
                {
                    "user_input": "你好",
                    "ai_output": "嗨~",
                    "turn": 2,
                    "role_name": "测试角色",
                    "personality": "温柔",
                    "relationship": "朋友",
                    "prompt_name": "test",
                    "history_context": "[用户] 第一轮\n[AI] 第一轮回复",
                },
                model_id="gemma4-31b-local",
            )
        )
    finally:
        _clear_score_excel_cache()

    assert captured["row"]["近期对话历史"] == "[用户] 第一轮\n[AI] 第一轮回复"


def test_score_conversation_builds_history_context_from_previous_turns(tmp_path, monkeypatch):
    service = _make_local_ready_service(tmp_path, monkeypatch)
    captured_turns: list[dict] = []

    async def fake_score_turn(turn_data, **kwargs):
        captured_turns.append(dict(turn_data))
        return {
            "success": True,
            "scores": {"persona_fidelity": 8},
            "weighted_total": 8,
            "mapped_total": 16,
            "reasoning": "ok",
            "latency": 0.1,
            "model_id": kwargs.get("model_id", ""),
            "score_status": "scored",
        }

    monkeypatch.setattr(service, "score_turn", fake_score_turn)
    config = {
        "character": {"Role_Nickname": "角色A", "personality": "冷静"},
        "context": {"relationship": "朋友"},
        "runtime": {"scoring_model_id": "gemma4-31b-local"},
        "prompt_file": "test",
    }
    results = [
        {"turn": 1, "user_input": "第一轮用户", "ai_output": "第一轮回复"},
        {"turn": 2, "user_input": "第二轮用户", "ai_output": "第二轮回复"},
        {"turn": 3, "user_input": "第三轮用户", "ai_output": "第三轮回复"},
    ]

    try:
        scored = asyncio.run(service.score_conversation("fake-conv-id", results, config))
    finally:
        _clear_score_excel_cache()

    assert len(scored) == 3
    assert captured_turns[0]["history_context"] == ""
    assert captured_turns[1]["history_context"] == "[用户] 第一轮用户\n[AI] 第一轮回复"
    assert captured_turns[2]["history_context"] == "\n".join(
        [
            "[用户] 第一轮用户",
            "[AI] 第一轮回复",
            "[用户] 第二轮用户",
            "[AI] 第二轮回复",
        ]
    )


def test_build_history_context_keeps_only_latest_ten_previous_turns():
    service = scoring_service.ScoringService()
    results = [
        {"turn": idx + 1, "user_input": f"用户{idx + 1}", "ai_output": f"回复{idx + 1}"}
        for idx in range(12)
    ]

    history = service._build_history_context(results, 11)
    lines = history.splitlines()

    assert "[用户] 用户1" not in lines
    assert "[AI] 回复1" not in lines
    assert "[用户] 用户2" in lines
    assert "[AI] 回复11" in lines
    assert "[用户] 用户12" not in lines
    assert "[AI] 回复12" not in lines


def test_load_prompt_bundle_blank_version_resolves_latest(tmp_path, monkeypatch):
    prompt_path = tmp_path / "长文模式打分提示词_v4.0_20260421.md"
    prompt_path.write_text(
        "<system_context>ok</system_context>\n<evaluation_input>\n{{history_context}}\n</evaluation_input>\n<output_format>ok</output_format>",
        encoding="utf-8",
    )
    service = scoring_service.ScoringService()
    service.pipeline_prompt_dir = tmp_path
    service._template_cache.clear()
    captured: dict = {}

    monkeypatch.setattr(service.prompt_store, "ensure_initialized", lambda: None)
    monkeypatch.setattr(
        service.prompt_store,
        "resolve_filename",
        lambda filename=None: captured.setdefault("filename", filename) or prompt_path.name,
    )
    monkeypatch.setattr(service.prompt_store, "download_path", lambda filename: prompt_path)

    bundle = service._load_prompt_bundle("")

    assert captured["filename"] == "latest"
    assert bundle[1].startswith("<evaluation_input>")


def test_generate_scoring_report_defaults_to_qwen_plus_and_persists_cache(monkeypatch):
    service = scoring_service.ScoringService()
    service._config = {
        "weights": {
            "persona_fidelity": 0.2,
            "narrative_immersion": 0.2,
            "emotional_tension": 0.2,
            "boundary_memory": 0.2,
            "format_compliance": 0.2,
        }
    }
    service.scoring_report_prompt_store = SimpleNamespace(
        read_prompt=lambda filename=None: {
            "filename": "长文模式评分摘要报告提示词_v1.0_20260420.md",
            "content": "report_meta_json:\n{{report_meta_json}}\n\ndimension_stats_json:\n{{dimension_stats_json}}\n\ncase_items_json:\n{{case_items_json}}",
        }
    )

    captured: dict = {}

    async def _fake_generate_report_markdown(*, model_id, prompt, max_tokens=4096):
        captured["model_id"] = model_id
        captured["prompt"] = prompt
        return "\n".join(
            [
                "# 示例打分报告",
                "",
                "## 总体统计",
                "ok",
                "## 维度分析",
                "ok",
                "## 逐条打分结果",
                "ok",
                "## Top 3 差评 Case",
                "ok",
                "## Top 3 优秀 Case",
                "ok",
                "## 优化建议",
                "ok",
            ]
        )

    monkeypatch.setattr(service, "_ensure_loaded", lambda require_api_key=False, model_id=None: None)
    monkeypatch.setattr(service, "_generate_report_markdown", _fake_generate_report_markdown)
    monkeypatch.setattr(scoring_service.db, "get_ai_report_summary", lambda **kwargs: None)

    saved: dict = {}

    def _fake_save_ai_report_summary(**kwargs):
        saved.update(kwargs)
        return kwargs

    monkeypatch.setattr(scoring_service.db, "save_ai_report_summary", _fake_save_ai_report_summary)

    result = asyncio.run(
        service.generate_scoring_report(
            [
                {
                    "turn": 1,
                    "status": "scored",
                    "success": True,
                    "mapped_total": 8.4,
                    "reasoning": "角色稳定，格式合规。",
                    "scores": {
                        "persona_fidelity": 4,
                        "narrative_immersion": 4,
                        "emotional_tension": 4,
                        "boundary_memory": 5,
                        "format_compliance": 4,
                    },
                }
            ],
            {
                "prompt_file": "星朋友长文模式_提示词_v3.6_20260416.md",
                "character": {"Role_Nickname": "池骋"},
                "context": {"relationship": "暧昧"},
                "runtime": {"model_id": "doubao-lite", "scoring_model_id": "gemma4-31b-it"},
            },
            conversation_id="conv-001",
        )
    )

    assert captured["model_id"] == "qwen-plus"
    assert "角色稳定，格式合规。" in captured["prompt"]
    assert result["cached"] is False
    assert saved["target_type"] == "conversation_scoring"
    assert saved["report_kind"] == "scoring_report"
    assert saved["target_id"] == "conv-001"
    assert saved["model_id"] == "qwen-plus"


def test_generate_scoring_report_rejects_missing_required_sections(monkeypatch):
    service = scoring_service.ScoringService()
    service._config = {"weights": {}}
    service.scoring_report_prompt_store = SimpleNamespace(
        read_prompt=lambda filename=None: {
            "filename": "长文模式评分摘要报告提示词_v1.0_20260420.md",
            "content": "{{report_meta_json}}",
        }
    )

    async def _fake_generate_report_markdown(*, model_id, prompt, max_tokens=4096):
        return "# 不完整报告\n\n## 总体统计\nok"

    monkeypatch.setattr(service, "_ensure_loaded", lambda require_api_key=False, model_id=None: None)
    monkeypatch.setattr(service, "_generate_report_markdown", _fake_generate_report_markdown)
    monkeypatch.setattr(scoring_service.db, "get_ai_report_summary", lambda **kwargs: None)

    result = asyncio.run(
        service.generate_scoring_report(
            [
                {
                    "turn": 1,
                    "status": "scored",
                    "success": True,
                    "mapped_total": 8.0,
                    "reasoning": "ok",
                    "scores": {},
                }
            ],
            {"character": {"Role_Nickname": "测试角色"}, "context": {}, "runtime": {}},
            conversation_id="conv-002",
        )
    )

    assert "报告缺少必要章节" in result["error"]


def test_generate_compare_report_supports_three_groups(monkeypatch):
    service = scoring_service.ScoringService()
    service.compare_report_prompt_store = SimpleNamespace(
        read_prompt=lambda filename=None: {
            "filename": "长文模式对比摘要报告提示词_v1.0_20260420.md",
            "content": "meta={{report_meta_json}}\nsummary={{groups_summary_json}}\nturns={{per_turn_comparison_json}}",
        }
    )

    captured: dict = {}

    async def _fake_generate_report_markdown(*, model_id, prompt, max_tokens=4096):
        captured["model_id"] = model_id
        captured["prompt"] = prompt
        return "\n".join(
            [
                "============================================================",
                "  A/B/C 对比摘要 | cmp-001",
                "============================================================",
                "",
                "============================================================",
                "  维度分析 (B vs A / C vs A)",
                "============================================================",
                "",
                "------------------------------------------------------------",
                "  概括性结论",
                "------------------------------------------------------------",
                "",
                "============================================================",
                "  逐条对比",
                "------------------------------------------------------------",
                "",
                "[PENDING] 未完成行:",
                "无",
                "",
                "[RETRY] 失败行:",
                "无",
            ]
        )

    monkeypatch.setattr(service, "_generate_report_markdown", _fake_generate_report_markdown)
    monkeypatch.setattr(scoring_service.db, "get_ai_report_summary", lambda **kwargs: None)
    monkeypatch.setattr(scoring_service.db, "save_ai_report_summary", lambda **kwargs: kwargs)

    report = {
        "id": "cmp-001",
        "compare_mode": "model",
        "group_results": [
            {
                "label": "A",
                "model_id": "model-a",
                "prompt_version": "prompt-a",
                "avg_scores": {"total": 8.1},
                "turn_count": 2,
                "scored_count": 2,
                "failed_count": 0,
                "pending_count": 0,
                "pass_count": 2,
                "manual_avg": 8.5,
                "total_input_tokens": 100,
                "total_output_tokens": 50,
                "avg_latency_s": 10.2,
            },
            {
                "label": "B",
                "model_id": "model-b",
                "prompt_version": "prompt-b",
                "avg_scores": {"total": 8.3},
                "turn_count": 2,
                "scored_count": 2,
                "failed_count": 0,
                "pending_count": 0,
                "pass_count": 2,
                "manual_avg": 8.4,
                "total_input_tokens": 90,
                "total_output_tokens": 44,
                "avg_latency_s": 9.1,
            },
            {
                "label": "C",
                "model_id": "model-c",
                "prompt_version": "prompt-c",
                "avg_scores": {"total": 7.9},
                "turn_count": 2,
                "scored_count": 1,
                "failed_count": 1,
                "pending_count": 0,
                "pass_count": 1,
                "manual_avg": None,
                "total_input_tokens": 88,
                "total_output_tokens": 40,
                "avg_latency_s": 8.8,
            },
        ],
        "per_dim_comparison": {"total": {"scores": {"A": 8.1, "B": 8.3, "C": 7.9}, "winner": "B"}},
        "per_turn_comparison": [
            {
                "turn": 1,
                "winners": ["B"],
                "groups": [
                    {"label": "A", "model_id": "model-a", "prompt_version": "prompt-a", "turn": 1, "total": 8.0, "status": "scored", "manual_star_score": 8, "dimension_scores": {"persona_fidelity": 4}, "reasoning": "A ok", "ai_output": "A 输出"},
                    {"label": "B", "model_id": "model-b", "prompt_version": "prompt-b", "turn": 1, "total": 8.6, "status": "scored", "manual_star_score": 9, "dimension_scores": {"persona_fidelity": 5}, "reasoning": "B better", "ai_output": "B 输出"},
                    {"label": "C", "model_id": "model-c", "prompt_version": "prompt-c", "turn": 1, "total": 0, "status": "failed", "manual_star_score": None, "dimension_scores": {}, "reasoning": "超时", "ai_output": "C 输出"},
                ],
            }
        ],
        "winners": {"total": "B"},
    }

    result = asyncio.run(service.generate_compare_report(report))

    assert captured["model_id"] == "qwen-plus"
    assert '"label": "C"' in captured["prompt"]
    assert result["group_count"] == 3
    assert result["cached"] is False
    assert "A/B/C 对比摘要" in result["markdown"]


def test_score_conversation_local_model_no_api_key_required(tmp_path, monkeypatch):
    """P0 回归: score_conversation() 走 local_openai 不应报 SCORING_API_KEY 未配置。"""
    service = _make_local_ready_service(tmp_path, monkeypatch)
    monkeypatch.setattr(
        service,
        "_parse_score_payload",
        lambda text: {
            "scores": {"persona_fidelity": 8},
            "weighted_total": 8,
            "mapped_total": 16,
            "reasoning": "good",
        },
    )

    config = {
        "character": {"Role_Nickname": "角色A"},
        "context": {"relationship": "朋友"},
        "runtime": {"scoring_model_id": "gemma4-31b-local"},
        "prompt_file": "test",
    }
    results = [
        {"user_input": "第1轮", "ai_output": "回复1", "turn": 1},
    ]

    try:
        scored = asyncio.run(
            service.score_conversation("fake-conv-id", results, config)
        )
    finally:
        _clear_score_excel_cache()

    assert len(scored) == 1
    assert scored[0]["success"] is True


def test_score_rows_local_model_passes_model_id(tmp_path, monkeypatch):
    """P1 回归: score_rows() 应将 model_id 传透到 _score_one_sync。"""
    service = _make_local_ready_service(tmp_path, monkeypatch)
    monkeypatch.setattr(
        service,
        "_parse_score_payload",
        lambda text: {
            "scores": {"persona_fidelity": 8},
            "weighted_total": 8,
            "mapped_total": 16,
            "reasoning": "good",
        },
    )

    rows = [{"用户输入": "测试", "AI输出": "回复"}]

    try:
        scored = asyncio.run(
            service.score_rows(rows, model_id="gemma4-31b-local")
        )
    finally:
        _clear_score_excel_cache()

    assert len(scored) == 1
    assert scored[0]["success"] is True


def test_score_rows_passes_prompt_and_thinking_config(tmp_path, monkeypatch):
    service = _make_local_ready_service(tmp_path, monkeypatch)
    captured: list[dict] = []

    def fake_score_one_sync(
        row,
        timeout_s=None,
        retry_delays=None,
        prompt_version=None,
        model_id=None,
        thinking_effort="",
    ):
        captured.append(
            {
                "row": dict(row),
                "prompt_version": prompt_version,
                "model_id": model_id,
                "thinking_effort": thinking_effort,
            }
        )
        return {
            "success": True,
            "scores": {"persona_fidelity": 9},
            "weighted_total": 9,
            "mapped_total": 18,
            "reasoning": "ok",
            "latency": 0.1,
            "model_id": model_id,
        }

    monkeypatch.setattr(service, "_score_one_sync", fake_score_one_sync)
    rows = [{"用户输入": "测试", "AI输出": "回复"}]

    try:
        scored = asyncio.run(
            service.score_rows(
                rows,
                model_id="gemma4-31b-local",
                prompt_version="打分提示词_v2",
                thinking_effort="high",
            )
        )
    finally:
        _clear_score_excel_cache()

    assert len(scored) == 1
    assert captured == [
        {
            "row": {"用户输入": "测试", "AI输出": "回复"},
            "prompt_version": "打分提示词_v2",
            "model_id": "gemma4-31b-local",
            "thinking_effort": "high",
        }
    ]


def test_get_dimensions_local_model_no_api_key_required(tmp_path, monkeypatch):
    """P1 回归: get_dimensions() 只需 config，本地模型不应要求 API Key。"""
    service = _make_local_ready_service(tmp_path, monkeypatch)

    try:
        dims = service.get_dimensions(model_id="gemma4-31b-local")
    finally:
        _clear_score_excel_cache()

    assert "dimensions" in dims
    assert dims["dimensions"] == ["persona_fidelity"]


def test_scoring_service_sends_dashscope_thinking_budget(monkeypatch):
    service = scoring_service.ScoringService()
    service._config = {"dimensions": ["persona_fidelity"]}
    captured = {}

    class _FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content='{"scores":{"persona_fidelity":5},"weighted_total":5,"mapped_total":10,"reasoning":"ok"}',
                            reasoning_content="思考轨迹",
                        )
                    )
                ],
                usage=SimpleNamespace(prompt_tokens=12, completion_tokens=34),
            )

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=_FakeCompletions()))
    monkeypatch.setattr(service, "_get_client", lambda timeout_s=None, model_id=None: fake_client)
    monkeypatch.setattr(service, "_resolve_scoring_provider", lambda model_id: "aliyun")
    monkeypatch.setattr(service, "_model_supports_thinking", lambda model_id: True)
    monkeypatch.setattr(
        service,
        "_parse_score_payload",
        lambda text: {
            "scores": {"persona_fidelity": 5},
            "weighted_total": 5,
            "mapped_total": 10,
            "reasoning": "ok",
        },
    )

    result = service._call_scoring_via_openai(
        model_alias="qwen3.6-plus",
        candidate_model="qwen3.6-plus",
        system_prompt="system",
        user_content="user",
        thinking_effort="high",
    )

    assert captured["extra_body"]["enable_thinking"] is True
    assert captured["extra_body"]["thinking_budget"] == 4096
    assert result["reasoning_content"] == "思考轨迹"


def test_scoring_service_set_max_workers_rebuilds_executor():
    service = scoring_service.ScoringService()
    original_executor = service._executor

    try:
      updated = service.set_max_workers(12)
      assert updated == 12
      assert service.get_max_workers() == 12
      assert service._executor is not original_executor
      assert service._executor._max_workers == 12
    finally:
      original_executor.shutdown(wait=False, cancel_futures=False)
      service._executor.shutdown(wait=False, cancel_futures=False)


def test_score_conversation_retries_failed_turn(monkeypatch):
    service = scoring_service.ScoringService()
    service._config = {"dimensions": ["persona_fidelity"]}
    service._default_retry_delays = (0,)
    attempts: list[int] = []
    progress_events: list[dict] = []

    monkeypatch.setattr(service, "_ensure_loaded", lambda **kwargs: None)
    monkeypatch.setattr(service, "resolve_scoring_thinking_effort", lambda *args: "high")

    async def fake_score_turn(turn_data, **kwargs):
        attempts.append(turn_data["turn"])
        if len(attempts) == 1:
            return {
                "success": False,
                "scores": {"persona_fidelity": 0},
                "weighted_total": 0,
                "mapped_total": 0,
                "reasoning": "first failed",
                "score_status": "failed",
            }
        return {
            "success": True,
            "scores": {"persona_fidelity": 9},
            "weighted_total": 9,
            "mapped_total": 18,
            "reasoning": "ok",
            "score_status": "scored",
        }

    async def on_progress(event):
        progress_events.append(dict(event))

    monkeypatch.setattr(service, "score_turn", fake_score_turn)

    try:
        scored = asyncio.run(
            service.score_conversation(
                "conv-1",
                [{"turn": 1, "user_input": "测试", "ai_output": "输出"}],
                {
                    "runtime": {
                        "scoring_model_id": "qwen3.6-plus",
                        "scoring_retry_count": 2,
                    },
                    "character": {},
                    "context": {},
                    "modules": {},
                },
                on_progress=on_progress,
                max_workers=2,
            )
        )
    finally:
        service._executor.shutdown(wait=False, cancel_futures=False)

    assert attempts == [1, 1]
    assert any(event["type"] == "retry" for event in progress_events)
    assert scored[0]["success"] is True
