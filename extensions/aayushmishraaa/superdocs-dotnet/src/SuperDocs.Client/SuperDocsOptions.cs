using System.ComponentModel.DataAnnotations;

namespace SuperDocs.Client;

/// <summary>
/// Configuration for <see cref="ISuperDocsClient"/>.
/// </summary>
/// <remarks>
/// Deliberately small. There is no retry count, no backoff curve, no circuit-breaker
/// threshold and no telemetry switch, because those belong to the host: an application that
/// has already decided how it retries should not have a second, different opinion smuggled
/// in by a client library. Add <c>AddStandardResilienceHandler()</c> to the returned builder
/// and the whole application shares one policy.
/// </remarks>
public sealed class SuperDocsOptions
{
    /// <summary>Configuration section name used by <c>AddSuperDocs(IConfiguration)</c>.</summary>
    public const string SectionName = "SuperDocs";

    /// <summary>Your API key. Starts with <c>sk_</c>.</summary>
    [Required(AllowEmptyStrings = false, ErrorMessage =
        "SuperDocs:ApiKey is required. Set it in configuration, or via the SUPERDOCS_API_KEY " +
        "environment variable. Never commit it.")]
    public string ApiKey { get; set; } = string.Empty;

    /// <summary>API base address.</summary>
    /// <remarks>
    /// Defaulted here because the published OpenAPI document has no <c>servers</c> block, so
    /// a generated client comes out with no base address and fails at the first call with a
    /// relative-URI error that does not point back at the spec.
    /// </remarks>
    [Required]
    public Uri BaseAddress { get; set; } = new("https://api.superdocs.app/");

    /// <summary>
    /// How long to wait for a single HTTP response.
    /// </summary>
    /// <remarks>
    /// Five minutes, which is far longer than a typical HTTP default and is deliberate:
    /// operations on large documents, or runs at the deepest model settings, legitimately
    /// take from thirty seconds to several minutes with no interim output. A 100-second
    /// default would turn "still working" into a spurious timeout.
    /// <para>
    /// Prefer cancelling through a <see cref="CancellationToken"/> over shortening this.
    /// </para>
    /// </remarks>
    public TimeSpan Timeout { get; set; } = TimeSpan.FromMinutes(5);

    /// <summary>How often <c>WaitForApprovalAsync</c> and <c>WaitForCompletionAsync</c> poll.</summary>
    public TimeSpan PollInterval { get; set; } = TimeSpan.FromSeconds(2);

    /// <summary>
    /// Value sent as <c>User-Agent</c>. Identifying your application helps when you need
    /// support to find your requests.
    /// </summary>
    public string? UserAgent { get; set; }

    internal void Validate()
    {
        if (string.IsNullOrWhiteSpace(ApiKey))
        {
            throw new InvalidOperationException(
                "SuperDocs:ApiKey is not configured. Set SuperDocs:ApiKey in configuration or " +
                "the SUPERDOCS_API_KEY environment variable, then register with " +
                "services.AddSuperDocs(configuration).");
        }

        if (!ApiKey.StartsWith("sk_", StringComparison.Ordinal))
        {
            // A wrong-shaped key otherwise surfaces as an opaque 401 on the first real call,
            // usually far from the configuration mistake that caused it.
            throw new InvalidOperationException(
                $"SuperDocs:ApiKey does not look like an API key (expected it to start with " +
                $"'sk_', got '{ApiKey[..Math.Min(3, ApiKey.Length)]}...'). Check you have not " +
                $"pasted a session token or a placeholder.");
        }
    }
}
