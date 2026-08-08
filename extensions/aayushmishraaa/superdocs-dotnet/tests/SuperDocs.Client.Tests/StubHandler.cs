using System.Net;
using System.Text;

namespace SuperDocs.Client.Tests;

/// <summary>
/// Serves canned responses so the whole suite runs with no API key and no network.
/// </summary>
/// <remarks>
/// The payloads here are copied from REAL responses observed against the live API, including
/// the awkward parts — most importantly the fact that the same proposed changes come back as
/// objects on the polling path and as a JSON-encoded string on the streaming path. A stub
/// built from what the docs imply rather than what the server sends would let the tests agree
/// with my assumptions instead of with reality.
/// </remarks>
internal sealed class StubHandler : HttpMessageHandler
{
    private readonly Func<HttpRequestMessage, HttpResponseMessage> _respond;

    public List<HttpRequestMessage> Requests { get; } = [];
    public List<string> Bodies { get; } = [];

    public StubHandler(Func<HttpRequestMessage, HttpResponseMessage> respond)
        => _respond = respond;

    public static StubHandler Json(string body, HttpStatusCode status = HttpStatusCode.OK)
        => new(_ => new HttpResponseMessage(status)
        {
            Content = new StringContent(body, Encoding.UTF8, "application/json"),
        });

    protected override async Task<HttpResponseMessage> SendAsync(
        HttpRequestMessage request, CancellationToken cancellationToken)
    {
        Requests.Add(request);
        if (request.Content is not null)
        {
            Bodies.Add(await request.Content.ReadAsStringAsync(cancellationToken));
        }

        // Honour cancellation, so cancellation tests exercise the real path rather than
        // completing before anyone can cancel them.
        cancellationToken.ThrowIfCancellationRequested();
        return _respond(request);
    }
}

internal static class Payloads
{
    /// <summary>
    /// A job awaiting approval, verbatim in shape from a real run.
    /// </summary>
    /// <remarks>
    /// Note the two encodings of the SAME change: <c>metadata.pending_changes</c> holds real
    /// objects, while <c>intermediate_responses[].content</c> holds a JSON-encoded string.
    /// </remarks>
    public const string AwaitingApproval = """
    {
      "job_id": "94d087b7-20ab-437c-953d-df88fe84dac2",
      "session_id": "s1",
      "status": "awaiting_approval",
      "progress": 88,
      "metadata": {
        "message": "Change the payment terms from net 30 to net 45 days.",
        "pending_changes": [
          {
            "change_id": "97ca364e-8ebb-4d19-8cac-ae8812663caf",
            "operation": "edit",
            "chunk_id": "70cdd20e-e8bd-476d-8500-5fda21c4df94",
            "document_id": "doc_primary",
            "old_html": "<p>Payment terms are net 30 days from invoice date.</p>",
            "new_html": "<p>Payment terms are net 45 days from invoice date.</p>",
            "ai_explanation": "I have updated the payment terms from net 30 to net 45 days."
          }
        ],
        "intermediate_responses": [
          {
            "type": "proposed_change_batch",
            "sequence": 4,
            "content": "{\"type\": \"single_approval\", \"batch_id\": \"97ca364e\", \"batch_total\": 1, \"changes\": [{\"change_id\": \"97ca364e-8ebb-4d19-8cac-ae8812663caf\", \"operation\": \"edit\", \"old_html\": \"<p>Payment terms are net 30 days from invoice date.</p>\", \"new_html\": \"<p>Payment terms are net 45 days from invoice date.</p>\"}]}"
          }
        ]
      }
    }
    """;

    public const string Completed = """
    {"job_id":"j1","session_id":"s1","status":"completed","progress":100,"metadata":{}}
    """;

    public const string ApprovalOk = """
    {"status":"ok","message":"Approval processed","batch_complete":true}
    """;

    public const string JobCreated = """
    {"job_id":"j1","session_id":"s1","status":"pending","message":"queued"}
    """;

    public const string Whoami = """
    {"account_id":"a1","tier":"free","quota":{"monthly_limit":500,"used":12,"remaining":488}}
    """;
}
