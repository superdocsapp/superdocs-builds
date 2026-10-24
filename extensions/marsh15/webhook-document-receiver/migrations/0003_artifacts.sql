CREATE TABLE artifacts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    delivery_id uuid NOT NULL UNIQUE REFERENCES deliveries(id) ON DELETE CASCADE,
    export_format varchar(32) NOT NULL,
    storage_adapter varchar(32) NOT NULL DEFAULT 'database',
    storage_key varchar(255) NOT NULL,
    content bytea NOT NULL,
    byte_size integer NOT NULL,
    sha256 char(64) NOT NULL,
    mime_type varchar(255) NOT NULL,
    filename varchar(255) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT artifacts_size_valid
        CHECK (byte_size >= 0 AND byte_size <= 10485760),
    CONSTRAINT artifacts_content_size_matches
        CHECK (octet_length(content) = byte_size),
    CONSTRAINT artifacts_sha256_format
        CHECK (sha256 ~ '^[0-9a-f]{64}$')
);
