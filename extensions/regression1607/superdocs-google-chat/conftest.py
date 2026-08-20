import sys
from pathlib import Path

# Make the project root importable so `app` and `tests.fakes` resolve in CI and locally.
sys.path.insert(0, str(Path(__file__).resolve().parent))
