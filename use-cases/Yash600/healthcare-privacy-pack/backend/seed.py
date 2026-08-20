"""
seed.py -- DEPRECATED / REMOVED.

This project no longer ships a hardcoded demo policy pack. Every Workspace,
Document, and reference in the system now originates from a real human
upload through the UI (POST /workspaces, POST /documents/upload) followed
by an Analyze References run (POST /workspaces/{id}/analyze) -- see
main.py and README.md.

This file is kept as a stub (rather than deleted, which this environment's
sandbox would not permit) purely so nothing that used to `import seed`
breaks. It performs no action.
"""

def seed(*args, **kwargs) -> None:
    raise RuntimeError(
        "seed.py has been removed. There is no hardcoded demo pack anymore -- "
        "create a Workspace and upload real documents through the API/UI instead."
    )


if __name__ == "__main__":
    print(
        "seed.py has been removed. There is no hardcoded demo pack anymore -- "
        "create a Workspace and upload real documents through the API/UI instead. "
        "See README.md for the new upload-driven flow."
    )
