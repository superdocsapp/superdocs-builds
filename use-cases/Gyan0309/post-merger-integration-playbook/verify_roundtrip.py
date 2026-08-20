"""Prove the edits were surgical, rather than asserting it.

Compares every rendered document with its exported counterpart and reports what
actually changed. Run it after `python -m imo.cli deals/northstar.yaml --out build`:

    python verify_roundtrip.py build

The claim under test is the brief's second behaviour — *"change what you meant to
change and nothing else, and be able to show that nothing else changed"* — so the
output is a count a reader can check, not a reassurance.

Markdown formatting is normalised first, because a markdown → HTML → markdown round
trip legitimately rewrites presentation: `|---|` becomes `| --- |`, `*` bullets become
`-`, and trailing double-space line breaks are dropped. None of that is a content
change. Everything left over is.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Bullet markers a markdown round trip may legitimately produce. The model does not
# always choose the same one: across two runs of the identical pipeline the flags came
# back as "-" once and "•" the next. A verifier keyed to a single character reports
# a real, correctly-applied edit as an unexplained content change — which is the worst
# possible failure for a check whose entire job is telling you whether to trust the
# output. Found by running the pipeline twice, not by reading it.
BULLETS = "-*•·–—◦▪"

FLAG = re.compile(rf"^[{re.escape(BULLETS)}]\s+\*\*\[?(HIGH|MEDIUM|LOW)\]?")
PLACEHOLDER = "_None recorded._"


def normalise(text: str) -> list[str]:
    """Strip presentation, keep content."""
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if re.fullmatch(r"\|[\s\-\|:]+\|", line):  # table separator row
            line = "|SEP|"
        elif line.startswith("|"):  # cell padding
            line = "|" + "|".join(c.strip() for c in line.strip("|").split("|")) + "|"
        line = re.sub(rf"^[{re.escape(BULLETS)}]\s+", "- ", line)  # any bullet marker
        lines.append(line)
    return lines


def main(build: Path) -> int:
    # Documents contain characters the Windows console encoding cannot represent, and
    # the default behaviour is to mangle them into replacement characters mid-report —
    # which makes a correct line look corrupt. Ask for UTF-8 where it is available.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    exported_dir = build / "exported"
    if not exported_dir.is_dir():
        print(f"no exported documents in {exported_dir}", file=sys.stderr)
        return 2

    print(f"{'document':<34} {'lines':>6} {'flags+':>7} {'other+':>7} {'other-':>7}  verdict")
    print("-" * 82)

    unexpected_total = 0
    flags_total = 0

    for source in sorted(build.glob("*.md")):
        exported = exported_dir / source.name
        if not exported.exists():
            continue

        before = normalise(source.read_text(encoding="utf-8"))
        after = normalise(exported.read_text(encoding="utf-8"))
        before_set, after_set = set(before), set(after)

        added = [ln for ln in after if ln not in before_set]
        removed = [ln for ln in before if ln not in after_set]

        flags = [ln for ln in added if FLAG.match(ln)]
        other_added = [ln for ln in added if not FLAG.match(ln)]
        # Losing the placeholder is the instructed change, not collateral damage.
        other_removed = [ln for ln in removed if PLACEHOLDER not in ln]

        flags_total += len(flags)
        unexpected_total += len(other_added) + len(other_removed)

        verdict = "surgical" if not (other_added or other_removed) else "!! CHANGED"
        print(
            f"{source.name:<34} {len(after):>6} {len(flags):>7} "
            f"{len(other_added):>7} {len(other_removed):>7}  {verdict}"
        )

        for line in other_removed:
            print(f"    LOST : {line[:110]}")
        for line in other_added:
            print(f"    GAINED: {line[:110]}")

    print("-" * 82)
    print(f"{flags_total} conflict flags added; {unexpected_total} unintended content changes")

    if unexpected_total:
        print("\nFAIL: the edits were not surgical.")
        return 1

    print("\nPASS: every content change was an intended conflict flag.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1] if len(sys.argv) > 1 else "build")))
