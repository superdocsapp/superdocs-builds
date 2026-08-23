from app.workflow.calibration import calibrate_fields


def test_agreement_boosts_confidence_above_self_reported():
    result = calibrate_fields(
        first_fields={"counterparty_name": "Acme Logistics Inc"},
        first_confidences={"counterparty_name": 0.6},
        second_fields={"counterparty_name": "Acme Logistics Inc"},
    )
    field = result["counterparty_name"]
    assert field.agreed is True
    assert field.calibrated_confidence > field.self_reported_confidence


def test_disagreement_caps_confidence_low_even_if_self_reported_was_high():
    result = calibrate_fields(
        first_fields={"counterparty_name": "Acme Logistics Inc"},
        first_confidences={"counterparty_name": 0.95},
        second_fields={"counterparty_name": "Globex Corp"},
    )
    field = result["counterparty_name"]
    assert field.agreed is False
    assert field.calibrated_confidence < 0.5
    assert field.calibrated_confidence <= field.self_reported_confidence


def test_dates_in_different_formats_still_count_as_agreement():
    result = calibrate_fields(
        first_fields={"effective_date": "2026-01-15"},
        first_confidences={"effective_date": 0.5},
        second_fields={"effective_date": "01/15/2026"},
    )
    assert result["effective_date"].agreed is True


def test_currency_formatting_differences_still_count_as_agreement():
    result = calibrate_fields(
        first_fields={"contract_value": "$84,000.00"},
        first_confidences={"contract_value": 0.5},
        second_fields={"contract_value": "84000"},
    )
    assert result["contract_value"].agreed is True


def test_confidence_never_exceeds_one():
    result = calibrate_fields(
        first_fields={"counterparty_name": "Acme"},
        first_confidences={"counterparty_name": 0.95},
        second_fields={"counterparty_name": "Acme"},
    )
    assert result["counterparty_name"].calibrated_confidence <= 1.0


def test_missing_from_second_run_counts_as_disagreement():
    result = calibrate_fields(
        first_fields={"counterparty_name": "Acme"},
        first_confidences={"counterparty_name": 0.9},
        second_fields={},
    )
    assert result["counterparty_name"].agreed is False


def test_only_fields_present_in_first_run_are_calibrated():
    result = calibrate_fields(
        first_fields={"counterparty_name": "Acme"},
        first_confidences={},
        second_fields={"counterparty_name": "Acme", "contract_value": "1000"},
    )
    assert set(result.keys()) == {"counterparty_name"}


# --- N-way ensemble voting ----------------------------------------------------


def test_unanimous_ensemble_gets_the_full_agreement_bonus():
    from app.workflow.calibration import calibrate_fields_ensemble

    result = calibrate_fields_ensemble(
        primary_fields={"counterparty_name": "Acme Logistics Inc"},
        primary_confidences={"counterparty_name": 0.6},
        additional_runs=[
            {"counterparty_name": "Acme Logistics Inc"},
            {"counterparty_name": "Acme Logistics Inc"},
            {"counterparty_name": "Acme Logistics Inc"},
        ],
    )
    field = result["counterparty_name"]
    assert field.agreement_fraction == 1.0
    assert field.run_count == 4
    assert field.calibrated_confidence > field.self_reported_confidence


def test_partial_agreement_gets_a_proportionally_smaller_bonus_than_unanimous():
    from app.workflow.calibration import calibrate_fields_ensemble

    unanimous = calibrate_fields_ensemble(
        primary_fields={"f": "X"},
        primary_confidences={"f": 0.6},
        additional_runs=[{"f": "X"}, {"f": "X"}, {"f": "X"}],
    )["f"]
    partial = calibrate_fields_ensemble(
        primary_fields={"f": "X"},
        primary_confidences={"f": 0.6},
        additional_runs=[{"f": "X"}, {"f": "Y"}, {"f": "Z"}],  # only 2/4 agree
    )["f"]
    assert partial.agreement_fraction < unanimous.agreement_fraction
    assert partial.calibrated_confidence < unanimous.calibrated_confidence


