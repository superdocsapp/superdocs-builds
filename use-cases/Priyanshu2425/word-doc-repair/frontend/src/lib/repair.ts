/**
 * The one conversation this page has with the server.
 *
 * `POST /api/recover` answers with Server-Sent Events: a `data:` line each time
 * the engine reaches a stage, then a final `data:` line carrying the manifest.
 * Reading it as a stream is the point -- someone watching their document being
 * read needs to see it happening, not a spinner that could mean anything.
 */

export interface Stage {
  stage: string;
  message: string;
}

/** The manifest the final recovery event carries. */
export interface Report {
  ok: boolean;
  /** One of the honest tokens: "full" | "partial" | "refused". */
  verdict: "full" | "partial" | "refused";
  word_count: number;
  /** How the text was recovered: "xml" | "regex" | "empty". */
  method: string;
  /** The recovered footnotes and headers, set down verbatim at the end. */
  asides_text: string;
  /** What could not be recovered, named plainly. */
  lost: string[];
  output_path: string;
  download: string | null;
  /** Where the optional styling pass can be started. Null on a failure. */
  style: string | null;
  /** The rebuilt document itself, pictures inline, for the preview. A verdict
   *  is a claim; this is the thing the claim is about. */
  preview_html: string;
  /** False when the structure was too damaged to read and only text came back. */
  structure_preserved: boolean;
  /** Pictures written into the rebuilt file. */
  images_recovered: number;
  /** Of those, how many had to be set at the end because their original
   *  position could not be worked out. */
  images_unplaced: number;
  /** Pictures that could not be put back, each with the reason. */
  images_lost: string[];
  tables_recovered: number;
  /** Whether the file at `download` went through the SuperDocs styling pass.
   *  Styling is part of the recovery, not a second step somebody asks for. */
  styled: boolean;
  /** One sentence about the styling pass — on success what it did, and on any
   *  failure which failure it was. Empty only when there was nothing to say. */
  styling_note: string;
  /** Set when a styled file came back and was thrown away because its words or
   *  its pictures no longer matched what was sent. */
  styling_rejected: boolean;
  /** The unstyled rebuild, kept available even when styling succeeded. */
  plain_download: string | null;
}

/** What this copy of the page can do. Asked before anything is offered, so the
 *  styling step is either genuinely available or plainly explained. */
export interface Capabilities {
  styling: boolean;
  note: string;
}

/** The optional second file, coming back from /api/style/{token}. */
export interface Styled {
  styled: boolean;
  path: string;
  download: string | null;
  note: string;
}

export const MAX_BYTES = 20 * 1024 * 1024;

export class RepairError extends Error {}

/** What we can tell before sending anything, said in the reader's words. */
export function checkFile(file: File): string | null {
  if (file.size === 0) {
    return "That file is empty — there is nothing inside it to recover. If you have another copy, even an older one, try that instead.";
  }
  if (file.size > MAX_BYTES) {
    return "That file is larger than 20 MB, which is more than this page can take.";
  }
  if (!/\.docx$/i.test(file.name)) {
    return "This page can only work on Word .docx files. If yours is a .doc, open it in Word once and save it as .docx — and if Word will not open it either, this page cannot recover that older format.";
  }
  return null;
}

export async function capabilities(): Promise<Capabilities> {
  try {
    const res = await fetch("/api/capabilities");
    if (!res.ok) throw new Error("unavailable");
    return (await res.json()) as Capabilities;
  } catch {
    // A page that cannot ask does not offer. Silence here is not "yes".
    return { styling: false, note: "" };
  }
}

/**
 * The second pass, only when somebody asks for it. Answers as JSON: whether a
 * styled file came back, and where to download it (or the local rebuild).
 */
export async function styleDocument(url: string): Promise<Styled> {
  let res: Response;
  try {
    res = await fetch(url, { method: "POST" });
  } catch {
    throw new RepairError(
      "The connection dropped. The rebuilt file above is unchanged and still yours.",
    );
  }
  if (!res.ok) {
    let detail = "";
    try {
      const body = await res.json();
      if (typeof body?.note === "string") detail = body.note;
    } catch {
      /* nothing more to learn */
    }
    throw new RepairError(
      detail || "Styling could not be started. The rebuilt file above is unchanged and still yours.",
    );
  }
  return (await res.json()) as Styled;
}

