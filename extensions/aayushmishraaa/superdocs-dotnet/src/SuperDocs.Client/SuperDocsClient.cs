using System.Net;
using System.Net.Http.Json;
using System.Runtime.CompilerServices;
using System.Text;
using System.Text.Json;
using Microsoft.Extensions.Options;

namespace SuperDocs.Client;

/// <inheritdoc cref="ISuperDocsClient"/>
public sealed class SuperDocsClient : ISuperDocsClient
{
    private readonly HttpClient _http;
    private readonly SuperDocsOptions _options;

    /// <summary>
    /// Constructed by dependency injection. The <see cref="HttpClient"/> comes from
    /// <c>IHttpClientFactory</c>, so its lifetime, pooling and handler pipeline belong to the
    /// host — this class neither creates nor disposes it.
    /// </summary>
    public SuperDocsClient(HttpClient httpClient, IOptions<SuperDocsOptions> options)
    {
        _http = httpClient ?? throw new ArgumentNullException(nameof(httpClient));
        _options = options?.Value ?? throw new ArgumentNullException(nameof(options));
    }

    // ------------------------------------------------------------------ upload --

    /// <inheritdoc/>
    public async Task<UploadedDocument> UploadDocumentAsync(
        string sessionId,
        string fileName,
        ReadOnlyMemory<byte> content,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(sessionId);
        ArgumentException.ThrowIfNullOrWhiteSpace(fileName);

        UploadBase64Request body = new()
        {
            Filename = fileName,
            FileBase64 = Convert.ToBase64String(content.Span),
            SessionId = sessionId,
            ReturnHtml = true,
        };

        return await PostAsync(
            "/v1/documents/upload-base64",
            body,
            SuperDocsJsonContext.Default.UploadBase64Request,
            SuperDocsJsonContext.Default.UploadedDocument,
            cancellationToken).ConfigureAwait(false);
    }

    // -------------------------------------------------------------------- chat --

    /// <inheritdoc/>
    public async Task<Job> ChatAsync(
        string sessionId,
        string message,
        string? documentHtml = null,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(sessionId);
        ArgumentException.ThrowIfNullOrWhiteSpace(message);

        ChatRequest body = new()
        {
            Message = message,
            SessionId = sessionId,
            DocumentHtml = documentHtml,
        };

        return await PostAsync(
            "/v1/chat",
            body,
            SuperDocsJsonContext.Default.ChatRequest,
            SuperDocsJsonContext.Default.Job,
            cancellationToken).ConfigureAwait(false);
    }

    /// <inheritdoc/>
    public async Task<ChatJobCreated> StartEditAsync(
        string sessionId,
        string message,
        string? documentHtml = null,
        bool requireApproval = true,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(sessionId);
        ArgumentException.ThrowIfNullOrWhiteSpace(message);

        ChatAsyncRequest body = new()
        {
            Message = message,
            SessionId = sessionId,
            DocumentHtml = documentHtml,
            ApprovalMode = requireApproval ? "ask_every_time" : null,
        };

        return await PostAsync(
            "/v1/chat/async",
            body,
            SuperDocsJsonContext.Default.ChatAsyncRequest,
            SuperDocsJsonContext.Default.ChatJobCreated,
            cancellationToken).ConfigureAwait(false);
    }

    // -------------------------------------------------------------------- jobs --

    /// <inheritdoc/>
    public async Task<Job> GetJobAsync(string jobId, CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(jobId);

        using HttpResponseMessage response = await _http
            .GetAsync(new Uri($"/v1/jobs/{Uri.EscapeDataString(jobId)}", UriKind.Relative),
                      cancellationToken)
            .ConfigureAwait(false);

        return await ReadAsync(response, SuperDocsJsonContext.Default.Job, cancellationToken)
            .ConfigureAwait(false);
    }

    /// <inheritdoc/>
    public Task<Job> WaitForApprovalAsync(string jobId, CancellationToken cancellationToken = default)
        => PollAsync(jobId, static job => job.IsAwaitingApproval || job.IsTerminal, cancellationToken);

    /// <inheritdoc/>
    public Task<Job> WaitForCompletionAsync(string jobId, CancellationToken cancellationToken = default)
        => PollAsync(jobId, static job => job.IsTerminal, cancellationToken);

    private async Task<Job> PollAsync(
        string jobId,
        Func<Job, bool> isDone,
        CancellationToken cancellationToken)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(jobId);

        // A PeriodicTimer rather than Task.Delay in a loop: it does not drift, and it
        // disposes cleanly on cancellation instead of leaving a timer queued.
        using PeriodicTimer timer = new(_options.PollInterval);

