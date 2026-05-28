"""
LocalOpenAIProvider — backward-compat shim (sys.modules alias)

实际实现已迁移至 server/lib/model_adapter_lib/openai_provider.py（W0 ADR-005，2026-05-28）。

本 shim 使用 `sys.modules` 别名技巧：
- `services.local_openai_provider` 模块对象直接替换为 `lib.model_adapter_lib.openai_provider`
- 所有 `from services.local_openai_provider import xxx` 拿到的就是 lib 模块本身
- `monkeypatch.setattr(provider_module, "OpenAI", FakeOpenAI)` 真的作用到 lib 生产代码
- 100% 兼容 import / monkeypatch / 属性访问

迁移路径：
- 旧：from services.local_openai_provider import LocalOpenAIProvider
- 新：from lib.model_adapter_lib import LocalOpenAIProvider
"""
import sys as _sys
from lib.model_adapter_lib import openai_provider as _real_module

# 把本模块对象整个替换为 lib 模块，所有访问透明指向 lib 真实代码
_sys.modules[__name__] = _real_module
