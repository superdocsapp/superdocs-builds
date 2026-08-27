# Agent-to-Agent Document Handoff

## The Problem Statement

When multiple AI agents work on the same document in sequence, there is no shared contract that defines what each agent may change, whether it is acting on the current document, or how a violation should be detected. This project addresses that problem with a small, generic, versioned handoff contract and an independently enforced validation layer.

## `SPEC.md`

[`SPEC.md`](SPEC.md) is the main deliverable.
It is a standalone specification for implementing a compatible handoff envelope, agents, validator, and orchestrator. The specification defines the schema, validation rules, review-state behavior, versioning requirements, diff-based enforcement, and rejection semantics without depending on this reference implementation.

## Setup

From the repository root, run:

```bash
cd extensions/agent-handoff-spec
uv sync
```

Copy the environment template in this directory:

```bash
cp .env.example .env
```

Update the `.env` file with the following values:

```dotenv
GOOGLE_API_KEY=your_google_api_key
SUPERDOCS_API_KEY=your_superdocs_api_key
```

Run the test suite with:

```bash
uv run pytest -v
```

## Preparing a SuperDocs document

1. Create a document in SuperDocs using [`assets/Invoice-2026-1.docx`](assets/Invoice-2026-1.docx).
   This is a fake, generated invoice used for the demo. The example agents expect this particular document structure, which is why this asset is the one used by the walkthrough.
2. Get the `session_id`. It appears in the browser start information with the prefix `session_editor_client_`.
3. Get the durable `document_id` by sending this request, including an `Authorization` header containing your `SUPERDOCS_API_KEY`:

   ```bash
   curl https://api.superdocs.app/v1/sessions/{session_id}/documents \
     -H "Authorization: Bearer ${SUPERDOCS_API_KEY}"
   ```

   The response contains `durable_document_id`; we will use that value as the `SUPERDOCS_DOCUMENT_ID` for the env.

4. Update the `.env` file with the `session_id` and `durable_document_id`.

   ```dotenv
   SUPERDOCS_DOCUMENT_ID=durable_document_id
   SUPERDOCS_SESSION_ID=session_id
   ```

5. Now we are ready to run the demo scripts.

Before running either demo, close the SuperDocs browser tab. If it remains open, the browser session can mismatch the script session and the browser may override the changes applied by the agents. After a script finishes, visit <https://use.superdocs.app> and inspect the resulting document.

## Demos

There are two end-to-end demos:

### Happy path

```bash
uv run python scripts/run_fetched_demo.py
```

The happy path passes the document through the reference agents. It corrects the spelling in the prose and checks the invoice pricing math.

### Rejected path

```bash
uv run python scripts/run_rejection_demo.py
```

The rejected path deliberately lets an agent change a section outside its declared scope. The independent validator catches and rejects that real violation. The output includes a result like:

```text
validation_2_accepted=False
validation_2_reason=action changed sections outside scope: notes
```

## Project components

- **Agents** receive an envelope and document snapshot, validate both, act only within their assigned scope, and issue the next envelope. The example spelling agent handles prose corrections; the pricing agent checks the invoice table's mathematics.
- **Orchestrator** coordinates the sequence, passes document state and envelopes between agents, derives the actual changed-section diff, invokes the validator, and records the run trace.
- **Validator** is independent of the agents. It checks the envelope and the observable result of each action, including document identity, review state, scope, restrictions, and forbidden actions. It returns a human-readable reason for every rejection.
- **Schema** contains the versioned handoff envelope definition and its strict structural guarantees.
- **SuperDocs client** connects the reference flow to the document backend.
- **Tests** cover valid handoffs, malformed and stale inputs, review-state protections, scope violations, and forbidden actions.

## How the Pieces Fit Together

![Workflow Diagram](/extensions/Sheikh-JamirAlam/agent-handoff-spec/assets/image.png)

Every handoff is a schema-validated envelope. Agents perform the assigned work, while the independent validator checks what actually changed rather than trusting an agent's self-report. Unknown envelope versions, unknown fields, malformed scope boundaries, stale documents, and out-of-scope changes are rejected explicitly.
