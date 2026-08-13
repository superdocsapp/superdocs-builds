# Live Sigma writeback spike

Status: **TODO — blocked on a Zoho Sigma/Writer account and connection credentials.**

Goal: determine whether the target Writer/Sigma environment provides a verified, selection-scoped replacement path and native Track Changes behavior. This spike must not use confidential documents.

## Setup

1. Create a disposable Writer document containing:
   - `Alpha UNIQUE_OLD Omega`
   - one richly formatted selected phrase
   - one selected table-cell phrase
2. Build the workspace bundle with the target workspace's ignored connector overlay.
3. In Sigma, run a temporary diagnostic branch that only:
   - reads `SelectedContent` as HTML immediately before the action;
   - calls the candidate documented host API;
   - records the resolved response/error locally in developer tools.
4. Never place API keys, connector JSON, document contents, or account identifiers in committed evidence.

## Selection replacement checks

Run each case with Track Changes off, then on:

1. Select only `UNIQUE_OLD`.
2. Confirm a fresh `SelectedContent` read exactly equals the expected captured selection.
3. Invoke the candidate host operation with `UNIQUE_NEW`.
4. Inspect the document, undo history, and any native review mark.
5. Repeat for rich text and table-cell selections.
6. Repeat after intentionally moving/collapsing the selection; the guarded implementation must refuse before dispatch.

Pass only if all scoped cases replace exactly one active selection, leave surrounding text/formatting untouched, and never append/duplicate at the cursor. Cursor-only insertion, ambiguous placement, or formatting loss is a failure.

## Native Track Changes checks

1. Enable Writer's native Track Changes in the UI.
2. Repeat the plain and rich-text replacement checks.
3. Verify the result appears as a native Writer tracked replacement, can be accepted/rejected through Writer review controls, and survives DOCX export/reopen.
4. Check whether Sigma exposes a **documented** API to read or enable the Track Changes state. An observed but undocumented event does not pass.

Pass only if native review marks are real Writer primitives and remain intact after export. Visual styling that merely resembles a redline is a failure.

## Evidence

- Date / tester: TODO
- Zoho Writer and Sigma environment/version: TODO
- Candidate documented API and documentation URL: TODO
- Plain selection result: TODO
- Rich-text selection result: TODO
- Table-cell selection result: TODO
- Moved-selection refusal result: TODO
- Native Track Changes result: TODO
- DOCX reopen result: TODO
- Sanitized console response/error: TODO
- Overall verdict: TODO

## Implementation gate

Writeback may be implemented only after the evidence above passes for an explicitly declared content scope. The implementation must remain off by default until then, compare a fresh exact selection with the captured expected selection immediately before mutation, reject unsupported `create`, `delete`, and `insert_after_chunk_id` proposals, avoid mapping SuperDocs structural HTML onto Zoho HTML, and include offline adapter tests plus a repeatable live regression test.
