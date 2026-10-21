from backend.modules.screenplay.validator import ContentDriftValidator


def test_no_drift_capitalization_only():
    v = ContentDriftValidator()
    assert not v.has_drift("int. office - day", "INT. OFFICE - DAY", "scene_heading")


def test_drift_detected_word_change_in_dialogue():
    v = ContentDriftValidator()
    assert v.has_drift("Hello there.", "Hello friend.", "dialogue")


def test_no_drift_spacing_change_in_action():
    v = ContentDriftValidator()
    # Same words, different spacing — no drift
    assert not v.has_drift("A man  enters  the room.", "A man enters the room.", "action")


def test_drift_detected_word_addition_in_dialogue():
    v = ContentDriftValidator()
    assert v.has_drift("I know.", "I really know.", "dialogue")


def test_no_drift_for_scene_heading_word_change():
    # scene_heading is allowed to change capitalisation/structure
    v = ContentDriftValidator()
    # scene headings are exempt from word-level drift check
    assert not v.has_drift("int. office - day", "INT. OFFICE - DAY", "scene_heading")


def test_no_drift_on_identical():
    v = ContentDriftValidator()
    assert not v.has_drift("Same text.", "Same text.", "action")