        Job job = await GetJobAsync(jobId, cancellationToken).ConfigureAwait(false);
        while (!isDone(job))
        {
            // Throws OperationCanceledException on cancellation, which is the documented
            // contract for a cancelled async method — not a silent return of a stale job.
            await timer.WaitForNextTickAsync(cancellationToken).ConfigureAwait(false);
            job = await GetJobAsync(jobId, cancellationToken).ConfigureAwait(false);
        }

        if (job.Status == JobStatus.Failed)
        {
            throw new SuperDocsException(
                $"Job {jobId} failed: {job.Error ?? "no reason given"}", HttpStatusCode.OK);
        }

        return job;
    }

    // ------------------------------------------------------------------ approve --

    /// <inheritdoc/>
    public async Task<ApprovalResult> ApproveAsync(
        string sessionId,
        string jobId,
        IReadOnlyList<ApprovalDecision> decisions,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(sessionId);
        ArgumentException.ThrowIfNullOrWhiteSpace(jobId);
        ArgumentNullException.ThrowIfNull(decisions);

        if (decisions.Count == 0)
        {
            throw new ArgumentException(
                "No decisions supplied. Approving nothing and approving everything are very " +
                "different outcomes, so this call will not guess which you meant.",
                nameof(decisions));
        }

        ApprovalRequest body = new()
        {
            JobId = jobId,
            // The API requires a top-level `approved` even when per-change decisions are
            // supplied. Setting it true here does NOT approve everything — the per-change
            // verdicts in `changes` govern. Omitting it is simply rejected.
            Approved = true,
            Changes = decisions,
        };

        return await PostAsync(
            $"/v1/chat/{Uri.EscapeDataString(sessionId)}/approve",
            body,
            SuperDocsJsonContext.Default.ApprovalRequest,
            SuperDocsJsonContext.Default.ApprovalResult,
            cancellationToken).ConfigureAwait(false);
    }

    /// <inheritdoc/>
    public async Task<ApprovalResult> ApproveAsync(
        string sessionId,
        string jobId,
        string changeId,
        bool approved,
        string? feedback = null,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(sessionId);
        ArgumentException.ThrowIfNullOrWhiteSpace(jobId);
        ArgumentException.ThrowIfNullOrWhiteSpace(changeId);

        ApprovalRequest body = new()
        {
            JobId = jobId,
            Approved = approved,
            ChangeId = changeId,
            Feedback = feedback,
        };

        return await PostAsync(
            $"/v1/chat/{Uri.EscapeDataString(sessionId)}/approve",
            body,
            SuperDocsJsonContext.Default.ApprovalRequest,
            SuperDocsJsonContext.Default.ApprovalResult,
            cancellationToken).ConfigureAwait(false);
    }

    /// <inheritdoc/>
    public async Task<Job> ReviewAsync(
        string sessionId,
        string jobId,
        Func<IReadOnlyList<ProposedChange>, CancellationToken, Task<IReadOnlyList<ApprovalDecision>>> decide,
        int maxRounds = 20,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(sessionId);
        ArgumentException.ThrowIfNullOrWhiteSpace(jobId);
        ArgumentNullException.ThrowIfNull(decide);
        ArgumentOutOfRangeException.ThrowIfNegativeOrZero(maxRounds);

        Job job = await WaitForApprovalAsync(jobId, cancellationToken).ConfigureAwait(false);

        for (int round = 0; round < maxRounds; round++)
        {
            if (job.IsTerminal)
            {
                return job;
            }

            IReadOnlyList<ProposedChange> pending = job.Metadata.PendingChanges;
            if (pending.Count == 0)
            {
                // Awaiting approval with nothing to approve. Waiting longer will not help,
                // and looping here is how the 146-poll stall happened.
                return job;
            }

            IReadOnlyList<ApprovalDecision> decisions =
                await decide(pending, cancellationToken).ConfigureAwait(false);

            if (decisions.Count == 0)
            {
                // The reviewer declined to decide. Ending here leaves the job untouched,
                // which is the safe outcome: nothing is applied.
                return job;
            }

            await ApproveAsync(sessionId, jobId, decisions, cancellationToken).ConfigureAwait(false);
            job = await WaitForApprovalAsync(jobId, cancellationToken).ConfigureAwait(false);
        }

        throw new SuperDocsException(
            $"Job {jobId} was still proposing changes after {maxRounds} review rounds. Either "
            + $"the edit is unusually large, or the job is not converging — stopping rather "
            + $"than looping. Raise maxRounds if the former.",
            HttpStatusCode.OK);
    }

    /// <inheritdoc/>
    public async Task<IReadOnlyList<Job>> ListSessionJobsAsync(
        string sessionId, CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(sessionId);

        using HttpResponseMessage response = await _http
            .GetAsync(
                new Uri($"/v1/sessions/{Uri.EscapeDataString(sessionId)}/jobs", UriKind.Relative),
                cancellationToken)
            .ConfigureAwait(false);

        SessionJobsResponse payload = await ReadAsync(
            response, SuperDocsJsonContext.Default.SessionJobsResponse, cancellationToken)
            .ConfigureAwait(false);

        return payload.Jobs;
    }

    /// <inheritdoc/>
    public async Task CancelJobAsync(string jobId, CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(jobId);

        using HttpResponseMessage response = await _http
            .PostAsync(
                new Uri($"/v1/jobs/{Uri.EscapeDataString(jobId)}/cancel", UriKind.Relative),
                content: null,
                cancellationToken)
            .ConfigureAwait(false);

        if (!response.IsSuccessStatusCode)
        {
            await ThrowApiExceptionAsync(response, cancellationToken).ConfigureAwait(false);
        }
    }

    // ------------------------------------------------------------------- export --

    /// <inheritdoc/>
    public async Task<ExportedFile> ExportAsync(
        string sessionId,
        ExportFormat format = ExportFormat.Docx,
        string? fileName = null,
        CancellationToken cancellationToken = default)
    {
        using HttpResponseMessage response =
            await SendExportAsync(sessionId, format, fileName, cancellationToken)
                .ConfigureAwait(false);

        byte[] bytes = await response.Content
            .ReadAsByteArrayAsync(cancellationToken).ConfigureAwait(false);

        return new ExportedFile(
            ResolveFileName(response, fileName, format),
            response.Content.Headers.ContentType?.MediaType ?? "application/octet-stream",
            bytes);
    }

    /// <inheritdoc/>
    public async Task ExportToStreamAsync(
        string sessionId,
        Stream destination,
        ExportFormat format = ExportFormat.Docx,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(destination);

        using HttpResponseMessage response =
            await SendExportAsync(sessionId, format, null, cancellationToken).ConfigureAwait(false);

        Stream source = await response.Content
            .ReadAsStreamAsync(cancellationToken).ConfigureAwait(false);
        await using (source.ConfigureAwait(false))
        {

            await source.CopyToAsync(destination, cancellationToken).ConfigureAwait(false);
        }
    }

    private async Task<HttpResponseMessage> SendExportAsync(
        string sessionId, ExportFormat format, string? fileName, CancellationToken cancellationToken)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(sessionId);

        ExportRequest body = new()
        {
            SessionId = sessionId,
            // CA1308 suggests ToUpperInvariant. The API's `format` enum is lowercase by
            // specification ("docx", "pdf", ...), so lowering is correct here and
            // uppercasing would simply be rejected.
#pragma warning disable CA1308
            Format = format.ToString().ToLowerInvariant(),
#pragma warning restore CA1308
            Filename = fileName,
        };

        using HttpRequestMessage request =
            new(HttpMethod.Post, new Uri("/v1/documents/export", UriKind.Relative))
            {
                Content = JsonContent.Create(
                    body, SuperDocsJsonContext.Default.ExportRequest),
            };

        // ResponseHeadersRead so the body is not buffered before we look at it — required
        // for ExportToStreamAsync to actually stream rather than merely appear to.
        HttpResponseMessage response = await _http
            .SendAsync(request, HttpCompletionOption.ResponseHeadersRead, cancellationToken)
            .ConfigureAwait(false);

        if (!response.IsSuccessStatusCode)
        {
            await ThrowApiExceptionAsync(response, cancellationToken).ConfigureAwait(false);
        }

        return response;
    }

    private static string ResolveFileName(
        HttpResponseMessage response, string? requested, ExportFormat format)
    {
        if (!string.IsNullOrWhiteSpace(requested))
        {
            return requested;
        }

        string? fromHeader = response.Content.Headers.ContentDisposition?.FileNameStar
                             ?? response.Content.Headers.ContentDisposition?.FileName;

        return string.IsNullOrWhiteSpace(fromHeader)
#pragma warning disable CA1308 // file extensions are lowercase by convention
            ? $"document.{format.ToString().ToLowerInvariant()}"
#pragma warning restore CA1308
            : fromHeader.Trim('"');
    }

    // ------------------------------------------------------------------ account --

    /// <inheritdoc/>
    public async Task<AccountStatus> GetAccountStatusAsync(
        CancellationToken cancellationToken = default)
    {
        using HttpResponseMessage response = await _http
            .GetAsync(new Uri("/v1/agents/whoami", UriKind.Relative), cancellationToken)
            .ConfigureAwait(false);

        return await ReadAsync(response, SuperDocsJsonContext.Default.AccountStatus, cancellationToken)
            .ConfigureAwait(false);
    }

    // ------------------------------------------------------------------- stream --

    /// <inheritdoc/>
    public async IAsyncEnumerable<ProposedChangeBatch> StreamChangesAsync(
        string sessionId,
        string jobId,
        [EnumeratorCancellation] CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(sessionId);
        ArgumentException.ThrowIfNullOrWhiteSpace(jobId);

        Uri uri = new(
            $"/v1/chat/{Uri.EscapeDataString(sessionId)}/stream?job_id={Uri.EscapeDataString(jobId)}",
            UriKind.Relative);

        using HttpRequestMessage request = new(HttpMethod.Get, uri);
        request.Headers.Add("Accept", "text/event-stream");

        using HttpResponseMessage response = await _http
            .SendAsync(request, HttpCompletionOption.ResponseHeadersRead, cancellationToken)
            .ConfigureAwait(false);

        if (!response.IsSuccessStatusCode)
        {
            await ThrowApiExceptionAsync(response, cancellationToken).ConfigureAwait(false);
        }

        Stream stream = await response.Content
            .ReadAsStreamAsync(cancellationToken).ConfigureAwait(false);
        await using ConfiguredAsyncDisposable _ = stream.ConfigureAwait(false);
        using StreamReader reader = new(stream, Encoding.UTF8);

        string? eventName = null;
        StringBuilder data = new();

        // Not `while (!reader.EndOfStream)`: EndOfStream performs a BLOCKING read to
        // determine the answer, which stalls the event loop inside an async iterator.
        // Reading until ReadLineAsync returns null is the async-safe equivalent.
        while (await reader.ReadLineAsync(cancellationToken).ConfigureAwait(false)
               is { } line)
        {
            if (line.StartsWith("event:", StringComparison.Ordinal))
            {
                eventName = line[6..].Trim();
                continue;
            }

            if (line.StartsWith("data:", StringComparison.Ordinal))
            {
                data.Append(line[5..].Trim());
                continue;
            }

            if (line.Length != 0)
            {
                continue;
            }

            // Blank line terminates an event.
            if (eventName == "proposed_change_batch" && data.Length > 0)
            {
                ProposedChangeBatch? batch = ParseBatchEvent(data.ToString());
                if (batch is not null)
                {
                    yield return batch;
                }
            }

            eventName = null;
            data.Clear();
        }
    }

    private static ProposedChangeBatch? ParseBatchEvent(string payload)
    {
        try
        {
            using JsonDocument envelope = JsonDocument.Parse(payload);
            string? content = envelope.RootElement.TryGetProperty("content", out JsonElement el)
                ? el.ToString()
                : payload;

            IReadOnlyList<ProposedChange> changes = ProposedChangeBatch.ParseContent(content);
            return changes.Count == 0
                ? null
                : new ProposedChangeBatch { Type = "proposed_change_batch", Changes = changes };
        }
        catch (JsonException)
        {
            // A malformed progress frame is not worth aborting a live review over; the
            // authoritative list is always Job.Metadata.PendingChanges.
            return null;
        }
    }

    // ------------------------------------------------------------------- plumbing --

    private async Task<TResponse> PostAsync<TRequest, TResponse>(
        string path,
        TRequest body,
        System.Text.Json.Serialization.Metadata.JsonTypeInfo<TRequest> requestInfo,
        System.Text.Json.Serialization.Metadata.JsonTypeInfo<TResponse> responseInfo,
        CancellationToken cancellationToken)
    {
        using HttpResponseMessage response = await _http
            .PostAsJsonAsync(new Uri(path, UriKind.Relative), body, requestInfo, cancellationToken)
            .ConfigureAwait(false);

        return await ReadAsync(response, responseInfo, cancellationToken).ConfigureAwait(false);
    }

    private static async Task<T> ReadAsync<T>(
        HttpResponseMessage response,
        System.Text.Json.Serialization.Metadata.JsonTypeInfo<T> typeInfo,
        CancellationToken cancellationToken)
    {
        if (!response.IsSuccessStatusCode)
        {
            await ThrowApiExceptionAsync(response, cancellationToken).ConfigureAwait(false);
        }

        T? value = await response.Content
            .ReadFromJsonAsync(typeInfo, cancellationToken).ConfigureAwait(false);

        return value ?? throw new SuperDocsException(
            $"The API returned success with an empty body for {response.RequestMessage?.RequestUri}.",
            response.StatusCode);
    }

    private static async Task ThrowApiExceptionAsync(
        HttpResponseMessage response, CancellationToken cancellationToken)
    {
        string raw = await response.Content.ReadAsStringAsync(cancellationToken)
            .ConfigureAwait(false);

        throw new SuperDocsException(
            SuperDocsException.Describe(response.StatusCode, raw),
            response.StatusCode,
            raw);
    }
}
