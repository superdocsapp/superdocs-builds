export interface DiyModelOutput {
  replacement_html: string;
  explanation: string;
}

export interface ParsedWithRetry {
  parsed: DiyModelOutput;
  raw: string;
  retryCount: 0 | 1;
}

export function parseDiyModelOutput(raw: string): DiyModelOutput {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    throw new Error("The model returned malformed JSON.");
  }

  if (
    !parsed ||
    typeof parsed !== "object" ||
    typeof (parsed as Record<string, unknown>).replacement_html !== "string" ||
    !(parsed as Record<string, unknown>).replacement_html
  ) {
    throw new Error("The model response did not include replacement_html.");
  }

  const value = parsed as Record<string, unknown>;
  return {
    replacement_html: value.replacement_html as string,
    explanation:
      typeof value.explanation === "string"
        ? value.explanation
        : "Proposed by the configured DIY model.",
  };
}

export async function parseWithOneRepair(
  initialRaw: string,
  repair: () => Promise<string>,
): Promise<ParsedWithRetry> {
  try {
    return {
      parsed: parseDiyModelOutput(initialRaw),
      raw: initialRaw,
      retryCount: 0,
    };
  } catch {
    const repairedRaw = await repair();
    return {
      parsed: parseDiyModelOutput(repairedRaw),
      raw: repairedRaw,
      retryCount: 1,
    };
  }
}