from src.models import Paper, Section


def test_revision_touches_only_target_section():
    paper = Paper(id="p1", topic="test topic")
    paper.sections = [
        Section(id="s1", paper_id="p1", title="Intro", order=1),
        Section(id="s2", paper_id="p1", title="Method", order=2),
    ]
    paper.get_section("s1").set_content("Initial intro text.")
    paper.get_section("s2").set_content("Initial method text.")

    before = paper.snapshot_all_hashes()

    # Simulate a targeted revision to s1 only
    paper.get_section("s1").set_content("Revised intro text.")

    changed = paper.diff_against(before)

    assert changed == ["s1"], f"Expected only s1 to change, got {changed}"