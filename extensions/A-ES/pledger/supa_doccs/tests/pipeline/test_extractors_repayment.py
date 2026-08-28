"""Unit tests for RepaymentExtractor.

Tests cover:
- Basic pipe-delimited table extraction
- Tab-delimited table extraction
- Multi-space separated table extraction
- Date normalization (various formats → ISO 8601)
- Unparseable date handling (value="unparseable", confidence=0.0)
- Monetary normalization (currency symbols, commas → 2 decimal places)
- Blank/non-numeric monetary fields (value="not_found", confidence=0.0)
- Row indexing (1-based, sequential)
- Fact group IDs (row_1, row_2, etc.)
- Source span correctness
- Tables with leading serial number column
- Header row skipping
- Separator row skipping
"""

import pytest

from src.pipeline.extractors.repayment import RepaymentExtractor


@pytest.fixture
def extractor() -> RepaymentExtractor:
    return RepaymentExtractor()


# --- Basic extraction tests ---


@pytest.mark.anyio
async def test_basic_pipe_delimited_extraction(extractor: RepaymentExtractor):
    """Pipe-delimited table rows are extracted correctly."""
    text = (
        "Date | Amount Paid | Late Fee | Outstanding Balance\n"
        "01/15/2024 | 5000.00 | 100.00 | 45000.00\n"
        "02/15/2024 | 5000.00 | 0 | 40000.00"
    )
    facts = await extractor.extract(text, [])

    # 2 rows × 5 facts = 10 facts
    assert len(facts) == 10

    # First row facts
    row1_facts = [f for f in facts if f.fact_group_id == "row_1"]
    assert len(row1_facts) == 5

    date_fact = next(f for f in row1_facts if f.field_name == "payment_date")
    assert date_fact.value == "2024-01-15"
    assert date_fact.confidence > 0.0

    amount_fact = next(f for f in row1_facts if f.field_name == "amount_paid")
    assert amount_fact.value == "5000.00"
    assert amount_fact.confidence > 0.0

    fee_fact = next(f for f in row1_facts if f.field_name == "late_fee_charged")
    assert fee_fact.value == "100.00"

    balance_fact = next(f for f in row1_facts if f.field_name == "outstanding_balance")
    assert balance_fact.value == "45000.00"

    idx_fact = next(f for f in row1_facts if f.field_name == "row_index")
    assert idx_fact.value == "1"
    assert idx_fact.confidence == 1.0


@pytest.mark.anyio
async def test_tab_delimited_extraction(extractor: RepaymentExtractor):
    """Tab-delimited rows are extracted correctly."""
    text = (
        "Date\tAmount Paid\tLate Fee\tOutstanding Balance\n"
        "2024-01-15\t5000.00\t100.00\t45000.00"
    )
    facts = await extractor.extract(text, [])

    assert len(facts) == 5
    date_fact = next(f for f in facts if f.field_name == "payment_date")
    assert date_fact.value == "2024-01-15"


@pytest.mark.anyio
async def test_multi_space_delimited_extraction(extractor: RepaymentExtractor):
    """Multi-space separated rows are extracted correctly."""
    text = (
        "Date          Amount Paid   Late Fee   Outstanding Balance\n"
        "01/15/2024    5000.00       100.00     45000.00"
    )
    facts = await extractor.extract(text, [])

    assert len(facts) == 5
    date_fact = next(f for f in facts if f.field_name == "payment_date")
    assert date_fact.value == "2024-01-15"


# --- Date normalization tests ---


@pytest.mark.anyio
async def test_date_format_mm_dd_yyyy(extractor: RepaymentExtractor):
    """MM/DD/YYYY format is normalized to ISO 8601."""
    text = "Date | Amount | Fee | Balance\n01/15/2024 | 1000 | 0 | 9000"
    facts = await extractor.extract(text, [])
    date_fact = next(f for f in facts if f.field_name == "payment_date")
    assert date_fact.value == "2024-01-15"


@pytest.mark.anyio
async def test_date_format_dd_mm_yyyy_dash(extractor: RepaymentExtractor):
    """DD-MM-YYYY format is normalized to ISO 8601."""
    text = "Date | Amount | Fee | Balance\n15-01-2024 | 1000 | 0 | 9000"
    facts = await extractor.extract(text, [])
    date_fact = next(f for f in facts if f.field_name == "payment_date")
    assert date_fact.value == "2024-01-15"


@pytest.mark.anyio
async def test_date_format_month_name(extractor: RepaymentExtractor):
    """'Jan 15, 2024' format is normalized to ISO 8601."""
    text = "Date | Amount | Fee | Balance\nJan 15, 2024 | 1000 | 0 | 9000"
    facts = await extractor.extract(text, [])
    date_fact = next(f for f in facts if f.field_name == "payment_date")
    assert date_fact.value == "2024-01-15"


