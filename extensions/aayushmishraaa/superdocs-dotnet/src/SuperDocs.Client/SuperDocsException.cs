using System.Net;
using System.Text.Json;

namespace SuperDocs.Client;

/// <summary>
/// An error returned by the SuperDocs API.
/// </summary>
/// <remarks>
/// The message names the cause AND the fix wherever the status code makes that knowable.
/// "Response status code does not indicate success: 401 (Unauthorized)" tells a developer
/// nothing they could not already see; "your API key was rejected — check SuperDocs:ApiKey"
/// tells them where to look.
/// </remarks>
public sealed class SuperDocsException : Exception
{
    /// <summary>Creates an exception describing an API failure.</summary>
    /// <param name="message">Human-readable description, naming the cause and the fix.</param>
    /// <param name="statusCode">HTTP status returned by the API.</param>
    /// <param name="responseBody">Raw response body, when there was one.</param>
    public SuperDocsException(string message, HttpStatusCode statusCode, string? responseBody = null)
        : base(message)
    {
        StatusCode = statusCode;
        ResponseBody = responseBody;
        ErrorCode = ExtractField(responseBody, "error_code");
    }

    /// <summary>Creates an exception with a message.</summary>
    /// <param name="message">Human-readable description.</param>
    public SuperDocsException(string message) : base(message) { }

    /// <summary>Creates an exception wrapping another.</summary>
    /// <param name="message">Human-readable description.</param>
    /// <param name="innerException">The underlying failure.</param>
    public SuperDocsException(string message, Exception innerException)
        : base(message, innerException) { }

    /// <summary>Creates an exception with no detail.</summary>
    public SuperDocsException() { }

    /// <summary>HTTP status returned by the API.</summary>
    public HttpStatusCode StatusCode { get; }

    /// <summary>Raw response body, when there was one.</summary>
    public string? ResponseBody { get; }

    /// <summary>
    /// The server's machine-readable error code, such as <c>session_busy</c>.
    /// </summary>
    /// <remarks>
    /// Exposed because branching on a status code alone is too coarse: a 409 can mean a busy
    /// session, which is recoverable by cancelling the active job, or something else
    /// entirely. The server distinguishes them and it would be wasteful to throw that away
    /// and make callers pattern-match on prose.
    /// </remarks>
    public string? ErrorCode { get; }

    /// <summary>True when a prior job in the same session is still running.</summary>
    public bool IsSessionBusy =>
        string.Equals(ErrorCode, "session_busy", StringComparison.Ordinal);

    /// <summary>
    /// True when retrying the identical request could plausibly succeed.
    /// </summary>
    /// <remarks>
    /// Exposed so a host's resilience policy can make an informed decision. The SDK does not
    /// retry on your behalf — that belongs to your policy, not to this library.
    /// </remarks>
    public bool IsTransient => StatusCode is HttpStatusCode.RequestTimeout
        or HttpStatusCode.TooManyRequests
        or HttpStatusCode.InternalServerError
        or HttpStatusCode.BadGateway
        or HttpStatusCode.ServiceUnavailable
        or HttpStatusCode.GatewayTimeout;

    internal static string Describe(HttpStatusCode status, string body)
    {
        string detail = ExtractDetail(body);
        string suffix = string.IsNullOrWhiteSpace(detail) ? "" : $" API said: {detail}";

        return status switch
        {
            HttpStatusCode.Unauthorized =>
                "SuperDocs rejected your API key (401). Check SuperDocs:ApiKey is a current "
                + "key and starts with 'sk_'." + suffix,

            HttpStatusCode.Forbidden =>
                "SuperDocs refused this request (403). The key may lack access to this "
                + "resource, or the endpoint may require a signed-in user session rather than "
                + "an API key." + suffix,

            HttpStatusCode.Conflict =>
                "The session is busy (409). A previous job in this session is still running "
                + "or still awaiting approval. Cancel it, finish reviewing it, or use a "
                + "different session id." + suffix,

            HttpStatusCode.NotFound =>
                "Not found (404). Check the session or job id — and note that a session is "
                + "created by its first upload or chat, not by naming it." + suffix,

            HttpStatusCode.TooManyRequests =>
                "Rate limited (429). Back off and retry; if you are on a free tier you may "
                + "have exhausted the monthly operation allowance." + suffix,

            HttpStatusCode.RequestEntityTooLarge =>
                "Payload too large (413). Documents over 100 KB must use the presigned upload "
                + "path rather than base64." + suffix,

            // The server's 422 body names the offending field precisely, so it leads. An
            // earlier version led with a canned hint about approvals, which was actively
            // misleading on an UPLOAD failure — the hint pointed at the wrong endpoint
            // entirely while the real answer sat unread in the body. A guess presented ahead
            // of the facts is worse than no guess.
            HttpStatusCode.UnprocessableEntity => string.IsNullOrWhiteSpace(detail)
                ? "The request was rejected as invalid (422). On an approval, check the "
                  + "top-level 'approved' field, which is required even when per-change "
                  + "decisions are supplied."
                : $"The request was rejected as invalid (422). {detail}",

            _ => $"SuperDocs returned {(int)status} {status}.{suffix}",
        };
    }

    private static string? ExtractField(string? body, string field)
    {
        if (string.IsNullOrWhiteSpace(body))
        {
            return null;
        }

        try
        {
            using JsonDocument document = JsonDocument.Parse(body);
            return document.RootElement.TryGetProperty(field, out JsonElement value)
                ? value.GetString()
                : null;
        }
        catch (JsonException)
        {
            return null;
        }
    }

    private static string ExtractDetail(string body)
    {
        if (string.IsNullOrWhiteSpace(body))
        {
            return string.Empty;
        }

        try
        {
            using JsonDocument document = JsonDocument.Parse(body);
            foreach (string key in new[] { "detail", "message", "error" })
            {
                if (document.RootElement.TryGetProperty(key, out JsonElement value))
                {
                    return value.ToString();
                }
            }
        }
        catch (JsonException)
        {
            // Not JSON. Fall through to the truncated raw body, which is still better than
            // discarding whatever the server tried to tell us.
        }

        return body.Length > 300 ? body[..300] + "…" : body;
    }
}
