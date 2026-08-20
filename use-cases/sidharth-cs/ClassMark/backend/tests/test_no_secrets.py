"""Secret-leak regression scan: no real credentials anywhere in the
committed surface of classroom-app (source, .env.example, README, tests).

Only pattern matches are reported — never the values.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # classroom-app/

# Real-key fingerprints: SuperDocs keys (sk_ + 32 hex), Google client ids
# (AIza...), PEM blocks, long hex blobs that look like secrets.
_SECRET_PATTERNS = [
    (re.compile(r"sk_[0-9a-f]{32}"), "SuperDocs API key (sk_ + 32 hex)"),
    (re.compile(r"AIza[0-9A-Za-z_\-]{20,}"), "Google OAuth client id (AIza...)"),
    (re.compile(r"-----BEGIN [A-Z ]+-----"), "PEM private key block"),
    (re.compile(r"session_secret[=:][^#\n]{16,}"), "session secret value"),
]


def _scan_file(path: Path, findings: list[str]) -> None:
    try:
        text = path.read_text(errors="replace")
    except (OSError, UnicodeError):
        return
    for pattern, label in _SECRET_PATTERNS:
        if pattern.search(text):
            findings.append(f"{path.relative_to(ROOT)}: {label}")


def test_no_real_credentials_in_committed_surface():
    findings: list[str] = []
    # Everything committed: source, tests, example env, README, Makefile.
    # .env itself is excluded — it is gitignored and lives outside the
    # committed surface by design.
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT)
        if any(
            part in {".venv", "node_modules", "dist", ".pytest_cache", "__pycache__"}
            for part in rel.parts
        ):
            continue
        if path.name == ".env":
            continue
        _scan_file(path, findings)
    assert findings == [], f"secret-like values found: {findings}"


def test_env_example_contains_no_credentials():
    text = (ROOT / ".env.example").read_text()
    assert "sk_" not in text
    assert "AIza" not in text
    for line in text.splitlines():
        if line.startswith(("GOOGLE_CLIENT_SECRET=", "SUPERDOCS_API_KEY=", "SESSION_SECRET=")):
            assert line.split("=", 1)[1] == "", f"credential value in .env.example: {line.split('=')[0]}"


def test_dotenv_is_gitignored():
    gitignore = (ROOT / ".gitignore").read_text()
    assert ".env" in gitignore
