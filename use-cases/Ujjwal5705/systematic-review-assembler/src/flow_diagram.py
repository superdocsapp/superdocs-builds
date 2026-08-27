import json
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from pathlib import Path


def load_counts(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def compute_derived_counts(counts: dict) -> dict:
    """All numbers a PRISMA diagram needs, derived from the raw counts —
    nothing here is typed independently of screening_counts.json."""
    total_identified = (
        sum(d["records_identified"] for d in counts["databases"])
        + counts["other_sources_identified"]
    )
    total_excluded_full_text = sum(
        r["count"] for r in counts["reports_excluded_full_text"]
    )

    return {
        "total_identified": total_identified,
        "duplicates_removed": counts["duplicates_removed"],
        "screened": counts["records_screened_title_abstract"],
        "excluded_screening": counts["records_excluded_title_abstract"],
        "sought_retrieval": counts["reports_sought_for_retrieval"],
        "not_retrieved": counts["reports_not_retrieved"],
        "assessed_full_text": counts["reports_assessed_full_text"],
        "excluded_full_text_total": total_excluded_full_text,
        "excluded_full_text_reasons": counts["reports_excluded_full_text"],
        "included_review": counts["studies_included_in_review"],
        "included_synthesis": counts["studies_included_in_synthesis"],
    }


def validate_counts(counts: dict) -> list[str]:
    """Returns a list of consistency errors, empty if the counts are internally
    coherent. This is what makes 'numbers cannot drift from the text' a checked
    guarantee rather than an assumption — run this before rendering or inserting
    anything into the manuscript."""
    d = compute_derived_counts(counts)
    errors = []

    expected_screened = d["total_identified"] - d["duplicates_removed"]
    if expected_screened != d["screened"]:
        errors.append(
            f"screened ({d['screened']}) != total_identified - duplicates_removed "
            f"({expected_screened})"
        )

    expected_sought = d["screened"] - d["excluded_screening"]
    if expected_sought != d["sought_retrieval"]:
        errors.append(
            f"sought_retrieval ({d['sought_retrieval']}) != screened - excluded_screening "
            f"({expected_sought})"
        )

    expected_assessed = d["sought_retrieval"] - d["not_retrieved"]
    if expected_assessed != d["assessed_full_text"]:
        errors.append(
            f"assessed_full_text ({d['assessed_full_text']}) != sought_retrieval - not_retrieved "
            f"({expected_assessed})"
        )

    expected_included = d["assessed_full_text"] - d["excluded_full_text_total"]
    if expected_included != d["included_review"]:
        errors.append(
            f"included_review ({d['included_review']}) != assessed_full_text - excluded_full_text_total "
            f"({expected_included})"
        )

    if d["included_synthesis"] > d["included_review"]:
        errors.append(
            f"included_synthesis ({d['included_synthesis']}) cannot exceed "
            f"included_review ({d['included_review']})"
        )

    return errors


def render_flow_diagram(
    counts: dict, output_path: str, max_height_inches: float = 9.0
) -> str:
    """Renders a PRISMA-style flow diagram as a PNG, purely from the counts dict.
    Height is capped so the image fits within a single standard page when
    embedded in an exported document — an earlier version let the image
    span multiple PDF pages awkwardly (see PROGRESS.md)."""
    d = compute_derived_counts(counts)

    fig, ax = plt.subplots(figsize=(6.5, max_height_inches))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 26)
    ax.axis("off")

    def box(y, text, height=1.6, width=8, x=1):
        rect = patches.FancyBboxPatch(
            (x, y),
            width,
            height,
            boxstyle="round,pad=0.1",
            linewidth=1.2,
            edgecolor="black",
            facecolor="white",
        )
        ax.add_patch(rect)
        ax.text(
            x + width / 2,
            y + height / 2,
            text,
            ha="center",
            va="center",
            fontsize=9,
            wrap=True,
        )

    def arrow(y_from, y_to, x=5):
        ax.annotate(
            "",
            xy=(x, y_to),
            xytext=(x, y_from),
            arrowprops=dict(arrowstyle="->", lw=1.2),
        )

    box(
        23.5,
        f"Records identified from databases (n={d['total_identified']})\n"
        f"and other sources (n={counts['other_sources_identified']})",
    )
    arrow(23.5, 21.6)
    box(20.0, f"Duplicates removed (n={d['duplicates_removed']})")
    arrow(20.0, 18.1)
    box(16.5, f"Records screened (n={d['screened']})")
    arrow(16.5, 14.6)
    box(13.0, f"Records excluded (n={d['excluded_screening']})")
    arrow(16.5, 11.1, x=6.5)
    box(9.5, f"Reports sought for retrieval (n={d['sought_retrieval']})")
    arrow(9.5, 7.6)
    box(6.0, f"Reports not retrieved (n={d['not_retrieved']})")
    arrow(9.5, 4.1, x=6.5)
    box(2.5, f"Reports assessed for eligibility (n={d['assessed_full_text']})")

    fig.savefig(output_path, dpi=110, bbox_inches="tight")
    plt.close(fig)
    return output_path


if __name__ == "__main__":
    counts = load_counts("../sample_data/screening_counts.json")
    errors = validate_counts(counts)
    if errors:
        print("Count validation FAILED:")
        for e in errors:
            print(f"  - {e}")
        raise SystemExit(1)
    path = render_flow_diagram(counts, "../output/flow_diagram.png")
    print(f"Diagram written to {path}")
    print(f"Derived counts: {json.dumps(compute_derived_counts(counts), indent=2)}")