def test_no_majority_is_treated_as_disagreement():
    from app.workflow.calibration import calibrate_fields_ensemble

    result = calibrate_fields_ensemble(
        primary_fields={"f": "X"},
        primary_confidences={"f": 0.9},
        additional_runs=[{"f": "Y"}, {"f": "Z"}],  # only 1/3 (33%) agree with primary
    )
    field = result["f"]
    assert field.agreement_fraction <= 0.5
    assert field.calibrated_confidence <= 0.4


def test_ensemble_canonical_value_always_comes_from_primary_run_not_the_vote():
    from app.workflow.calibration import calibrate_fields_ensemble

    result = calibrate_fields_ensemble(
        primary_fields={"f": "Primary Value"},
        primary_confidences={"f": 0.5},
        additional_runs=[{"f": "Other A"}, {"f": "Other A"}, {"f": "Other A"}],  # majority disagrees
    )
    # even though 3/4 runs said "Other A", the written value is still
    # what the primary run said -- ensemble is a confidence signal, not
    # a value source
    assert result["f"].canonical_value == "Primary Value"
    assert result["f"].agreement_fraction == 0.25  # only the primary run itself matches "Primary Value"


def test_ensemble_with_zero_additional_runs_behaves_like_a_single_run():
    from app.workflow.calibration import calibrate_fields_ensemble

    result = calibrate_fields_ensemble(
        primary_fields={"f": "X"}, primary_confidences={"f": 0.6}, additional_runs=[]
    )
    assert result["f"].run_count == 1
    assert result["f"].agreement_fraction == 1.0  # the primary run trivially agrees with itself


# --- wired into the pipeline (opt-in) ---------------------------------------


def test_pipeline_calibration_disabled_by_default_makes_one_extract_call():
    from app.clients.fake_box_client import FakeBoxClient
    from app.clients.fake_superdocs_client import FakeSuperDocsClient
    from app.workflow.pipeline import BoxMetadataWritebackPipeline

    box, sd = FakeBoxClient(), FakeSuperDocsClient()
    box.seed_file(
        "f1",
        "contract.txt",
        b"SERVICES AGREEMENT\nCounterparty: Acme Logistics Inc\nEffective Date: 2026-01-15\nValue: $84,000\n",
    )
    pipeline = BoxMetadataWritebackPipeline(box, sd, retry_sleep_fn=lambda s: None)
    pipeline.process("f1")
    extract_calls = [c for c in sd.call_log if "extract key terms" in c.lower()]
    assert len(extract_calls) == 1


def test_pipeline_calibration_enabled_makes_two_extract_calls_and_adjusts_confidence():
    from app.clients.fake_box_client import FakeBoxClient
    from app.clients.fake_superdocs_client import FakeSuperDocsClient
    from app.workflow.pipeline import BoxMetadataWritebackPipeline

    box, sd = FakeBoxClient(), FakeSuperDocsClient()
    box.seed_file(
        "f1",
        "contract.txt",
        b"SERVICES AGREEMENT\nCounterparty: Acme Logistics Inc\nEffective Date: 2026-01-15\nValue: $84,000\n",
    )
    pipeline = BoxMetadataWritebackPipeline(box, sd, retry_sleep_fn=lambda s: None, enable_calibration=True)
    report = pipeline.process("f1")
    extract_calls = [c for c in sd.call_log if "extract key terms" in c.lower()]
    assert len(extract_calls) == 2

    # The fake client's second run returns identical field values (same
    # deterministic source text), so calibration should AGREE on
    # counterparty_name and effective_date, boosting their confidence
    # above what the (single) fake model self-reported.
    assert report.extracted.field_confidence["counterparty_name"] > 0.93
    assert report.extracted.field_confidence["effective_date"] > 0.95


# --- N-way ensemble, wired into the pipeline (opt-in) -----------------------


