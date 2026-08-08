using System.Text.Json.Serialization;

namespace SuperDocs.Client;

/// <summary>What a proposed change does to the document.</summary>
[JsonConverter(typeof(TolerantEnumConverter<ChangeOperation>))]
public enum ChangeOperation
{
    /// <summary>Unrecognised. Present so a new server-side operation does not throw.</summary>
    Unknown = 0,

    /// <summary>Modify an existing section. Has both <c>OldHtml</c> and <c>NewHtml</c>.</summary>
    [JsonStringEnumMemberName("edit")] Edit,

    /// <summary>Add a new section. Has <c>NewHtml</c> and <c>InsertAfterChunkId</c>.</summary>
    [JsonStringEnumMemberName("create")] Create,

    /// <summary>Remove a section. Has <c>OldHtml</c>.</summary>
    [JsonStringEnumMemberName("delete")] Delete,
}

/// <summary>One edit the AI proposes, awaiting a human decision.</summary>
public sealed record ProposedChange
{
    /// <summary>Identifier to quote back when approving or rejecting this change.</summary>
    [JsonPropertyName("change_id")] public string ChangeId { get; init; } = string.Empty;
    /// <summary>What this change does to the document.</summary>
    [JsonPropertyName("operation")] public ChangeOperation Operation { get; init; }
    /// <summary>The document section this change applies to.</summary>
    [JsonPropertyName("chunk_id")] public string? ChunkId { get; init; }
    /// <summary>The document within a multi-document session.</summary>
    [JsonPropertyName("document_id")] public string? DocumentId { get; init; }

    /// <summary>The section as it stands. Null for <see cref="ChangeOperation.Create"/>.</summary>
    [JsonPropertyName("old_html")] public string? OldHtml { get; init; }

    /// <summary>The section as proposed. Null for <see cref="ChangeOperation.Delete"/>.</summary>
    [JsonPropertyName("new_html")] public string? NewHtml { get; init; }

    /// <summary>For a create, the section this one is inserted after.</summary>
    [JsonPropertyName("insert_after_chunk_id")] public string? InsertAfterChunkId { get; init; }

    /// <summary>The AI's own explanation. Worth showing beside the diff.</summary>
    [JsonPropertyName("ai_explanation")] public string? AiExplanation { get; init; }
}

/// <summary>Status of an asynchronous chat job.</summary>
[JsonConverter(typeof(TolerantEnumConverter<JobStatus>))]
public enum JobStatus
{
    /// <summary>Unrecognised. Present so a new server-side status does not throw.</summary>
    Unknown = 0,

    /// <summary>Queued, not yet started.</summary>
    [JsonStringEnumMemberName("pending")] Pending,
    /// <summary>Running.</summary>
    [JsonStringEnumMemberName("in_progress")] InProgress,

    /// <summary>Waiting for a human. <c>Metadata.PendingChanges</c> holds what to review.</summary>
    [JsonStringEnumMemberName("awaiting_approval")] AwaitingApproval,

    /// <summary>Finished successfully.</summary>
    [JsonStringEnumMemberName("completed")] Completed,
    /// <summary>Finished unsuccessfully. See <see cref="Job.Error"/>.</summary>
    [JsonStringEnumMemberName("failed")] Failed,
    /// <summary>Cancelled before completion.</summary>
    [JsonStringEnumMemberName("cancelled")] Cancelled,
}

/// <summary>A message emitted while a job runs.</summary>
public sealed record IntermediateResponse
{
    /// <summary>Event kind, for example <c>proposed_change_batch</c> or <c>user_facing</c>.</summary>
    [JsonPropertyName("type")] public string Type { get; init; } = string.Empty;
    /// <summary>Where in the pipeline this was emitted.</summary>
    [JsonPropertyName("context")] public string? Context { get; init; }
    /// <summary>Monotonic ordering within the job.</summary>
    [JsonPropertyName("sequence")] public int Sequence { get; init; }
    /// <summary>When the server emitted this.</summary>
    [JsonPropertyName("timestamp")] public DateTimeOffset? Timestamp { get; init; }

    /// <summary>
    /// Raw content. For <c>type == "proposed_change_batch"</c> this is a JSON-ENCODED STRING
    /// rather than an object; use <see cref="Changes"/>, which unwraps it for you.
    /// </summary>
    [JsonPropertyName("content")] public string? Content { get; init; }