@pytest.mark.anyio
async def test_date_format_iso(extractor: RepaymentExtractor):
    """ISO 8601 format passes through correctly."""
    text = "Date | Amount | Fee | Balance\n2024-01-15 | 1000 | 0 | 9000"
    facts = await extractor.extract(text, [])
    date_fact = next(f for f in facts if f.field_name == "payment_date")
    assert date_fact.value == "2024-01-15"


@pytest.mark.anyio
async def test_unparseable_date(extractor: RepaymentExtractor):
    """Unparseable dates get value='unparseable', confidence=0.0."""
    text = "Date | Amount | Fee | Balance\nnot-a-date | 1000 | 0 | 9000"
    facts = await extractor.extract(text, [])
    date_fact = next(f for f in facts if f.field_name == "payment_date")
    assert date_fact.value == "unparseable"
    assert date_fact.confidence == 0.0


# --- Monetary normalization tests ---


@pytest.mark.anyio
async def test_monetary_with_currency_symbol(extractor: RepaymentExtractor):
    """Currency symbols are stripped and value normalized to 2 decimal places."""
    text = "Date | Amount | Fee | Balance\n2024-01-15 | ₹5,000.50 | ₹100 | ₹45,000.00"
    facts = await extractor.extract(text, [])

    amount_fact = next(f for f in facts if f.field_name == "amount_paid")
    assert amount_fact.value == "5000.50"

    fee_fact = next(f for f in facts if f.field_name == "late_fee_charged")
    assert fee_fact.value == "100.00"

    balance_fact = next(f for f in facts if f.field_name == "outstanding_balance")
    assert balance_fact.value == "45000.00"


@pytest.mark.anyio
async def test_monetary_integer_gets_two_decimals(extractor: RepaymentExtractor):
    """Integer monetary values get .00 appended."""
    text = "Date | Amount | Fee | Balance\n2024-01-15 | 1000 | 0 | 9000"
    facts = await extractor.extract(text, [])
    amount_fact = next(f for f in facts if f.field_name == "amount_paid")
    assert amount_fact.value == "1000.00"


@pytest.mark.anyio
async def test_monetary_blank_field(extractor: RepaymentExtractor):
    """Blank monetary fields get value='not_found', confidence=0.0."""
    text = "Date | Amount | Fee | Balance\n2024-01-15 | 1000 |  | 9000"
    facts = await extractor.extract(text, [])
    fee_fact = next(f for f in facts if f.field_name == "late_fee_charged")
    assert fee_fact.value == "not_found"
    assert fee_fact.confidence == 0.0


@pytest.mark.anyio
async def test_monetary_non_numeric_dash(extractor: RepaymentExtractor):
    """Dash '-' in monetary field gets value='not_found', confidence=0.0."""
    text = "Date | Amount | Fee | Balance\n2024-01-15 | 1000 | - | 9000"
    facts = await extractor.extract(text, [])
    fee_fact = next(f for f in facts if f.field_name == "late_fee_charged")
    assert fee_fact.value == "not_found"
    assert fee_fact.confidence == 0.0


@pytest.mark.anyio
async def test_monetary_na_value(extractor: RepaymentExtractor):
    """'N/A' in monetary field gets value='not_found', confidence=0.0."""
    text = "Date | Amount | Fee | Balance\n2024-01-15 | 1000 | N/A | 9000"
    facts = await extractor.extract(text, [])
    fee_fact = next(f for f in facts if f.field_name == "late_fee_charged")
    assert fee_fact.value == "not_found"
    assert fee_fact.confidence == 0.0


# --- Row indexing tests ---


@pytest.mark.anyio
async def test_row_index_is_one_based_sequential(extractor: RepaymentExtractor):
    """Row index is 1-based and sequential across rows."""
    text = (
        "Date | Amount | Fee | Balance\n"
        "2024-01-15 | 1000 | 0 | 9000\n"
        "2024-02-15 | 1000 | 0 | 8000\n"
        "2024-03-15 | 1000 | 0 | 7000"
    )
    facts = await extractor.extract(text, [])

    row1_idx = next(f for f in facts if f.fact_group_id == "row_1" and f.field_name == "row_index")
    row2_idx = next(f for f in facts if f.fact_group_id == "row_2" and f.field_name == "row_index")
    row3_idx = next(f for f in facts if f.fact_group_id == "row_3" and f.field_name == "row_index")

    assert row1_idx.value == "1"
    assert row2_idx.value == "2"
    assert row3_idx.value == "3"


# --- Fact group tests ---


@pytest.mark.anyio
async def test_each_row_has_unique_fact_group_id(extractor: RepaymentExtractor):
    """Each row's 5 facts share a unique fact_group_id."""
    text = (
        "Date | Amount | Fee | Balance\n"
        "2024-01-15 | 1000 | 0 | 9000\n"
        "2024-02-15 | 1000 | 0 | 8000"
    )
    facts = await extractor.extract(text, [])

    group_ids = set(f.fact_group_id for f in facts)
    assert group_ids == {"row_1", "row_2"}

    for gid in group_ids:
        group_facts = [f for f in facts if f.fact_group_id == gid]
        assert len(group_facts) == 5
        field_names = {f.field_name for f in group_facts}
        assert field_names == {
            "payment_date", "amount_paid", "late_fee_charged",
            "outstanding_balance", "row_index"
        }


