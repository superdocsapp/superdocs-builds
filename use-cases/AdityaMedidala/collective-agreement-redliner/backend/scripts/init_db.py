import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import Base, engine
from app import models  # noqa: F401 — registers models on Base.metadata


def main():
    Base.metadata.create_all(engine)
    print("✓ redliner.db tables ready")


if __name__ == "__main__":
    main()
