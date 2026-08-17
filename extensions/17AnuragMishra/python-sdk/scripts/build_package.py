from __future__ import annotations

import base64
import csv
import hashlib
import io
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAME = "superdocs_python"
DIST_NAME = "superdocs-python"
VERSION = "0.2.0"
DIST = ROOT / "dist"
PACKAGE = ROOT / "src" / "superdocs_sdk"


def package_files() -> list[Path]:
    return sorted([*PACKAGE.rglob("*.py"), PACKAGE / "py.typed"])


def hash_record(data: bytes) -> tuple[str, str]:
    digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode("ascii")
    return f"sha256={digest}", str(len(data))


def main() -> None:
    DIST.mkdir(exist_ok=True)
    build_sdist()
    build_wheel()
    print(f"Built packages in {DIST}")


def build_sdist() -> None:
    target = DIST / f"{DIST_NAME}-{VERSION}.tar.gz"
    with tarfile.open(target, "w:gz") as tar:
        paths = [ROOT / "README.md", ROOT / "CHANGELOG.md", ROOT / "pyproject.toml", *package_files()]
        for path in paths:
            tar.add(path, arcname=f"{DIST_NAME}-{VERSION}/{path.relative_to(ROOT)}")


def build_wheel() -> None:
    dist_info = f"{NAME}-{VERSION}.dist-info"
    wheel_name = DIST / f"{NAME}-{VERSION}-py3-none-any.whl"
    entries: list[tuple[str, bytes]] = []
    for path in package_files():
        arcname = str(path.relative_to(ROOT / "src")).replace("\\", "/")
        entries.append((arcname, path.read_bytes()))
    entries.append((f"{dist_info}/METADATA", metadata().encode("utf-8")))
    entries.append((f"{dist_info}/WHEEL", wheel().encode("utf-8")))
    record_rows: list[list[str]] = []
    for arcname, data in entries:
        digest, size = hash_record(data)
        record_rows.append([arcname, digest, size])
    record_rows.append([f"{dist_info}/RECORD", "", ""])
    record_buffer = io.StringIO()
    csv.writer(record_buffer, lineterminator="\n").writerows(record_rows)
    entries.append((f"{dist_info}/RECORD", record_buffer.getvalue().encode("utf-8")))
    with zipfile.ZipFile(wheel_name, "w", compression=zipfile.ZIP_DEFLATED) as wheel_file:
        for arcname, data in entries:
            wheel_file.writestr(arcname, data)


def metadata() -> str:
    return "\n".join(
        [
            "Metadata-Version: 2.3",
            f"Name: {DIST_NAME}",
            f"Version: {VERSION}",
            "Summary: Typed Python SDK for the SuperDocs API.",
            "Requires-Python: >=3.12",
            "Requires-Dist: pydantic>=2.7",
            "Requires-Dist: httpx>=0.27",
            "",
        ]
    )


def wheel() -> str:
    return (
        "Wheel-Version: 1.0\n"
        "Generator: superdocs-sdk-stdlib-builder\n"
        "Root-Is-Purelib: true\n"
        "Tag: py3-none-any\n"
    )


if __name__ == "__main__":
    main()
