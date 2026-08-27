ALTER TABLE jobs
ADD COLUMN route_config jsonb NOT NULL DEFAULT '{}'::jsonb;
