from __future__ import annotations

import importlib
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent
SERVER_DIR = PROJECT_DIR / "server"

if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))


def _reload_config():
    # 使用 importlib.reload 而不是 pop+import_module，避免替换 sys.modules['config']
    # 后导致其他测试缓存的旧模块对象失效（importlib.reload 要求模块已在 sys.modules）。
    import config
    return importlib.reload(config)


def test_config_supports_bundle_relative_paths(monkeypatch, tmp_path: Path):
    bundle_dir = tmp_path / "bundle_assets"
    (bundle_dir / "长文模式" / "提示词").mkdir(parents=True)
    (bundle_dir / "长文模式" / "测试提示词").mkdir(parents=True)
    (bundle_dir / "长文模式" / "摘要提示词").mkdir(parents=True)
    (bundle_dir / "长文模式" / "打分提示词").mkdir(parents=True)
    (bundle_dir / "长文模式" / "变量").mkdir(parents=True)
    (bundle_dir / "prompt-validator-llm" / "configs" / "models").mkdir(parents=True)
    (bundle_dir / "promptfoo-pipeline" / "scoring_prompts" / "长文模式").mkdir(parents=True)
    (bundle_dir / "promptfoo-pipeline" / "scripts").mkdir(parents=True)

    monkeypatch.setenv("LONGFORM_BUNDLE_DIR", str(bundle_dir))
    monkeypatch.setenv("LONGFORM_TOOLCHAIN_ROOT", str(bundle_dir))
    monkeypatch.delenv("LONGFORM_CONTENT_ROOT", raising=False)
    monkeypatch.delenv("LONGFORM_PROMPT_DIR", raising=False)
    monkeypatch.delenv("LONGFORM_PROVIDER_LLM_DIR", raising=False)
    monkeypatch.delenv("LONGFORM_SCORING_PIPELINE_DIR", raising=False)
    monkeypatch.delenv("LONGFORM_PIPELINE_SCRIPTS_DIR", raising=False)

    module = _reload_config()

    try:
        assert module.CONTENT_ROOT == bundle_dir / "长文模式"
        assert module.PROMPT_DIR == bundle_dir / "长文模式" / "提示词"
        assert module.TEST_PROMPT_DIR == bundle_dir / "长文模式" / "测试提示词"
        assert module.SUMMARY_PROMPT_DIR == bundle_dir / "长文模式" / "摘要提示词"
        assert module.SCORING_PROMPT_DIR == bundle_dir / "长文模式" / "打分提示词"
        assert module.VARIABLE_DIR == bundle_dir / "长文模式" / "变量"
        assert module.PROVIDER_LLM_DIR == bundle_dir / "prompt-validator-llm"
        assert module.MODELS_CONFIG_DIR == bundle_dir / "prompt-validator-llm" / "configs" / "models"
        assert module.SCORING_PIPELINE_DIR == bundle_dir / "promptfoo-pipeline" / "scoring_prompts" / "长文模式"
        assert module.PIPELINE_SCRIPTS_DIR == bundle_dir / "promptfoo-pipeline" / "scripts"
    finally:
        monkeypatch.delenv("LONGFORM_BUNDLE_DIR", raising=False)
        monkeypatch.delenv("LONGFORM_TOOLCHAIN_ROOT", raising=False)
        _reload_config()