def test_pipeline_ensemble_runs_makes_n_plus_one_extract_calls():
    from app.clients.fake_box_client import FakeBoxClient
    from app.clients.fake_superdocs_client import FakeSuperDocsClient
    from app.workflow.pipeline import BoxMetadataWritebackPipeline

    box, sd = FakeBoxClient(), FakeSuperDocsClient()
    box.seed_file(
        "f1",
        "contract.txt",
        b"SERVICES AGREEMENT\nCounterparty: Acme Logistics Inc\nEffective Date: 2026-01-15\nValue: $84,000\n",
    )
    pipeline = BoxMetadataWritebackPipeline(box, sd, retry_sleep_fn=lambda s: None, ensemble_runs=4)
    pipeline.process("f1")
    extract_calls = [c for c in sd.call_log if "extract key terms" in c.lower()]
    # 1 primary run + 4 additional ensemble runs = 5 total
    assert len(extract_calls) == 5


def test_pipeline_ensemble_unanimous_agreement_boosts_confidence_more_than_pairwise():
    from app.clients.fake_box_client import FakeBoxClient
    from app.clients.fake_superdocs_client import FakeSuperDocsClient
    from app.workflow.pipeline import BoxMetadataWritebackPipeline

    source = b"SERVICES AGREEMENT\nCounterparty: Acme Logistics Inc\nEffective Date: 2026-01-15\nValue: $84,000\n"

    box1, sd1 = FakeBoxClient(), FakeSuperDocsClient()
    box1.seed_file("f1", "contract.txt", source)
    pairwise_pipeline = BoxMetadataWritebackPipeline(
        box1, sd1, retry_sleep_fn=lambda s: None, enable_calibration=True
    )
    pairwise_report = pairwise_pipeline.process("f1")

    box2, sd2 = FakeBoxClient(), FakeSuperDocsClient()
    box2.seed_file("f1", "contract.txt", source)
    ensemble_pipeline = BoxMetadataWritebackPipeline(box2, sd2, retry_sleep_fn=lambda s: None, ensemble_runs=4)
    ensemble_report = ensemble_pipeline.process("f1")

    # Same deterministic source -> every run agrees in both modes, but
    # unanimous agreement across 5 runs is stronger evidence than
    # agreement across 2, so the ensemble path's calibrated confidence
    # should be at least as high.
    assert (
        ensemble_report.extracted.field_confidence["counterparty_name"]
        >= pairwise_report.extracted.field_confidence["counterparty_name"]
    )


def test_pipeline_ensemble_records_disagreement_note_when_no_majority():
    from app.clients.fake_box_client import FakeBoxClient
    from app.clients.fake_superdocs_client import FakeSuperDocsClient
    from app.workflow.pipeline import BoxMetadataWritebackPipeline

    class DisagreeingEnsembleClient(FakeSuperDocsClient):
        """First extract call returns the real value; every ensemble
        pass after that returns a different fabricated value, so no
        majority ever forms."""

        def __init__(self):
            super().__init__()
            self._extract_call_count = 0

        def chat(self, document_id, instruction):
            result = super().chat(document_id, instruction)
            if "extract key terms" in instruction.lower() and result.proposed_change:
                self._extract_call_count += 1
                if self._extract_call_count > 1:  # any ensemble pass after the primary
                    change = dict(result.proposed_change)
                    fields = dict(change.get("fields", {}))
                    fields["counterparty_name"] = f"Disagreeing Value {self._extract_call_count}"
                    change["fields"] = fields
                    result.proposed_change = change
            return result

    box, sd = FakeBoxClient(), DisagreeingEnsembleClient()
    box.seed_file(
        "f1",
        "contract.txt",
        b"SERVICES AGREEMENT\nCounterparty: Acme Logistics Inc\nEffective Date: 2026-01-15\nValue: $84,000\n",
    )
    pipeline = BoxMetadataWritebackPipeline(box, sd, retry_sleep_fn=lambda s: None, ensemble_runs=3)
    report = pipeline.process("f1")
    assert "ensemble calibration disagreement" in report.extracted.extraction_notes.lower()
    # Should be queued for review, not written straight through, given
    # the low post-calibration confidence
    pending_fields = {r.field_name for r in pipeline.review_queue.list_pending(file_id="f1")}
    assert "counterparty_name" in pending_fields


# --- cost tracking, wired through process() -------------------------------


