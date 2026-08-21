"""The pathology catalogue.

Cases are data, not code. Adding a pathology is a new entry here; it needs no
change to the generator, the extractor, the comparator or the runner.

Each case names one cell as the edit target. Everything else in the document
is an invariant: after the edit round-trip it must come back unchanged. That
asymmetry is the whole measurement -- a system that mangles nothing but also
changes nothing is not passing, and neither is one that makes the edit and
flattens the table around it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

AXES = ("merged_cells", "nested_tables", "spanning_headers", "numeric_formatting")

HDR = "D9E2F3"
ALT = "F2F2F2"


@dataclass
class Case:
    id: str
    title: str
    axis: str
    edit: str
    target: tuple[int, int, int]        # (table index, row, col) in the grid
    also_changes: list[tuple[int, int, int]] = field(default_factory=list)
    """Other cells the instruction legitimately asks to change.

    An instruction that names two figures must exempt both. Declaring only one
    makes the benchmark report the model for obeying it, which is a false
    finding and worse than no finding at all."""
    expect_contains: str | None = None  # proof the edit actually landed
    intro: str = ""
    tables: list[dict] = field(default_factory=list)
    trailing_paragraphs: list[str] = field(default_factory=list)
    notes: str = ""


def _row(*cells) -> list[dict]:
    out = []
    for c in cells:
        out.append({"text": c} if isinstance(c, str) else c)
    return out


CASES: list[Case] = [

    # ---------------- merged cells ----------------
    Case(
        id="merge_horizontal_header",
        title="Horizontal merge across a header",
        axis="merged_cells",
        notes="A single header cell spanning three data columns.",
        tables=[{
            "header_rows": [0],
            "rows": [
                _row({"text": "Region", "rowspan": 2, "fill": HDR, "bold": True},
                     {"text": "Quarterly revenue", "colspan": 3, "fill": HDR, "bold": True,
                      "align": "center"}),
                _row({"text": "Q1", "fill": HDR, "bold": True},
                     {"text": "Q2", "fill": HDR, "bold": True},
                     {"text": "Q3", "fill": HDR, "bold": True}),
                _row("North", "1,204.50", "1,388.00", "1,401.25"),
                _row("South", "980.00", "1,012.75", "1,150.00"),
            ],
        }],
        edit="In the first table, change the Q2 value on the South row to 1,099.40. "
             "Change nothing else.",
        target=(0, 3, 2),
        expect_contains="1,099.40",
    ),

    Case(
        id="merge_vertical_label",
        title="Vertical merge on a stub column",
        axis="merged_cells",
        notes="A row label merged down three body rows.",
        tables=[{
            "rows": [
                _row({"text": "Division", "fill": HDR, "bold": True},
                     {"text": "Line item", "fill": HDR, "bold": True},
                     {"text": "Amount", "fill": HDR, "bold": True, "align": "right"}),
                _row({"text": "Upstream", "rowspan": 3, "valign": "center"},
                     "Drilling", {"text": "4,210.00", "align": "right"}),
                _row("Completion", {"text": "1,875.50", "align": "right"}),
                _row("Logistics", {"text": "962.25", "align": "right"}),
                _row({"text": "Downstream", "rowspan": 2, "valign": "center"},
                     "Refining", {"text": "7,430.00", "align": "right"}),
                _row("Distribution", {"text": "2,118.75", "align": "right"}),
            ],
        }],
        edit="Change the Logistics amount to 1,004.00. Leave every other cell alone.",
        target=(0, 3, 2),
        expect_contains="1,004.00",
    ),

    Case(
        id="merge_l_shaped",
        title="L-shaped merge: row span and column span in one table",
        axis="merged_cells",
        notes="Vertical and horizontal merges interlocking; the classic case "
              "that collapses to a flat grid when a converter resolves spans naively.",
        tables=[{
            "rows": [
                _row({"text": "Asset", "rowspan": 2, "fill": HDR, "bold": True},
                     {"text": "Planned", "colspan": 2, "fill": HDR, "bold": True,
                      "align": "center"},
                     {"text": "Actual", "rowspan": 2, "fill": HDR, "bold": True}),
                _row({"text": "Start", "fill": HDR}, {"text": "Finish", "fill": HDR}),
                _row("Platform A", "2026-01-04", "2026-02-18", "2026-02-25"),
                _row({"text": "Shutdown window", "colspan": 4, "fill": ALT,
                      "align": "center", "bold": True}),
                _row("Platform B", "2026-03-01", "2026-04-12", "2026-04-09"),
            ],
        }],
        edit="Change the Actual date for Platform A to 2026-03-02. Change nothing else.",
        target=(0, 2, 3),
        expect_contains="2026-03-02",
    ),

    Case(
        id="merge_full_row_divider",
        title="Full-width merged row used as a section divider",
        axis="merged_cells",
        tables=[{
            "rows": [
                _row({"text": "Item", "fill": HDR, "bold": True},
                     {"text": "Qty", "fill": HDR, "bold": True},
                     {"text": "Unit", "fill": HDR, "bold": True},
                     {"text": "Total", "fill": HDR, "bold": True}),
                _row({"text": "Section 1 - Mechanical", "colspan": 4, "fill": ALT,
                      "bold": True}),
                _row("Gasket set", "12", "18.40", "220.80"),
                _row({"text": "Section 2 - Electrical", "colspan": 4, "fill": ALT,
                      "bold": True}),
                _row("Cable tray", "40", "31.00", "1,240.00"),
            ],
        }],
        edit="Change the quantity of Cable tray to 46 and its total to 1,426.00.",
        target=(0, 4, 1),
        also_changes=[(0, 4, 3)],
        expect_contains="46",
    ),

    Case(
        id="merge_containing_nested",
        title="Nested table inside a merged cell",
        axis="merged_cells",
        notes="Merge and nesting combined -- each is survivable alone; together "
              "they are where most converters give up.",
        tables=[{
            "col_widths": [1800, 2600],
            "rows": [
                _row({"text": "Package", "fill": HDR, "bold": True},
                     {"text": "Breakdown", "fill": HDR, "bold": True}),
                _row({"text": "Turnaround 2026", "rowspan": 2, "valign": "center"},
                     {"text": "", "nested": {
                         "col_widths": [1300, 1100],
                         "rows": [
                             _row({"text": "Phase", "bold": True},
                                  {"text": "Days", "bold": True}),
                             _row("Prep", "9"),
                             _row("Execution", "21"),
                         ],
                     }}),
                _row("Contingency 4 days"),
            ],
        }],
        edit="In the nested breakdown table, change Execution from 21 to 24 days.",
        target=(0, 1, 1),
        expect_contains="24",
    ),

    # ---------------- nested tables ----------------
    Case(
        id="nested_simple",
        title="Table inside a cell",
        axis="nested_tables",
        tables=[{
            "col_widths": [2000, 2600],
            "rows": [
                _row({"text": "Vendor", "fill": HDR, "bold": True},
                     {"text": "Rates", "fill": HDR, "bold": True}),
                _row("Halberd Services", {"text": "", "nested": {
                    "col_widths": [1400, 1000],
                    "rows": [
                        _row("Day rate", "1,450.00"),
                        _row("Standby", "610.00"),
                    ],
                }}),
            ],
        }],
        edit="Change the standby rate in the nested table to 645.00.",
        target=(0, 1, 1),
        expect_contains="645.00",
    ),

    Case(
        id="nested_two_deep",
        title="Two levels of nesting",
        axis="nested_tables",
        notes="Depth is where chunk-id schemes usually stop addressing cells.",
        tables=[{
            "col_widths": [1800, 3400],
            "rows": [
                _row({"text": "Contract", "fill": HDR, "bold": True},
                     {"text": "Structure", "fill": HDR, "bold": True}),
                _row("MSA-2026-11", {"text": "", "nested": {
                    "col_widths": [1200, 2000],
                    "rows": [
                        _row("Schedule A", {"text": "", "nested": {
                            "col_widths": [900, 900],
                            "rows": [
                                _row("Tier 1", "0.85"),
                                _row("Tier 2", "0.72"),
                            ],
                        }}),
                        _row("Schedule B", "See annex"),
                    ],
                }}),
            ],
        }],
        edit="In the innermost table, change the Tier 2 value to 0.70.",
        target=(0, 1, 1),
        expect_contains="0.70",
    ),

    Case(
        id="nested_side_by_side",
        title="Two nested tables in adjacent cells of one row",
        axis="nested_tables",
        tables=[{
            "col_widths": [2400, 2400],
            "rows": [
                _row({"text": "Before", "fill": HDR, "bold": True},
                     {"text": "After", "fill": HDR, "bold": True}),
                _row({"text": "", "nested": {
                    "col_widths": [1100, 1100],
                    "rows": [_row("Flow", "412"), _row("Pressure", "88.4")],
                }},
                     {"text": "", "nested": {
                         "col_widths": [1100, 1100],
                         "rows": [_row("Flow", "455"), _row("Pressure", "91.0")],
                     }}),
            ],
        }],
        edit="In the After table, change Pressure to 92.6.",
        target=(0, 1, 1),
        expect_contains="92.6",
    ),

    # ---------------- spanning headers ----------------
    Case(
        id="header_two_level",
        title="Two-level spanning header",
        axis="spanning_headers",
        tables=[{
            "header_rows": [0, 1],
            "rows": [
                _row({"text": "Well", "rowspan": 2, "fill": HDR, "bold": True},
                     {"text": "Production", "colspan": 2, "fill": HDR, "bold": True,
                      "align": "center"},
                     {"text": "Downtime", "colspan": 2, "fill": HDR, "bold": True,
                      "align": "center"}),
                _row({"text": "Oil", "fill": HDR}, {"text": "Gas", "fill": HDR},
                     {"text": "Planned", "fill": HDR}, {"text": "Unplanned", "fill": HDR}),
                _row("A-14", "1,240", "3,880", "6.0", "1.5"),
                _row("A-15", "980", "2,410", "4.5", "0.0"),
            ],
        }],
        edit="Change the unplanned downtime for A-15 to 2.5.",
        target=(0, 3, 4),
        expect_contains="2.5",
    ),

    Case(
        id="header_three_level",
        title="Three-level spanning header",
        axis="spanning_headers",
        notes="Three header tiers with spans at two of them.",
        tables=[{
            "header_rows": [0, 1, 2],
            "col_widths": [1500, 1100, 1100, 1100, 1100],
            "rows": [
                _row({"text": "Facility", "rowspan": 3, "fill": HDR, "bold": True},
                     {"text": "2026", "colspan": 4, "fill": HDR, "bold": True,
                      "align": "center"}),
                _row({"text": "H1", "colspan": 2, "fill": HDR, "align": "center"},
                     {"text": "H2", "colspan": 2, "fill": HDR, "align": "center"}),
                _row({"text": "Q1", "fill": HDR}, {"text": "Q2", "fill": HDR},
                     {"text": "Q3", "fill": HDR}, {"text": "Q4", "fill": HDR}),
                _row("Terminal 1", "18.2", "19.0", "17.4", "20.1"),
                _row("Terminal 2", "11.9", "12.3", "12.0", "13.8"),
            ],
        }],
        edit="Change the Q3 figure for Terminal 1 to 18.9.",
        target=(0, 3, 3),
        expect_contains="18.9",
    ),

    Case(
        id="header_repeat_flag",
        title="Repeating header rows across a long table",
        axis="spanning_headers",
        notes="w:tblHeader on two rows; the repeat flag is invisible on page one "
              "and silently dropped by most round-trips.",
        tables=[{
            "header_rows": [0, 1],
            "rows": [
                _row({"text": "Tag", "rowspan": 2, "fill": HDR, "bold": True},
                     {"text": "Readings", "colspan": 2, "fill": HDR, "bold": True,
                      "align": "center"}),
                _row({"text": "Min", "fill": HDR}, {"text": "Max", "fill": HDR}),
            ] + [
                _row(f"PT-{100 + i}", f"{2.0 + i * 0.13:.2f}", f"{9.0 + i * 0.21:.2f}")
                for i in range(28)
            ],
        }],
        edit="Change the Max reading on the PT-105 row to 12.00.",
        target=(0, 7, 2),
        expect_contains="12.00",
    ),

    Case(
        id="header_rotated_text",
        title="Rotated header cells",
        axis="spanning_headers",
        tables=[{
            "header_rows": [0],
            "col_widths": [1800, 700, 700, 700],
            "rows": [
                _row({"text": "Component", "fill": HDR, "bold": True},
                     {"text": "Inspected", "fill": HDR, "dir": "btLr", "valign": "bottom"},
                     {"text": "Cleaned", "fill": HDR, "dir": "btLr", "valign": "bottom"},
                     {"text": "Replaced", "fill": HDR, "dir": "btLr", "valign": "bottom"}),
                _row("Seal ring", "Y", "Y", "N"),
                _row("Impeller", "Y", "N", "N"),
            ],
        }],
        edit="On the Impeller row, change Replaced from N to Y.",
        target=(0, 2, 3),
        expect_contains="Y",
    ),

    # ---------------- numeric formatting ----------------
    Case(
        id="num_thousands_currency",
        title="Thousands separators and currency symbols",
        axis="numeric_formatting",
        tables=[{
            "rows": [
                _row({"text": "Account", "fill": HDR, "bold": True},
                     {"text": "Opening", "fill": HDR, "bold": True, "align": "right"},
                     {"text": "Closing", "fill": HDR, "bold": True, "align": "right"}),
                _row("Operating", {"text": "$1,204,880.00", "align": "right"},
                     {"text": "$1,190,455.20", "align": "right"}),
                _row("Reserve", {"text": "$88,000.00", "align": "right"},
                     {"text": "$92,500.00", "align": "right"}),
                _row("Escrow", {"text": "$0.00", "align": "right"},
                     {"text": "$15,000.00", "align": "right"}),
            ],
        }],
        edit="Change the Reserve closing balance to $94,750.00.",
        target=(0, 2, 2),
        expect_contains="$94,750.00",
    ),

    Case(
        id="num_negative_parentheses",
        title="Negatives in parentheses and em-dash zeros",
        axis="numeric_formatting",
        notes="Accounting convention: (1,234.00) means negative, an em dash "
              "means nil. A model that normalizes these has changed the meaning.",
        tables=[{
            "rows": [
                _row({"text": "Line", "fill": HDR, "bold": True},
                     {"text": "Variance", "fill": HDR, "bold": True, "align": "right"}),
                _row("Labour", {"text": "(12,400.00)", "align": "right"}),
                _row("Materials", {"text": "3,150.00", "align": "right"}),
                _row("Freight", {"text": "\u2014", "align": "right"}),
                _row("Permits", {"text": "(875.50)", "align": "right"}),
            ],
        }],
        edit="Change the Materials variance to 3,480.00.",
        target=(0, 2, 1),
        expect_contains="3,480.00",
    ),

    Case(
        id="num_trailing_zeros",
        title="Significant trailing zeros and fixed precision",
        axis="numeric_formatting",
        notes="1.230 is not 1.23 in an instrument reading.",
        tables=[{
            "rows": [
                _row({"text": "Instrument", "fill": HDR, "bold": True},
                     {"text": "Reading", "fill": HDR, "bold": True, "align": "right"},
                     {"text": "Tolerance", "fill": HDR, "bold": True, "align": "right"}),
                _row("FT-201", {"text": "1.230", "align": "right"},
                     {"text": "\u00b10.005", "align": "right"}),
                _row("FT-202", {"text": "12.500", "align": "right"},
                     {"text": "\u00b10.010", "align": "right"}),
                _row("FT-203", {"text": "0.900", "align": "right"},
                     {"text": "\u00b10.050", "align": "right"}),
            ],
        }],
        edit="Change the FT-202 reading to 12.480.",
        target=(0, 2, 1),
        expect_contains="12.480",
    ),

    Case(
        id="num_leading_zero_ids",
        title="Leading-zero identifiers that must not become integers",
        axis="numeric_formatting",
        tables=[{
            "rows": [
                _row({"text": "Part no.", "fill": HDR, "bold": True},
                     {"text": "Batch", "fill": HDR, "bold": True},
                     {"text": "Qty", "fill": HDR, "bold": True, "align": "right"}),
                _row("0041-77", "0007", {"text": "18", "align": "right"}),
                _row("0100-02", "0012", {"text": "6", "align": "right"}),
                _row("9000-01", "0100", {"text": "44", "align": "right"}),
            ],
        }],
        edit="Change the quantity on the 0100-02 row to 9.",
        target=(0, 2, 2),
        expect_contains="9",
    ),

    Case(
        id="num_percent_scientific",
        title="Percentages, scientific notation and units",
        axis="numeric_formatting",
        tables=[{
            "rows": [
                _row({"text": "Metric", "fill": HDR, "bold": True},
                     {"text": "Value", "fill": HDR, "bold": True, "align": "right"}),
                _row("Availability", {"text": "99.87%", "align": "right"}),
                _row("Leak rate", {"text": "3.2\u00d710\u207b\u2076 mbar\u00b7L/s",
                                   "align": "right"}),
                _row("Efficiency", {"text": "0.4%", "align": "right"}),
                _row("Throughput", {"text": "1.4 \u00d7 10\u2076 m\u00b3/d", "align": "right"}),
            ],
        }],
        edit="Change Availability to 99.92%.",
        target=(0, 1, 1),
        expect_contains="99.92%",
    ),

    Case(
        id="num_mixed_date_formats",
        title="Mixed date and time formats in one column",
        axis="numeric_formatting",
        tables=[{
            "rows": [
                _row({"text": "Event", "fill": HDR, "bold": True},
                     {"text": "Timestamp", "fill": HDR, "bold": True}),
                _row("Trip", "2026-03-04 08:12:47Z"),
                _row("Restart", "04/03/2026 09:05"),
                _row("Report filed", "4 March 2026"),
            ],
        }],
        edit="Change the Restart timestamp to 04/03/2026 09:40.",
        target=(0, 2, 1),
        expect_contains="09:40",
    ),

    # ---------------- structure and invariance ----------------
    Case(
        id="struct_wide_fixed_layout",
        title="Wide table with fixed layout and explicit column widths",
        axis="merged_cells",
        notes="Column widths are the quietest thing to lose; nothing looks "
              "broken, the table is just no longer the shape it was.",
        tables=[{
            "layout": "fixed",
            "col_widths": [1600, 700, 700, 700, 700, 700, 700, 900],
            "header_rows": [0],
            "rows": [
                _row({"text": "Line", "fill": HDR, "bold": True},
                     *[{"text": m, "fill": HDR, "bold": True, "align": "center"}
                       for m in ("Jan", "Feb", "Mar", "Apr", "May", "Jun")],
                     {"text": "YTD", "fill": HDR, "bold": True, "align": "right"}),
                _row("Volume", "412", "398", "444", "460", "451", "470",
                     {"text": "2,635", "align": "right"}),
                _row("Downtime", "6.0", "2.5", "0.0", "1.5", "3.0", "0.5",
                     {"text": "13.5", "align": "right"}),
            ],
        }],
        edit="Change the March volume to 448 and the YTD volume to 2,639.",
        target=(0, 1, 3),
        also_changes=[(0, 1, 7)],
        expect_contains="448",
    ),

    Case(
        id="struct_shading_borders",
        title="Alternating row shading with per-cell borders",
        axis="merged_cells",
        tables=[{
            "header_rows": [0],
            "rows": [
                _row({"text": "Check", "fill": HDR, "bold": True},
                     {"text": "Result", "fill": HDR, "bold": True},
                     {"text": "Signed", "fill": HDR, "bold": True}),
                _row({"text": "Isolation verified", "fill": ALT},
                     {"text": "Pass", "fill": ALT,
                      "borders": {"bottom": ("18", "2E7D32")}},
                     {"text": "RK", "fill": ALT}),
                _row("Gas test", {"text": "Pass",
                                  "borders": {"bottom": ("18", "2E7D32")}}, "RK"),
                _row({"text": "Pressure hold", "fill": ALT},
                     {"text": "Fail", "fill": ALT,
                      "borders": {"bottom": ("18", "C62828")}},
                     {"text": "RK", "fill": ALT}),
            ],
        }],
        edit="Change the Pressure hold result from Fail to Pass.",
        target=(0, 3, 1),
        expect_contains="Pass",
    ),
]


# Every case gets the same surrounding prose. If a round-trip rewrites body
# text that was never mentioned, that is a finding too.
for _c in CASES:
    _c.intro = _c.intro or (
        "The table below is a fixture. Only the cell named in the instruction "
        "may change."
    )
    if not _c.trailing_paragraphs:
        _c.trailing_paragraphs = [
            "Prepared for benchmark purposes. All figures are fabricated.",
            "Reference: TFB/" + _c.id.upper(),
        ]


BY_ID = {c.id: c for c in CASES}


def select(ids: list[str] | None = None, axis: str | None = None,
           limit: int | None = None) -> list[Case]:
    out = CASES
    if ids:
        out = [BY_ID[i] for i in ids]
    if axis:
        out = [c for c in out if c.axis == axis]
    if limit is not None:
        out = out[:limit]
    return out
