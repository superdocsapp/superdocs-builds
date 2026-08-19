"""Thin boto3 wrapper. Every operation here either lists metadata or
generates a pre-signed URL — nothing in this module ever calls
get_object/put_object to move bytes through the orchestrator's process.
Bytes flow directly between S3 and SuperDocs over the pre-signed URLs;
this client's job is only to hand out and manage those URLs."""

from __future__ import annotations

from dataclasses import dataclass

import boto3
from botocore.client import Config as BotoConfig

from app.config import Settings


@dataclass
class IncomingObject:
    key: str
    filename: str
    size_bytes: int


class S3Gateway:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            region_name=settings.s3_region,
            config=BotoConfig(signature_version="s3v4"),
        )

    def ensure_bucket(self) -> None:
        """Idempotent bucket creation — safe to call on every startup,
        useful for MinIO/LocalStack where the bucket doesn't pre-exist."""
        try:
            self._client.head_bucket(Bucket=self._settings.s3_bucket)
        except Exception:
            self._client.create_bucket(Bucket=self._settings.s3_bucket)

    def list_incoming(self) -> list[IncomingObject]:
        prefix = self._settings.s3_incoming_prefix
        resp = self._client.list_objects_v2(
            Bucket=self._settings.s3_bucket, Prefix=prefix
        )
        objects = []
        for item in resp.get("Contents", []):
            key = item["Key"]
            if key == prefix:  # the "directory marker" itself, not a file
                continue
            objects.append(
                IncomingObject(
                    key=key,
                    filename=key[len(prefix):],
                    size_bytes=item["Size"],
                )
            )
        return objects

    def presigned_get(self, key: str) -> str:
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._settings.s3_bucket, "Key": key},
            ExpiresIn=self._settings.presigned_url_ttl_seconds,
        )

    def presigned_put(self, key: str, content_type: str = "application/octet-stream") -> str:
        return self._client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": self._settings.s3_bucket,
                "Key": key,
                "ContentType": content_type,
            },
            ExpiresIn=self._settings.presigned_url_ttl_seconds,
        )

    def mark_processed(self, incoming_key: str, filename: str) -> None:
        """Moves the source key out of incoming/ so the poller doesn't
        pick it up again. This is a metadata-only S3-side copy+delete —
        S3 server-side copy never routes bytes through the orchestrator
        either."""
        processed_key = f"{self._settings.s3_processed_prefix}source/{filename}"
        self._client.copy_object(
            Bucket=self._settings.s3_bucket,
            CopySource={"Bucket": self._settings.s3_bucket, "Key": incoming_key},
            Key=processed_key,
        )
        self._client.delete_object(Bucket=self._settings.s3_bucket, Key=incoming_key)

    def result_key_for(self, filename: str, export_format: str) -> str:
        stem = filename.rsplit(".", 1)[0]
        return f"{self._settings.s3_processed_prefix}{stem}.{export_format}"
