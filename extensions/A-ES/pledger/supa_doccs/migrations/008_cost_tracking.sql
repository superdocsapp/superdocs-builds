-- Migration 008: Add per-stage cost and time tracking columns to run_steps
-- Requirements: Per-node duration and token/cost estimation

BEGIN;

-- Add cost tracking columns to run_steps (all nullable for backward compat)
ALTER TABLE run_steps
    ADD COLUMN IF NOT EXISTS duration_ms INTEGER NULL,
    ADD COLUMN IF NOT EXISTS input_tokens INTEGER NULL,
    ADD COLUMN IF NOT EXISTS output_tokens INTEGER NULL,
    ADD COLUMN IF NOT EXISTS cost_usd NUMERIC(12, 6) NULL;

-- Add constraint to ensure non-negative values when present
ALTER TABLE run_steps
    ADD CONSTRAINT chk_run_steps_duration_ms CHECK (duration_ms IS NULL OR duration_ms >= 0),
    ADD CONSTRAINT chk_run_steps_input_tokens CHECK (input_tokens IS NULL OR input_tokens >= 0),
    ADD CONSTRAINT chk_run_steps_output_tokens CHECK (output_tokens IS NULL OR output_tokens >= 0),
    ADD CONSTRAINT chk_run_steps_cost_usd CHECK (cost_usd IS NULL OR cost_usd >= 0);

COMMIT;
