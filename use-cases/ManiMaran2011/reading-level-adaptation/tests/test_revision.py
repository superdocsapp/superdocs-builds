from src.revision import plan_revision, apply_revision
from src.fake_client import FakeSuperDocsClient, default_simplify_transform
from src.chunk_classifier import protected_ids
from tests.fixtures import SAMPLE_CHAPTER_HTML


REVISED_HTML = SAMPLE_CHAPTER_HTML.replace(
    "A force is a push or a pull that acts on an object as a result of its interaction with another object.",
    "A force is a push or a pull that acts on an object because of its interaction with a second object -- revised wording.",
)


def test_plan_revision_flags_only_the_actually_changed_chunk():
    plan = plan_revision(SAMPLE_CHAPTER_HTML, REVISED_HTML, locked_chunk_ids=set())
    assert plan.changed_chunk_ids == ["c2"], "only the chunk whose source text actually changed should be flagged"
    assert "c6" in plan.unchanged_chunk_ids
    assert "c9" in plan.unchanged_chunk_ids
    assert plan.needs_regeneration is True


def test_locked_teacher_edited_chunk_is_skipped_even_if_source_changed():
    plan = plan_revision(SAMPLE_CHAPTER_HTML, REVISED_HTML, locked_chunk_ids={"c2"})
    assert plan.changed_chunk_ids == [], "the only changed chunk was locked, so nothing should be queued for regeneration"
    assert plan.locked_and_skipped_chunk_ids == ["c2"]
    assert plan.needs_regeneration is False, "no unlocked chunk changed -- regenerating would be pure waste, an update must cost like an update"


def test_apply_revision_is_a_noop_when_nothing_needs_regeneration():
    client = FakeSuperDocsClient()
    plan = plan_revision(SAMPLE_CHAPTER_HTML, SAMPLE_CHAPTER_HTML, locked_chunk_ids=set())  # identical source
    result = apply_revision(client, "source-1", SAMPLE_CHAPTER_HTML, "lower_reading_level", plan)
    assert result is None
    assert client.chat_log == [], "no LLM call should happen when nothing actually changed"


def test_apply_revision_regenerates_when_something_changed():
    client = FakeSuperDocsClient()
    protected = set(protected_ids(SAMPLE_CHAPTER_HTML))
    client.script_edit("Rewrite the prose", default_simplify_transform(protected))

    plan = plan_revision(SAMPLE_CHAPTER_HTML, REVISED_HTML, locked_chunk_ids=set())
    result = apply_revision(client, "source-1", REVISED_HTML, "lower_reading_level", plan)

    assert result is not None
    assert result.verification.ok
    assert len(client.chat_log) == 1
