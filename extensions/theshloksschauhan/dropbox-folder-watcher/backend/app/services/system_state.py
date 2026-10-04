"""Runtime system toggles (in-memory; survives within a single process)."""

_global_preview_mode: bool = False


def get_global_preview_mode() -> bool:
    return _global_preview_mode


def set_global_preview_mode(enabled: bool) -> None:
    global _global_preview_mode
    _global_preview_mode = enabled
