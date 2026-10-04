"""Client folder isolation — a client's files never leave their Dropbox root."""


def normalize_dropbox_path(path: str) -> str:
    cleaned = (path or "").strip().replace("\\", "/")
    if not cleaned.startswith("/"):
        cleaned = "/" + cleaned
    if len(cleaned) > 1:
        cleaned = cleaned.rstrip("/")
    return cleaned


def path_is_under(path: str, root: str) -> bool:
    """True if path is the root itself or a descendant of it."""
    p = normalize_dropbox_path(path)
    r = normalize_dropbox_path(root)
    return p == r or p.startswith(r + "/")
