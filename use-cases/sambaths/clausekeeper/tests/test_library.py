from clausekeeper.library import LIBRARY_PATH, load_library, sample_ids, subset


def test_library_loads_with_expected_shape():
    clauses = load_library(LIBRARY_PATH)
    linkable = [c for c in clauses if c["linkable"]]
    assert 24 <= len(linkable) <= 28
    ids = [c["id"] for c in clauses]
    assert len(ids) == len(set(ids))
    assert all(c["expectation"].strip() for c in linkable)
    assert all(c["title"].strip() for c in clauses)


def test_sample_subset_is_deterministic():
    assert sample_ids(LIBRARY_PATH) == ["4.4", "7.5", "8.7", "9.2", "10.2"]
    picked = subset(load_library(LIBRARY_PATH), 5)
    assert [c["id"] for c in picked] == ["4.4", "7.5", "8.7", "9.2", "10.2"]


def test_no_verbatim_standard_text():
    banned = [
        "shall determine", "shall establish", "shall ensure",
        "needs and expectations of relevant interested parties",
        "this International Standard",
    ]
    text = LIBRARY_PATH.read_text().lower()
    corpus = list((LIBRARY_PATH.parent.parent / "corpus").rglob("*.md"))
    blob = " ".join(p.read_text().lower() for p in corpus)
    for phrase in banned:
        assert phrase not in text
        assert phrase not in blob