/** Read the SSE stream: stage lines, then a final line marked done. */
async function readStream(
  res: Response,
  onStage: (stage: Stage) => void,
): Promise<Record<string, unknown> | null> {
  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let final: Record<string, unknown> | null = null;

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let cut: number;
    while ((cut = buffer.indexOf("\n\n")) >= 0) {
      const raw = buffer.slice(0, cut).trim();
      buffer = buffer.slice(cut + 2);
      if (!raw.startsWith("data:")) continue;
      const line = raw.slice(5).trim();
      if (!line) continue;
      const parsed = JSON.parse(line) as Record<string, unknown>;
      if (parsed.done) final = parsed;
      else onStage({ stage: String(parsed.stage ?? ""), message: String(parsed.message ?? "") });
    }
  }
  return final;
}

/** The token the counter's endpoints hang off, pulled from `report.style`
 *  ("/api/style/{token}") rather than duplicated anywhere. Null when there is
 *  nothing to open a counter on. */
export function styleToken(report: Report): string | null {
  if (!report.style) return null;
  const parts = report.style.split("/").filter(Boolean);
  return parts.length ? parts[parts.length - 1] : null;
}

/** One line on the ledger: one instruction and what happened to it. `note`
 *  is the server's own sentence and is shown verbatim — every outcome states
 *  its own reason once (B21), so nothing here needs to be assembled from
 *  parts on the page. What a turn costs us is not on a receipt: the person
 *  arrived with a broken file, not an account. */
export interface Receipt {
  asked: string;
  note: string;
  turn_index: number;
  applied: boolean;
  supplied: string | null;
}

/** What `POST /api/style/{token}/open` and `POST /api/style/{token}/revert`
 *  both hand back — the state of the conversation itself, as opposed to the
 *  outcome of one turn. */
export interface CounterOpen {
  session: string;
  turns_left: number;
  turns_cap: number;
  retention_seconds: number;
  receipts: Receipt[];
}

/** `POST /api/style/{token}/revert` additionally hands back the reverted
 *  instruction's own text, so the field can be refilled with it — "put it
 *  back" leaves the person holding what they said, not an empty box. */
export interface RevertResult extends CounterOpen {
  note: string;
  compose_text: string;
  /** The current sheet, rendered fresh from the version this revert landed
   *  on. Empty when the revert took the session back to the original rebuild
   *  -- an empty string here means "show `report.preview_html` instead", not
   *  a failure. */
  preview_html: string;
}

/** The manifest at the end of a turn's SSE stream — the same shape a repair
 *  ends on, because streaming a change to a document is the same situation as
 *  streaming the recovery of one. */
export interface TurnResult {
  applied: boolean;
  note: string;
  turns_left: number;
  turns_cap: number;
  receipts: Receipt[];
  download: string | null;
  plain_download: string | null;
  /** B27: words the person supplied verbatim, cumulative across the session. */
  authored_words: number;
  /** The current sheet: the same salvage -> media -> read_blocks ->
   *  blocks_to_html path the recovery itself renders with, so it can never
   *  disagree with the report's own preview. Empty when nothing changed yet
   *  or the export could not be rendered -- an unreadable preview costs the
   *  toggle, never the change -- in which case the sheet should stay on
   *  `report.preview_html` rather than go blank. */
  preview_html: string;
}

/** `GET /api/style/{token}/session` — session state for reopening the counter
 *  (a page reload, or coming back from the report) without spending a turn. */
export interface CounterState {
  turns_left: number;
  turns_cap: number;
  receipts: Receipt[];
  download: string | null;
  plain_download: string | null;
  authored_words: number;
  /** The current sheet -- see `TurnResult.preview_html`. Empty when the
   *  session has no accepted turns yet, meaning `report.preview_html` is
   *  still the right thing on screen. */
  preview_html: string;
}

function counterError(detail: string, fallback: string): RepairError {
  return new RepairError(detail || fallback);
}

