ALTER TABLE deliveries DROP CONSTRAINT deliveries_state_valid;
ALTER TABLE deliveries ADD CONSTRAINT deliveries_state_valid CHECK (
    state IN (
        'received', 'queued', 'preparing_document', 'starting_superdocs',
        'processing', 'awaiting_approval', 'approving', 'exporting',
        'completed', 'retry_wait', 'needs_attention', 'rejected', 'failed'
    )
);

ALTER TABLE jobs DROP CONSTRAINT jobs_state_valid;
ALTER TABLE jobs ADD CONSTRAINT jobs_state_valid CHECK (
    state IN (
        'queued', 'processing', 'awaiting_approval', 'completed',
        'retry_wait', 'needs_attention', 'rejected', 'failed'
    )
);

CREATE TABLE pending_changes (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    delivery_id uuid NOT NULL REFERENCES deliveries(id) ON DELETE CASCADE,
    external_change_id varchar(128) NOT NULL,
    operation varchar(32) NOT NULL,
    chunk_id varchar(128),
    old_html text,
    new_html text,
    ai_explanation text,
    review_state varchar(16) NOT NULL DEFAULT 'pending',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pending_changes_delivery_external_unique
        UNIQUE (delivery_id, external_change_id),
    CONSTRAINT pending_changes_operation_valid
        CHECK (operation IN ('edit', 'create', 'delete')),
    CONSTRAINT pending_changes_review_state_valid
        CHECK (review_state IN ('pending', 'approved', 'rejected'))
);

CREATE TABLE decisions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    change_id uuid NOT NULL UNIQUE REFERENCES pending_changes(id) ON DELETE CASCADE,
    approved boolean NOT NULL,
    reason varchar(1000),
    actor_id varchar(128) NOT NULL,
    batch_id uuid NOT NULL,
    decided_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX pending_changes_review_idx
ON pending_changes (delivery_id, review_state);
