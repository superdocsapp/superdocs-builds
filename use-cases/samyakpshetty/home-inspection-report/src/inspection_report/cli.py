"""Command line: build the sample report, and verify what came out.

``demo`` runs the whole thing on the deterministic fake — no key, no cost — and writes real
files into a mounted directory, because anything a ``--rm`` container writes outside a
mounted path is destroyed when it exits.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import click

from inspection_report import sample
from inspection_report.domain import catalogue
from inspection_report.logging import get_logger, setup_logging
from inspection_report.render import pipeline
from inspection_report.superdocs.base import SuperDocsClient
from inspection_report.superdocs.fake import FakeSuperDocsClient
from inspection_report.superdocs.live import LiveSuperDocsClient
from inspection_report.templates import binding, registry
from inspection_report.verify import exports as verify_exports

_log = get_logger("inspection_report.cli")

EXPORT_DIR = Path(os.environ.get("EXPORT_DIR", "exports"))
TEMPLATE_DIR = Path(os.environ.get("TEMPLATE_DIR", "templates"))


def build_client() -> SuperDocsClient:
    """The provider seam. Defaults to the fake, which is why no key is ever required."""
    if os.environ.get("PROVIDER", "fake").lower() == "live":
        return LiveSuperDocsClient(api_key=os.environ.get("SUPERDOCS_API_KEY", ""))
    return FakeSuperDocsClient()


@click.group()
def main() -> None:
    """A structured home-inspection report builder, built on SuperDocs."""
    setup_logging(os.environ.get("LOG_FORMAT", "console"))


@main.command()
@click.option("--template", default="buyer_summary", help="Report format to use.")
@click.option("--polish/--no-polish", default=True, help="Run the AI rewrite pass.")
@click.option(
    "--model-tier",
    default="core",
    type=click.Choice(["core", "turbo", "pro", "max"]),
    help="Precision/speed. Never hard-coded — see the README.",
)
def demo(template: str, polish: bool, model_tier: str) -> None:
    """Build the sample report end to end and verify the exported files."""
    inspection = sample.sample_inspection()
    photo_data = sample.sample_photo_data()
    template_path = TEMPLATE_DIR / f"{template}.docx"
    if not template_path.exists():
        available = sorted(p.stem for p in TEMPLATE_DIR.glob("*.docx"))
        raise click.ClickException(
            f"no report format called {template!r}. Available: {available}. "
            f"Formats live in {TEMPLATE_DIR}/."
        )

    client = build_client()
    provider = os.environ.get("PROVIDER", "fake")
    click.echo(
        f"Building {inspection.property.one_line()} — "
        f"{len(inspection.findings)} findings, {inspection.photo_count()} photographs, "
        f"provider={provider}, format={template}"
    )

    # The format is registered with SuperDocs and the report is built from the document
    # SuperDocs hands back, not from the local file. The local copy is the fallback only.
    report_format = registry.ensure_registered(client, TEMPLATE_DIR)[template]
    template_html, from_service = registry.materialise(
        client, report_format, session_id=f"format-{report_format.content_sha[:8]}"
    )
    click.echo(
        f"  format: '{report_format.name}' — skeleton "
        + ("loaded from SuperDocs" if from_service else "served from the local copy")
    )

    result = pipeline.build(
        inspection,
        template_html,
        photo_data,
        client,
        session_id=f"inspection-{inspection.id.hex[:12]}",
        polish=polish,
        model_tier=model_tier,
        # The in-memory implementation applies approvals synchronously; only the live
        # service needs time to settle before an export reflects them.
        settle_s=pipeline.SETTLE_AFTER_APPROVE_S if provider == "live" else 0.0,
    )

    click.echo(f"  photographs: {result.photos_uploaded} uploaded, {result.photos_reused} reused")
    if polish:
        approved = sum(1 for p in result.proposals if p.approved)
        click.echo(
            f"  rewrites: {len(result.proposals)} proposed, {approved} approved, "
            f"{result.rail_refusals} refused by the language rail"
        )
        for p in result.proposals:
            if p.refused_by_rail:
                click.echo(f"    refused — {p.verdict.summary()}")
        if result.ops_remaining is not None:
            click.echo(
                f"  operations: {result.ops_charged} charged, {result.ops_remaining} remaining"
            )

    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    # What the report is held to depends on what the format promises: the repair-priority
    # list shows no photograph in its worked example, so photographs are not expected in it.
    carries_photos = binding.carries_photos(template_html, [s.name for s in catalogue.systems()])
    ok = True
    for fmt, export in result.exports.items():
        path = EXPORT_DIR / export.filename
        path.write_bytes(export.content)
        click.echo(f"  wrote {path} ({len(export.content):,} bytes)")
        report = verify_exports.verify(
            data=export.content,
            fmt=fmt,
            inspection=inspection,
            expect_photos=carries_photos,
        )
        click.echo(report.render())
        ok = ok and report.passed

    client.close()
    click.echo("\nAll checks passed." if ok else "\nSome checks FAILED.")
    if not ok:
        sys.exit(1)


@main.command()
@click.option("--template", default="buyer_summary")
def verify(template: str) -> None:
    """Re-verify the files already in the export directory."""
    inspection = sample.sample_inspection()
    for finding in inspection.findings:
        for photo in finding.photos:
            photo.remote_url = f"local://{photo.sha256}"  # presence, not fetchability

    found = sorted(EXPORT_DIR.glob("*.pdf")) + sorted(EXPORT_DIR.glob("*.docx"))
    if not found:
        raise click.ClickException(f"nothing to verify in {EXPORT_DIR}/. Run `make demo` first.")
    ok = True
    for path in found:
        report = verify_exports.verify(
            data=path.read_bytes(), fmt=path.suffix.lstrip("."), inspection=inspection
        )
        click.echo(f"{path.name}")
        click.echo(report.render())
        ok = ok and report.passed
    if not ok:
        sys.exit(1)


@main.command()
def formats() -> None:
    """List the report formats this build ships."""
    for path in sorted(TEMPLATE_DIR.glob("*.docx")):
        click.echo(f"  {path.stem}")


@main.command()
@click.option("--reset", is_flag=True, help="Remove seeded inspections first.")
def seed(reset: bool) -> None:
    """Put the sample property into the database, so the interface opens onto real data.

    `docker compose up` otherwise gives you an empty list and a New-inspection button, which
    is a poor first thirty seconds for anyone opening this to look at it. This writes the
    same eight findings and eight photographs the demo uses, through the same photo pipeline
    the browser uses — size-checked, decoded, EXIF stripped — so what you see is what the
    application actually stores.
    """
    from inspection_report.photos.pipeline import clean
    from inspection_report.store import db

    inspection = sample.sample_inspection()
    photo_data = sample.sample_photo_data()

    with db.connect() as conn:
        db.apply_schema(conn)
        if reset:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM inspections WHERE address_line = %s",
                    (inspection.property.address_line,),
                )
            conn.commit()
            click.echo(f"  removed existing {inspection.property.address_line!r} inspections")

        db.save_inspection(conn, inspection, prune=True)
        stored = 0
        for finding in inspection.findings:
            for position, photo in enumerate(finding.photos):
                raw = photo_data.get(photo.filename)
                if raw is None:
                    continue
                cleaned = clean(raw, filename=photo.filename)
                db.save_photo(
                    conn,
                    finding_id=finding.id,
                    photo=photo,
                    data=cleaned.data,
                    thumbnail=cleaned.thumbnail,
                    position=position,
                )
                stored += 1

    click.echo(
        f"Seeded {inspection.property.one_line()} — "
        f"{len(inspection.findings)} findings, {stored} photographs."
    )
    click.echo("Open http://localhost:5174 and it is the first row.")


if __name__ == "__main__":
    main()
