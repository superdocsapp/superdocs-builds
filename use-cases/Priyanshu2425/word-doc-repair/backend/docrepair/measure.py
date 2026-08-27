"""Run the corpus and write down what happened, method first.

    python3 -m docrepair.measure            # print the tables
    python3 -m docrepair.measure --write    # and rewrite corpus/measurements.json

The JSON is written by this module and never by hand, and a test fails if it and
the code disagree. That is not tidiness: a recovery rate typed into a README is
a claim nobody is holding, and this build's whole argument is that a claim
nobody is holding stops being true.

**What the verdicts mean.** Every fixture gets exactly one:

- `full` — the rebuilt file opens and carries every word of the original.
- `partial` — it opens and carries some of them. On `lossy` damage this is the
  correct answer; on `lossless` damage it is a defect, and the tables separate
  the two so nobody has to take that on trust.
- `refused` — the tool reported that it could not repair the file. On `fatal`
  damage this is the correct answer.
- `empty-success` — it reported success and returned none of the words. This is
  the output this build exists to prevent, and the count is expected to be zero.
- `crashed` — the repair raised. Also expected to be zero, and recorded
  separately because a crash and a refusal are not the same event.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from . import corpus
from .corpus import FATAL, LOSSLESS, LOSSY
from .engine import repair

OUT = Path(__file__).resolve().parents[2] / "corpus" / "measurements.json"

FULL, PARTIAL, REFUSED, EMPTY_SUCCESS, CRASHED = (
    "full", "partial", "refused", "empty-success", "crashed")

#: What each kind of damage allows. Written down before the run rather than read
#: off it -- a bar that moves to wherever the results landed is not a bar.
#:
#: `lossy` allows a refusal because damage that took the body with it leaves
#: nothing to return, and `fatal` allows a partial because a document whose body
#: was emptied can still have a photograph or a header in the archive, and
#: handing those back is recovery rather than invention. Neither kind allows an
#: empty success or a crash under any circumstances.
ACCEPTABLE = {
    LOSSLESS: {FULL},
    LOSSY: {FULL, PARTIAL, REFUSED},
    FATAL: {REFUSED, PARTIAL},
}


def _structure_lost(truth: dict, got: dict) -> list[str]:
    """What a reader would notice going missing, named.

    Kept separate from the verdict so the artifact can say *which* structure was
    dropped, not only that something was. A count that went up is not loss --
    the rebuild sets unplaceable pictures at the end under a heading, so it can
    legitimately carry more headings than the original.
    """
    out = []
    for key in ("images", "tables", "rows"):
        before, after = truth.get(key, 0), got.get(key, 0)
        if after < before:
            out.append(f"{key}: {before} -> {after}")
    return out


def _verdict(ok: bool, word_recall: float, recovered_pictures: int,
             structure_lost: list[str] | None = None) -> str:
    """One verdict per fixture, with pictures counted as content.

    A document whose body was emptied but whose photographs were still in the
    archive comes back as a file with the photographs in it and no words. That
    is a partial recovery, not an empty success -- and an earlier version of
    this function called it the latter, which would have reported a defect that
    was not there.
    """
    if not ok:
        return REFUSED
    if word_recall <= 0.0 and recovered_pictures == 0:
        return EMPTY_SUCCESS
    if word_recall >= 1.0:
        # Every word back is not every thing back. This harness used to stop at
        # the word count, and so scored a rebuild that had dropped every
        # photograph and every table in the document a complete success --
        # which is how a regression that lost 100% of images on 100% of files
        # passed 40/40 on lossless damage without tripping anything. A picture
        # is content. So is a table.
        return PARTIAL if structure_lost else FULL
    return PARTIAL


def run() -> dict:
    rows = []
    for fixture in corpus.build():
        try:
            result = repair(fixture.data, filename=f"{fixture.name}.docx")
        except Exception as exc:                          # noqa: BLE001
            rows.append({
                "fixture": fixture.name,
                "base": fixture.base.name,
                "written_by": fixture.base.written_by,
                "damage": fixture.damage.name,
                "kind": fixture.damage.kind,
                "verdict": CRASHED,
                "error": f"{type(exc).__name__}: {exc}",
                "word_recall": 0.0,
            })
            continue

        got_text = corpus.text_of(result.output) if result.output else ""
        got_counts = corpus.counts_of(result.output) if result.output else {
            "tables": 0, "rows": 0, "images": 0}
        word_recall = corpus.recall(fixture.truth_text, got_text)
        structure_lost = _structure_lost(fixture.truth_counts, got_counts)

        rows.append({
            "fixture": fixture.name,
            "base": fixture.base.name,
            "written_by": fixture.base.written_by,
            "damage": fixture.damage.name,
            "kind": fixture.damage.kind,
            "verdict": _verdict(result.ok, word_recall, got_counts["images"],
                                structure_lost),
            "ok": result.ok,
            "word_recall": round(word_recall, 4),
            "truth_words": sum(corpus.words(fixture.truth_text).values()),
            "recovered_words": sum(corpus.words(got_text).values()),
            "structure_preserved": result.structure_preserved,
            "structure_lost": structure_lost,
            "images_lost": result.images_lost,
            "truth_counts": fixture.truth_counts,
            "recovered_counts": got_counts,
            "lost": result.lost,
        })

    return {"method": _method(), "fixtures": rows, "summary": summarise(rows)}


def _method() -> dict:
    """Stated before the result, in the artifact that carries the result."""
    return {
        "corpus": {
            "base_documents": [
                {"name": b.name, "written_by": b.written_by, "source": b.source}
                for b in corpus.BASES
            ],
            "damage_modes": [
                {"name": d.name, "kind": d.kind, "what_happened": d.what_happened}
                for d in corpus.DAMAGES
            ],
            "note": "Every base document is damaged every way that applies to it. "
                    "Media damage is skipped on a document with no pictures.",
        },
        "ground_truth": "The words of the intact original, scraped out of "
                        "word/document.xml by corpus.text_of -- regex over <w:t> "
                        "runs, standard library only, no code shared with the "
                        "repair path. The same function reads the rebuilt file, "
                        "so both sides of every ratio are measured the same way.",
        "word_recall": "The share of the original's words present in the "
                       "recovered text, as multisets: a word said four times and "
                       "recovered once counts as one quarter of four.",
        "damage_kinds": {
            LOSSLESS: "No content was destroyed -- every word is still in the "
                      "bytes. Full recovery is owed, and anything less is this "
                      "tool's defect.",
            LOSSY: "Bytes were physically removed. Partial recovery is the "
                   "honest answer; full recovery is not available at any price, "
                   "so no rate over these fixtures is a score out of 100.",
            FATAL: "The words are not in the file at all. Refusing is the only "
                   "correct answer.",
        },
        "not_measured": [
            "Formatting fidelity. The rebuild is deliberately plain -- theme, "
            "fonts and spacing are not carried, so no figure here is about how "
            "the document looks.",
            "Real-world damage. Every fixture was damaged by this module in a "
            "named way. No public corpus of genuinely corrupt DOCX with known "
            "originals was found to measure against; see RECOVERY.md.",
            "Word's own verdict. Outputs are re-opened and re-read by Python, "
            "not by Microsoft Word. Eight of them are opened in Word by hand -- "
            "manual-test/MANUAL_QA_PLAN.html records that separately.",
        ],
    }


def summarise(rows: list[dict]) -> dict:
    by_kind: dict[str, dict] = {}
    for kind in (LOSSLESS, LOSSY, FATAL):
        subset = [r for r in rows if r["kind"] == kind]
        verdicts: dict[str, int] = {}
        for r in subset:
            verdicts[r["verdict"]] = verdicts.get(r["verdict"], 0) + 1
        recalls = [r["word_recall"] for r in subset]
        by_kind[kind] = {
            "fixtures": len(subset),
            "verdicts": dict(sorted(verdicts.items())),
            "mean_word_recall": round(sum(recalls) / len(recalls), 4) if recalls else 0.0,
            "min_word_recall": round(min(recalls), 4) if recalls else 0.0,
        }

    lossless = [r for r in rows if r["kind"] == LOSSLESS]
    fatal = [r for r in rows if r["kind"] == FATAL]
    return {
        "unexpected": [r["fixture"] for r in rows if r["verdict"] not in ACCEPTABLE[r["kind"]]],
        "fatal_returned_furniture": [
            r["fixture"] for r in fatal if r["verdict"] == PARTIAL],
        "fixtures": len(rows),
        "by_kind": by_kind,
        "headline": {
            "lossless_full_recovery": f"{sum(1 for r in lossless if r['verdict'] == FULL)}"
                                      f"/{len(lossless)}",
            "fatal_correctly_refused": f"{sum(1 for r in fatal if r['verdict'] == REFUSED)}"
                                       f"/{len(fatal)}",
            "empty_successes": sum(1 for r in rows if r["verdict"] == EMPTY_SUCCESS),
            "crashes": sum(1 for r in rows if r["verdict"] == CRASHED),
        },
    }


# -- printing ----------------------------------------------------------------

def _print(data: dict) -> None:
    s = data["summary"]
    print("METHOD")
    print("  Ground truth:", data["method"]["ground_truth"][:78], "...")
    for kind, text in data["method"]["damage_kinds"].items():
        print(f"  {kind:9} {text[:70]}...")
    print()
    print(f"RESULT — {s['fixtures']} fixtures")
    print(f"{'kind':10} {'n':>3}  {'mean recall':>11}  {'min':>6}  verdicts")
    for kind, block in s["by_kind"].items():
        verdicts = " ".join(f"{k}={v}" for k, v in block["verdicts"].items())
        print(f"{kind:10} {block['fixtures']:>3}  {block['mean_word_recall']:>11.3f}"
              f"  {block['min_word_recall']:>6.3f}  {verdicts}")
    print()
    for key, val in s["headline"].items():
        print(f"  {key:28} {val}")
    print()
    bad = [r for r in data["fixtures"] if r["verdict"] not in ACCEPTABLE[r["kind"]]]
    if bad:
        print("NOT WHAT THE KIND ALLOWS — every one, by name:")
        for r in bad:
            print(f"  {r['fixture']:52} {r['verdict']:14} "
                  f"recall={r['word_recall']:.3f} {r.get('error', '')}")
    else:
        print("Every fixture landed inside what its damage kind allows.")

    furniture = s["fatal_returned_furniture"]
    if furniture:
        print(f"\nOn {len(furniture)} of the {s['by_kind'][FATAL]['fixtures']} fatal "
              "fixtures the body was gone and something else was not — a picture, a "
              "header, a footnote. Each returned that and no body text:")
        for name in furniture:
            print(f"  {name}")

    refused_lossy = [r["fixture"] for r in data["fixtures"]
                     if r["kind"] == LOSSY and r["verdict"] == REFUSED]
    if refused_lossy:
        print(f"\n{len(refused_lossy)} lossy fixtures were refused outright — the "
              "damage took the body with it and nothing was invented to fill the gap:")
        for name in refused_lossy:
            print(f"  {name}")


def main(argv: list[str]) -> int:
    data = run()
    _print(data)
    if "--write" in argv:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(data, indent=2, sort_keys=False) + "\n")
        print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
