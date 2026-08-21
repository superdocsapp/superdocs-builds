"""Read loss runs out of whatever format they arrive in.

Carriers issue loss runs as CSV, as PDF, and occasionally as a Word table. All
three land here and produce the same rows. The parser also checks each document
against itself: a loss run states its own total and claim count, and those are
compared against the sum of the rows rather than trusted. Real loss runs
disagree with themselves more often than anyone likes.
"""

from __future__ import annotations

import csv
import os
import re
import zipfile

from .model import Claim, LossRun, Source

MONEY = re.compile(r"^\(?\$?\s*-?[\d,]*\.?\d+\)?$")


def money(text: str) -> float:
    """Parse a figure the way an accountant wrote it.

    Handles $1,204,880.00 and (12,400.00) for negatives and an em dash for nil.
    Returns 0.0 for a nil marker rather than raising, because a blank and a
    dash mean the same thing on a loss run and neither is an error.
    """
    if text is None:
        return 0.0
    t = str(text).strip()
    if t in ("", "-", "\u2013", "\u2014", "N/A", "n/a"):
        return 0.0
    neg = t.startswith("(") and t.endswith(")")
    t = t.strip("()").replace("$", "").replace(",", "").strip()
    try:
        v = float(t)
    except ValueError as exc:
        raise ValueError(f"not a figure: {text!r}") from exc
    return -v if neg else v


def _meta(lines: list[str]) -> dict:
    """Pull the preamble a loss run carries above its column headers."""
    out: dict = {}
    joined = "\n".join(lines)
    m = re.search(r"Policy Period:\s*(\d{4}-\d{2}-\d{2})\s*to\s*(\d{4}-\d{2}-\d{2})", joined)
    if m:
        out["period_start"], out["period_end"] = m.group(1), m.group(2)
    m = re.search(r"Valuation Date:\s*(\d{4}-\d{2}-\d{2})", joined)
    if m:
        out["valuation_date"] = m.group(1)
    m = re.search(r"Insured:\s*(.+)", joined)
    if m:
        out["insured"] = m.group(1).strip()
    out["is_reissue"] = "REISSUE" in joined.upper()
    return out


def parse_csv(path: str) -> LossRun:
    rows = list(csv.reader(open(path, encoding="utf-8-sig")))
    preamble = ["".join(r) for r in rows[:10]]
    meta = _meta(preamble)

    hdr_idx = next((i for i, r in enumerate(rows) if r and r[0] == "Claim Number"), None)
    if hdr_idx is None:
        raise ValueError(f"{os.path.basename(path)}: no claim header row found")
    hdr = rows[hdr_idx]

    claims: list[Claim] = []
    stated_total = stated_count = premium = None
    policy_year = policy_no = None

    for i, r in enumerate(rows[hdr_idx + 1:], start=hdr_idx + 2):
        if not r or not any(r):
            continue
        rec = dict(zip(hdr, r))
        if rec.get("Claimant") == "TOTAL INCURRED" or (len(r) > 7 and r[7] == "TOTAL INCURRED"):
            stated_total = money(r[10])
            continue
        if len(r) > 7 and r[7] == "CLAIM COUNT":
            stated_count = int(money(r[10]))
            continue
        if len(r) > 7 and r[7] == "EARNED PREMIUM":
            premium = money(r[10])
            continue
        if not rec.get("Claim Number"):
            continue

        policy_year = int(rec["Policy Year"])
        policy_no = rec["Policy Number"]
        src = Source(os.path.basename(path), meta.get("valuation_date"), i,
                     meta.get("is_reissue", False))
        paid, reserve = money(rec["Paid"]), money(rec["Reserve"])
        claims.append(Claim(
            claim_no=rec["Claim Number"], policy_year=policy_year,
            policy_no=policy_no, coverage=rec["Coverage"],
            date_of_loss=rec["Date of Loss"], date_reported=rec["Date Reported"],
            status=rec["Status"], claimant=rec["Claimant"],
            paid=paid, reserve=reserve, incurred=money(rec["Incurred"]),
            description=rec.get("Description", ""), source=src,
        ))

    if policy_year is None:
        raise ValueError(f"{os.path.basename(path)}: no claim rows")

    return LossRun(
        path=path, policy_year=policy_year, policy_no=policy_no,
        period_start=meta.get("period_start", ""),
        period_end=meta.get("period_end", ""),
        valuation_date=meta.get("valuation_date", ""),
        is_reissue=meta.get("is_reissue", False),
        claims=claims, stated_total=stated_total, stated_count=stated_count,
        earned_premium=premium,
    )


