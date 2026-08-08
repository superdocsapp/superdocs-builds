namespace SuperDocs.Client;

/// <summary>
/// Client for the SuperDocs document-editing API.
/// </summary>
/// <remarks>
/// Every method is asynchronous and accepts a <see cref="CancellationToken"/>. There is no
/// synchronous overload anywhere in this library, deliberately: a blocking wrapper around an
/// async call is the classic ASP.NET deadlock, and offering one invites exactly the misuse
/// that the card warns about. If you need to block, that decision belongs at your
/// application's entry point where you can see the synchronization context, not here.
/// </remarks>
public interface ISuperDocsClient
{
    /// <summary>Uploads a document and returns the session it now lives in.</summary>
    /// <param name="sessionId">Session to upload into. Created if it does not exist.</param>
    /// <param name="fileName">Original file name, including extension.</param>
    /// <param name="content">File bytes. Keep under 100 KB; larger files need the presigned upload path.</param>
    /// <param name="cancellationToken">Cancels the request.</param>
    Task<UploadedDocument> UploadDocumentAsync(
        string sessionId,
        string fileName,
        ReadOnlyMemory<byte> content,
        CancellationToken cancellationToken = default);

    /// <summary>Sends an editing instruction and applies the result immediately.</summary>
    /// <remarks>Use <see cref="StartEditAsync"/> when a human should review first.</remarks>
    Task<Job> ChatAsync(
        string sessionId,
        string message,
        string? documentHtml = null,
        CancellationToken cancellationToken = default);

    /// <summary>
    /// Starts an edit that will pause for human review before anything is applied.
    /// </summary>
    /// <returns>A job to poll with <see cref="WaitForApprovalAsync"/>.</returns>
    Task<ChatJobCreated> StartEditAsync(
        string sessionId,
        string message,
        string? documentHtml = null,
        bool requireApproval = true,
        CancellationToken cancellationToken = default);

    /// <summary>Fetches a job's current state.</summary>
    Task<Job> GetJobAsync(string jobId, CancellationToken cancellationToken = default);

    /// <summary>
    /// Polls until the job is awaiting approval, finishes, or fails.
    /// </summary>
    /// <remarks>
    /// Honours <see cref="SuperDocsOptions.PollInterval"/>. Long waits are normal: large
    /// documents and deep model settings legitimately take minutes with no interim signal,
    /// so a job that appears stuck is usually still working. Cancel through the token rather
    /// than by shortening the timeout.
    /// </remarks>
    Task<Job> WaitForApprovalAsync(string jobId, CancellationToken cancellationToken = default);

    /// <summary>Polls until the job reaches a terminal state.</summary>
    Task<Job> WaitForCompletionAsync(string jobId, CancellationToken cancellationToken = default);

    /// <summary>
    /// Records a decision on every proposed change, in one call.
    /// </summary>
    /// <remarks>
    /// Approve some and reject others in the same review; each decision is independent.
    /// There is no "approve everything" overload — approving fifteen changes means naming
    /// fifteen changes, because a review that can be passed with one keystroke is not a
    /// review.
    /// </remarks>
    Task<ApprovalResult> ApproveAsync(
        string sessionId,
        string jobId,
        IReadOnlyList<ApprovalDecision> decisions,
        CancellationToken cancellationToken = default);

    /// <summary>Records a decision on a single change.</summary>
    Task<ApprovalResult> ApproveAsync(
        string sessionId,
        string jobId,
        string changeId,
        bool approved,
        string? feedback = null,
        CancellationToken cancellationToken = default);

    /// <summary>
    /// Drives a complete review: waits for each batch of proposed changes, asks
    /// <paramref name="decide"/> what to do with it, applies the verdicts, and repeats until
    /// the job finishes.
    /// </summary>
    /// <remarks>
    /// A large edit does NOT arrive as one batch. The job returns to
    /// <see cref="JobStatus.AwaitingApproval"/> after each round, so code that approves once
    /// and then calls <see cref="WaitForCompletionAsync"/> polls forever — observed against
    /// the live API at 146 requests and still going, with the job patiently waiting for a
    /// second decision nobody was going to make.
    /// <para>
    /// This method exists so that every consumer gets the multi-round shape right without
    /// having to discover it. <paramref name="decide"/> is called once per batch and returns
    /// a verdict for each change; returning an empty list ends the review without approving
    /// anything further.
    /// </para>
    /// </remarks>
    /// <param name="sessionId">Session the job belongs to.</param>
    /// <param name="jobId">Job to review.</param>
    /// <param name="decide">Called per batch. Receives the proposed changes, returns verdicts.</param>
    /// <param name="maxRounds">
    /// Safety bound. A server that never reaches a terminal state would otherwise loop
    /// indefinitely, and an unattended worker should give up and say so rather than spin.
    /// </param>
    /// <param name="cancellationToken">Cancels the review.</param>
    /// <returns>The job in its final state.</returns>
    Task<Job> ReviewAsync(
        string sessionId,
        string jobId,
        Func<IReadOnlyList<ProposedChange>, CancellationToken, Task<IReadOnlyList<ApprovalDecision>>> decide,
        int maxRounds = 20,
        CancellationToken cancellationToken = default);

    /// <summary>Lists the jobs belonging to a session, most recent first.</summary>
    /// <param name="sessionId">Session to inspect.</param>
    /// <param name="cancellationToken">Cancels the request.</param>
    Task<IReadOnlyList<Job>> ListSessionJobsAsync(
        string sessionId, CancellationToken cancellationToken = default);

    /// <summary>Cancels a pending or in-progress job.</summary>
    /// <remarks>
    /// The way out of a busy session: an abandoned job left <c>awaiting_approval</c> blocks
    /// every later request in that session until it is decided or cancelled.
    /// </remarks>
    /// <param name="jobId">Job to cancel.</param>
    /// <param name="cancellationToken">Cancels the request.</param>
    Task CancelJobAsync(string jobId, CancellationToken cancellationToken = default);

    /// <summary>Exports the session's document.</summary>
    Task<ExportedFile> ExportAsync(
        string sessionId,
        ExportFormat format = ExportFormat.Docx,
        string? fileName = null,
        CancellationToken cancellationToken = default);

    /// <summary>Exports the session's document straight to a stream, without buffering it.</summary>
    /// <remarks>
    /// Prefer this for large exports. <see cref="ExportAsync"/> materialises the whole file
    /// in memory, which is fine for a letter and wasteful for a thousand-page contract.
    /// </remarks>
    Task ExportToStreamAsync(
        string sessionId,
        Stream destination,
        ExportFormat format = ExportFormat.Docx,
        CancellationToken cancellationToken = default);

    /// <summary>Reads the current account's tier and remaining monthly operations.</summary>
    /// <remarks>Does not itself consume an operation.</remarks>
    Task<AccountStatus> GetAccountStatusAsync(CancellationToken cancellationToken = default);

    /// <summary>
    /// Streams progress and proposed changes for a running job as they occur.
    /// </summary>
    /// <remarks>
    /// The double-encoding on this path is handled for you: yielded batches carry decoded
    /// <see cref="ProposedChange"/> objects.
    /// </remarks>
    IAsyncEnumerable<ProposedChangeBatch> StreamChangesAsync(
        string sessionId,
        string jobId,
        CancellationToken cancellationToken = default);
}
