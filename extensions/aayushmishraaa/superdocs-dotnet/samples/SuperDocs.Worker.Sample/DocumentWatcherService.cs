using System.Collections.Concurrent;
using System.Security.Cryptography;
using Microsoft.Extensions.Options;
using SuperDocs.Client;

namespace SuperDocs.Worker.Sample;

public sealed class WatcherOptions
{
    /// <summary>Folder to watch. Created if missing.</summary>
    public string InboxPath { get; set; } = "inbox";

    /// <summary>Where branded documents are written.</summary>
    public string OutboxPath { get; set; } = "outbox";

    /// <summary>The instruction applied to every arriving document.</summary>
    public string Instruction { get; set; } =
        "Apply our house style: add a title page heading, ensure headings are sentence case, "
        + "and append a confidentiality footer paragraph at the end.";

    /// <summary>Export format for the branded result.</summary>
    public ExportFormat OutputFormat { get; set; } = ExportFormat.Docx;

    /// <summary>
    /// When true, every proposed change is approved automatically.
    /// </summary>
    /// <remarks>
    /// Default FALSE, deliberately. An unattended worker that approves its own edits is not
    /// a human-in-the-loop system, and defaulting to convenience here would quietly teach
    /// the wrong pattern to anyone who copies this sample. With it off, the worker prints
    /// each proposed change and waits — which is what a review actually looks like.
    /// </remarks>
    public bool AutoApprove { get; set; }

    public TimeSpan PollInterval { get; set; } = TimeSpan.FromSeconds(2);
}

/// <summary>
/// Watches a folder, applies branding to each arriving document, and exports the result.
/// </summary>
public sealed class DocumentWatcherService : BackgroundService
{
    private static readonly string[] Supported = [".docx", ".pdf", ".html", ".md", ".txt", ".rtf"];

    private readonly ISuperDocsClient _client;
    private readonly WatcherOptions _options;
    private readonly ILogger<DocumentWatcherService> _logger;

    // Content hashes already handled. Identity is the CONTENT, not the path or timestamp:
    // editors and sync clients rewrite files without changing them, and keying on mtime
    // would spend an API operation every time somebody merely opened a document.
    private readonly ConcurrentDictionary<string, byte> _processed = new();

    public DocumentWatcherService(
        ISuperDocsClient client,
        IOptions<WatcherOptions> options,
        ILogger<DocumentWatcherService> logger)
    {
        _client = client;
        _options = options.Value;
        _logger = logger;
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        Directory.CreateDirectory(_options.InboxPath);
        Directory.CreateDirectory(_options.OutboxPath);

        _logger.LogInformation(
            "Watching {Inbox} -> {Outbox}. Drop a .docx in and it will be branded. "
            + "AutoApprove={AutoApprove}",
            Path.GetFullPath(_options.InboxPath),
            Path.GetFullPath(_options.OutboxPath),
            _options.AutoApprove);

        using PeriodicTimer timer = new(_options.PollInterval);
        while (await timer.WaitForNextTickAsync(stoppingToken).ConfigureAwait(false))
        {
            foreach (string path in Directory.EnumerateFiles(_options.InboxPath))
            {
                if (!Supported.Contains(Path.GetExtension(path), StringComparer.OrdinalIgnoreCase))
                {
                    continue;
                }

                try
                {
                    await ProcessAsync(path, stoppingToken).ConfigureAwait(false);
                }
                catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
                {
                    throw; // shutting down, not a failure
                }
                catch (SuperDocsException ex)
                {
                    // Named cause, and the file stays unprocessed so it is retried rather
                    // than silently skipped.
                    _logger.LogError(
                        "Could not process {File}: {Message} (transient: {Transient})",
                        Path.GetFileName(path), ex.Message, ex.IsTransient);
                }
                catch (IOException ex)
                {
                    _logger.LogWarning(
                        "{File} is not readable yet ({Message}); will retry.",
                        Path.GetFileName(path), ex.Message);
                }
            }
        }
    }

    private async Task<ChatJobCreated> StartWithSessionRecoveryAsync(
        string sessionId, string name, byte[] bytes, CancellationToken cancellationToken)
    {
        try
        {
            return await UploadAndStartAsync(sessionId, name, bytes, cancellationToken)
                .ConfigureAwait(false);
        }
        catch (SuperDocsException ex) when (ex.IsSessionBusy)
        {
            // The session id is derived from file CONTENT, deliberately, so re-dropping the
            // same document reuses its session instead of starting a parallel edit. The cost
            // is that an abandoned job from an earlier run blocks it. The server says exactly
            // this and suggests cancelling, so do that rather than surfacing an error a human
            // would resolve the same way.
            await ClearStaleJobsAsync(sessionId, cancellationToken).ConfigureAwait(false);
            return await UploadAndStartAsync(sessionId, name, bytes, cancellationToken)
                .ConfigureAwait(false);
        }
    }

