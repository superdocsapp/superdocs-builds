CREATE TABLE deliveries (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    provider text NOT NULL,
    external_delivery_id varchar(128) NOT NULL,
    event_type varchar(128) NOT NULL,
    payload_sha256 char(64) NOT NULL,
    sanitized_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    route_id varchar(128) NOT NULL,
    route_config_version varchar(64) NOT NULL,
    state varchar(32) NOT NULL DEFAULT 'received',
    received_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT deliveries_provider_id_unique
        UNIQUE (provider, external_delivery_id),
    CONSTRAINT deliveries_payload_sha256_format
        CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT deliveries_state_valid
        CHECK (state IN ('received', 'queued', 'processing', 'completed', 'failed'))
);

CREATE TABLE jobs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    delivery_id uuid NOT NULL UNIQUE REFERENCES deliveries(id) ON DELETE CASCADE,
    job_type varchar(64) NOT NULL DEFAULT 'document_workflow',
    state varchar(32) NOT NULL DEFAULT 'queued',
    attempt_count integer NOT NULL DEFAULT 0,
    available_at timestamptz NOT NULL DEFAULT now(),
    leased_by varchar(128),
    lease_until timestamptz,
    last_error_class varchar(128),
    last_error_message varchar(512),
    superdocs_session_id varchar(128),
    superdocs_job_id varchar(128),
    external_wait_kind varchar(64),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT jobs_attempt_count_nonnegative CHECK (attempt_count >= 0),
    CONSTRAINT jobs_state_valid
        CHECK (state IN ('queued', 'processing', 'completed', 'failed'))
);

CREATE INDEX jobs_claimable_idx ON jobs (available_at, created_at)
WHERE state = 'queued';
