import { useCallback, useEffect, useMemo, useState } from "react";
import { Preview } from "./Preview";
import {
  type Block,
  type Coverage,
  type Cut,
  type PageSetup,
  type PartPreview,
  exportWarning,
  markersNeeded,
  ordered,
  partAfter,
  type Snap,
} from "./split";

/** Three steps in work order: upload the master, mark where each part begins,
 * see what you would get, export. The preview (`/split`) is free and re-runs on
 * every change; only export spends operations, and the button says how many.
 *
 * See use-cases/doc-splitter/README.md § "Marking where the parts begin".
 */
export function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [doc, setDoc] = useState<Uploaded | null>(null);
  const [parts, setParts] = useState(3);
  const [cuts, setCuts] = useState<Cut[]>([]);
  /** Word by default — "start of this word" is what most splits mean. Exact is
   * there because some cuts really are mid-word. */
  const [snap, setSnap] = useState<Snap>("word");
  const [preview, setPreview] = useState<PreviewResult | null>(null);
  const [result, setResult] = useState<ExportResult | null>(null);
  const [busy, setBusy] = useState<"upload" | "export" | "log" | null>(null);
  const [message, setMessage] = useState<Banner | null>(null);

  useEffect(() => {
    void fetch("/health")
      .then((response) => response.json())
      .then(setHealth)
      .catch(() => setHealth(null));
  }, []);

  // Free, so it runs on every change: the reviewer sees the parts while still
  // deciding, not after paying for them.
  useEffect(() => {
    if (!doc) return;
    let current = true;
    void post<PreviewResult>("/split", { document_id: doc.document_id, cuts })
      .then((payload) => current && setPreview(payload))
      .catch((error: Error) => current && setMessage({ kind: "bad", text: error.message }));
    return () => {
      current = false;
    };
  }, [doc, cuts]);

  const upload = useCallback(async (file: File) => {
    setBusy("upload");
    setMessage({ kind: "busy", text: "Uploading and reading the structure…" });
    setResult(null);
    try {
      const body = new FormData();
      body.append("file", file);
      const response = await fetch("/upload", { method: "POST", body });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || response.statusText);
      setDoc(payload);
      setCuts([]);
      setMessage({
        kind: "ok",
        text:
          `${payload.blocks.length} blocks, ${payload.headings} headings` +
          (payload.furniture
            ? ` · ${payload.furniture} header/footer block(s) will repeat in every part`
            : ""),
      });
    } catch (error) {
      setMessage({ kind: "bad", text: (error as Error).message });
    } finally {
      setBusy(null);
    }
  }, []);

  const runExport = useCallback(async () => {
    if (!doc) return;
    setBusy("export");
    setMessage({ kind: "busy", text: "Exporting one document per part…" });
    try {
      const payload = await post<ExportResult>("/export", {
        document_id: doc.document_id,
        cuts,
      });
      setResult(payload);
      setMessage({ kind: "ok", text: payload.coverage.summary });
    } catch (error) {
      setResult(null);
      setMessage({ kind: "bad", text: (error as Error).message });
    } finally {
      setBusy(null);
    }
  }, [doc, cuts]);

  const downloadLog = useCallback(async () => {
    setBusy("log");
    try {
      const payload = await post<{ path: string; entries: number }>("/log/download", {});
      setMessage({ kind: "ok", text: `Saved ${payload.entries} rows to ${payload.path}` });
    } catch (error) {
      setMessage({ kind: "bad", text: (error as Error).message });
    } finally {
      setBusy(null);
    }
  }, []);

  const order = useMemo(
    () => new Map((doc?.blocks ?? []).map((block) => [block.chunk_id, block.index])),
    [doc],
  );
  const placed = useMemo(() => ordered(cuts, order), [cuts, order]);
  const needed = markersNeeded(parts);
  const warning = exportWarning(placed.length + 1, health?.max_parts ?? 10);

  const addCut = useCallback(
    (cut: Cut) =>
      setCuts((current) => {
        // Never more markers than the part count asks for; the oldest goes, so
        // clicking again moves the split rather than doing nothing.
        const next = [...current, cut];
        return next.length > needed ? next.slice(next.length - needed) : next;
      }),
    [needed],
  );

  return (
    <main>
      <header>
        <h1>Split a Document</h1>
        <p className="lede">
          Cut a master document into separate clean <code>.docx</code> files — and check the
          parts add up to the master before you keep them.
        </p>
        {health?.degraded && <p className="note bad">{health.missing_configuration.join(" ")}</p>}
      </header>

      <section>
        <h2>1 · The master document</h2>
        <div className="row">
          <input
            type="file"
            accept=".docx,.pdf,.md,.txt,.html"
            disabled={busy !== null}
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) void upload(file);
            }}
          />
          {busy === "upload" && <span className="note">reading…</span>}
        </div>
        <p className="note">Uploading is free and does not change the document.</p>
      </section>

      {doc && (
        <section>
          <h2>2 · How many parts, and where they start</h2>
          <div className="row">
            <label className="parts">
              Number of parts
              <input
                type="number"
                min={1}
                max={health?.max_parts ?? 10}
                value={parts}
                onChange={(event) => {
                  const value = Math.max(1, Number(event.target.value) || 1);
                  setParts(value);
                  // Drop markers the new count has no room for — else a hidden
                  // cut stays in effect.
                  setCuts((current) => current.slice(0, markersNeeded(value)));
                }}
              />
            </label>
            <span className="count">
              {placed.length} of {needed} split point(s) placed
            </span>
            {placed.length > 0 && (
              <button onClick={() => setCuts([])}>Clear split points</button>
            )}
          </div>

          <div className="row">
            <span className="note">Cut at</span>
            {(["word", "exact"] as const).map((mode) => (
              <button
                key={mode}
                className={snap === mode ? "chip on" : "chip"}
                onClick={() => setSnap(mode)}
              >
                {mode === "word" ? "the start of a word" : "the exact character"}
              </button>
            ))}
            <span className="note">
              {snap === "word"
                ? "Clicking inside a word cuts before it."
                : "Cuts precisely where you click — mid-word if that is where you click."}
            </span>
          </div>
          <p className="note">
            {needed === 0
              ? "One part is the whole document — nothing to mark."
              : `Click in the document below where part 2${needed > 1 ? " onwards" : ""} should begin. ` +
                "The cut lands exactly where you click, including in the middle of a word."}
          </p>

          <Preview
            html={doc.html}
            pageSetup={doc.page_setup}
            cuts={placed}
            snap={snap}
            onCut={addCut}
            onRemove={(index) =>
              setCuts((current) => current.filter((cut) => cut !== placed[index]))
            }
          />

          {placed.length > 0 && (
            <table className="cuts">
              <thead>
                <tr>
                  <th>Starts</th>
                  <th>Page</th>
                  <th>Line</th>
                  <th>Cut here</th>
                </tr>
              </thead>
              <tbody>
                {placed.map((cut, index) => (
                  <tr key={`${cut.chunk_id}:${cut.offset}`}>
                    <td>part {partAfter(index)}</td>
                    <td>{cut.page}</td>
                    <td>{cut.line}</td>
                    <td>
                      <code>{cut.quote}</code>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      )}

      {doc && preview && (
        <section>
          <h2>3 · What you would get</h2>
          <PartsTable parts={preview.parts} />
          <Verdict coverage={preview.coverage} />
          {warning && <p className="note warn">{warning}</p>}
          <div className="row">
            <button
              className="primary"
              disabled={!preview.coverage.complete || busy === "export"}
              onClick={() => void runExport()}
            >
              {busy === "export" ? "Exporting…" : `Export ${placed.length + 1} part(s)`}
            </button>
            <button disabled={busy === "log"} onClick={() => void downloadLog()}>
              {busy === "log" ? "Saving…" : "Download split log"}
            </button>
          </div>
        </section>
      )}

      {result && (
        <section>
          <h2>Exported</h2>
          <table>
            <thead>
              <tr>
                <th>Part</th>
                <th>File</th>
                <th>SuperDocs document</th>
                <th>Blocks</th>
              </tr>
            </thead>
            <tbody>
              {result.parts.map((part) => (
                <tr key={part.part}>
                  <td>{part.part}</td>
                  <td>
                    <code>{part.path}</code>
                  </td>
                  <td>
                    <code>{part.document_id.slice(0, 18)}…</code>
                  </td>
                  <td>{part.blocks}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <Verdict coverage={result.coverage} />
          <p className="note">
            Each part is a real SuperDocs document, not just a file — reopen, edit or share it.
            {result.session_with_all_parts && " All of them are gathered into one session."}
          </p>
        </section>
      )}

      {message && (
        <div className={`banner ${message.kind}`} role="status">
          <span>{message.text}</span>
          {message.kind !== "busy" && (
            <button className="close" onClick={() => setMessage(null)} aria-label="Dismiss">
              ×
            </button>
          )}
        </div>
      )}

      {health && <p className="limit">{health.limitation}</p>}
    </main>
  );
}

function PartsTable({ parts }: { parts: PartPreview[] }) {
  return (
    <table>
      <thead>
        <tr>
          <th>Part</th>
          <th>Begins</th>
          <th>Blocks</th>
          <th>Headings</th>
          <th>Characters</th>
        </tr>
      </thead>
      <tbody>
        {parts.map((part) => (
          <tr key={part.part}>
            <td>{part.part}</td>
            <td>{part.title}</td>
            <td>{part.blocks}</td>
            <td>{part.headings}</td>
            <td>{part.characters}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** The completeness verdict. Never a tick on its own — the numbers are the
 * claim, and a reviewer should be able to check them against the master. */
function Verdict({ coverage }: { coverage: Coverage }) {
  return (
    <div className={`verdict ${coverage.complete ? "ok" : "bad"}`}>
      <b>{coverage.complete ? "Checked" : "Will not export"}</b> — {coverage.summary}
      {coverage.repeated_furniture > 0 && (
        <span className="furniture">
          {" "}
          ({coverage.repeated_furniture} header/footer block(s) repeated across parts — page
          furniture, not duplicated content.)
        </span>
      )}
    </div>
  );
}

async function post<T>(url: string, body: unknown): Promise<T> {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || response.statusText);
  return payload as T;
}

interface Banner {
  kind: "ok" | "bad" | "busy";
  text: string;
}
interface Health {
  degraded: boolean;
  missing_configuration: string[];
  max_parts: number;
  limitation: string;
}
interface Uploaded {
  document_id: string;
  filename: string;
  html: string;
  page_setup: PageSetup | null;
  blocks: Block[];
  headings: number;
  furniture: number;
}
interface PreviewResult {
  parts: PartPreview[];
  coverage: Coverage;
}
interface ExportResult {
  parts: {
    part: number;
    title: string;
    path: string;
    document_id: string;
    blocks: number;
    headings: number;
  }[];
  coverage: Coverage;
  session_with_all_parts: string;
}
