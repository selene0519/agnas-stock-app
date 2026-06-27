"""MONE web app backend package.

Some legacy tests import the root Streamlit ``app.py`` as ``app`` while backend
tests import this package as ``app`` after putting ``mone-web-app/backend`` at
the front of ``sys.path``.  Keep backend package imports working, and lazily
delegate unknown top-level attributes to the root ``app.py`` for that mixed
test environment.
"""

from __future__ import annotations

import importlib.util
import importlib
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

_LEGACY_MODULE_NAME = "_mone_legacy_streamlit_app"
_LEGACY_MODULE: ModuleType | None = None
_BACKEND_SUBMODULES = {"main", "services", "engine", "db"}


def _load_legacy_streamlit_app() -> ModuleType:
    global _LEGACY_MODULE
    if _LEGACY_MODULE is not None:
        return _LEGACY_MODULE

    repo_root = Path(__file__).resolve().parents[3]
    app_path = repo_root / "app.py"
    spec = importlib.util.spec_from_file_location(_LEGACY_MODULE_NAME, app_path)
    if spec is None or spec.loader is None:
        raise AttributeError(f"Cannot load legacy app.py from {app_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[_LEGACY_MODULE_NAME] = module
    root_text = str(repo_root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
    spec.loader.exec_module(module)
    _LEGACY_MODULE = module
    return module


def __getattr__(name: str) -> Any:
    if name in _BACKEND_SUBMODULES:
        return importlib.import_module(f"{__name__}.{name}")
    module = _load_legacy_streamlit_app()
    try:
        return getattr(module, name)
    except AttributeError as exc:
        raise AttributeError(f"module 'app' has no attribute {name!r}") from exc


class _BackendAppModule(ModuleType):
    def __getattribute__(self, name: str) -> Any:
        if name == "__file__":
            return _load_legacy_streamlit_app().__file__
        return super().__getattribute__(name)

    def __setattr__(self, name: str, value: Any) -> None:
        legacy = _LEGACY_MODULE
        if legacy is not None and hasattr(legacy, name):
            setattr(legacy, name, value)
        super().__setattr__(name, value)

    def __delattr__(self, name: str) -> None:
        legacy = _LEGACY_MODULE
        if legacy is not None and hasattr(legacy, name):
            delattr(legacy, name)
        super().__delattr__(name)


sys.modules[__name__].__class__ = _BackendAppModule
