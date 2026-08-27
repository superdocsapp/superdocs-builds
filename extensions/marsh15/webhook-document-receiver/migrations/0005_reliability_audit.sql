ALTER TABLE jobs
ADD COLUMN retry_count integer NOT NULL DEFAULT 0,
ADD COLUMN external_effect_started_at timestamptz;

ALTER TABLE jobs
ADD CONSTRAINT jobs_retry_count_nonnegative CHECK (retry_count >= 0);

CREATE TABLE delivery_transitions (
    id bigserial PRIMARY KEY,
    delivery_id uuid NOT NULL REFERENCES deliveries(id) ON DELETE CASCADE,
    previous_state varchar(32),
    next_state varchar(32) NOT NULL,
    reason_code varchar(128) NOT NULL,
    sanitized_detail jsonb NOT NULL DEFAULT '{}'::jsonb,
    actor_type varchar(32) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT delivery_transitions_actor_valid
        CHECK (actor_type IN ('ingress', 'worker', 'administrator', 'system'))
);

CREATE INDEX delivery_transitions_timeline_idx
ON delivery_transitions (delivery_id, created_at, id);

CREATE FUNCTION record_delivery_transition() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO delivery_transitions (
            delivery_id, previous_state, next_state, reason_code, actor_type
        ) VALUES (NEW.id, NULL, NEW.state, 'delivery_created', 'ingress');
    ELSIF OLD.state IS DISTINCT FROM NEW.state THEN
        INSERT INTO delivery_transitions (
            delivery_id, previous_state, next_state, reason_code, actor_type
        ) VALUES (NEW.id, OLD.state, NEW.state, 'state_changed', 'system');
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER deliveries_transition_audit
AFTER INSERT OR UPDATE OF state ON deliveries
FOR EACH ROW EXECUTE FUNCTION record_delivery_transition();
