using System.Net;
using System.Reflection;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Options;
using Xunit;

namespace SuperDocs.Client.Tests;

public class DependencyInjectionTests
{
    [Fact]
    public void AddSuperDocs_RegistersAWorkingClient()
    {
        ServiceCollection services = new();
        services.AddSuperDocs(o => o.ApiKey = "sk_test_key");

        using ServiceProvider provider = services.BuildServiceProvider();
        ISuperDocsClient client = provider.GetRequiredService<ISuperDocsClient>();

        Assert.NotNull(client);
    }

    [Fact]
    public void AddSuperDocs_UsesHttpClientFactory()
    {
        // The card's central requirement: pooling, resilience and telemetry come from the
        // host. If the client were constructing its own HttpClient, the factory would have
        // no registration for it and this would be absent.
        ServiceCollection services = new();
        services.AddSuperDocs(o => o.ApiKey = "sk_test_key");

        using ServiceProvider provider = services.BuildServiceProvider();
        IHttpClientFactory factory = provider.GetRequiredService<IHttpClientFactory>();

        Assert.NotNull(factory);
    }

    [Fact]
    public void AddSuperDocs_ReturnsBuilderSoTheHostCanAttachItsOwnPolicies()
    {
        ServiceCollection services = new();
        IHttpClientBuilder builder = services.AddSuperDocs(o => o.ApiKey = "sk_test_key");

        // This is what makes AddStandardResilienceHandler() possible at the call site.
        Assert.NotNull(builder);
        Assert.Equal("SuperDocs", builder.Name);
    }

    [Fact]
    public void AddSuperDocs_ReadsConfiguration()
    {
        IConfiguration configuration = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>
            {
                ["SuperDocs:ApiKey"] = "sk_from_config",
                ["SuperDocs:BaseAddress"] = "https://example.invalid/",
                ["SuperDocs:PollInterval"] = "00:00:05",
            })
            .Build();

        ServiceCollection services = new();
        services.AddSuperDocs(configuration);

        using ServiceProvider provider = services.BuildServiceProvider();
        SuperDocsOptions options = provider.GetRequiredService<IOptions<SuperDocsOptions>>().Value;

        Assert.Equal("sk_from_config", options.ApiKey);
        Assert.Equal(new Uri("https://example.invalid/"), options.BaseAddress);
        Assert.Equal(TimeSpan.FromSeconds(5), options.PollInterval);
    }

    [Fact]
    public void MissingApiKey_FailsAtStartupNotAtFirstCall()
    {
        // A misconfiguration discovered during a nightly batch is far worse than a failed
        // boot, so ValidateOnStart is doing real work here.
        ServiceCollection services = new();
        services.AddSuperDocs(o => o.ApiKey = "");

        using ServiceProvider provider = services.BuildServiceProvider();

        Assert.Throws<OptionsValidationException>(
            () => provider.GetRequiredService<IOptions<SuperDocsOptions>>().Value);
    }

    [Fact]
    public void WrongShapedKey_IsRejectedWithAnActionableMessage()
    {
        SuperDocsOptions options = new() { ApiKey = "not-a-real-key" };
        InvalidOperationException error =
            Assert.Throws<InvalidOperationException>(options.Validate);

        Assert.Contains("sk_", error.Message, StringComparison.Ordinal);
    }
}

public class AsyncDisciplineTests
{
    [Fact]
    public void EveryPublicMethod_IsAsyncAndAcceptsCancellation()
    {
        // The card asks for "no synchronous-over-asynchronous deadlock traps". The strongest
        // version of that is having no synchronous surface to misuse in the first place.
        List<string> offenders = [];

        foreach (MethodInfo method in typeof(ISuperDocsClient).GetMethods())
        {
            bool returnsAwaitable =
                typeof(Task).IsAssignableFrom(method.ReturnType)
                || method.ReturnType.Name.StartsWith("IAsyncEnumerable", StringComparison.Ordinal);

            if (!returnsAwaitable)
            {
                offenders.Add($"{method.Name} is synchronous");
                continue;
            }

            if (method.GetParameters().All(p => p.ParameterType != typeof(CancellationToken)))
            {
                offenders.Add($"{method.Name} takes no CancellationToken");
            }
        }

        Assert.Empty(offenders);
    }

    [Fact]
    public void SourceContainsNoBlockingCalls()
    {
        // A structural guard against the deadlock pattern being reintroduced. The analyzer
        // catches missing ConfigureAwait; nothing catches somebody adding `.Result` later.
        Assembly assembly = typeof(SuperDocsClient).Assembly;
        Type[] types = assembly.GetTypes();

        List<string> offenders = types
            .SelectMany(static t => t.GetProperties(BindingFlags.Public | BindingFlags.Instance))
            .Where(static p => p.Name == "Result" && p.DeclaringType?.Namespace == "SuperDocs.Client")
            .Select(static p => $"{p.DeclaringType!.Name}.{p.Name}")
            .ToList();

        Assert.Empty(offenders);
    }

