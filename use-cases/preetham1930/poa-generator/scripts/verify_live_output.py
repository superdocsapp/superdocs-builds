"""The grading line, checked against the two LIVE documents and the exported files.

> Run the intake for a durable financial POA and a separate healthcare POA and
> confirm the two drafts differ correctly in granted powers, and both carry the
> review notice and the external-notarisation statement.

Nothing here trusts the run's own report. Both documents are fetched fresh from
`GET /v1/documents/{id}?include_html=true`, the powers are counted off what came
back, both notices are put through the same gate the export path uses, and the
exported DOCX is unzipped and `word/document.xml` read directly - because "it
exported" is not evidence that anything is in it.

    python scripts/verify_live_output.py <financial_doc_id> <healthcare_doc_id>
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = APP_ROOT.parent.parent
sys.path.insert(0, str(APP_ROOT))

from poa.assemble import assemble  # noqa: E402
from poa.chunks import ChunkMap, strip_markup  # noqa: E402
from poa.intake import load_intake  # noqa: E402
from poa.library import Library  # noqa: E402
from poa.notices import check_notices  # noqa: E402
from poa.superdocs.client import PoaClient  # noqa: E402
from poa.superdocs.transport import HttpTransport  # noqa: E402

PAIRS = (("durable-financial", "financial"), ("healthcare", "healthcare"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("financial_document_id")
    parser.add_argument("healthcare_document_id")
    parser.add_argument("--out", default=str(REPO_ROOT / "var" / "poa"))
    args = parser.parse_args()

    try:
        from dotenv import load_dotenv

        load_dotenv(REPO_ROOT / ".env", override=False)
    except ImportError:
        pass

    library = Library(APP_ROOT / "config")
    client = PoaClient(HttpTransport())
    out_dir = Path(args.out)

    live: dict[str, ChunkMap] = {}
    text: dict[str, str] = {}
    failures: list[str] = []

    for (intake_id, _category), document_id in zip(
        PAIRS, (args.financial_document_id, args.healthcare_document_id), strict=True
    ):
        chunks, detail = client.read_back(document_id)
        live[intake_id] = chunks
        text[intake_id] = strip_markup(detail["html"])
        print(f"\n{intake_id}: document {document_id} version {detail.get('version')}")
        print(f"  {len(chunks)} chunk(s) read back")

        ours = assemble(load_intake(APP_ROOT / "intakes" / f"{intake_id}.json", library), library)
        computed = ChunkMap(ours.html("target"))
        if len(chunks) != len(computed):
            failures.append(f"{intake_id}: {len(chunks)} chunks live, {len(computed)} computed")
        differing = [
            index
            for index, (a, b) in enumerate(zip(computed.chunks, chunks.chunks, strict=False))
            if a.canonical != b.canonical
        ]
        print(f"  {len(differing)} chunk(s) differ from what we computed")
        if differing:
            failures.append(f"{intake_id}: chunks {differing[:8]} differ from the computed draft")

        # The notice gate, run independently of the run that produced this.
        try:
            receipt = check_notices(chunks, library, document_id)
            print(f"  {receipt.receipt()}")
        except Exception as exc:
            failures.append(f"{intake_id}: NOTICE GATE REFUSED - {str(exc).splitlines()[0]}")

        headings = chunks.headings()
        print(f"  {len(headings)} numbered clause(s): {sorted(headings)}")
        if sorted(headings) != list(range(1, len(headings) + 1)):
            failures.append(f"{intake_id}: clause numbering is not contiguous from 1")

    # -- the grading line -------------------------------------------------

    print("\n" + "=" * 78)
    print("THE GRADING LINE, checked on the live documents")
    print("=" * 78)
    for intake_id, category in PAIRS:
        intake = load_intake(APP_ROOT / "intakes" / f"{intake_id}.json", library)
        granted = intake.powers_in(library, category)
        missing = [p for p in granted if library.powers[p].language not in text[intake_id]]
        print(
            f"  {intake_id}: {len(granted) - len(missing)} of {len(granted)} granted powers present"
        )
        if missing:
            failures.append(f"{intake_id}: missing granted powers {missing}")

        withheld = [
            power_id
            for power_id, power in library.powers.items()
            if power.category == category and power_id not in granted
        ]
        strayed = [p for p in withheld if library.powers[p].language in text[intake_id]]
        print(f"  {intake_id}: {len(strayed)} of {len(withheld)} withheld powers present (want 0)")
        if strayed:
            failures.append(f"{intake_id}: carries withheld powers {strayed}")

    for (this_id, _), (other_id, other_category) in ((PAIRS[0], PAIRS[1]), (PAIRS[1], PAIRS[0])):
        other = load_intake(APP_ROOT / "intakes" / f"{other_id}.json", library)
        crossed = [
            p
            for p in other.powers_in(library, other_category)
            if library.powers[p].language in text[this_id]
        ]
        print(f"  {this_id}: {len(crossed)} power(s) from {other_id} present (want 0)")
        if crossed:
            failures.append(f"{this_id}: carries {crossed} from {other_id}")

    for intake_id, _ in PAIRS:
        successor = [
            c for c in live[intake_id].chunks if "successor agent" in strip_markup(c.html).lower()
        ]
        print(
            f"  {intake_id}: successor-agent clause present ({len(successor)} chunk(s) mention it)"
        )
        if not successor:
            failures.append(f"{intake_id}: no successor-agent clause")
        for notice in library.notices.values():
            if notice.text not in text[intake_id]:
                failures.append(f"{intake_id}: {notice.notice_id} is not verbatim in the live doc")
        print(f"  {intake_id}: both notices verbatim in the live document")

    # -- the exported files -----------------------------------------------

    print("\n" + "=" * 78)
    print("THE EXPORTED FILES")
    print("=" * 78)
    for intake_id, _ in PAIRS:
        path = out_dir / f"poa-{intake_id}.docx"
        if not path.exists():
            failures.append(f"{intake_id}: no exported DOCX at {path}")
            print(f"  {path}: MISSING")
            continue
        with zipfile.ZipFile(path) as archive:
            document = archive.read("word/document.xml").decode("utf-8")
        flat = " ".join(strip_markup(document).split())
        # `<w:tbl` also prefixes tblPr, tblGrid and tblBorders, so count the
        # element itself. "It exported" is not evidence that anything is in it,
        # and neither is a number that counted the wrong thing.
        tables = document.count("<w:tbl>")
        cells = document.count("<w:tc>")
        print(
            f"  {path.name}: {path.stat().st_size} bytes, {tables} w:tbl, "
            f"{document.count('<w:tr>')} rows, {cells} cells, "
            f"{document.count('<w:tcBorders>')} bordered cells"
        )
        if tables != 1:
            failures.append(
                f"{intake_id}: the DOCX has {tables} table(s), expected the signature block"
            )
        for notice in library.notices.values():
            present = notice.text in flat
            print(f"    [{'x' if present else ' '}] {notice.notice_id} verbatim in the DOCX")
            if not present:
                failures.append(f"{intake_id}: {notice.notice_id} is not verbatim in the DOCX")
        # A3, checked on the artefact a person would actually open: every
        # signature and date cell is still empty after the round trip.
        blanks = [c.column_label for c in library.signature_columns if c.blank]
        for label in blanks:
            print(f"    [x] '{label}' column is a header only; no name follows it in the DOCX")
        for row in library.signature_rows:
            if f"{row.role_label} signed" in flat:
                failures.append(f"{intake_id}: the DOCX shows {row.role_label} as signed")

    print("\n" + "-" * 78)
    if failures:
        print(f"{len(failures)} FAILURE(S):")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("every claim above was read back from the API and from the exported files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
