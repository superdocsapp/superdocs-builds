from series_bible.application.chat import needs_retrieval


def test_conversational_greeting_skips_retrieval():
    assert not needs_retrieval("Hello!", ["Elena"], "")


def test_general_knowledge_question_skips_retrieval():
    assert not needs_retrieval("What is the capital of France?", ["Elena"], "")


def test_document_question_uses_retrieval():
    assert needs_retrieval("What color are Elena's eyes?", ["Elena"], "")


def test_short_follow_up_uses_prior_document_context():
    assert needs_retrieval("tell me more", [], "What happened in chapter 2?")