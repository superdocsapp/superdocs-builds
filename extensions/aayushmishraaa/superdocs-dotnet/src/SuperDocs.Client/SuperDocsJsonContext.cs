using System.Text.Json;
using System.Text.Json.Serialization;

namespace SuperDocs.Client;

/// <summary>
/// Source-generated serialization metadata.
/// </summary>
/// <remarks>
/// Every type crossing the wire is declared here so serialization is compiled rather than
/// discovered by reflection at runtime. That is what makes the package trim- and
/// AOT-friendly: a trimmed host would otherwise strip the model types it cannot see being
/// used, and fail at runtime with a message that says nothing about trimming.
/// <para>
/// It is also measurably faster to start, which matters for the worker sample: a background
/// service that processes one file and exits pays reflection startup cost every time.
/// </para>
/// </remarks>
[JsonSourceGenerationOptions(
    PropertyNamingPolicy = JsonKnownNamingPolicy.SnakeCaseLower,
    DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
    // The API adds fields over time. Ignoring unknown members means a server-side addition
    // is a non-event for existing consumers rather than a deserialization failure.
    UnmappedMemberHandling = JsonUnmappedMemberHandling.Skip)]
[JsonSerializable(typeof(ProposedChange))]
[JsonSerializable(typeof(IReadOnlyList<ProposedChange>))]
[JsonSerializable(typeof(ProposedChangeBatch))]
[JsonSerializable(typeof(IntermediateResponse))]
[JsonSerializable(typeof(JobMetadata))]
[JsonSerializable(typeof(Job))]
[JsonSerializable(typeof(IReadOnlyList<Job>))]
[JsonSerializable(typeof(SessionJobsResponse))]
[JsonSerializable(typeof(ApprovalDecision))]
[JsonSerializable(typeof(IReadOnlyList<ApprovalDecision>))]
[JsonSerializable(typeof(ApprovalResult))]
[JsonSerializable(typeof(ChatJobCreated))]
[JsonSerializable(typeof(AccountStatus))]
[JsonSerializable(typeof(Quota))]
[JsonSerializable(typeof(UploadedDocument))]
[JsonSerializable(typeof(ChatRequest))]
[JsonSerializable(typeof(ChatAsyncRequest))]
[JsonSerializable(typeof(ApprovalRequest))]
[JsonSerializable(typeof(ExportRequest))]
[JsonSerializable(typeof(UploadBase64Request))]
[JsonSerializable(typeof(ApiErrorBody))]
internal sealed partial class SuperDocsJsonContext : JsonSerializerContext;

// ---------------------------------------------------------------- request bodies --

internal sealed record ChatRequest
{
    [JsonPropertyName("message")] public required string Message { get; init; }
    [JsonPropertyName("session_id")] public required string SessionId { get; init; }
    [JsonPropertyName("document_html")] public string? DocumentHtml { get; init; }
}

internal sealed record ChatAsyncRequest
{
    [JsonPropertyName("message")] public required string Message { get; init; }
    [JsonPropertyName("session_id")] public required string SessionId { get; init; }
    [JsonPropertyName("document_html")] public string? DocumentHtml { get; init; }
    [JsonPropertyName("approval_mode")] public string? ApprovalMode { get; init; }
}

internal sealed record ApprovalRequest
{
    [JsonPropertyName("job_id")] public required string JobId { get; init; }

    /// <summary>
    /// Required by the API even when per-change decisions are supplied in
    /// <see cref="Changes"/>. Omitting it is rejected, which is not obvious from the docs.
    /// </summary>
    [JsonPropertyName("approved")] public required bool Approved { get; init; }

    [JsonPropertyName("change_id")] public string? ChangeId { get; init; }
    [JsonPropertyName("feedback")] public string? Feedback { get; init; }
    [JsonPropertyName("changes")] public IReadOnlyList<ApprovalDecision>? Changes { get; init; }
}

internal sealed record ExportRequest
{
    [JsonPropertyName("session_id")] public string? SessionId { get; init; }
    [JsonPropertyName("html")] public string? Html { get; init; }
    [JsonPropertyName("format")] public required string Format { get; init; }
    [JsonPropertyName("filename")] public string? Filename { get; init; }
}

internal sealed record UploadBase64Request
{
    [JsonPropertyName("filename")] public required string Filename { get; init; }

    /// <summary>
    /// Base64 file content. The field is <c>file_base64</c>, NOT <c>content_base64</c>.
    /// </summary>
    /// <remarks>
    /// Guessed wrong first time and only found out by calling the live API, which returned a
    /// 422 naming the missing field. A stub built from my own assumption accepted the wrong
    /// shape happily — the exact failure mode of testing against mocks that encode what you
    /// believe rather than what the server does.
    /// </remarks>
    [JsonPropertyName("file_base64")] public required string FileBase64 { get; init; }

    [JsonPropertyName("session_id")] public string? SessionId { get; init; }

    /// <summary>Ask for the parsed HTML back, so a caller can edit without a second fetch.</summary>
    [JsonPropertyName("return_html")] public bool ReturnHtml { get; init; } = true;
}

/// <summary>Envelope returned by GET /v1/sessions/{id}/jobs.</summary>
/// <remarks>
/// The endpoint returns an OBJECT with a "jobs" array, not a bare array. Modelling it as a
/// list deserialised to nothing and made a wedged session look empty.
/// </remarks>
internal sealed record SessionJobsResponse
{
    [JsonPropertyName("jobs")] public IReadOnlyList<Job> Jobs { get; init; } = [];
    [JsonPropertyName("total")] public int Total { get; init; }
}

internal sealed record ApiErrorBody
{
    [JsonPropertyName("detail")] public JsonElement Detail { get; init; }
    [JsonPropertyName("message")] public string? Message { get; init; }
    [JsonPropertyName("error")] public string? Error { get; init; }
}
