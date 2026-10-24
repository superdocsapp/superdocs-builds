CREATE UNIQUE INDEX deliveries_github_payload_digest_unique
ON deliveries (payload_sha256)
WHERE provider = 'github';
