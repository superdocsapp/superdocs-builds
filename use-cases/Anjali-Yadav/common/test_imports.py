from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


def load_local_module(module_name: str, path: Path, dependencies: dict[str, Path] | None = None) -> ModuleType:
    """Load a standalone build module without sharing its generic module names."""
    saved: dict[str, ModuleType | None] = {}
    dependency_modules = dependencies or {}

    for name, dependency_path in dependency_modules.items():
        saved[name] = sys.modules.get(name)
        sys.modules.pop(name, None)
        dependency_spec = importlib.util.spec_from_file_location(name, dependency_path)
        if dependency_spec is None or dependency_spec.loader is None:
            raise ImportError(f"Cannot load {name} from {dependency_path}")
        dependency_module = importlib.util.module_from_spec(dependency_spec)
        sys.modules[name] = dependency_module
        dependency_spec.loader.exec_module(dependency_module)

    saved[module_name] = sys.modules.get(module_name)
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {module_name} from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(module_name, None)
        for name, previous in saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous
    return module
