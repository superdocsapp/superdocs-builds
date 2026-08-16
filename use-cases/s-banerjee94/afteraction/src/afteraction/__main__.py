"""`python -m afteraction …`

The console script installed by pip lands in the interpreter's Scripts directory,
which is not always on PATH — notably for a per-user install on Windows. This entry
point works regardless, so the documented command never depends on how pip was run.
"""

from .cli import app

if __name__ == "__main__":
    app()
