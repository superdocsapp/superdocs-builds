# SuperDocs.Client — .NET SDK

A .NET client for the [SuperDocs](https://use.superdocs.app) document-editing API, built the
way a Microsoft-stack team would expect: registered through `IHttpClientFactory`, so pooling,
resilience and telemetry come from your host rather than being reinvented inside a library you
did not write.

Built by **Aayush Mishra** for the SuperDocs engineer task.

---

## Install

```bash
dotnet add package SuperDocs.Client
```

Targets **.NET 10** (current LTS, supported to Nov 2028) and **.NET 8** (previous LTS, to
Nov 10 2026). Multi-targeted rather than 10-only because enterprise teams are frequently a
release behind, and those are exactly the people who cannot upgrade on someone else's schedule.

## Use it

```csharp
builder.Services.AddSuperDocs(builder.Configuration);
```

That is the whole registration. It returns the `IHttpClientBuilder`, so your policies apply:

```csharp
builder.Services
    .AddSuperDocs(builder.Configuration)
    .AddStandardResilienceHandler();     // your retries, your circuit breaker, your timeouts
```

```json
{ "SuperDocs": { "ApiKey": "sk_your_key_here" } }
```

Then inject `ISuperDocsClient`:

```csharp
await client.UploadDocumentAsync(sessionId, "contract.docx", bytes, ct);

ChatJobCreated job = await client.StartEditAsync(
    sessionId, "Change the payment terms from net 30 to net 45.", ct: ct);

// Drives the ENTIRE review, including the rounds you did not know about — see below.
Job final = await client.ReviewAsync(sessionId, job.JobId, async (changes, ct) =>
{
    foreach (ProposedChange c in changes)
        Console.WriteLine($"[{c.Operation}] {c.AiExplanation}");

    return await MyReviewUi.AskAsync(changes, ct);   // approve some, reject others
}, cancellationToken: ct);

ExportedFile file = await client.ExportAsync(sessionId, ExportFormat.Docx, ct: ct);
await file.SaveAsAsync("contract-updated.docx", ct);
```

---

## What this SDK does for you

Four things that cost me real time to discover, each handled once here so they cost you none.

### 1. The proposed-change double encoding

The API returns the **same** proposed changes two different ways. `metadata.pending_changes`
(polling) gives real objects; `intermediate_responses[].content` and the SSE stream give a
**JSON-encoded string** needing a second parse.

Guidance describing the second parse as universal is therefore true of one path and false of
the other — apply it to the polling path and you get an exception, skip it on the streaming
path and you get nothing. Both directions break.

This SDK decodes both. `PendingChanges` and `IntermediateResponse.Changes` yield the same
`ProposedChange` objects, and there is no path on which you must know which one you are on.

### 2. A large edit arrives in several approval rounds

This is not documented anywhere I could find, and the obvious client shape is wrong:

```csharp
// WRONG — polls forever. I watched this reach 146 requests.
await client.ApproveAsync(sessionId, jobId, decisions, ct);
await client.WaitForCompletionAsync(jobId, ct);
```

After you approve a batch, the job returns to `awaiting_approval` with **more** changes. Use
`ReviewAsync`, which loops until the job actually finishes.

### 3. Unknown values degrade instead of disappearing

An unrecognised `operation` used to make the whole `ProposedChange` fail to deserialise — so
the change **vanished from the review** and a human would approve a batch without being shown
one of its edits. Unknown values now map to `ChangeOperation.Unknown` and the change stays
visible, with its before-and-after HTML intact.

### 4. Errors name the cause and the fix

```
SuperDocs rejected your API key (401). Check SuperDocs:ApiKey is a current key and
starts with 'sk_'.
```

rather than `Response status code does not indicate success: 401 (Unauthorized)`.

Where the server sends a specific detail it **leads** with that, because a canned hint printed
ahead of the facts is worse than no hint — an earlier version advised checking an approval
field during an *upload* failure while the server's answer sat unread underneath.

`SuperDocsException` also exposes `ErrorCode` and `IsTransient`, so your resilience policy can
branch on facts rather than pattern-match prose.

---

## Async discipline

Every method is `async` and takes a `CancellationToken`. There is **no synchronous overload
anywhere**, deliberately — a blocking wrapper around an async call is the classic ASP.NET
deadlock, and offering one invites the misuse. `ConfigureAwait(false)` throughout; a test
asserts the surface stays fully async so it cannot regress.

## Trim and AOT

`System.Text.Json` source generation for every wire type, no reflection-based serialization,
`IsTrimmable` and `IsAotCompatible` on. Configuration is bound by hand rather than with
`.Bind()`, because reflection binding is not trim-safe and would quietly undermine the claim.

---

## Run the sample

A worker service that watches a folder, applies house branding, and exports the result.

```bash
cd samples/SuperDocs.Worker.Sample
export SUPERDOCS_API_KEY=sk_your_key_here
dotnet run
```

Drop a `.docx`, `.md` or `.pdf` into `inbox/`; the branded result appears in `outbox/`.

**`AutoApprove` defaults to `false`.** An unattended worker that approves its own edits has no
human gate, and a sample that pretended otherwise would teach the wrong shape. With it off the
worker prints each proposed change and applies nothing. Set `Watcher__AutoApprove=true` where
that risk is genuinely acceptable.

The sample also recovers from a wedged session: if a previous run abandoned a review, it finds
the stale job and resolves it. Note it does this by **denying** the pending changes, not by
cancelling — `cancel_job` returns `400 "Job cannot be cancelled"` on an `awaiting_approval`
job, despite the API's own `suggested_action` recommending exactly that.

## Run the tests

```bash
dotnet test
```

38 tests. **No API key, no network.** The stub payloads are copied from real responses,
including the awkward parts — a stub built from what the docs imply rather than what the
server sends is how I shipped a wrong upload field name in the first place.

---

## Honest limitations

- **Large uploads are not implemented.** Only the base64 path (<100 KB). The presigned
  `/v1/uploads` flow is the correct route for bigger files and is not wrapped here.
- **Multi-document sessions are not wrapped.** The API supports tabs, focus and per-document
  operations; this client models a single active document per session.
- **Templates are not wrapped.** The sample brands via an instruction, not by uploading a
  reusable template.
- **`ReviewAsync` bounds itself at 20 rounds** and throws rather than looping. That is a guess
  at "unreasonable", not a measured limit.
- **The SSE parser handles the event shapes I observed.** It ignores frames it does not
  recognise rather than failing, so an unfamiliar event type is silently skipped — the
  authoritative list is always `Job.Metadata.PendingChanges`.

## License

MIT.
