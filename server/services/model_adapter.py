"""
ModelAdapter — backward-compat shim (sys.modules alias)

实际实现已迁移至 server/lib/model_adapter_lib/adapter.py（W0 ADR-005，2026-05-28）。

本 shim 使用 `sys.modules` 别名技巧：
- `services.model_adapter` 模块对象直接替换为 `lib.model_adapter_lib.adapter`
- `monkeypatch.setattr(model_adapter, "_PROVIDER_BASE_CACHE", None)` 真的作用到 lib 生产代码
- 测试中所有针对 `services.model_adapter` 的 monkeypatch / 属性赋值 100% 兼容

迁移路径：
- 旧：from services.model_adapter import ModelAdapter, ChatResult
- 新：from lib.model_adapter_lib import ModelAdapter, ChatResult
"""
import sys as _sys
from lib.model_adapter_lib import adapter as _real_module

# 把本模块对象整个替换为 lib 模块
_sys.modules[__name__] = _real_module
