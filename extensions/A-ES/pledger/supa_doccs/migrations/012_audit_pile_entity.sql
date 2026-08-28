-- Migration 012: Allow 'pile' events in audit_events
--
-- The incremental flow's audit writes failed silently since Phase 5:
-- they used entity_type='pile', which migration 006's CHECK constraint
-- rejects (and 'incremental_update'/'watch_configured' are not legal
-- actions either). The incremental-update writer now uses conforming
-- values (entity_type='run', action='updated'); this migration adds
-- 'pile' so pile-level configuration changes (e.g. watch config) can
-- be recorded truthfully rather than failing silently.

BEGIN;

ALTER TABLE audit_events DROP CONSTRAINT chk_audit_events_entity_type;
ALTER TABLE audit_events ADD CONSTRAINT chk_audit_events_entity_type CHECK (
    entity_type IN (
        'document', 'document_version', 'claim', 'source_location',
        'run', 'run_step', 'approval_queue', 'decision', 'pile'
    )
);

COMMIT;