    private async Task<ChatJobCreated> UploadAndStartAsync(
        string sessionId, string name, byte[] bytes, CancellationToken cancellationToken)
    {
        await _client.UploadDocumentAsync(sessionId, name, bytes, cancellationToken)
            .ConfigureAwait(false);

        return await _client
            .StartEditAsync(sessionId, _options.Instruction, requireApproval: true,
                            cancellationToken: cancellationToken)
            .ConfigureAwait(false);
    }

    private async Task ClearStaleJobsAsync(string sessionId, CancellationToken cancellationToken)
    {
        IReadOnlyList<Job> jobs =
            await _client.ListSessionJobsAsync(sessionId, cancellationToken).ConfigureAwait(false);

        foreach (Job stale in jobs.Where(static j => !j.IsTerminal))
        {
            _logger.LogWarning(
                "Clearing stale job {JobId} ({Status}) left in session {Session}",
                stale.JobId, stale.Status, sessionId);

            // A job stuck in awaiting_approval CANNOT be cancelled: cancel_job returns
            // 400 "Job cannot be cancelled", even though the 409's own suggested_action
            // recommends exactly that. The remedy that works is to DENY its pending
            // changes, which resolves the review and lets the job finish.
            if (stale.IsAwaitingApproval && stale.Metadata.PendingChanges.Count > 0)
            {
                await _client.ApproveAsync(
                    sessionId,
                    stale.JobId,
                    [.. stale.Metadata.PendingChanges.Select(
                        c => ApprovalDecision.Reject(c.ChangeId, "abandoned by a previous run"))],
                    cancellationToken).ConfigureAwait(false);
                continue;
            }

            try
            {
                await _client.CancelJobAsync(stale.JobId, cancellationToken).ConfigureAwait(false);
            }
            catch (SuperDocsException ex)
            {
                _logger.LogWarning(
                    "Could not cancel {JobId}: {Message}", stale.JobId, ex.Message);
            }
        }
    }

    private async Task ProcessAsync(string path, CancellationToken cancellationToken)
    {
        byte[] bytes;
        try
        {
            bytes = await File.ReadAllBytesAsync(path, cancellationToken).ConfigureAwait(false);
        }
        catch (IOException)
        {
            // Still being copied. Try again next tick rather than sending a truncated file,
            // which would produce a confidently wrong result from a half-read document.
            return;
        }

        string contentId = Convert.ToHexString(SHA256.HashData(bytes));
        if (!_processed.TryAdd(contentId, 0))
        {
            return;
        }

        string name = Path.GetFileName(path);
        string sessionId = $"brand-{contentId[..12]}";
        _logger.LogInformation("Processing {File} ({Bytes} bytes)", name, bytes.Length);

        // Guard the whole upload+start sequence, not just the edit. The 409 arrived from
        // the UPLOAD, because that is the first call to touch the session — guarding only
        // StartEditAsync left the handler in place and never reached.
        ChatJobCreated job = await StartWithSessionRecoveryAsync(
            sessionId, name, bytes, cancellationToken).ConfigureAwait(false);

        // ReviewAsync drives the WHOLE review, not one round of it. A large edit comes back
        // in several batches: the job returns to awaiting_approval after each one, so
        // approving once and waiting for completion polls forever.
        int round = 0;
        Job final = await _client.ReviewAsync(
            sessionId,
            job.JobId,
            (changes, ct) =>
            {
                round++;
                _logger.LogInformation(
                    "{File}: review round {Round}, {Count} change(s) proposed:",
                    name, round, changes.Count);
                foreach (ProposedChange change in changes)
                {
                    _logger.LogInformation(
                        "   [{Operation}] {Explanation}", change.Operation,
                        change.AiExplanation ?? "(no explanation)");
                }

                if (!_options.AutoApprove)
                {
                    // The honest default. An unattended worker that approves its own edits
                    // has no gate, and a sample that pretends otherwise teaches the wrong
                    // shape. Returning no decisions ends the review with nothing applied.
                    _logger.LogWarning(
                        "{File}: AutoApprove is off, so nothing was applied. Review these "
                        + "changes and approve them through your own UI, or set "
                        + "Watcher:AutoApprove=true where that risk is acceptable.", name);
                    return Task.FromResult<IReadOnlyList<ApprovalDecision>>([]);
                }

                return Task.FromResult<IReadOnlyList<ApprovalDecision>>(
                    [.. changes.Select(c => ApprovalDecision.Approve(c.ChangeId, "branding worker"))]);
            },
            cancellationToken: cancellationToken).ConfigureAwait(false);

        if (!_options.AutoApprove && !final.IsTerminal)
        {
            return;
        }

        string outputPath = Path.Combine(
            _options.OutboxPath,
            $"{Path.GetFileNameWithoutExtension(name)}-branded"
            + $".{_options.OutputFormat.ToString().ToLowerInvariant()}");

        // Streamed straight to disk rather than buffered. A thousand-page contract should
        // not have to fit in memory to be saved.
        FileStream output = File.Create(outputPath);
        await using (output.ConfigureAwait(false))
        {
            await _client.ExportToStreamAsync(
                sessionId, output, _options.OutputFormat, cancellationToken).ConfigureAwait(false);
        }

        _logger.LogInformation("{File} -> {Output}", name, outputPath);
    }
}
