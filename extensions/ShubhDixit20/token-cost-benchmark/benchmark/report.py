"""
Turns data/results/raw_edits.csv into published tables + charts.

Publishes (into the results dir):
  - summary_by_arm.csv           : totals and per-edit means by arm
  - summary_by_tier_and_arm.csv  : the actual finding — cost/tokens by doc
                                    size tier x arm, i.e. "the curve, not
                                    one number"
  - cumulative_session_cost.png  : cumulative $ across a multi-turn session,
                                    both arms, per tier
  - cost_vs_doc_size.png         : per-edit cost vs. document size, both arms
  - variance_report.csv          : mean/stdev per (tier, edit_type, arm) when
                                    repeats > 1
"""
from __future__ import annotations

import re
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


def _tier_from_doc_id(doc_id: str) -> str:
    # doc_id like "small-00" -> "small"
    m = re.match(r"([a-z]+)-\d+", doc_id)
    return m.group(1) if m else doc_id


TIER_ORDER = ["tiny", "small", "medium", "large", "xlarge"]


def load_records(results_dir: Path) -> pd.DataFrame:
    csv_path = results_dir / "raw_edits.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"No raw_edits.csv in {results_dir}. Run the benchmark first.")
    df = pd.read_csv(csv_path)
    df["tier"] = df["doc_id"].apply(_tier_from_doc_id)
    df["tier"] = pd.Categorical(df["tier"], categories=TIER_ORDER, ordered=True)
    return df


def build_reports(results_dir: Path) -> None:
    df = load_records(results_dir)

    # --- summary by arm ---------------------------------------------------
    by_arm = df.groupby("arm").agg(
        num_edits=("task_id", "count"),
        total_input_tokens=("input_tokens", "sum"),
        total_output_tokens=("output_tokens", "sum"),
        total_cost_usd=("cost_usd", "sum"),
        mean_cost_usd=("cost_usd", "mean"),
        total_wall_clock_s=("wall_clock_s", "sum"),
        mean_chars_sent=("chars_sent", "mean"),
    ).reset_index()
    by_arm.to_csv(results_dir / "summary_by_arm.csv", index=False)

    # --- summary by tier x arm (the actual finding) -----------------------
    by_tier_arm = df.groupby(["tier", "arm"], observed=True).agg(
        num_edits=("task_id", "count"),
        mean_input_tokens=("input_tokens", "mean"),
        mean_output_tokens=("output_tokens", "mean"),
        mean_cost_usd=("cost_usd", "mean"),
        mean_chars_sent=("chars_sent", "mean"),
        mean_wall_clock_s=("wall_clock_s", "mean"),
    ).reset_index()
    by_tier_arm.to_csv(results_dir / "summary_by_tier_and_arm.csv", index=False)

    # --- variance report (only meaningful if repeats > 1) ------------------
    df["repeat"] = df["task_id"].str.extract(r"^r(\d+)-").astype(int)
    if df["repeat"].nunique() > 1:
        variance = df.groupby(["tier", "edit_type", "arm"], observed=True)["cost_usd"].agg(
            ["mean", "std", "count"]
        ).reset_index()
        variance.to_csv(results_dir / "variance_report.csv", index=False)

    # --- chart: cost vs doc size, both arms --------------------------------
    fig, ax = plt.subplots(figsize=(8, 5))
    for arm, group in df.groupby("arm"):
        tier_means = group.groupby("tier", observed=True)["cost_usd"].mean()
        tier_means = tier_means.reindex(TIER_ORDER).dropna()
        ax.plot(tier_means.index.astype(str), tier_means.values, marker="o", label=arm)
    ax.set_xlabel("Document size tier")
    ax.set_ylabel("Mean cost per edit (USD, estimated)")
    ax.set_title("Cost per edit vs. document size, by arm")
    ax.legend()
    fig.tight_layout()
    fig.savefig(results_dir / "cost_vs_doc_size.png", dpi=150)
    plt.close(fig)

    # --- chart: cumulative session cost, both arms, largest tier available -
    largest_tier = None
    for t in reversed(TIER_ORDER):
        if (df["tier"] == t).any():
            largest_tier = t
            break

    if largest_tier:
        fig, ax = plt.subplots(figsize=(8, 5))
        subset = df[df["tier"] == largest_tier].copy()
        for arm, group in subset.groupby("arm"):
            group = group.sort_values(["doc_id", "turn"])
            cum = group.groupby("doc_id")["cost_usd"].cumsum()
            # average cumulative cost by turn number across docs in this tier
            group = group.assign(cum_cost=cum)
            by_turn = group.groupby("turn")["cum_cost"].mean()
            ax.plot(by_turn.index, by_turn.values, marker="o", label=arm)
        ax.set_xlabel("Turn number in session")
        ax.set_ylabel("Mean cumulative cost (USD, estimated)")
        ax.set_title(f"Cumulative multi-turn session cost, by arm (tier={largest_tier})")
        ax.legend()
        fig.tight_layout()
        fig.savefig(results_dir / "cumulative_session_cost.png", dpi=150)
        plt.close(fig)

    print(f"Wrote reports to {results_dir}/")


if __name__ == "__main__":
    import sys
    results_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/results")
    build_reports(results_dir)
