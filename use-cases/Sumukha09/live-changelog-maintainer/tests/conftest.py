"""Pytest configuration.

Adds the project root to sys.path so `import changelog_maintainer` works
without installing the package.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
