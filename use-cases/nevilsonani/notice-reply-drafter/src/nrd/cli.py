from __future__ import annotations

import os
from pathlib import Path

import typer

app = typer.Typer(help="GST notice reply drafter - built ON SuperDocs.",
                  no_args_is_help=True, pretty_exceptions_enable=False)

ROOT = Path(__file__).resolve().parent.parent.parent


def _load_env() -> None:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8-sig").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


@app.command()
def run(case: Path = typer.Option(ROOT / "case", help="case directory"),
        out: Path = typer.Option(ROOT / "out", help="output directory"),
        auto_approve: bool = typer.Option(False, help="machine mode"),
        budget: int = typer.Option(0, help="op budget override"),
        skip_verify: bool = typer.Option(False)) -> None:
    """Draft the reply, gate the changes, export, verify completeness."""
    _load_env()
    from .build import run_build
    from .completeness import print_report, verify

    report = run_build(case, out, auto_approve=auto_approve, budget=budget or None)
    if not skip_verify:
        result = verify(Path(report["exports"][0]), case)
        print()
        print_report(result)
        if not result["ok"]:
            raise typer.Exit(2)


@app.command()
def verify_doc(md_file: Path, case: Path = typer.Option(ROOT / "case")) -> None:
    """Re-run the completeness check on an exported reply."""
    from .completeness import print_report, verify

    result = verify(md_file, case)
    print_report(result)
    if not result["ok"]:
        raise typer.Exit(2)


if __name__ == "__main__":
    app()
