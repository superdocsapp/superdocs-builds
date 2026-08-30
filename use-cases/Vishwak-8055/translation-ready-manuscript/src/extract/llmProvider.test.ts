import { describe, expect, it, vi } from "vitest";
import { AnthropicProvider } from "./llmProvider.js";
import type { Chapter } from "../types.js";

const chapters: Chapter[] = [
  { id: "ch01", index: 1, title: "Chapter One", blocks: [{ id: "b0", kind: "paragraph", text: "Aetherfall began.", spans: [], hasEmphasis: false }] },
];

function mockFetchReturning(text: string): typeof fetch {
  return vi.fn(async () =>
    new Response(JSON.stringify({ content: [{ type: "text", text }] }), { status: 200, headers: { "content-type": "application/json" } }),
  ) as unknown as typeof fetch;
}

describe("AnthropicProvider", () => {
  it("throws a clear error rather than calling the API when no key is configured", async () => {
    const provider = new AnthropicProvider({ apiKey: undefined, fetchImpl: vi.fn() as unknown as typeof fetch });
    await expect(provider.extractTerms(chapters)).rejects.toThrow(/no API key/);
  });

  it("sends the documented request shape: correct URL, auth header, and anthropic-version", async () => {
    const fetchSpy = mockFetchReturning("[]");
    const provider = new AnthropicProvider({ apiKey: "sk-test-key", fetchImpl: fetchSpy, baseUrl: "https://api.anthropic.com" });
    await provider.extractTerms(chapters);

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const [url, init] = (fetchSpy as ReturnType<typeof vi.fn>).mock.calls[0] as [string, RequestInit];
    expect(url).toBe("https://api.anthropic.com/v1/messages");
    const headers = init.headers as Record<string, string>;
    expect(headers["x-api-key"]).toBe("sk-test-key");
    expect(headers["anthropic-version"]).toBe("2023-06-01");
    const body = JSON.parse(init.body as string);
    expect(body.model).toBeTruthy();
    expect(body.messages[0].content).toContain("Aetherfall began");
  });

  it("parses a well-formed JSON array response into term suggestions", async () => {
    const suggestion = [
      {
        canonicalForm: "Aetherfall",
        category: "invented_word",
        meaning: "x",
        pronunciation: null,
        pronunciationConfidence: null,
        suggestedPolicy: "do_not_translate",
        confidence: "high",
        occurrences: [{ chapterId: "ch01", evidenceQuote: "Aetherfall began" }],
      },
    ];
    const provider = new AnthropicProvider({ apiKey: "sk-test", fetchImpl: mockFetchReturning(JSON.stringify(suggestion)) });
    const result = await provider.extractTerms(chapters);
    expect(result).toEqual(suggestion);
  });

  it("strips markdown code fences before parsing, since models sometimes wrap JSON despite instructions", async () => {
    const fenced = "```json\n[]\n```";
    const provider = new AnthropicProvider({ apiKey: "sk-test", fetchImpl: mockFetchReturning(fenced) });
    await expect(provider.extractTerms(chapters)).resolves.toEqual([]);
  });

  it("raises a clear error (not a silent empty result) when the model does not return valid JSON", async () => {
    const provider = new AnthropicProvider({ apiKey: "sk-test", fetchImpl: mockFetchReturning("Sure, here are some terms: Aetherfall, Xylora.") });
    await expect(provider.extractTerms(chapters)).rejects.toThrow(/did not return valid JSON/);
  });

  it("surfaces a non-2xx API response as a clear error including the status code", async () => {
    const fetchSpy = vi.fn(async () => new Response("rate limited", { status: 429, statusText: "Too Many Requests" })) as unknown as typeof fetch;
    const provider = new AnthropicProvider({ apiKey: "sk-test", fetchImpl: fetchSpy });
    await expect(provider.extractTerms(chapters)).rejects.toThrow(/429/);
  });
});
