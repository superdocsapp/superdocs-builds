"""Apply the two deliberately small, repeatable SDK metadata patches.

OpenAPI Generator owns the implementation.  These patches only replace its
placeholder publisher metadata, so package users see the real SuperDocs source
repository and the SDK version tracks the input OpenAPI document.  Fail loudly
if a generator upgrade changes either file's expected shape.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
REPOSITORY = "https://github.com/superdocsapp/superdocs-builds"


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise RuntimeError(f"expected exactly one {old!r} in {path}")
    path.write_text(text.replace(old, new), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", required=True)
    args = parser.parse_args()
    spec_bytes = Path(args.spec).read_bytes()
    version = json.loads(spec_bytes)["info"]["version"]
    # Published specs have historically changed without bumping info.version.
    # Registry versions must still be unique on a scheduled release.
    if os.environ.get("RELEASE_VERSION_SUFFIX") == "1":
        fingerprint = hashlib.sha256(spec_bytes).hexdigest()[:8]
        python_version = f"{version}.post{int(fingerprint, 16)}"
        typescript_version = f"{version}-superdocs.{fingerprint}"
    else:
        python_version = typescript_version = version

    setup = ROOT / "clients/python/setup.py"
    replace_once(setup, 'VERSION = "1.0.0"', f'VERSION = "{python_version}"')
    replace_once(setup, 'url=""', f'url="{REPOSITORY}"')

    pyproject = ROOT / "clients/python/pyproject.toml"
    replace_once(pyproject, 'version = "1.0.0"', f'version = "{python_version}"')
    replace_once(pyproject, 'repository = "https://github.com/GIT_USER_ID/GIT_REPO_ID"', f'repository = "{REPOSITORY}"')

    package = ROOT / "clients/typescript/package.json"
    data = json.loads(package.read_text(encoding="utf-8"))
    data["name"] = "@superdocs/superdocs-client"
    data["version"] = typescript_version
    data["repository"] = {"type": "git", "url": f"git+{REPOSITORY}.git"}
    data["homepage"] = REPOSITORY
    data["bugs"] = {"url": f"{REPOSITORY}/issues"}
    package.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"patched generated package metadata for API version {version}")


if __name__ == "__main__":
    main()
