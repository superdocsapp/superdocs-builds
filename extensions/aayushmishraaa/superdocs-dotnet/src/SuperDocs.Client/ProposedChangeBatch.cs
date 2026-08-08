using System.Text.Json;
using System.Text.Json.Serialization;

namespace SuperDocs.Client;

/// <summary>
/// A batch of proposed changes as delivered on the streaming path.
/// </summary>
/// <remarks>
/// The SSE and <c>intermediate_responses</c> paths wrap this object in a JSON-encoded STRING,
/// so reading it requires a second parse:
/// <code>JSON.parse(JSON.parse(event.data).content)</code>
/// The polling path (<c>metadata.pending_changes</c>) does not. Same data, two encodings.
/// <para>
/// <see cref="ParseContent"/> exists so that no consumer of this SDK ever has to know which
/// path they are on. It is a workaround for an API inconsistency, not a fix — every other
/// language's integrators still meet it — and the correct server-side fix is to emit
/// <c>content</c> as a real nested object on the streaming path too.
/// </para>
/// </remarks>
public sealed record ProposedChangeBatch
{
    /// <summary>Batch kind reported by the server.</summary>
    [JsonPropertyName("type")] public string Type { get; init; } = string.Empty;
    /// <summary>Identifier for this batch of changes.</summary>
    [JsonPropertyName("batch_id")] public string? BatchId { get; init; }
    /// <summary>How many changes the batch contains.</summary>
    [JsonPropertyName("batch_total")] public int BatchTotal { get; init; }

    /// <summary>The decoded changes.</summary>

    [JsonPropertyName("changes")]
    public IReadOnlyList<ProposedChange> Changes { get; init; } = [];

    /// <summary>
    /// Decode a <c>content</c> field into proposed changes, tolerating both encodings.
    /// </summary>
    /// <remarks>
    /// Returns an empty list rather than throwing on unparseable content. A malformed
    /// progress message should not take down a review the user is in the middle of — the
    /// authoritative list is always <c>Job.Metadata.PendingChanges</c>, and losing a
    /// streamed preview is a far smaller harm than losing the session.
    /// </remarks>
    public static IReadOnlyList<ProposedChange> ParseContent(string? content)
    {
        if (string.IsNullOrWhiteSpace(content))
        {
            return [];
        }

        try
        {
            string payload = content;

            // The first parse. If `content` is a JSON string literal it yields the inner
            // JSON text; if it is already an object, we keep the original.
            using (JsonDocument outer = JsonDocument.Parse(content))
            {
                if (outer.RootElement.ValueKind == JsonValueKind.String)
                {
                    payload = outer.RootElement.GetString() ?? string.Empty;
                }
            }

            if (string.IsNullOrWhiteSpace(payload))
            {
                return [];
            }

            using JsonDocument document = JsonDocument.Parse(payload);
            JsonElement root = document.RootElement;

            // A bare array of changes.
            if (root.ValueKind == JsonValueKind.Array)
            {
                return JsonSerializer.Deserialize(
                    root.GetRawText(), SuperDocsJsonContext.Default.IReadOnlyListProposedChange) ?? [];
            }

            if (root.ValueKind != JsonValueKind.Object)
            {
                return [];
            }

            // The usual shape: an object with a "changes" array.
            if (root.TryGetProperty("changes", out JsonElement changes)
                && changes.ValueKind == JsonValueKind.Array)
            {
                return JsonSerializer.Deserialize(
                    changes.GetRawText(),
                    SuperDocsJsonContext.Default.IReadOnlyListProposedChange) ?? [];
            }

            // A single change delivered without a wrapper.
            if (root.TryGetProperty("change_id", out _))
            {
                ProposedChange? single = JsonSerializer.Deserialize(
                    root.GetRawText(), SuperDocsJsonContext.Default.ProposedChange);
                return single is null ? [] : [single];
            }

            return [];
        }
        catch (JsonException)
        {
            return [];
        }
    }
}