def test_run_report_tags_its_calibration_mode():
    from app.clients.fake_box_client import FakeBoxClient
    from app.clients.fake_superdocs_client import FakeSuperDocsClient
    from app.workflow.pipeline import BoxMetadataWritebackPipeline

    source = b"SERVICES AGREEMENT\nCounterparty: Acme Logistics Inc\nEffective Date: 2026-01-15\nValue: $84,000\n"

    box1, sd1 = FakeBoxClient(), FakeSuperDocsClient()
    box1.seed_file("f1", "c.txt", source)
    plain = BoxMetadataWritebackPipeline(box1, sd1, retry_sleep_fn=lambda s: None)
    assert plain.process("f1").calibration_mode == "none"

    box2, sd2 = FakeBoxClient(), FakeSuperDocsClient()
    box2.seed_file("f1", "c.txt", source)
    pairwise = BoxMetadataWritebackPipeline(box2, sd2, retry_sleep_fn=lambda s: None, enable_calibration=True)
    assert pairwise.process("f1").calibration_mode == "pairwise"

    box3, sd3 = FakeBoxClient(), FakeSuperDocsClient()
    box3.seed_file("f1", "c.txt", source)
    ensemble = BoxMetadataWritebackPipeline(box3, sd3, retry_sleep_fn=lambda s: None, ensemble_runs=2)
    assert ensemble.process("f1").calibration_mode == "ensemble"


def test_cost_tracker_accumulates_across_runs_by_mode():
    from app.clients.fake_box_client import FakeBoxClient
    from app.clients.fake_superdocs_client import FakeSuperDocsClient
    from app.workflow.pipeline import BoxMetadataWritebackPipeline

    source = b"SERVICES AGREEMENT\nCounterparty: Acme Logistics Inc\nEffective Date: 2026-01-15\nValue: $84,000\n"
    box, sd = FakeBoxClient(), FakeSuperDocsClient()
    pipeline = BoxMetadataWritebackPipeline(box, sd, retry_sleep_fn=lambda s: None)
    for i in range(3):
        box.seed_file(f"f{i}", f"c{i}.txt", source)
        pipeline.process(f"f{i}")

    report = pipeline.cost_tracker.report()
    assert report["none"]["run_count"] == 3
    assert report["none"]["total_operations"] > 0


def test_cost_report_shows_realized_multiplier_of_calibrated_mode_vs_baseline():
    from app.clients.fake_box_client import FakeBoxClient
    from app.clients.fake_superdocs_client import FakeSuperDocsClient
    from app.workflow.pipeline import BoxMetadataWritebackPipeline

    source = b"SERVICES AGREEMENT\nCounterparty: Acme Logistics Inc\nEffective Date: 2026-01-15\nValue: $84,000\n"
    box, sd = FakeBoxClient(), FakeSuperDocsClient()
    pipeline = BoxMetadataWritebackPipeline(box, sd, retry_sleep_fn=lambda s: None)

    box.seed_file("f1", "c1.txt", source)
    pipeline.process("f1")  # baseline "none" run

    pipeline.enable_calibration = True
    box.seed_file("f2", "c2.txt", source)
    pipeline.process("f2")  # pairwise run, same pipeline/tracker

    report = pipeline.cost_tracker.report()
    assert report["pairwise"]["operations_multiplier_vs_none"] is not None
    assert report["pairwise"]["operations_multiplier_vs_none"] > 1.0


def test_cost_report_over_http_after_real_runs():
    from fastapi.testclient import TestClient

    import app.api.main as m
    from app.api.main import app

    client = TestClient(app)
    m._tenants.context_for("default").box.seed_file(
        "cost-http-1",
        "c.txt",
        b"SERVICES AGREEMENT\nCounterparty: Acme Logistics Inc\nEffective Date: 2026-01-15\nValue: $84,000\n",
    )
    resp = client.post("/process/cost-http-1")
    assert resp.status_code == 200

    cost_resp = client.get("/cost-report")
    assert cost_resp.status_code == 200
    body = cost_resp.json()
    assert "none" in body
    assert body["none"]["run_count"] >= 1
