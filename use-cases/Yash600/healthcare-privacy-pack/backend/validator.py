"""
validator.py -- DEPRECATED as a standalone module.

Validation logic now lives directly in main.py's POST /workspaces/{id}/validate
(function `validate_workspace`), because it no longer needs a SuperDocsClient
at all -- every section's full content is persisted in Postgres now (see the
"store everything in the DB" schema decision), so the independent re-check
runs entirely against our own data instead of re-fetching from SuperDocs.
See main.py for the five checks (HAS_PARENT_POLICY, SECTION_EXISTS,
HASH_MATCH, MISSING_REFERENCE, LOW_CONFIDENCE_UNREVIEWED, plus a best-effort
CONTRADICTION heuristic) and Finding creation.

Kept as a stub (rather than deleted, which this sandbox would not permit)
so nothing that used to `import validator` breaks outright.
"""

def run_validation(*args, **kwargs):
    raise RuntimeError(
        "validator.py has been superseded by main.validate_workspace(workspace_id) -- "
        "see main.py, this module no longer does anything."
    )


def main() -> int:
    print("validator.py has been superseded by POST /workspaces/{id}/validate in main.py.")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
