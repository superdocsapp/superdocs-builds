

# --- anchors tolerate morphology, never values ------------------------------
#
# What this must never do: reject a correct paraphrase over a plural. Live,
# the transcript carried a Whisper artifact ("we'll provide the productS
# images"), SuperDocs wrote the correct "product images", and the gate
# rejected the operation for a missing 's'. The retries then hit SuperDocs'
# placeholder defect and Assumptions & Dependencies exported empty.

def test_plural_singular_paraphrase_is_preserved():
    from app.drafting.validator import _anchor_present
    assert _anchor_present("products", "we will provide all product images")
    assert _anchor_present("product", "we will provide the products images")
    assert _anchor_present("assets", "the branding asset library")


def test_money_and_dates_never_get_morphological_slack():
    """The values the gate exists to protect must still match exactly."""
    from app.drafting.validator import _anchor_present
    assert not _anchor_present("$45,000", "the total budget is $55,000")
    assert _anchor_present("$55,000", "the total budget is $55,000")
    assert not _anchor_present("september 15th", "delivery is october 30th")


def test_a_genuinely_absent_anchor_is_still_missing():
    from app.drafting.validator import _anchor_present
    assert not _anchor_present("pricing", "no mention of that here at all")
    assert not _anchor_present("domain", "nothing relevant in this sentence")


def test_preservation_check_shares_the_same_tolerance():
    """The cumulative check rolled back correct batches for the same reason."""
    from app.drafting.validator import facts_preserved_in_html
    ok, missing = facts_preserved_in_html(
        ["We'll provide the products images and branding assets."],
        "<p>We will provide product images and branding asset files.</p>",
    )
    assert ok, f"correct paraphrase reported as dropped: {missing}"


def test_a_contrastive_repair_does_not_require_the_retired_value():
    """"$55,000, not $45,000" must not demand $45,000 in the result.

    Live, all three attempts failed with
    "missing expected content anchors: ['$45,000']" — the gate demanding the
    presence of the exact figure the utterance existed to remove. Unpassable
    by construction.
    """
    from app.drafting.validator import _fact_anchors
    assert _fact_anchors("the total budget is $55,000, not $45,000.") == ["$55,000"]
    assert _fact_anchors(
        "The start date is October 1st, not September 15th."
    ) == ["october 1st"]


def test_a_negation_sentence_keeps_all_of_its_content():
    """The narrow rule must not eat Out-of-Scope content."""
    from app.drafting.validator import _fact_anchors
    anchors = _fact_anchors(
        "The project does not include ongoing marketing, SEO, or content creation."
    )
    for expected in ("marketing", "seo", "content", "creation"):
        assert expected in anchors, f"{expected} was stripped from a real fact"


def test_irregular_plurals_match_both_directions():
    """Stem-guessing failed both ways.

    Stripping "es" turned "deliverables" into "deliverabl", matching neither
    form, and it could not reach "company" from "companies" at all. Live, the
    speaker said "a small e-commerce company", SuperDocs wrote the correct
    singular, and Scope of Work was rejected three times over one letter.
    """
    from app.drafting.validator import _anchor_present
    assert _anchor_present("companies", "a small e-commerce company")
    assert _anchor_present("company", "two e-commerce companies")
    assert _anchor_present("deliverables", "the deliverable is a website")
    assert _anchor_present("policies", "the policy states")


def test_values_still_never_get_morphological_slack():
    from app.drafting.validator import _anchor_present
    assert not _anchor_present("$45,000", "the budget is $55,000")
    assert not _anchor_present("september 15th", "delivery is october 30th")
