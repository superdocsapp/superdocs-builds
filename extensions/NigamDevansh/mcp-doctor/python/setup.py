"""Bundle the shared contract into distribution artifacts, never into source."""

from __future__ import annotations

import shutil
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py
from setuptools.command.sdist import sdist

ROOT = Path(__file__).resolve().parent
# In the repository the contract is a sibling of python/.  During the wheel
# build from an sdist that sibling does not exist, so use the copy carried in
# the sdist instead. This keeps both artifacts self-contained.
SHARED = ROOT.parent / "shared"
if not SHARED.is_dir():
    SHARED = ROOT / "src" / "mcp_doctor" / "shared"


def copy_shared(destination: Path) -> None:
    shutil.copytree(SHARED, destination / "mcp_doctor" / "shared", dirs_exist_ok=True)


class BuildPy(build_py):
    def run(self) -> None:
        super().run()
        copy_shared(Path(self.build_lib))


class SourceDist(sdist):
    def make_release_tree(self, base_dir: str, files: list[str]) -> None:
        super().make_release_tree(base_dir, files)
        copy_shared(Path(base_dir) / "src")


setup(cmdclass={"build_py": BuildPy, "sdist": SourceDist})
