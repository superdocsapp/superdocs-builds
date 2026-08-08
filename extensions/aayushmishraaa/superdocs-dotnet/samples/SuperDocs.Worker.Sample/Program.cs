using SuperDocs.Client;
using SuperDocs.Worker.Sample;

HostApplicationBuilder builder = Host.CreateApplicationBuilder(args);

// ---------------------------------------------------------------------------------------
// One line to register the client.
//
// AddSuperDocs returns the IHttpClientBuilder, so the resilience policy below belongs to
// THIS application and is shared with every other typed client it registers. The SDK does
// not retry on its own, does not carry its own circuit breaker, and does not have a second
// opinion about timeouts — which is exactly what you want from a library you did not write.
// ---------------------------------------------------------------------------------------
builder.Services
    .AddSuperDocs(builder.Configuration)
    .AddStandardResilienceHandler(options =>
    {
        // Document operations legitimately take minutes. The default 30-second attempt
        // timeout would cancel healthy work and then retry it, turning one slow request
        // into several.
        options.AttemptTimeout.Timeout = TimeSpan.FromMinutes(4);
        options.TotalRequestTimeout.Timeout = TimeSpan.FromMinutes(10);
        options.CircuitBreaker.SamplingDuration = TimeSpan.FromMinutes(8);
    });

builder.Services.Configure<WatcherOptions>(builder.Configuration.GetSection("Watcher"));
builder.Services.AddHostedService<DocumentWatcherService>();

IHost host = builder.Build();

// Fail fast and legibly rather than at the first API call, three minutes into a batch.
try
{
    _ = host.Services.GetRequiredService<ISuperDocsClient>();
}
catch (Exception ex)
{
    Console.Error.WriteLine($"""
        Could not start.

          {ex.Message}

        Set your key and try again:

          export SUPERDOCS_API_KEY=sk_your_key_here
          dotnet run

        Or use user-secrets, which keeps it out of your shell history:

          dotnet user-secrets set "SuperDocs:ApiKey" "sk_your_key_here"
        """);
    return 1;
}

await host.RunAsync();
return 0;