# --- Source span tests ---


@pytest.mark.anyio
async def test_source_spans_point_to_cell_text(extractor: RepaymentExtractor):
    """Source spans correctly point to cell positions in text."""
    text = "Date | Amount | Fee | Balance\n2024-01-15 | 5000 | 100 | 45000"
    facts = await extractor.extract(text, [])

    date_fact = next(f for f in facts if f.field_name == "payment_date")
    span = date_fact.source_span
    assert span.start_offset < span.end_offset
    assert text[span.start_offset:span.end_offset] == "2024-01-15"


@pytest.mark.anyio
async def test_row_index_source_span_covers_full_line(extractor: RepaymentExtractor):
    """Row index source span covers the entire line."""
    text = "Date | Amount | Fee | Balance\n2024-01-15 | 5000 | 100 | 45000"
    facts = await extractor.extract(text, [])

    idx_fact = next(f for f in facts if f.field_name == "row_index")
    span = idx_fact.source_span
    assert span.start_offset < span.end_offset


# --- Edge cases ---


@pytest.mark.anyio
async def test_empty_text_returns_no_facts(extractor: RepaymentExtractor):
    """Empty text produces no facts."""
    facts = await extractor.extract("", [])
    assert facts == []


@pytest.mark.anyio
async def test_header_only_returns_no_facts(extractor: RepaymentExtractor):
    """Text with only headers and no data rows returns no facts."""
    text = "Date | Amount Paid | Late Fee | Outstanding Balance"
    facts = await extractor.extract(text, [])
    assert facts == []


@pytest.mark.anyio
async def test_table_with_separator_rows(extractor: RepaymentExtractor):
    """Separator rows (dashes) are skipped."""
    text = (
        "Date | Amount | Fee | Balance\n"
        "------+--------+-----+--------\n"
        "2024-01-15 | 1000 | 0 | 9000"
    )
    facts = await extractor.extract(text, [])
    assert len(facts) == 5
    date_fact = next(f for f in facts if f.field_name == "payment_date")
    assert date_fact.value == "2024-01-15"


@pytest.mark.anyio
async def test_table_with_serial_number_column(extractor: RepaymentExtractor):
    """Tables with a leading serial number column are handled correctly."""
    text = (
        "Sr | Date | Amount | Fee | Balance\n"
        "1 | 2024-01-15 | 5000 | 100 | 45000\n"
        "2 | 2024-02-15 | 5000 | 0 | 40000"
    )
    facts = await extractor.extract(text, [])

    # Should extract 2 rows
    assert len(facts) == 10

    row1_date = next(f for f in facts if f.fact_group_id == "row_1" and f.field_name == "payment_date")
    assert row1_date.value == "2024-01-15"

    row2_date = next(f for f in facts if f.fact_group_id == "row_2" and f.field_name == "payment_date")
    assert row2_date.value == "2024-02-15"


@pytest.mark.anyio
async def test_remaining_fields_extracted_when_date_unparseable(extractor: RepaymentExtractor):
    """When date is unparseable, remaining row fields are still extracted normally."""
    text = "Date | Amount | Fee | Balance\nbogus_date | 5000 | 100 | 45000"
    facts = await extractor.extract(text, [])

    date_fact = next(f for f in facts if f.field_name == "payment_date")
    assert date_fact.value == "unparseable"
    assert date_fact.confidence == 0.0

    amount_fact = next(f for f in facts if f.field_name == "amount_paid")
    assert amount_fact.value == "5000.00"
    assert amount_fact.confidence > 0.0


@pytest.mark.anyio
async def test_remaining_fields_extracted_when_monetary_not_found(extractor: RepaymentExtractor):
    """When a monetary field is not_found, other fields in that row are still extracted."""
    text = "Date | Amount | Fee | Balance\n2024-01-15 | N/A | - | 45000"
    facts = await extractor.extract(text, [])

    amount_fact = next(f for f in facts if f.field_name == "amount_paid")
    assert amount_fact.value == "not_found"
    assert amount_fact.confidence == 0.0

    fee_fact = next(f for f in facts if f.field_name == "late_fee_charged")
    assert fee_fact.value == "not_found"
    assert fee_fact.confidence == 0.0

    balance_fact = next(f for f in facts if f.field_name == "outstanding_balance")
    assert balance_fact.value == "45000.00"
    assert balance_fact.confidence > 0.0

    date_fact = next(f for f in facts if f.field_name == "payment_date")
    assert date_fact.value == "2024-01-15"
    assert date_fact.confidence > 0.0
