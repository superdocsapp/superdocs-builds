using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Http;
using Microsoft.Extensions.Options;

namespace SuperDocs.Client;

/// <summary>
/// Registers the SuperDocs client in one line.
/// </summary>
public static class ServiceCollectionExtensions
{
    internal const string HttpClientName = "SuperDocs";

    /// <summary>
    /// Registers <see cref="ISuperDocsClient"/> using configuration section <c>SuperDocs</c>.
    /// </summary>
    /// <example>
    /// <code>
    /// builder.Services.AddSuperDocs(builder.Configuration);
    /// </code>
    /// </example>
    /// <returns>
    /// The <see cref="IHttpClientBuilder"/>, so the host can attach its own resilience and
    /// telemetry:
    /// <code>
    /// builder.Services.AddSuperDocs(builder.Configuration)
    ///        .AddStandardResilienceHandler();
    /// </code>
    /// </returns>
    public static IHttpClientBuilder AddSuperDocs(
        this IServiceCollection services,
        IConfiguration configuration,
        string sectionName = SuperDocsOptions.SectionName)
    {
        ArgumentNullException.ThrowIfNull(services);
        ArgumentNullException.ThrowIfNull(configuration);

        IConfigurationSection section = configuration.GetSection(sectionName);

        services.AddOptions<SuperDocsOptions>()
                // Bound by hand rather than with .Bind(). Reflection-based binding is not
                // trim- or AOT-safe (IL2026/IL3050) and would silently undermine the
                // trim-friendliness this package advertises. Five keys do not justify that.
                .Configure(options => BindFrom(section, options))
                .Validate(
                    static options => !string.IsNullOrWhiteSpace(options.ApiKey),
                    "SuperDocs:ApiKey is required. Set it in configuration or the "
                    + "SUPERDOCS_API_KEY environment variable.")
                // Fail at startup, not at the first call. A misconfigured key discovered
                // during a nightly batch is a much worse outcome than a failed boot.
                .ValidateOnStart();

        return AddSuperDocsCore(services);
    }

    private static void BindFrom(IConfiguration section, SuperDocsOptions options)
    {
        string? apiKey = section["ApiKey"] ?? Environment.GetEnvironmentVariable("SUPERDOCS_API_KEY");
        if (!string.IsNullOrWhiteSpace(apiKey))
        {
            options.ApiKey = apiKey;
        }

        if (Uri.TryCreate(section["BaseAddress"], UriKind.Absolute, out Uri? baseAddress))
        {
            options.BaseAddress = baseAddress;
        }

        if (TimeSpan.TryParse(section["Timeout"], out TimeSpan timeout))
        {
            options.Timeout = timeout;
        }

        if (TimeSpan.TryParse(section["PollInterval"], out TimeSpan pollInterval))
        {
            options.PollInterval = pollInterval;
        }

        options.UserAgent = section["UserAgent"] ?? options.UserAgent;
    }

    /// <summary>
    /// Registers <see cref="ISuperDocsClient"/> with options configured in code.
    /// </summary>
    /// <example>
    /// <code>
    /// builder.Services.AddSuperDocs(o => o.ApiKey = Environment.GetEnvironmentVariable("SUPERDOCS_API_KEY")!);
    /// </code>
    /// </example>
    public static IHttpClientBuilder AddSuperDocs(
        this IServiceCollection services,
        Action<SuperDocsOptions> configure)
    {
        ArgumentNullException.ThrowIfNull(services);
        ArgumentNullException.ThrowIfNull(configure);

        services.AddOptions<SuperDocsOptions>()
                .Configure(configure)
                .Validate(
                    static options => !string.IsNullOrWhiteSpace(options.ApiKey),
                    "SuperDocs:ApiKey is required.")
                .ValidateOnStart();

        return AddSuperDocsCore(services);
    }

    private static IHttpClientBuilder AddSuperDocsCore(IServiceCollection services)
    {
        // A TYPED client over IHttpClientFactory. This is the whole point of the design:
        // connection pooling, DNS rotation, resilience handlers, OpenTelemetry
        // instrumentation and logging all come from the host's existing HTTP stack rather
        // than being reimplemented — badly, and differently — inside this library.
        //
        // A hand-rolled HttpClient here would either leak sockets (new HttpClient per call)
        // or pin stale DNS (one static HttpClient forever). Both are classic, and both are
        // solved already by the platform.
        IHttpClientBuilder builder = services.AddHttpClient<ISuperDocsClient, SuperDocsClient>(
            HttpClientName,
            static (serviceProvider, http) =>
            {
                SuperDocsOptions options =
                    serviceProvider.GetRequiredService<IOptions<SuperDocsOptions>>().Value;
                options.Validate();

                http.BaseAddress = options.BaseAddress;
                http.Timeout = options.Timeout;
                http.DefaultRequestHeaders.Authorization =
                    new System.Net.Http.Headers.AuthenticationHeaderValue("Bearer", options.ApiKey);
                http.DefaultRequestHeaders.Add("Accept", "application/json");

                if (!string.IsNullOrWhiteSpace(options.UserAgent))
                {
                    http.DefaultRequestHeaders.Add("User-Agent", options.UserAgent);
                }
                else
                {
                    http.DefaultRequestHeaders.Add(
                        "User-Agent", $"SuperDocs.Client/{ThisAssembly.Version}");
                }
            });

        return builder;
    }
}

internal static class ThisAssembly
{
    public static string Version { get; } =
        typeof(SuperDocsClient).Assembly.GetName().Version?.ToString(3) ?? "0.1.0";
}
