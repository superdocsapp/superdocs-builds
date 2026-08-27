/* ============================================================================
   DIRECTION CONTRACT

   THESIS: What an institution sends you when your item arrived damaged. This is
   a recovery notice with a docket number and a stamped verdict, not the SaaS
   uploader page — no hero, no feature cards, no dashed rectangle.

   OWN-WORLD: Cool form stock, black print, postal blue for the institution and
   postal red for the damage. Airmail chevron tape edges anything we have taken
   custody of. A rubber-stamped verdict lands once. Mono only for the record
   line: filename, size, docket.

   STORY: Someone whose only copy will not open hands it over, watches it pass
   through real stations, reads a stamped verdict and two lists — what came
   through and what did not — and takes the file back.

   FIRST VIEWPORT: Wordmark, one sentence of what this is, the handover panel at
   full width, and the custody promises directly beneath it: original never
   changed, nothing kept, no account.

   FORM: Postal damaged-item recovery notice. Seventh on my grounded list, which
   is the one the seed assigned (key e3d60a22, direction scope, persuade).
   ========================================================================== */
import { useCallback, useEffect, useRef, useState } from "react";
import {
  capabilities as fetchCapabilities,
  checkFile,
  repairFile,
  RepairError,
  type Capabilities,
  type Report as ReportT,
  type Stage,
} from "./lib/repair";
import { Report } from "./components/Report";
import { Preview } from "./components/Preview";
import { Counter } from "./components/Counter";

type Phase = "idle" | "working" | "done" | "counter";

function docket(name: string): string {
  // A docket number is a receipt, not an identifier the server knows about.
  let h = 0;
  for (const ch of name) h = (h * 31 + ch.charCodeAt(0)) % 99991;
  return `SLV-${String(h).padStart(5, "0")}`;
}

function readableSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} bytes`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function App() {
  const [phase, setPhase] = useState<Phase>("idle");
  const [stages, setStages] = useState<Stage[]>([]);
  const [report, setReport] = useState<ReportT | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [handed, setHanded] = useState<{ name: string; size: number } | null>(null);
  const [over, setOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  // Asked once, before anything is offered (lib/repair.ts docstring) -- the
  // door either genuinely opens or is not drawn, never a button that fails
  // when pressed.
  const [capabilities, setCapabilities] = useState<Capabilities>({ styling: false, note: "" });
  useEffect(() => {
    let cancelled = false;
    void fetchCapabilities().then((c) => {
      if (!cancelled) setCapabilities(c);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const start = useCallback(async (file: File) => {
    const refusal = checkFile(file);
    setProblem(refusal);
    if (refusal) return;

    setHanded({ name: file.name, size: file.size });
    setStages([]);
    setReport(null);
    setPhase("working");
    try {
      const result = await repairFile(file, (s) => setStages((prev) => [...prev, s]));
      setReport(result);
      setPhase("done");
    } catch (e) {
      setProblem(
        e instanceof RepairError
          ? e.message
          : "Something went wrong before your file could be read. Nothing was changed.",
      );
      setPhase("idle");
    }
  }, []);

  const another = useCallback(() => {
    setPhase("idle");
    setStages([]);
    setReport(null);
    setProblem(null);
    setHanded(null);
    if (input.current) input.current.value = "";
  }, []);

  // The door: entered from the handover panel, left by "back to the report".
  // The report and the handed-over file it describes stay in state across the
  // round trip -- going back finds the same verdict, not a fresh upload.
  const openCounter = useCallback(() => setPhase("counter"), []);
  const backToReport = useCallback(() => setPhase("done"), []);

  if (phase === "counter" && report && handed) {
    return <Counter report={report} handed={handed} onBack={backToReport} />;
  }

  return (
    <>
      <div className="page">
        <header className="brand">
          <p className="brand__mark">
            Salvage<span>.</span>
          </p>
          <span className="brand__line">document recovery</span>
        </header>

        <div className="notice">
          <div className="tape" />
          <div className="notice__body">
            {phase === "idle" ? (
              <>
                <h1>Your Word file will not open.</h1>
                <p className="sub">
                  Hand it over and this page will read whatever is still intact inside it, rebuild
                  what it can, and tell you plainly what it could not.
                </p>

                <label
                  className={`dropzone${over ? " is-over" : ""}`}
                  onDragOver={(e) => {
                    e.preventDefault();
                    setOver(true);
                  }}
                  onDragLeave={() => setOver(false)}
                  onDrop={(e) => {
                    e.preventDefault();
                    setOver(false);
                    const file = e.dataTransfer.files?.[0];
                    if (file) void start(file);
                  }}
                >
                  <span className="dropzone__title">Choose the damaged file</span>
                  <span className="dropzone__hint">or drag it onto this panel · Word .docx · up to 20 MB</span>
                  <input
                    ref={input}
                    type="file"
                    accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      if (file) void start(file);
                    }}
                  />
                </label>

                {problem ? (
                  <p className="problem" role="alert">
                    <b>That file was not taken. </b>
                    {problem}
                  </p>
                ) : null}

                <ul className="custody">
                  <li>
                    <i aria-hidden="true" />
                    <span>
                      <b>Your original is never changed.</b> It is read, not written to, and it stays
                      exactly where it is on your machine.
                    </span>
                  </li>
                  <li>
                    <i aria-hidden="true" />
                    <span>
                      <b>Your file is not kept.</b> The repaired copy is held for about thirty minutes
                      so you can download it, then it is let go.
                    </span>
                  </li>
                  <li>
                    <i aria-hidden="true" />
                    <span>
                      <b>No account, and nothing to install.</b> This works in the page you are
                      looking at.
                    </span>
                  </li>
                  <li>
                    <i aria-hidden="true" />
                    <span>
                      <b>It is a best-effort recovery.</b> It will not promise you a complete repair,
                      and it will name anything it could not bring back.
                    </span>
                  </li>
                </ul>
              </>
            ) : null}

            {phase !== "idle" && handed ? (
              <>
                <h1 style={{ fontSize: "var(--t6)" }}>
                  {phase === "working"
                    ? "Reading your document"
                    : report?.verdict !== "refused"
                      ? "Your document, as far as it could be read"
                      : "This file could not be repaired"}
                </h1>
                <div className="record">
                  <span>
                    file <b>{handed.name}</b>
                  </span>
                  <span>
                    size <b>{readableSize(handed.size)}</b>
                  </span>
                  <span>
                    docket <b>{docket(handed.name)}</b>
                  </span>
                </div>

                {phase === "working" ? (
                  <ul className="stations" aria-label="What this page is doing">
                    {stages.map((s, i) => (
                      <li
                        className={`station${i < stages.length - 1 ? " station--done" : ""}`}
                        key={`${s.stage}-${i}`}
                      >
                        <span className="station__mark" aria-hidden="true" />
                        <span className="station__text">{s.message}</span>
                      </li>
                    ))}
                  </ul>
                ) : null}

                {/* The verdict, and — when the styling pass degraded — the
                    sentence saying so. DESIGN.md: "A degraded styling pass is
                    stated, never silent." It was stated on screen and nowhere
                    else, so by ear it was silent: this region announced the
                    verdict token alone, and somebody listening would not learn
                    that a styled copy had been thrown away or that nothing
                    could be sent this month. On success there is nothing to
                    add — the file simply arrived as promised. */}
                <p aria-live="polite" className="sr-only">
                   {phase === "working"
                    ? stages[stages.length - 1]?.message ?? "Working."
                    : report
                      ? [report.verdict, report.styled ? "" : report.styling_note]
                          .filter(Boolean)
                          .join(". ")
                      : ""}
                </p>

                {phase === "working" ? (
                  <p className="working">
                    <span>Working</span>
                    <span className="working__bar" aria-hidden="true" />
                  </p>
                ) : null}

                {phase === "done" && report ? (
                  <>
                    {/* The document before the verdict about it. Someone
                        deciding whether this was worth anything is answering a
                        question only the thing itself can answer — and the
                        pictures are the part they are checking for. */}
                    <Preview html={report.preview_html ?? ""} />
                    <Report
                      report={report}
                      capabilities={capabilities}
                      onAnother={another}
                      onOpenCounter={openCounter}
                    />
                    {/* The verdict is what someone came for; the steps are what
                        they read only if they want to check the working. */}
                    <details className="steps">
                      <summary>What it did, step by step ({stages.length})</summary>
                      <ul className="stations" aria-label="What this page did">
                        {stages.map((s, i) => (
                          <li className="station station--done" key={`${s.stage}-${i}`}>
                            <span className="station__mark" aria-hidden="true" />
                            <span className="station__text">{s.message}</span>
                          </li>
                        ))}
                      </ul>
                    </details>
                  </>
                ) : null}
              </>
            ) : null}
          </div>
          <div className="tape" />
        </div>

        <p className="cli">
          There is a command-line version of the same engine for a folder of damaged files:{" "}
          <code>python3 backend/cli.py broken.docx</code>
        </p>
      </div>

      <footer className="foot">
        <span>Salvage · best-effort DOCX recovery</span>
        <span>MIT licensed</span>
        <span>Built for the SuperDocs engineer round</span>
      </footer>
    </>
  );
}
