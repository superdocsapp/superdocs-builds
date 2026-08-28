-- Migration 001: Enable extensions and create schema_migrations table
-- Requirements: 8.1, 8.2, 8.3, 8.4

BEGIN;

-- Enable pgcrypto for gen_random_uuid() support
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Enable vector for embedding storage
CREATE EXTENSION IF NOT EXISTS vector;

-- Create schema_migrations table to track applied migrations
CREATE TABLE IF NOT EXISTS schema_migrations (
    id INTEGER PRIMARY KEY,
    filename VARCHAR(255) NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMIT;