    /// <summary>
    /// The proposed changes carried by this response, already decoded.
    /// </summary>
    /// <remarks>
    /// This is the property that exists because of a real inconsistency in the API: the same
    /// proposed changes are encoded two different ways depending on how you fetch them.
    /// <c>metadata.pending_changes</c> (the polling path) returns real objects, while
    /// <c>intermediate_responses[].content</c> and the SSE stream return a JSON-encoded
    /// STRING that needs a second parse. Guidance describing the second parse as universal
    /// is therefore true of one path and false of the other, and applying it to the wrong one
    /// throws.
    /// <para>
    /// Rather than pass that on, this SDK handles it: poll or stream, you get
    /// <see cref="ProposedChange"/> objects either way, and there is no path on which a
    /// consumer must know about the encoding at all.
    /// </para>
    /// </remarks>
    [JsonIgnore]
    public IReadOnlyList<ProposedChange> Changes =>
        _changes ??= ProposedChangeBatch.ParseContent(Content);

    private IReadOnlyList<ProposedChange>? _changes;
}

/// <summary>Metadata attached to a job.</summary>
public sealed record JobMetadata
{
    /// <summary>The instruction that started this job.</summary>
    [JsonPropertyName("message")] public string? Message { get; init; }

    /// <summary>
    /// Changes awaiting a decision. On this path they are real objects — do NOT apply a
    /// second JSON parse to them.
    /// </summary>
    [JsonPropertyName("pending_changes")]
    public IReadOnlyList<ProposedChange> PendingChanges { get; init; } = [];

    /// <summary>Progress messages emitted while the job ran.</summary>
    [JsonPropertyName("intermediate_responses")]
    public IReadOnlyList<IntermediateResponse> IntermediateResponses { get; init; } = [];

    /// <summary>What kind of decision the job is waiting for.</summary>
    [JsonPropertyName("awaiting_kind")] public string? AwaitingKind { get; init; }

    /// <summary>Decisions already recorded, so a reloaded UI can skip them.</summary>
    [JsonPropertyName("pending_batch_decisions")]
    public IReadOnlyList<ApprovalDecision> PendingBatchDecisions { get; init; } = [];
}

/// <summary>An asynchronous chat job.</summary>
public sealed record Job
{
    /// <summary>Server-assigned job identifier.</summary>
    [JsonPropertyName("job_id")] public string JobId { get; init; } = string.Empty;
    /// <summary>Session this job belongs to.</summary>
    [JsonPropertyName("session_id")] public string SessionId { get; init; } = string.Empty;
    /// <summary>Current status.</summary>
    [JsonPropertyName("status")] public JobStatus Status { get; init; }
    /// <summary>Rough completion percentage. Advisory only.</summary>
    [JsonPropertyName("progress")] public int Progress { get; init; }
    /// <summary>Failure reason, when the job failed.</summary>
    [JsonPropertyName("error")] public string? Error { get; init; }
    /// <summary>When the job was created.</summary>
    [JsonPropertyName("created_at")] public DateTimeOffset? CreatedAt { get; init; }
    /// <summary>When the job last changed.</summary>
    [JsonPropertyName("updated_at")] public DateTimeOffset? UpdatedAt { get; init; }
    /// <summary>Pending changes and progress detail.</summary>
    [JsonPropertyName("metadata")] public JobMetadata Metadata { get; init; } = new();

    /// <summary>True when a human decision is required before anything else can happen.</summary>
    [JsonIgnore] public bool IsAwaitingApproval => Status == JobStatus.AwaitingApproval;

    /// <summary>True when the job will not progress further without intervention.</summary>
    [JsonIgnore]
    public bool IsTerminal =>
        Status is JobStatus.Completed or JobStatus.Failed or JobStatus.Cancelled;
}

/// <summary>A per-change verdict.</summary>
public sealed record ApprovalDecision
{
    /// <summary>The change this verdict applies to.</summary>
    [JsonPropertyName("change_id")] public string ChangeId { get; init; } = string.Empty;
    /// <summary>True to apply the change, false to discard it.</summary>
    [JsonPropertyName("approved")] public bool Approved { get; init; }
    /// <summary>Optional reason. Sent to the AI to inform later suggestions.</summary>
    [JsonPropertyName("feedback")] public string? Feedback { get; init; }

    /// <summary>Creates an approving verdict for one change.</summary>
    public static ApprovalDecision Approve(string changeId, string? feedback = null)
        => new() { ChangeId = changeId, Approved = true, Feedback = feedback };