async function readJsonDetail(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") return body.detail;
    if (typeof body?.note === "string") return body.note;
  } catch {
    /* nothing more to learn */
  }
  return "";
}

/** Open a conversation on the styled file at `token`. Mirrors the shape of
 *  `repairFile`'s error handling: the counter failing to open never touches
 *  the report already on screen. */
export async function openCounter(token: string): Promise<CounterOpen> {
  let res: Response;
  try {
    res = await fetch(`/api/style/${token}/open`, { method: "POST" });
  } catch {
    throw new RepairError(
      "The counter could not be reached just now. Your document is unchanged.",
    );
  }
  if (!res.ok) {
    throw counterError(
      await readJsonDetail(res),
      "The counter could not be opened just now. Your document is unchanged.",
    );
  }
  return (await res.json()) as CounterOpen;
}

/** One instruction, sent and watched the same way a repair is: stage lines on
 *  an SSE stream, then a manifest. Reuses `readStream` rather than a second
 *  reader, because this is the same wire shape as `/api/recover`. */
export async function sendTurn(
  token: string,
  message: string,
  onStage: (stage: Stage) => void,
  signal?: AbortSignal,
): Promise<TurnResult> {
  let res: Response;
  try {
    res = await fetch(`/api/style/${token}/turn`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ message }),
      signal,
    });
  } catch {
    throw new RepairError(
      "The connection dropped before that change could be sent. Nothing was changed.",
    );
  }
  if (!res.ok || !res.body) {
    throw counterError(
      await readJsonDetail(res),
      "That change could not be sent just now. Nothing was changed.",
    );
  }
  const result = await readStream(res, onStage);
  if (!result) {
    throw new RepairError(
      "The connection dropped part-way through. A change that was already applied is not lost — it will show on the ledger once the counter can be reached again.",
    );
  }
  return result as unknown as TurnResult;
}

/** Back one accepted version. Free (PRD §7) and does not spend a turn. */
export async function revertTurn(token: string): Promise<RevertResult> {
  let res: Response;
  try {
    res = await fetch(`/api/style/${token}/revert`, { method: "POST" });
  } catch {
    throw new RepairError(
      "The connection dropped before that could be put back. Nothing was changed.",
    );
  }
  if (!res.ok) {
    throw counterError(
      await readJsonDetail(res),
      "That could not be put back just now.",
    );
  }
  return (await res.json()) as RevertResult;
}

/** Reopening the counter without spending anything — a page that was left and
 *  come back to, rather than a fresh conversation. */
export async function getCounterSession(token: string): Promise<CounterState> {
  let res: Response;
  try {
    res = await fetch(`/api/style/${token}/session`);
  } catch {
    throw new RepairError("The counter could not be reached just now.");
  }
  if (!res.ok) {
    throw counterError(await readJsonDetail(res), "The counter could not be reached just now.");
  }
  return (await res.json()) as CounterState;
}

/** "Let it go" — dispose of the session early rather than waiting out the
 *  idle timer. */
export async function closeCounter(token: string): Promise<void> {
  try {
    await fetch(`/api/style/${token}/session`, { method: "DELETE" });
  } catch {
    /* Closing early is a courtesy, not a promise; the idle timer still runs. */
  }
}

export async function repairFile(
  file: File,
  onStage: (stage: Stage) => void,
  signal?: AbortSignal,
): Promise<Report> {
  const form = new FormData();
  form.append("file", file, file.name);

  let res: Response;
  try {
    res = await fetch("/api/recover", { method: "POST", body: form, signal });
  } catch {
    throw new RepairError(
      "The connection dropped before your file could be read. Nothing was changed — your original is exactly as it was.",
    );
  }

  if (!res.ok || !res.body) {
    let detail = "";
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      /* nothing more to learn */
    }
    throw new RepairError(
      detail || "This page could not take that file just now. Nothing was changed.",
    );
  }

  const report = (await readStream(res, onStage)) as unknown as Report | null;

  if (!report) {
    throw new RepairError(
      "The connection dropped part-way through. Nothing was changed — your original is exactly as it was.",
    );
  }
  return report;
}
