from __future__ import annotations

import os
import sys

import pytest

from tests._loader import load_legacy_tests

_LEGACY_PUBLIC_DEMO_MODE = "LONGFORM_PUBLIC_DEMO_MODE"
_legacy_module = load_legacy_tests(globals(), "test_public_demo_mode.py")
os.environ.pop(_LEGACY_PUBLIC_DEMO_MODE, None)


@pytest.fixture(autouse=True)
def isolate_public_demo_mode(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(_LEGACY_PUBLIC_DEMO_MODE, "1")
    target_modules = (
        "config",
        "main",
        "services.public_demo",
        "server.config",
        "server.main",
        "server.services.public_demo",
    )
    previous_modules = {
        module_name: sys.modules.get(module_name)
        for module_name in target_modules
    }
    for module_name in target_modules:
        sys.modules.pop(module_name, None)
    yield
    for module_name in target_modules:
        sys.modules.pop(module_name, None)
        previous = previous_modules.get(module_name)
        if previous is not None:
            sys.modules[module_name] = previous