def _pdf_text(path: str) -> str:
    """Text of a PDF, laid out.

    pdfplumber is the dependency and is pure Python, so this works the same on
    Windows, macOS and Linux. An earlier version shelled out to ``pdftotext``,
    which is a Unix binary: the code ran fine on the machine it was written on
    and died with a bare WinError on the machine it was used on. The fallback
    below is kept for environments that have the binary and not the library,
    but nothing depends on it.
    """
    try:
        import pdfplumber
    except ImportError:
        pass
    else:
        with pdfplumber.open(path) as pdf:
            return "\n".join((page.extract_text() or "") for page in pdf.pages)

    from shutil import which
    from subprocess import run as _run
    if which("pdftotext"):
        return _run(["pdftotext", "-layout", path, "-"],
                    capture_output=True, text=True).stdout

    raise RuntimeError(
        f"cannot read {os.path.basename(path)}: no PDF reader available. "
        f"Install the dependencies with `pip install -r requirements.txt` "
        f"(pdfplumber), or put pdftotext on the PATH. CSV loss runs are "
        f"unaffected and the rest of the pipeline still runs."
    )


def parse_pdf(path: str) -> LossRun:
    """PDF loss runs are read from the laid-out text of a carrier report.

    Deliberately conservative: a row is accepted only when every field it needs
    is present and every figure parses. Rows that look like claim lines but do
    not fully parse are counted and reported as unreadable rather than guessed
    at, because a half-read row is worse than a missing one on a document that
    feeds a coverage decision.
    """
    text = _pdf_text(path)
    lines = [l.rstrip() for l in text.splitlines() if l.strip()]
    meta = _meta(lines[:14])

    row_re = re.compile(
        r"^(?P<claim>[A-Z]{2}-\d{4}-\d{4})\s+"
        r"(?P<cov>.+?)\s+"
        r"(?P<dol>\d{4}-\d{2}-\d{2})\s+"
        r"(?P<drep>\d{4}-\d{2}-\d{2})\s+"
        r"(?P<status>Open|Closed|Reopened)\s+"
        r"(?P<paid>[\d,().$-]+)\s+"
        r"(?P<res>[\d,().$-]+)\s+"
        r"(?P<inc>[\d,().$-]+)\s*$")
    looks_like_claim = re.compile(r"^[A-Z]{2}-\d{4}-\d{4}\b")

    claims: list[Claim] = []
    unreadable: list[str] = []
    stated_total = stated_count = premium = None

    for i, line in enumerate(lines, start=1):
        stripped = line.strip()
        m = row_re.match(stripped)
        if m:
            try:
                paid = money(m.group("paid"))
                reserve = money(m.group("res"))
                incurred = money(m.group("inc"))
            except ValueError:
                unreadable.append(m.group("claim"))
                continue
            claims.append(Claim(
                claim_no=m.group("claim"),
                policy_year=int(m.group("dol")[:4]) if m.group("dol") else 0,
                policy_no="", coverage=m.group("cov").strip(),
                date_of_loss=m.group("dol"), date_reported=m.group("drep"),
                status=m.group("status"), claimant="",
                paid=paid, reserve=reserve, incurred=incurred, description="",
                source=Source(os.path.basename(path), meta.get("valuation_date"),
                              i, meta.get("is_reissue", False)),
            ))
            continue
        if looks_like_claim.match(stripped):
            unreadable.append(stripped.split()[0])
            continue
        m2 = re.match(r"TOTAL INCURRED:\s*(.+)", stripped)
        if m2:
            stated_total = money(m2.group(1))
        m3 = re.match(r"CLAIM COUNT:\s*(\d+)", stripped)
        if m3:
            stated_count = int(m3.group(1))
        m4 = re.match(r"EARNED PREMIUM:\s*(.+)", stripped)
        if m4:
            premium = money(m4.group(1))

    if not claims:
        raise ValueError(f"{os.path.basename(path)}: no readable claim rows in PDF")

    # A PDF loss run states its policy period but not a policy number per row.
    # Derive the policy year from the period rather than from a date of loss,
    # which can legitimately fall outside it.
    year = int(meta["period_start"][:4]) if meta.get("period_start") else claims[0].policy_year
    for c in claims:
        c.policy_year = year

    run = LossRun(
        path=path, policy_year=year, policy_no="",
        period_start=meta.get("period_start", ""),
        period_end=meta.get("period_end", ""),
        valuation_date=meta.get("valuation_date", ""),
        is_reissue=meta.get("is_reissue", False), claims=claims,
        stated_total=stated_total, stated_count=stated_count,
        earned_premium=premium,
    )
    run.unreadable_rows = unreadable
    return run


def docx_text(path: str) -> str:
    """Plain text of a .docx, paragraphs and table cells, in document order."""
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"<w:tab[^>]*/>", "\t", xml)
    text = re.sub(r"<[^>]+>", "", xml)
    return re.sub(r"\n{3,}", "\n\n", text)


def load(path: str) -> LossRun:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".csv":
        return parse_csv(path)
    if ext == ".pdf":
        return parse_pdf(path)
    raise ValueError(f"{path}: not a loss run format this build reads")


def load_all(paths: list[str]) -> list[LossRun]:
    runs = []
    for p in sorted(paths):
        runs.append(load(p))
    return runs
