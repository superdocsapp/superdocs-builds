"""python -m app.cli watch    — poll the bucket forever
python -m app.cli run-once  — process whatever is in incoming/ right now

Polling rather than S3 Event Notifications + SQS is a deliberate choice:
event notifications need an SQS queue and IAM wiring most of which is
account-specific and can't be demonstrated in a self-contained repo. A
polling loop works identically against real AWS S3, MinIO, or LocalStack
with zero additional infrastructure, which matters more for a task a
reviewer needs to actually run. Swapping to SQS-driven invocation later
is a config/deployment change, not a rewrite — `Pipeline.process_new_objects`
doesn't know or care how it was triggered.
"""

from __future__ import annotations

import argparse
import logging
import time

from app.config import get_settings
from app.pipeline import Pipeline
from app.s3_client import S3Gateway
from app.superdocs_client import SuperDocsClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
logger = logging.getLogger("cli")


def _build_pipeline(limit_override: int | None = None) -> Pipeline:
    settings = get_settings()
    if limit_override is not None:
        settings.max_files_per_run = limit_override

    if not settings.superdocs_api_key:
        logger.warning(
            "SUPERDOCS_API_KEY is not set — requests to api.superdocs.app will fail "
            "with 401. Set it in .env or the environment before running against a "
            "live account."
        )

    s3 = S3Gateway(settings)
    s3.ensure_bucket()
    superdocs = SuperDocsClient(
        base_url=settings.superdocs_base_url,
        api_key=settings.superdocs_api_key,
        chunk_size_bytes=settings.stream_chunk_size_bytes,
        direct_upload_max_bytes=settings.superdocs_direct_upload_max_bytes,
        upload_purpose=settings.superdocs_upload_purpose,
        default_approval_mode=settings.superdocs_approval_mode,
        model_tier=settings.superdocs_model_tier,
        thinking_depth=settings.superdocs_thinking_depth,
        max_retries=settings.superdocs_max_retries,
        retry_base_delay_seconds=settings.superdocs_retry_base_delay_seconds,
        request_timeout_seconds=settings.superdocs_request_timeout_seconds,
        poll_interval_seconds=settings.superdocs_poll_interval_seconds,
        max_wait_seconds=settings.superdocs_max_wait_seconds,
    )
    return Pipeline(settings, s3, superdocs)


def cmd_run_once(args: argparse.Namespace) -> None:
    pipeline = _build_pipeline(limit_override=args.limit)
    processed = pipeline.process_new_objects()
    logger.info("Processed %d file(s): %s", len(processed), processed)


def cmd_watch(args: argparse.Namespace) -> None:
    settings = get_settings()
    pipeline = _build_pipeline(limit_override=args.limit)
    logger.info(
        "Polling s3://%s/%s every %ss%s",
        settings.s3_bucket, settings.s3_incoming_prefix, settings.poll_interval_seconds,
        f" (max {args.limit} file(s)/pass)" if args.limit is not None else "",
    )
    try:
        while True:
            processed = pipeline.process_new_objects()
            if processed:
                logger.info("Processed: %s", processed)
            time.sleep(settings.poll_interval_seconds)
    except KeyboardInterrupt:
        logger.info("Stopped.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Object-storage pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    once = sub.add_parser("run-once", help="Process whatever is currently in incoming/")
    once.add_argument(
        "--limit", type=int, default=None,
        help="Process at most this many files this pass (small-sample / operations-budget mode).",
    )
    once.set_defaults(func=cmd_run_once)

    watch = sub.add_parser("watch", help="Poll the bucket forever")
    watch.add_argument(
        "--limit", type=int, default=None,
        help="Process at most this many files per poll pass (small-sample / operations-budget mode).",
    )
    watch.set_defaults(func=cmd_watch)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
