using Xunit;

namespace SuperDocs.Client.Tests;

/// <summary>
/// The headline behaviour: proposed changes decode correctly whichever path they arrive on.
/// </summary>
/// <remarks>
/// The API encodes the same data two ways. <c>metadata.pending_changes</c> returns real
/// objects; <c>intermediate_responses[].content</c> and the SSE stream return a JSON-encoded
/// string needing a second parse. Guidance describing the second parse as universal is true
/// of one path and false of the other, so an integrator following it breaks in one direction
/// and an integrator ignoring it breaks in the other.
/// <para>
/// These tests pin both directions, because "handles the double encoding" is only worth
/// anything if it also does NOT double-parse the path that must not be double-parsed.
/// </para>
/// </remarks>
public class DoubleEncodingTests
{
    [Fact]
    public void EncodedStringContent_IsDecoded()
    {
        const string encoded =
            """{"type":"single_approval","batch_total":1,"changes":[{"change_id":"c1","operation":"edit","old_html":"<p>net 30</p>","new_html":"<p>net 45</p>"}]}""";

        // As it arrives on the wire: a JSON string literal whose VALUE is JSON.
        string wire = System.Text.Json.JsonSerializer.Serialize(encoded);

        IReadOnlyList<ProposedChange> changes = ProposedChangeBatch.ParseContent(wire);

        ProposedChange change = Assert.Single(changes);
        Assert.Equal("c1", change.ChangeId);
        Assert.Equal(ChangeOperation.Edit, change.Operation);
        Assert.Equal("<p>net 45</p>", change.NewHtml);
    }

    [Fact]
    public void PlainObjectContent_IsAlsoAccepted()
    {
        // The same payload NOT double-encoded. Must work identically, so a server-side fix
        // to emit real objects does not break every consumer of this SDK.
        const string plain =
            """{"type":"batch","changes":[{"change_id":"c1","operation":"edit","new_html":"<p>x</p>"}]}""";

        ProposedChange change = Assert.Single(ProposedChangeBatch.ParseContent(plain));
        Assert.Equal("c1", change.ChangeId);
    }

    [Fact]
    public void BareArray_IsAccepted()
    {
        const string array = """[{"change_id":"c1","operation":"delete","old_html":"<p>x</p>"}]""";
        ProposedChange change = Assert.Single(ProposedChangeBatch.ParseContent(array));
        Assert.Equal(ChangeOperation.Delete, change.Operation);
    }

    [Fact]
    public void SingleUnwrappedChange_IsAccepted()
    {
        const string single = """{"change_id":"c9","operation":"create","new_html":"<p>new</p>"}""";
        ProposedChange change = Assert.Single(ProposedChangeBatch.ParseContent(single));
        Assert.Equal("c9", change.ChangeId);
        Assert.Equal(ChangeOperation.Create, change.Operation);
    }

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData("   ")]
    [InlineData("not json at all")]
    [InlineData("{\"unexpected\":\"shape\"}")]
    public void UnparseableContent_YieldsEmptyRatherThanThrowing(string? content)
    {
        // A malformed progress frame must not abort a review in flight. The authoritative
        // list is always Job.Metadata.PendingChanges.
        Assert.Empty(ProposedChangeBatch.ParseContent(content));
    }

    [Fact]
    public void PendingChanges_AreNotDoubleParsed()
    {
        // The bug in the other direction, and the one the documentation actively encourages:
        // applying the second parse to the polling path, which returns real objects.
        Job job = System.Text.Json.JsonSerializer.Deserialize<Job>(
            Payloads.AwaitingApproval, JsonOptions.Value)!;

        ProposedChange change = Assert.Single(job.Metadata.PendingChanges);
        Assert.Equal("97ca364e-8ebb-4d19-8cac-ae8812663caf", change.ChangeId);
        Assert.Equal("<p>Payment terms are net 45 days from invoice date.</p>", change.NewHtml);
        Assert.Equal(ChangeOperation.Edit, change.Operation);
    }

    [Fact]
    public void BothPathsAgreeOnTheSameChange()
    {
        // The property that actually matters to a consumer: it should not be possible to
        // tell which path a change arrived on.
        Job job = System.Text.Json.JsonSerializer.Deserialize<Job>(
            Payloads.AwaitingApproval, JsonOptions.Value)!;

        ProposedChange fromPolling = Assert.Single(job.Metadata.PendingChanges);
        ProposedChange fromStream =
            Assert.Single(Assert.Single(job.Metadata.IntermediateResponses).Changes);

        Assert.Equal(fromPolling.ChangeId, fromStream.ChangeId);
        Assert.Equal(fromPolling.NewHtml, fromStream.NewHtml);
        Assert.Equal(fromPolling.OldHtml, fromStream.OldHtml);
        Assert.Equal(fromPolling.Operation, fromStream.Operation);
    }

    [Fact]
    public void UnknownOperation_DoesNotThrow()
    {
        // A server adding an operation must not break existing consumers.
        const string future = """[{"change_id":"c1","operation":"transmogrify"}]""";
        ProposedChange change = Assert.Single(ProposedChangeBatch.ParseContent(future));
        Assert.Equal(ChangeOperation.Unknown, change.Operation);
    }
}

internal static class JsonOptions
{
    public static readonly System.Text.Json.JsonSerializerOptions Value = new()
    {
        PropertyNameCaseInsensitive = true,
    };
}
