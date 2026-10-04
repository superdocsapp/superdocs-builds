# Working Agreements & Rules
1. **Source of Truth**: The SuperDocs Engineer Task Document.
2. **Migrations**: Always write an Alembic migration alongside any SQLAlchemy model change.
3. **Core Services**: Never touch `superdocs_client.py`'s preview chokepoint without flagging it for manual review.
4. **Resilience**: State is durable in PostgreSQL. Never rely on in-memory state for job tracking.
5. **No Scope Creep**: Stick to the mandatory requirements for the S2 Dropbox watcher. Defer extras to `NOT_DOING.md`.
