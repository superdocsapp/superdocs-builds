import pytest

from verification import check_entailment, quote_grounded


class ChatClient:
    def __init__(self, response):
        self.response = response

    def chat(self, **kwargs):
        return self.response


def test_quote_grounded_is_case_insensitive_and_whitespace_normalized():
    source = "Payment Terms\nfor all invoices."
    assert quote_grounded(" payment   terms ", source) is True


def test_quote_grounded_rejects_missing_quote_in_wrong_document():
    source = "Shipping schedule\nOrders ship in 5 business days."
    assert quote_grounded("payment terms", source) is False


def test_check_entailment_parses_structured_response():
    client = ChatClient({"verdict": "yes", "reason": "It explicitly states the same rule."})

    result = check_entailment(
        "Late fees apply after 30 days.",
        "Late fees apply after 30 days.",
        client,
    )

    assert result == {"verdict": "yes", "reason": "It explicitly states the same rule."}


def test_check_entailment_parses_text_response():
    client = ChatClient("VERDICT: partial\nReason: The passage supports the idea but omits the exact time window.")

    result = check_entailment(
        "The fee is due after a grace period.",
        "Late fees apply after 30 days.",
        client,
    )

    assert result["verdict"] == "partial"
    assert "supports the idea" in result["reason"].lower()


def test_check_entailment_rejects_unknown_verdict():
    client = ChatClient({"verdict": "maybe", "reason": "This is not a valid category."})

    with pytest.raises(ValueError, match="verdict"):
        check_entailment("Claim", "Source", client)
