from engine.verify_citations import citation_is_verbatim, find_citation_failures


def test_a_real_quote_passes_whitespace_and_case_insensitively(petition):
    quote = "equivalent to a Bachelor of Science in Computer   Science"
    assert citation_is_verbatim(quote, petition["04-beneficiary-credentials.md"])


def test_a_paraphrase_is_not_a_citation(petition):
    paraphrase = "his degree is basically the same as an American one"
    assert not citation_is_verbatim(
        paraphrase, petition["04-beneficiary-credentials.md"]
    )


def test_a_fabricated_quote_fails_naming_the_section(petition):
    failures = find_citation_failures(
        [
            {
                "section": "Response to Request 1",
                "file": "04-beneficiary-credentials.md",
                "quote": "the beneficiary also holds a master's degree",
            }
        ],
        petition,
    )
    assert len(failures) == 1
    assert "Response to Request 1" in failures[0]


def test_a_citation_to_a_nonexistent_file_is_called_invented(petition):
    failures = find_citation_failures(
        [
            {
                "section": "Response to Request 2",
                "file": "expert-opinion-letter.md",
                "quote": "anything",
            }
        ],
        petition,
    )
    assert len(failures) == 1
    assert "invented" in failures[0]


def test_clean_citations_produce_no_failures(petition):
    failures = find_citation_failures(
        [
            {
                "section": "Response to Request 3",
                "file": "02-employer-support-letter.md",
                "quote": "report directly to Ms. Dana Whitfield",
            }
        ],
        petition,
    )
    assert failures == []


def test_a_code_fence_the_export_rewrote_as_inline_code_still_matches():
    # SuperDocs re-serialises markdown on export: a fenced block in the
    # petition comes back as inline code — same words, different syntax
    source = "Letterhead:\n```\nLARKSPUR ANALYTICS GROUP, INC.\nSuite 620\n```\nDear Devika,"
    quote = "`LARKSPUR ANALYTICS GROUP, INC. Suite 620` Dear Devika,"
    assert citation_is_verbatim(quote, source)


def test_a_backslash_escape_the_export_added_still_matches():
    source = "SOC (O*NET/OES) code 15-2051.00"
    assert citation_is_verbatim("SOC (O\\*NET/OES) code 15-2051.00", source)


def test_formatting_tolerance_does_not_let_a_changed_word_through():
    source = "```\nSOC (O*NET/OES) code 15-2051.00\n```"
    assert not citation_is_verbatim("`SOC (O*NET/OES) code 15-2052.00`", source)
    assert not citation_is_verbatim("`SOC (O*NET/OES) code 15-2051.00 confirmed`", source)


def test_a_table_cell_line_break_the_export_turned_into_a_space_still_matches():
    source = "| Site | (a) Suite 620 — headquarters<br>(b) 22 Harkin Row — client site |"
    assert citation_is_verbatim("(a) Suite 620 — headquarters (b) 22 Harkin Row — client site", source)


def test_a_table_cell_line_break_the_export_deleted_entirely_still_matches():
    # since SuperDocs' 2026-08 update the export drops the <br> instead of
    # turning it into a space, joining the words around it
    source = "| Address | 123 Main St<br>Suite 4 |"
    assert citation_is_verbatim("123 Main StSuite 4", source)


def test_the_deleted_line_break_tolerance_does_not_let_a_changed_word_through():
    source = "| Address | 123 Main St<br>Suite 4 |"
    assert not citation_is_verbatim("123 Main StSuite 5", source)
