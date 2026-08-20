from core.evidence import analyze_bullet, extract_evidence, metric_question


def test_detects_volume_metric():
    bullet = "Processed 500 invoices per month using Python."

    analysis = analyze_bullet(bullet)

    assert analysis.has_quantified_evidence is True
    assert any(item.text == "500 invoices" for item in analysis.evidence)


def test_missing_metric_is_reported():
    bullet = "Automated invoice processing using Python."

    analysis = analyze_bullet(bullet)

    assert analysis.has_quantified_evidence is False
    assert "quantified impact" in analysis.missing_evidence


def test_detects_percentage():
    evidence = extract_evidence(
        "Reduced processing time by 40% using Python automation."
    )

    assert any(
        item.kind == "percentage" and item.text == "40%"
        for item in evidence
    )


def test_detects_currency():
    evidence = extract_evidence(
        "Reduced annual operating costs by $25,000."
    )

    assert any(
        item.kind == "currency" and item.text == "$25,000"
        for item in evidence
    )


def test_detects_duration_metrics():
    evidence = extract_evidence(
        "Reduced processing time from 3 hours to 45 minutes."
    )

    values = [item.text for item in evidence]

    assert "3 hours" in values
    assert "45 minutes" in values


def test_empty_bullet_has_no_evidence():
    analysis = analyze_bullet("")

    assert analysis.has_quantified_evidence is False
    assert analysis.evidence == []


def test_metric_question_does_not_suggest_fake_number():
    question = metric_question()

    assert "Do you know" in question
    assert "measurable result" in question