from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import typer

from soc2_index.ingest import IngestError
from soc2_index.pipeline import SuperDocsRunError, UsageError, run
from soc2_index.validate import ValidationError

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="SOC 2 evidence-index — fire-and-forget SuperDocs driver",
)


@app.command("run")
def run_cmd(
    evidence: Path = typer.Option(..., "--evidence", exists=True, file_okay=False, dir_okay=True),
    out: Path = typer.Option(..., "--out"),
    from_run: Optional[Path] = typer.Option(None, "--from"),
    catalog: Optional[Path] = typer.Option(None, "--catalog", exists=True),
    session: str = typer.Option("cedar-harbor-idx-v1", "--session"),
    org: str = typer.Option("Cedar Harbor Labs", "--org"),
    period: str = typer.Option("2025-01-01/2025-12-31", "--period"),
    generated_at: Optional[str] = typer.Option(None, "--generated-at"),
    max_ops: int = typer.Option(15, "--max-ops"),
    wait_timeout: int = typer.Option(300, "--wait-timeout"),
) -> None:
    """Map a folder and print the index through SuperDocs (approve + export included)."""
    logging.basicConfig(level=logging.ERROR)
    sample = catalog is None
    try:
        run(
            evidence=evidence,
            out=out,
            from_run=from_run,
            catalog=catalog,
            sample=sample,
            org=org,
            period=period,
            generated_at=generated_at,
            session=session,
            max_ops=max_ops,
            wait_timeout=wait_timeout,
        )
    except UsageError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(exc.code) from exc
    except IngestError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(exc.code) from exc
    except ValidationError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(exc.code) from exc
    except SuperDocsRunError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(exc.code) from exc


def main() -> None:
    app()


if __name__ == "__main__":
    main()
