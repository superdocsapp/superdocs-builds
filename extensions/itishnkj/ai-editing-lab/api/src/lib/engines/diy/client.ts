import { EngineUnavailableError, type EngineUsage } from "../types";

interface ChatMessage {
  role: "system" | "user" | "assistant";
  content: string;
}

interface OpenAiResponse {
  choices?: Array<{ message?: { content?: string | null } }>;
  usage?: {
    prompt_tokens?: number;
    completion_tokens?: number;
    total_tokens?: number;
  };
  error?: { message?: string };
}

export interface DiyCompletion {
  content: string;
  usage: EngineUsage;
}

export async function createDiyCompletion(
  messages: ChatMessage[],
): Promise<DiyCompletion> {
  const apiKey = process.env.OPENAI_API_KEY;
  const model = process.env.OPENAI_MODEL;
  if (!apiKey || !model) {
    throw new EngineUnavailableError(
      "DIY Toolkit requires both OPENAI_API_KEY and OPENAI_MODEL.",
    );
  }

  const baseUrl = (process.env.OPENAI_BASE_URL ?? "https://api.openai.com/v1")
    .replace(/\/+$/, "");
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 90_000);

  try {
    const response = await fetch(`${baseUrl}/chat/completions`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${apiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        model,
        temperature: 0.2,
        response_format: { type: "json_object" },
        messages,
      }),
      signal: controller.signal,
    });
    const data = (await response.json()) as OpenAiResponse;
    if (!response.ok) {
      const providerMessage = data.error?.message;
      throw new Error(
        providerMessage
          ? `Model provider error: ${providerMessage}`
          : `Model provider returned HTTP ${response.status}.`,
      );
    }

    const content = data.choices?.[0]?.message?.content;
    if (!content) {
      throw new Error("The model provider returned an empty response.");
    }

    return {
      content,
      usage: {
        inputTokens: data.usage?.prompt_tokens ?? null,
        outputTokens: data.usage?.completion_tokens ?? null,
        totalTokens: data.usage?.total_tokens ?? null,
        hostedUsage: null,
      },
    };
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") {
      throw new Error("The DIY model request timed out after 90 seconds.");
    }
    throw error;
  } finally {
    clearTimeout(timer);
  }
}