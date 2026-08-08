using System.Text.Json;
using System.Text.Json.Serialization;

namespace SuperDocs.Client;

/// <summary>
/// Deserialises string enums, mapping anything unrecognised to the zero value.
/// </summary>
/// <remarks>
/// The built-in <see cref="JsonStringEnumConverter{T}"/> throws on an unknown value. In this
/// SDK that failure is much worse than it first appears: an unknown <c>operation</c> makes the
/// whole <see cref="ProposedChange"/> fail to deserialise, the surrounding parse is caught,
/// and the change simply DISAPPEARS from the review. A reviewer would approve a batch without
/// ever being shown one of its edits.
/// <para>
/// So an unrecognised value becomes <c>Unknown</c> and the rest of the object survives.
/// Degrading to "there is a change here and I do not recognise its type" is strictly better
/// than degrading to silence — the change is still visible, still has its before-and-after
/// HTML, and a human can still judge it.
/// </para>
/// <para>
/// Writing is unaffected: values round-trip using their declared names.
/// </para>
/// </remarks>
/// <typeparam name="TEnum">The enum type. Its zero value is used for unknown input.</typeparam>
internal sealed class TolerantEnumConverter<
    [System.Diagnostics.CodeAnalysis.DynamicallyAccessedMembers(
        System.Diagnostics.CodeAnalysis.DynamicallyAccessedMemberTypes.PublicFields)] TEnum>
    : JsonConverter<TEnum>
    where TEnum : struct, Enum
{
    // The annotation tells the trimmer to keep this enum's fields. Without it the wire-name
    // lookup silently finds nothing in a trimmed build, every value deserialises to Unknown,
    // and the failure appears only in production — which is precisely the class of bug the
    // trim analyzer exists to prevent, so suppressing it rather than annotating would have
    // traded a build error for a runtime one.
    private static readonly Dictionary<string, TEnum> ByName = BuildLookup();
    private static readonly Dictionary<TEnum, string> ByValue = BuildReverse();

    public override TEnum Read(
        ref Utf8JsonReader reader, Type typeToConvert, JsonSerializerOptions options)
    {
        if (reader.TokenType == JsonTokenType.Null)
        {
            return default;
        }

        if (reader.TokenType == JsonTokenType.Number)
        {
            // Numeric enums are not used by this API, but tolerating them costs nothing.
            return reader.TryGetInt32(out int number) && Enum.IsDefined(typeof(TEnum), number)
                ? (TEnum)Enum.ToObject(typeof(TEnum), number)
                : default;
        }

        string? text = reader.GetString();
        if (string.IsNullOrWhiteSpace(text))
        {
            return default;
        }

        return ByName.TryGetValue(text, out TEnum value) ? value : default;
    }

    public override void Write(Utf8JsonWriter writer, TEnum value, JsonSerializerOptions options)
    {
        ArgumentNullException.ThrowIfNull(writer);
        writer.WriteStringValue(
            ByValue.TryGetValue(value, out string? name) ? name : value.ToString().ToUpperInvariant());
    }

    private static Dictionary<string, TEnum> BuildLookup()
    {
        Dictionary<string, TEnum> map = new(StringComparer.OrdinalIgnoreCase);
        foreach (TEnum value in Enum.GetValues<TEnum>())
        {
            map[WireName(value)] = value;
            map[value.ToString()] = value;
        }
        return map;
    }

    private static Dictionary<TEnum, string> BuildReverse()
    {
        Dictionary<TEnum, string> map = [];
        foreach (TEnum value in Enum.GetValues<TEnum>())
        {
            map[value] = WireName(value);
        }
        return map;
    }

    private static string WireName(TEnum value)
    {
        System.Reflection.FieldInfo? field = typeof(TEnum).GetField(value.ToString());
        JsonStringEnumMemberNameAttribute? attribute =
            field?.GetCustomAttributes(typeof(JsonStringEnumMemberNameAttribute), false)
                  .OfType<JsonStringEnumMemberNameAttribute>()
                  .FirstOrDefault();

        return attribute?.Name ?? value.ToString();
    }
}