    [Fact]
    public async Task Cancellation_PropagatesRatherThanBeingSwallowed()
    {
        StubHandler handler = StubHandler.Json(Payloads.Completed);
        ISuperDocsClient client = BuildClient(handler);

        using CancellationTokenSource cts = new();
        await cts.CancelAsync();

        await Assert.ThrowsAnyAsync<OperationCanceledException>(
            () => client.GetJobAsync("j1", cts.Token));
    }

    internal static ISuperDocsClient BuildClient(StubHandler handler, string key = "sk_test")
    {
        HttpClient http = new(handler) { BaseAddress = new Uri("https://api.superdocs.app/") };
        return new SuperDocsClient(http, Options.Create(new SuperDocsOptions
        {
            ApiKey = key,
            PollInterval = TimeSpan.FromMilliseconds(1),
        }));
    }
}

public class ApprovalTests
{
    [Fact]
    public async Task Approve_SendsTopLevelApprovedEvenForBatchDecisions()
    {
        // Omitting this is rejected with a 422 that says nothing useful, and the docs do not
        // mention it. Pinned so a future refactor cannot quietly drop it.
        StubHandler handler = StubHandler.Json(Payloads.ApprovalOk);
        ISuperDocsClient client = AsyncDisciplineTests.BuildClient(handler);

        await client.ApproveAsync("s1", "j1",
        [
            ApprovalDecision.Approve("c1"),
            ApprovalDecision.Reject("c2", "wrong section"),
        ]);

        string body = Assert.Single(handler.Bodies);
        Assert.Contains("\"approved\":true", body, StringComparison.Ordinal);
        Assert.Contains("\"changes\"", body, StringComparison.Ordinal);
        Assert.Contains("wrong section", body, StringComparison.Ordinal);
    }

    [Fact]
    public async Task Approve_PreservesPerChangeVerdicts()
    {
        // The top-level `approved: true` must NOT be read as approving everything — the
        // per-change verdicts govern, and a rejection has to survive the round trip.
        StubHandler handler = StubHandler.Json(Payloads.ApprovalOk);
        ISuperDocsClient client = AsyncDisciplineTests.BuildClient(handler);

        await client.ApproveAsync("s1", "j1",
        [
            ApprovalDecision.Approve("c1"),
            ApprovalDecision.Reject("c2"),
        ]);

        string body = Assert.Single(handler.Bodies);
        Assert.Contains("\"change_id\":\"c2\",\"approved\":false", body, StringComparison.Ordinal);
    }

