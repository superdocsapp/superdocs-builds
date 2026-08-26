"""§5 compliance scan — generated narratives must not claim certifications or guaranteed redaction."""

from __future__ import annotations

import re
from pathlib import Path

from generator.manifest import project_root

# Fail the class of claim, not one wording. YAML already forbids certifying ClarityDocs.
_FORBIDDEN = (
    (
        re.compile(r"meets HIPAA.{0,80}by design", re.IGNORECASE | re.DOTALL),
        "HIPAA met 'by design' (certification-adjacent)",
    ),
    (
        re.compile(r"ensuring that you meet HIPAA", re.IGNORECASE),
        "tool claimed to make the buyer meet HIPAA",
    ),
    (
        re.compile(r"PHI redacted, of course", re.IGNORECASE),
        "casual guaranteed-sounding PHI redaction",
    ),
    (
        re.compile(r"guaranteed removal", re.IGNORECASE),
        "promised guaranteed removal of personal data",
    ),
    (
        re.compile(
            r"(?<!not a claim that )ClarityDocs is (HIPAA|FERPA|COPPA|SOC\s*2|ISO)\s*certified",
            re.IGNORECASE,
        ),
        "ClarityDocs claimed certified",
    ),
    (
        re.compile(
            r"SuperDocs is (HIPAA|FERPA|COPPA|SOC\s*2|ISO)\s*certified",
            re.IGNORECASE,
        ),
        "SuperDocs claimed certified",
    ),
)

# Explicit denials are allowed ("we don't promise guaranteed removal").
_ALLOWED_NEGATION = re.compile(
    r"(do not|don't|never|no claim|not a claim|without).{0,40}guaranteed removal",
    re.IGNORECASE | re.DOTALL,
)


def test_evidence_narratives_have_no_certification_or_guaranteed_redaction() -> None:
    folder = project_root() / "evidence" / "narratives"
    failures: list[str] = []
    for path in sorted(folder.glob("pitch-script-*.md")):
        text = path.read_text(encoding="utf-8")
        for pattern, label in _FORBIDDEN:
            for match in pattern.finditer(text):
                snippet = match.group(0)
                if "guaranteed removal" in label.lower() and _ALLOWED_NEGATION.search(
                    text[max(0, match.start() - 80) : match.end() + 40]
                ):
                    continue
                failures.append(f"{path.name}: {label}: {snippet!r}")
    assert not failures, "§5 compliance gaps:\n" + "\n".join(failures)
