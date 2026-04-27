from __future__ import annotations

import shutil
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_DIR.parent.parent
TOOLCHAIN_ROOT = PROJECT_DIR.parent
DIST_DIR = PROJECT_DIR / "dist" / "longform-tool-portable"
BUNDLE_DIR = DIST_DIR / "bundle_assets"


def _reset_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def _copy_tree(src: Path, dst: Path) -> None:
    if not src.exists():
        raise FileNotFoundError(f"缺少目录: {src}")
    shutil.copytree(
        src,
        dst,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns(
            "__pycache__",
            "*.pyc",
            ".pytest_cache",
            ".env",
            "longform.db",
            "*.log",
            "*.sqlite*",
        ),
    )


def _copy_file(src: Path, dst: Path) -> None:
    if not src.exists():
        raise FileNotFoundError(f"缺少文件: {src}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def main() -> None:
    _reset_dir(DIST_DIR)
    (DIST_DIR / "output").mkdir(parents=True, exist_ok=True)

    # 应用主体
    _copy_tree(PROJECT_DIR / "server", DIST_DIR / "server")
    _copy_file(PROJECT_DIR / "launcher.py", DIST_DIR / "launcher.py")
    _copy_file(PROJECT_DIR / "start.bat", DIST_DIR / "start.bat")
    _copy_file(PROJECT_DIR / "start.command", DIST_DIR / "start.command")
    _copy_file(PROJECT_DIR / "README.md", DIST_DIR / "README.md")
    _copy_file(PROJECT_DIR / "打包与一键启动方案.md", DIST_DIR / "打包与一键启动方案.md")
    _copy_file(PROJECT_DIR / "server" / ".env.example", DIST_DIR / "server" / ".env.example")

    for optional_file in (
        "长文模式_测试输入_模板.xlsx",
        "长文模式_测试输出_模板.xlsx",
        "longform_multi_turn.py",
    ):
        src = PROJECT_DIR / optional_file
        if src.exists():
            _copy_file(src, DIST_DIR / optional_file)

    # 运行时依赖
    _copy_tree(
        TOOLCHAIN_ROOT / "prompt-validator-llm" / "providers",
        BUNDLE_DIR / "prompt-validator-llm" / "providers",
    )
    _copy_tree(
        TOOLCHAIN_ROOT / "prompt-validator-llm" / "configs" / "models",
        BUNDLE_DIR / "prompt-validator-llm" / "configs" / "models",
    )
    _copy_file(
        TOOLCHAIN_ROOT / "promptfoo-pipeline" / "scripts" / "score_excel.py",
        BUNDLE_DIR / "promptfoo-pipeline" / "scripts" / "score_excel.py",
    )
    _copy_tree(
        TOOLCHAIN_ROOT / "promptfoo-pipeline" / "scoring_prompts" / "长文模式",
        BUNDLE_DIR / "promptfoo-pipeline" / "scoring_prompts" / "长文模式",
    )

    # 内容资产
    content_root = WORKSPACE_ROOT / "工作资料" / "产品资料" / "提示词资料" / "长文模式"
    for folder_name in ("提示词", "测试提示词", "摘要提示词", "打分提示词", "变量"):
        _copy_tree(
            content_root / folder_name,
            BUNDLE_DIR / "长文模式" / folder_name,
        )

    print(f"[OK] 便携包已生成: {DIST_DIR}")


if __name__ == "__main__":
    main()