    /// <summary>Creates a rejecting verdict for one change.</summary>
    public static ApprovalDecision Reject(string changeId, string? feedback = null)
        => new() { ChangeId = changeId, Approved = false, Feedback = feedback };
}

/// <summary>Result of an approval call.</summary>
public sealed record ApprovalResult
{
    /// <summary>Server status string, normally <c>ok</c>.</summary>
    [JsonPropertyName("status")] public string Status { get; init; } = string.Empty;
    /// <summary>Human-readable detail.</summary>
    [JsonPropertyName("message")] public string? Message { get; init; }
    /// <summary>True when every change in the batch has been decided.</summary>
    [JsonPropertyName("batch_complete")] public bool BatchComplete { get; init; }
}

/// <summary>Response from starting an asynchronous chat.</summary>
public sealed record ChatJobCreated
{
    /// <summary>Poll this with <c>GetJobAsync</c>.</summary>
    [JsonPropertyName("job_id")] public string JobId { get; init; } = string.Empty;
    /// <summary>Session the job runs in.</summary>
    [JsonPropertyName("session_id")] public string SessionId { get; init; } = string.Empty;
    /// <summary>Initial status.</summary>
    [JsonPropertyName("status")] public JobStatus Status { get; init; }
    /// <summary>Server acknowledgement text.</summary>
    [JsonPropertyName("message")] public string? Message { get; init; }
}

/// <summary>Quota and tier for the current account.</summary>
public sealed record AccountStatus
{
    /// <summary>Your account identifier.</summary>
    [JsonPropertyName("account_id")] public string AccountId { get; init; } = string.Empty;
    /// <summary>Subscription tier, for example <c>free</c>.</summary>
    [JsonPropertyName("tier")] public string Tier { get; init; } = string.Empty;
    /// <summary>Monthly operation allowance and usage.</summary>
    [JsonPropertyName("quota")] public Quota Quota { get; init; } = new();
}

/// <summary>Monthly operation allowance.</summary>
public sealed record Quota
{
    /// <summary>Operations included per month.</summary>
    [JsonPropertyName("monthly_limit")] public int MonthlyLimit { get; init; }
    /// <summary>Operations consumed this period.</summary>
    [JsonPropertyName("used")] public int Used { get; init; }
    /// <summary>Operations still available.</summary>
    [JsonPropertyName("remaining")] public int Remaining { get; init; }
    /// <summary>When the allowance resets.</summary>
    [JsonPropertyName("resets_at")] public DateTimeOffset? ResetsAt { get; init; }
}

/// <summary>An uploaded document.</summary>
public sealed record UploadedDocument
{
    /// <summary>Session the document was uploaded into.</summary>
    [JsonPropertyName("session_id")] public string SessionId { get; init; } = string.Empty;
    /// <summary>Server-assigned document identifier.</summary>
    [JsonPropertyName("document_id")] public string? DocumentId { get; init; }
    /// <summary>Name the document was stored under.</summary>
    [JsonPropertyName("filename")] public string? Filename { get; init; }
    /// <summary>Parsed document HTML, with chunk ids for targeted editing.</summary>
    [JsonPropertyName("html")] public string? Html { get; init; }
}

/// <summary>Export formats.</summary>
public enum ExportFormat
{
    /// <summary>Word document. The default.</summary>
    Docx = 0,
    /// <summary>PDF.</summary>
    Pdf,
    /// <summary>HTML.</summary>
    Html,
    /// <summary>Markdown.</summary>
    Markdown,
    /// <summary>Plain text.</summary>
    Txt,
}

/// <summary>An exported file.</summary>
/// <remarks>
/// <paramref name="Content"/> is a <see cref="ReadOnlyMemory{T}"/> rather than a byte array
/// so callers cannot mutate the buffer behind the record, and so slicing is free.
/// Use <c>Content.Span</c> to write it, or prefer
/// <c>ISuperDocsClient.ExportToStreamAsync</c> for anything large.
/// </remarks>
public sealed record ExportedFile(string FileName, string ContentType, ReadOnlyMemory<byte> Content)
{
    /// <summary>Size of the exported file in bytes.</summary>
    public long Length => Content.Length;

    /// <summary>Writes the exported bytes to a file.</summary>
    public async Task SaveAsAsync(string path, CancellationToken cancellationToken = default)
    {
        FileStream stream = File.Create(path);
        await using (stream.ConfigureAwait(false))
        {
            await stream.WriteAsync(Content, cancellationToken).ConfigureAwait(false);
        }
    }
}
