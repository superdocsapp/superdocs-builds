# Studio Dropbox Watcher — one page

**Built by:** Shlok Chauhan
**Assigned build:** Dropbox folder watcher with write-back
**Who it serves:** A small studio or freelancer collective whose business already lives in Dropbox.

## What it does

A client drops a file into a nominated shared folder. The watcher waits until Dropbox has finished writing it, ignores anything we already wrote back, and sends the file through SuperDocs (upload → edit instruction → human review → approve → export). The finished file is stored beside the original as `{basename}.superdocs.{treatment}{ext}`. Treatments: normalize, companion brief, or standard response.

## Measured

- **89** pytest cases, **~19s**, **no live API key**.
- Claims under test: half-written files wait; own outputs never re-queue; two workers cannot claim the same job; preview mode spends **zero** SuperDocs operations; reject writes **nothing** back; crash after review resumes without a second upload.
- Clone to running: `docker-compose up -d --build` then `alembic upgrade head`. Console: `http://localhost:5173`.

## Trade-offs

Polling is the source of truth because Dropbox webhooks only say “something changed.” A generated access token is enough at this scope; per-client OAuth would dominate the build. Approve/reject is job-level because SuperDocs’ four-call contract approves a document, not a hunk. Client isolation is path scoping under each client’s Dropbox root, not Dropbox shared-link ACLs.

## Honest limits

Without tokens the console can still seed a job for UI review. Preview jobs never produce a live SuperDocs diff. The first SuperDocs request in a cold session can stall; that is their product, not this watcher. This is an integration **on** SuperDocs, not a clone.

## SuperDocs surfaces used

Upload, chat (including the double JSON parse on proposed changes), approve, export. Optional webhook receiver; daemon poll covers discovery.
