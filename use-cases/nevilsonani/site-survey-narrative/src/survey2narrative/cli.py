from __future__ import annotations

import os
from pathlib import Path

import typer

app = typer.Typer(help="Site Survey to Design Narrative - built ON SuperDocs.",
                  no_args_is_help=True, pretty_exceptions_enable=False)

ROOT = Path(__file__).resolve().parent.parent.parent


def _load_env() -> None:
    env = ROOT / ".env"
    if env.exists():
        # utf-8-sig: tolerate the BOM that Windows editors and PowerShell add
        for line in env.read_text(encoding="utf-8-sig").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


@app.command()
def run(bundle: Path = typer.Option(ROOT / "bundle", help="survey bundle directory"),
        out: Path = typer.Option(ROOT / "out", help="output directory"),
        max_photos: int = typer.Option(12, help="small-sample mode: cap uploads"),
        auto_approve: bool = typer.Option(False, help="machine mode: approve every change"),
        budget: int = typer.Option(0, help="op budget override (0 = S2N_OP_BUDGET)"),
        skip_verify: bool = typer.Option(False, help="skip the grounding check")) -> None:
    """Upload the bundle, draft the narrative, gate the changes, export, verify."""
    _load_env()
    from .build import run_build
    from .grounding import print_report, verify

    report = run_build(bundle, out, max_photos=max_photos,
                       auto_approve=auto_approve, budget=budget or None)
    if not skip_verify:
        md = Path(report["exports"][0])
        result = verify(md, bundle)
        print()
        print_report(result)
        if not result["ok"]:
            raise typer.Exit(2)


@app.command()
def verify_doc(md_file: Path,
               bundle: Path = typer.Option(ROOT / "bundle")) -> None:
    """Re-run the grounding check on an exported markdown narrative."""
    from .grounding import print_report, verify

    result = verify(md_file, bundle)
    print_report(result)
    if not result["ok"]:
        raise typer.Exit(2)


if __name__ == "__main__":
    app()
