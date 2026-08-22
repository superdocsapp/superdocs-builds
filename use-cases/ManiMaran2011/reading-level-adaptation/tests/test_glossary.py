import json

from src.fake_client import FakeSuperDocsClient
from src.glossary import extract_glossary
from tests.fixtures import SAMPLE_CHAPTER_HTML


def test_glossary_accepts_grounded_terms_and_rejects_invented_ones():
    client = FakeSuperDocsClient()

    def fake_glossary_response(html):
        return html  # chat() applies this to session state; we don't need document mutation here

    # Script the chat call to return a JSON glossary response with one real term and one fabricated one.
    scripted_response = json.dumps([
        {"term": "acceleration", "definition": "how fast something speeds up"},
        {"term": "quantum entanglement", "definition": "a made-up term the model hallucinated"},
    ])

    # Monkeypatch chat to return our scripted JSON in the 'response' field directly.
    original_chat = client.chat

    def patched_chat(session_id, message, document_html=None):
        result = original_chat(session_id, message, document_html)
        result["response"] = scripted_response
        return result

    client.chat = patched_chat

    terms = extract_glossary(client, "session-1", SAMPLE_CHAPTER_HTML)
    term_names = [t.term for t in terms]

    assert "acceleration" in term_names, "a term that genuinely appears in the text must be kept"
    assert "quantum entanglement" not in term_names, "a term absent from the text must be rejected, not trusted"


def test_glossary_handles_unparseable_response_gracefully():
    client = FakeSuperDocsClient()
    original_chat = client.chat

    def patched_chat(session_id, message, document_html=None):
        result = original_chat(session_id, message, document_html)
        result["response"] = "not valid json at all"
        return result

    client.chat = patched_chat

    terms = extract_glossary(client, "session-1", SAMPLE_CHAPTER_HTML)
    assert terms == [], "an unparseable response must yield an empty glossary, never fabricated terms"