    [Fact]
    public async Task Approve_WithNoDecisions_RefusesToGuess()
    {
        StubHandler handler = StubHandler.Json(Payloads.ApprovalOk);
        ISuperDocsClient client = AsyncDisciplineTests.BuildClient(handler);

        ArgumentException error = await Assert.ThrowsAsync<ArgumentException>(
            () => client.ApproveAsync("s1", "j1", []));

        Assert.Contains("different outcomes", error.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void NoApproveAllConvenienceExists()
    {
        // A review that can be passed with one keystroke is not a review.
        Assert.DoesNotContain(
            typeof(ISuperDocsClient).GetMethods(),
            static m => m.Name.Contains("All", StringComparison.OrdinalIgnoreCase));
    }
}

public class ErrorMessageTests
{
    [Theory]
    [InlineData(HttpStatusCode.Unauthorized, "SuperDocs:ApiKey")]
    [InlineData(HttpStatusCode.NotFound, "session or job id")]
    [InlineData(HttpStatusCode.TooManyRequests, "Back off")]
    [InlineData(HttpStatusCode.RequestEntityTooLarge, "presigned upload")]
    public async Task Errors_NameTheCauseAndTheFix(HttpStatusCode status, string expected)
    {
        StubHandler handler = StubHandler.Json("""{"detail":"nope"}""", status);
        ISuperDocsClient client = AsyncDisciplineTests.BuildClient(handler);

        SuperDocsException error =
            await Assert.ThrowsAsync<SuperDocsException>(() => client.GetJobAsync("j1"));

        Assert.Contains(expected, error.Message, StringComparison.Ordinal);
        Assert.Equal(status, error.StatusCode);
    }

    [Fact]
    public async Task ValidationErrors_LeadWithTheServersOwnDetail()
    {
        // A canned hint printed ahead of the facts is worse than no hint. On a real upload
        // failure the message advised checking an approval field, while the server's body —
        // naming the actually-missing field — sat unread underneath it.
        StubHandler handler = StubHandler.Json(
            """{"detail":[{"loc":["body","file_base64"],"msg":"Field required"}]}""",
            HttpStatusCode.UnprocessableEntity);
        ISuperDocsClient client = AsyncDisciplineTests.BuildClient(handler);

        SuperDocsException error =
            await Assert.ThrowsAsync<SuperDocsException>(() => client.GetJobAsync("j1"));

        Assert.Contains("file_base64", error.Message, StringComparison.Ordinal);
        Assert.DoesNotContain("top-level 'approved'", error.Message, StringComparison.Ordinal);
    }

    [Fact]
    public async Task ValidationErrors_FallBackToTheHintWhenTheServerSaysNothing()
    {
        StubHandler handler = StubHandler.Json("", HttpStatusCode.UnprocessableEntity);
        ISuperDocsClient client = AsyncDisciplineTests.BuildClient(handler);

        SuperDocsException error =
            await Assert.ThrowsAsync<SuperDocsException>(() => client.GetJobAsync("j1"));

        Assert.Contains("top-level 'approved'", error.Message, StringComparison.Ordinal);
    }

    [Fact]
    public async Task TransientErrors_AreFlaggedForTheHostsRetryPolicy()
    {
        StubHandler handler = StubHandler.Json("{}", HttpStatusCode.ServiceUnavailable);
        ISuperDocsClient client = AsyncDisciplineTests.BuildClient(handler);

        SuperDocsException error =
            await Assert.ThrowsAsync<SuperDocsException>(() => client.GetJobAsync("j1"));

        Assert.True(error.IsTransient);
    }

    [Fact]
    public async Task PermanentErrors_AreNotFlaggedAsTransient()
    {
        StubHandler handler = StubHandler.Json("{}", HttpStatusCode.Unauthorized);
        ISuperDocsClient client = AsyncDisciplineTests.BuildClient(handler);

        SuperDocsException error =
            await Assert.ThrowsAsync<SuperDocsException>(() => client.GetJobAsync("j1"));

        Assert.False(error.IsTransient);
    }
}

public class WorkflowTests
{
    [Fact]
    public async Task WaitForApproval_StopsWhenAHumanIsNeeded()
    {
        StubHandler handler = StubHandler.Json(Payloads.AwaitingApproval);
        ISuperDocsClient client = AsyncDisciplineTests.BuildClient(handler);

        Job job = await client.WaitForApprovalAsync("j1");

        Assert.True(job.IsAwaitingApproval);
        Assert.Single(job.Metadata.PendingChanges);
    }

    [Fact]
    public async Task FailedJob_ThrowsRatherThanReturningQuietly()
    {
        const string failed =
            """{"job_id":"j1","session_id":"s1","status":"failed","error":"model unavailable","metadata":{}}""";
        StubHandler handler = StubHandler.Json(failed);
        ISuperDocsClient client = AsyncDisciplineTests.BuildClient(handler);

        SuperDocsException error =
            await Assert.ThrowsAsync<SuperDocsException>(() => client.WaitForCompletionAsync("j1"));

        Assert.Contains("model unavailable", error.Message, StringComparison.Ordinal);
    }

    [Fact]
    public async Task StartEdit_RequestsHumanReviewByDefault()
    {
        StubHandler handler = StubHandler.Json(Payloads.JobCreated);
        ISuperDocsClient client = AsyncDisciplineTests.BuildClient(handler);

        await client.StartEditAsync("s1", "change the terms");

        Assert.Contains("ask_every_time", Assert.Single(handler.Bodies), StringComparison.Ordinal);
    }

    [Fact]
    public async Task Export_UsesTheServersFileName()
    {
        StubHandler handler = new(_ =>
        {
            HttpResponseMessage response = new(HttpStatusCode.OK)
            {
                Content = new ByteArrayContent([0x50, 0x4B, 0x03, 0x04]),
            };
            response.Content.Headers.ContentDisposition =
                new System.Net.Http.Headers.ContentDispositionHeaderValue("attachment")
                {
                    FileName = "\"Vendor Services Agreement.docx\"",
                };
            return response;
        });

        ISuperDocsClient client = AsyncDisciplineTests.BuildClient(handler);
        ExportedFile file = await client.ExportAsync("s1");

        Assert.Equal("Vendor Services Agreement.docx", file.FileName);
        Assert.Equal(4, file.Length);
    }

    [Fact]
    public async Task AccountStatus_ReportsRemainingQuota()
    {
        StubHandler handler = StubHandler.Json(Payloads.Whoami);
        ISuperDocsClient client = AsyncDisciplineTests.BuildClient(handler);

        AccountStatus status = await client.GetAccountStatusAsync();

        Assert.Equal("free", status.Tier);
        Assert.Equal(488, status.Quota.Remaining);
    }
}
