ALTER TABLE jobs
ADD COLUMN input_data jsonb NOT NULL DEFAULT '{}'::jsonb;
