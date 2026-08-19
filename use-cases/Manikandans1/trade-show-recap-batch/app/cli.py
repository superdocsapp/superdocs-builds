"""python -m app.cli --leads fixtures/leads.csv --template fixtures/recap_template.txt --output output/"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from app.batch import run_batch
from app.config import get_settings
from app.superdocs_client import SuperDocsClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
logger = logging.getLogger("cli")


def main() -> None:
    parser = argparse.ArgumentParser(description="Trade-show lead recap batch generator")
    parser.add_argument("--leads", required=True, type=Path)
    parser.add_argument("--template", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Process at most this many leads from the CSV (small-sample / operations-budget mode).",
    )
    args = parser.parse_args()

    settings = get_settings()
    if not settings.superdocs_api_key:
        logger.warning(
            "SUPERDOCS_API_KEY is not set — requests to api.superdocs.app will fail "
            "with 401. Set it in .env or the environment before running against a "
            "live account."
        )

    client = SuperDocsClient(
        settings.superdocs_base_url,
        settings.superdocs_api_key,
        default_approval_mode=settings.superdocs_approval_mode,
        model_tier=settings.superdocs_model_tier,
        thinking_depth=settings.superdocs_thinking_depth,
        max_retries=settings.superdocs_max_retries,
        retry_base_delay_seconds=settings.superdocs_retry_base_delay_seconds,
        request_timeout_seconds=settings.superdocs_request_timeout_seconds,
        poll_interval_seconds=settings.superdocs_poll_interval_seconds,
        max_wait_seconds=settings.superdocs_max_wait_seconds,
    )

    max_leads = args.limit if args.limit is not None else settings.max_leads_per_run
    results = run_batch(
        args.leads, args.template, args.output, client, settings.export_format, max_leads=max_leads
    )

    print(f"\n{len(results)} recap document(s) generated:")
    for r in results:
        flags = []
        if r.used_fallback_notes:
            flags.append("no notes recorded")
        if r.used_fallback_next_step:
            flags.append("no next step recorded")
        if r.attempts > 1:
            flags.append(f"needed {r.attempts} attempts")
        if r.verification_issues:
            flags.append(f"VERIFICATION ISSUES: {'; '.join(r.verification_issues)}")
        flag_str = f" [{', '.join(flags)}]" if flags else ""
        print(f"  {r.lead_id} -> {r.output_path}{flag_str}")


if __name__ == "__main__":
    main()
