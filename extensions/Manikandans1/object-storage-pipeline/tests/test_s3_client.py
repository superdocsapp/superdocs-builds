"""S3Gateway tested against moto's in-memory S3 mock — no real AWS
account, no MinIO container, no network. Everything here is pure
boto3-level behavior (listing, presigning, copy/delete for the
mark-processed move), which moto intercepts completely."""

from __future__ import annotations

import boto3
import pytest
from moto import mock_aws

from app.config import Settings
from app.s3_client import S3Gateway


@pytest.fixture
def settings() -> Settings:
    return Settings(
        s3_bucket="test-vendor-docs",
        s3_region="us-east-1",
        s3_endpoint_url=None,
    )


@mock_aws
def test_ensure_bucket_is_idempotent(settings):
    gateway = S3Gateway(settings)
    gateway.ensure_bucket()
    gateway.ensure_bucket()  # must not raise the second time

    client = boto3.client("s3", region_name="us-east-1")
    client.head_bucket(Bucket=settings.s3_bucket)  # raises if it doesn't exist


@mock_aws
def test_list_incoming_returns_only_files_under_the_prefix(settings):
    gateway = S3Gateway(settings)
    gateway.ensure_bucket()

    client = boto3.client("s3", region_name="us-east-1")
    client.put_object(Bucket=settings.s3_bucket, Key="incoming/contract.txt", Body=b"hello")
    client.put_object(Bucket=settings.s3_bucket, Key="incoming/invoice.txt", Body=b"world")
    client.put_object(Bucket=settings.s3_bucket, Key="processed/source/old.txt", Body=b"ignored")

    objects = gateway.list_incoming()
    filenames = {o.filename for o in objects}

    assert filenames == {"contract.txt", "invoice.txt"}
    assert all(o.size_bytes > 0 for o in objects)


@mock_aws
def test_presigned_urls_are_real_usable_urls(settings):
    gateway = S3Gateway(settings)
    gateway.ensure_bucket()

    client = boto3.client("s3", region_name="us-east-1")
    client.put_object(Bucket=settings.s3_bucket, Key="incoming/doc.txt", Body=b"content")

    get_url = gateway.presigned_get("incoming/doc.txt")
    put_url = gateway.presigned_put("processed/doc.txt")

    assert get_url.startswith("https://")
    assert "X-Amz-Signature" in get_url
    assert put_url.startswith("https://")
    assert "X-Amz-Signature" in put_url
    assert get_url != put_url


@mock_aws
def test_mark_processed_moves_the_object_out_of_incoming(settings):
    gateway = S3Gateway(settings)
    gateway.ensure_bucket()

    client = boto3.client("s3", region_name="us-east-1")
    client.put_object(Bucket=settings.s3_bucket, Key="incoming/doc.txt", Body=b"content")

    gateway.mark_processed("incoming/doc.txt", "doc.txt")

    # No longer in incoming/
    remaining = gateway.list_incoming()
    assert remaining == []

    # Exists under processed/source/ with the same content — a genuine
    # move, not a delete-and-forget.
    obj = client.get_object(Bucket=settings.s3_bucket, Key="processed/source/doc.txt")
    assert obj["Body"].read() == b"content"


@mock_aws
def test_result_key_uses_the_export_format_extension(settings):
    gateway = S3Gateway(settings)
    assert gateway.result_key_for("contract.txt", "pdf") == "processed/contract.pdf"
    assert gateway.result_key_for("invoice.docx", "html") == "processed/invoice.html"
