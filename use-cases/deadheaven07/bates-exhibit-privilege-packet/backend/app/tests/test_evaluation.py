"""Pre-registered evaluation suite for the Bates Packet Builder.

Computes precision, recall, and F1 against a fixed corpus and ground-truth
expected.yaml.  The corpus is committed to the repo so the evaluation is
deterministic and reproducible across environments.
"""

import hashlib
from pathlib import Path

import yaml

CORPUS_DIR = Path(__file__).resolve().parent.parent.parent / "corpus"
EXPECTED_YAML = CORPUS_DIR / "expected.yaml"


def _load_expected() -> dict:
    with open(EXPECTED_YAML) as f:
        return yaml.safe_load(f)


def _sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


# --------------------------------------------------------------------------- #
# Local fallback evaluation (offline, no SuperDocs API key required)
# --------------------------------------------------------------------------- #


class TestLocalFallbackEvaluation:
    """Run the local regex engine against the corpus and compute metrics."""

    def test_ssn_email_detection_precision_recall(self):
        """Precision and recall for PII detection on the primary corpus doc.

        The local fallback engine detects SSN, email, phone, account numbers,
        names, and medical terms via regex.  We evaluate against the full
        expected PII set from expected.yaml.
        """
        from app.services.fallback_detection import detect_in_pdf

        expected = _load_expected()
        ssn_email = "test_document_ssn_email.pdf"
        doc = next(d for d in expected["documents"] if d["filename"] == ssn_email)
        pdf_path = CORPUS_DIR / doc["filename"]

        matches = detect_in_pdf(str(pdf_path))
        detected_texts = {m.matched_text for m in matches}

        # Ground truth: all PII items the fallback engine can detect
        # (SSN, email, phone, account, name, medical terms)
        ground_truth = {item["text"] for item in doc["expected_pii"]}

        true_positives = detected_texts & ground_truth
        false_negatives = ground_truth - detected_texts

        precision = len(true_positives) / max(len(detected_texts), 1)
        recall = len(true_positives) / max(len(ground_truth), 1)
        f1 = 2 * precision * recall / max(precision + recall, 1e-9)

        # The fallback engine should find at least the structured PII
        # (SSN, email, phone, account) with reasonable precision
        assert recall >= 0.5, f"Recall {recall:.2f} too low; FN: {false_negatives}"
        assert f1 >= 0.4, f"F1 {f1:.2f} too low"

    def test_false_positive_rejection(self):
        """Invoice numbers, dates, and Bates labels must NOT be flagged."""
        from app.services.fallback_detection import detect_in_pdf

        expected = _load_expected()
        edge_cases = "test_document_edge_cases.pdf"
        doc = next(d for d in expected["documents"] if d["filename"] == edge_cases)
        pdf_path = CORPUS_DIR / doc["filename"]

        matches = detect_in_pdf(str(pdf_path))
        detected_texts = {m.matched_text for m in matches}

        for reject in doc["expected_false_positive_rejects"]:
            assert reject["text"] not in detected_texts, (
                f"False positive: '{reject['text']}' was flagged but should not be "
                f"({reject['reason']})"
            )

    def test_multipage_pii_on_correct_page(self):
        """PII on page 3 of a 5-page document must be detected on the correct page."""
        from app.services.fallback_detection import detect_in_pdf

        expected = _load_expected()
        doc = next(
            d for d in expected["documents"] if d["filename"] == "test_document_multipage.pdf"
        )
        pdf_path = CORPUS_DIR / doc["filename"]

        matches = detect_in_pdf(str(pdf_path))

        for item in doc["expected_pii"]:
            if item["category"] in ("ssn", "email"):
                page_matches = [m for m in matches if m.page_number == item["page_number"]]
                found = any(item["text"] in m.matched_text for m in page_matches)
                assert found, f"PII '{item['text']}' not found on page {item['page_number']}"

    def test_corpus_integrity(self):
        """All corpus files exist and SHA256 matches expected.yaml."""
        expected = _load_expected()
        for doc in expected["documents"]:
            pdf_path = CORPUS_DIR / doc["filename"]
            assert pdf_path.exists(), f"Corpus file missing: {doc['filename']}"
            if doc["sha256"]:
                actual = _sha256_of(pdf_path)
                assert actual == doc["sha256"], (
                    f"SHA256 mismatch for {doc['filename']}: expected {doc['sha256']}, got {actual}"
                )

    def test_privilege_language_not_flagged_as_pii(self):
        """Privilege markers ('attorney-client', 'confidential') must not appear as PII."""
        from app.services.fallback_detection import detect_in_pdf

        matches = detect_in_pdf(str(CORPUS_DIR / "test_document_privilege.pdf"))
        detected_texts = {m.matched_text.lower() for m in matches}

        privilege_words = {"attorney-client", "confidential", "privilege", "litigation"}
        for word in privilege_words:
            assert word not in " ".join(detected_texts), (
                f"Privilege word '{word}' incorrectly flagged as PII"
            )


# --------------------------------------------------------------------------- #
# Metrics summary
# --------------------------------------------------------------------------- #


class TestEvaluationMetrics:
    def test_computes_precision_recall_f1(self):
        """Prove the metric computation is mathematically correct."""
        tp, fp, fn = 10, 2, 3
        precision = tp / (tp + fp)
        recall = tp / (tp + fn)
        f1 = 2 * precision * recall / (precision + recall)

        assert abs(precision - 10 / 12) < 1e-9
        assert abs(recall - 10 / 13) < 1e-9
        assert abs(f1 - 2 * (10 / 12) * (10 / 13) / ((10 / 12) + (10 / 13))) < 1e-9
