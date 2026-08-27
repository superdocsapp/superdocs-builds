import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { AccountStatus, DocumentSnapshot, Measurement } from "../shared/types.js";
import * as api from "./api.js";
import { Callout, ErrorCallout } from "./components/Callout.js";
import { DemoDocument, type DemoSize } from "./components/DemoDocument.js";
import { OutOfScopeEdit, ProposedEdit } from "./components/ProposedEdit.js";
import { TokenComparison } from "./components/TokenComparison.js";
import { createDemoHost } from "./host/demo.js";
import { createWordHost, whenOfficeReady } from "./host/word.js";
import type { DocumentHost } from "./host/types.js";

/**
 * The task pane.
 *
 * One flow, six states: empty, selected, rewriting, result, applied, error. The
 * pane holds no document of its own - it asks the host what is selected and what
 * the document says, every time, so it cannot drift from what the user sees.
 */

type Phase = "idle" | "rewriting" | "result";

export function App(): JSX.Element {
  const surfaceRef = useRef<HTMLDivElement>(null);
  const [host, setHost] = useState<DocumentHost | null>(null);
  const [status, setStatus] = useState<AccountStatus | null>(null);
  const [pages, setPages] = useState<DemoSize>(3);

  const [selectedText, setSelectedText] = useState("");
  const [instruction, setInstruction] = useState("Make this more concise.");
  const [phase, setPhase] = useState<Phase>("idle");
  const [result, setResult] = useState<api.RewriteResponse | null>(null);
  const [measurement, setMeasurement] = useState<Measurement | null>(null);
  const [measuringWhole, setMeasuringWhole] = useState(false);
  const [appliedChangeIds, setAppliedChangeIds] = useState<string[]>([]);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  // Word if we are inside Word, the demo surface otherwise. Decided once.
  useEffect(() => {
    let cancelled = false;

    void (async () => {
      const inWord = await whenOfficeReady();
      if (cancelled) return;

      if (inWord) {
        setHost(createWordHost());
      } else if (surfaceRef.current !== null) {
        setHost(createDemoHost(surfaceRef.current));
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    void api.getStatus().then(setStatus).catch(setError);
  }, []);

  // Track the host's selection. Everything downstream reads this.
  useEffect(() => {
    if (host === null) return;

    let active = true;

    const sync = () => {
      void host.readSelection().then((text) => {
        if (active) setSelectedText(text);
      });
    };

    sync();
    const unsubscribe = host.onSelectionChange(sync);

    return () => {
      active = false;
      unsubscribe();
    };
  }, [host]);

  // Switching document size invalidates any result that was about the old one.
  useEffect(() => {
    setResult(null);
    setMeasurement(null);
    setAppliedChangeIds([]);
    setPhase("idle");
  }, [pages]);

  const trimmedSelection = selectedText.trim();
  const hasSelection = trimmedSelection.length > 0;
  const canRewrite = hasSelection && instruction.trim().length > 0 && phase !== "rewriting";

  const readDocument = useCallback(async (): Promise<DocumentSnapshot> => {
    if (host === null) throw new Error("No document host is connected yet.");
    return host.readDocument();
  }, [host]);

  const onRewrite = useCallback(async () => {
    setError(null);
    setPhase("rewriting");
    setResult(null);
    setMeasurement(null);
    setAppliedChangeIds([]);

    try {
      const document = await readDocument();
      const response = await api.rewrite({ document, selectedText, instruction });
      setResult(response);
      setMeasurement(response.measurement);
      setPhase("result");
    } catch (caught) {
      setError(caught instanceof Error ? caught : new Error(String(caught)));
      setPhase("idle");
    }
  }, [instruction, readDocument, selectedText]);

  /**
   * Replace the estimate with a measurement.
   *
   * This runs the whole-document regeneration for real, against a copy of the
   * document in a throwaway SuperDocs session. The user's document is not
   * involved and nothing that comes back is ever applied.
   */
  const onMeasureWholeDocument = useCallback(async () => {
    if (result === null) return;

    setError(null);
    setMeasuringWhole(true);

    try {
      const document = await readDocument();

      const response = await api.measureWholeDocument({
        document,
        selectedText,
        instruction,
        surgical: {
          work: result.work,
          reportedTokens: result.measurement.reported.surgical?.tokens ?? null
        }
      });

      setMeasurement(response.measurement);
    } catch (caught) {
      setError(caught instanceof Error ? caught : new Error(String(caught)));
    } finally {
      setMeasuringWhole(false);
    }
  }, [instruction, readDocument, result, selectedText]);

  /**
   * Apply one approved change.
   *
   * Two things have to happen and both have to succeed: SuperDocs is told the
   * change was approved, so the session's document version matches, and the host
   * document is edited. The host edit is refused outright if the original text is
   * not in the document exactly once.
   */
  const onApply = useCallback(
    async (changeId: string) => {
      if (result === null || host === null) return;

      const change = result.changes.find((c) => c.changeId === changeId);
      if (change === undefined) return;

      setError(null);
      setApplying(true);

      try {
        await api.applyChange({
          sessionId: result.sessionId,
          jobId: result.jobId,
          changeId: change.changeId
        });
        await host.applyEdit(change.oldText, change.newText);
        setAppliedChangeIds((ids) => [...ids, change.changeId]);
      } catch (caught) {
        setError(caught instanceof Error ? caught : new Error(String(caught)));
      } finally {
        setApplying(false);
      }
    },
    [host, result]
  );

  const preview = useMemo(
    () => (trimmedSelection.length > 320 ? `${trimmedSelection.slice(0, 320)}…` : trimmedSelection),
    [trimmedSelection]
  );

  return (
    <div className="layout">
      <main className="pane">
        <header className="pane__header">
          <h1>TokenScope</h1>
          <p className="pane__tagline">
            Why regenerate the whole document when you only changed one paragraph?
          </p>
          <StatusLine status={status} host={host} />
        </header>

        {error !== null && <ErrorCallout error={error} onDismiss={() => setError(null)} />}

        {status !== null && !status.configured && (
          <Callout tone="warn" title="TokenScope cannot reach SuperDocs">
            {status.problem}
          </Callout>
        )}

        <section className="step">
          <h2>
            <span className="step__number">1</span> Selection
          </h2>

          {hasSelection ? (
            <blockquote className="selection">{preview}</blockquote>
          ) : (
            <p className="empty">
              Nothing is selected. Select a paragraph in the document
              {host?.kind === "word" ? "" : " on the right"} and it will appear here.
            </p>
          )}
        </section>

        <section className="step">
          <h2>
            <span className="step__number">2</span> Rewrite instruction
          </h2>
          <textarea
            value={instruction}
            onChange={(event) => setInstruction(event.target.value)}
            rows={2}
            placeholder="Make this more concise."
            aria-label="Rewrite instruction"
          />
          <button
            type="button"
            className="button button--primary button--wide"
            onClick={() => void onRewrite()}
            disabled={!canRewrite}
          >
            {phase === "rewriting" ? "Rewriting…" : "Rewrite selection"}
          </button>
          {!hasSelection && <p className="hint">Select some text first.</p>}
          {hasSelection && instruction.trim().length === 0 && (
            <p className="hint">Enter an instruction, for example “Make this more concise”.</p>
          )}
        </section>

        {phase === "rewriting" && (
          <section className="step">
            <div className="loading">
              <span className="spinner" aria-hidden="true" />
              <div>
                <strong>Rewriting the selection</strong>
                <p>
                  SuperDocs is editing one paragraph and reporting what the operation cost. Large
                  documents take longer.
                </p>
              </div>
            </div>
          </section>
        )}

        {phase === "result" && result !== null && measurement !== null && (
          <>
            <section className="step">
              <h2>
                <span className="step__number">3</span> Result
              </h2>

              {result.scope.inScope.length === 0 && (
                <Callout tone="warn" title="No change inside the selection">
                  SuperDocs did not propose an edit to the text you selected. Try a more specific
                  instruction.
                </Callout>
              )}

              {result.scope.inScope.map((change) => (
                <ProposedEdit
                  key={change.changeId}
                  change={change}
                  applied={appliedChangeIds.includes(change.changeId)}
                  applying={applying}
                  onApply={() => void onApply(change.changeId)}
                />
              ))}

              {result.scope.outOfScope.map((change) => (
                <OutOfScopeEdit key={change.changeId} change={change} />
              ))}
            </section>

            <section className="step">
              <h2>
                <span className="step__number">4</span> What it cost
              </h2>
              <TokenComparison
                measurement={measurement}
                measuring={measuringWhole}
                onMeasureWholeDocument={() => void onMeasureWholeDocument()}
              />
              <p className="provenance">
                Measured on SuperDocs job <code>{result.jobId.slice(0, 8)}</code>, which took{" "}
                {(result.elapsedMs / 1000).toFixed(1)}s and changed{" "}
                {result.work.sectionsChanged === 1
                  ? "one section"
                  : `${result.work.sectionsChanged} sections`}{" "}
                of the document.
              </p>
            </section>
          </>
        )}
      </main>

      {host?.kind !== "word" && (
        <DemoDocument pages={pages} onPagesChange={setPages} surfaceRef={surfaceRef} />
      )}
    </div>
  );
}

function StatusLine({
  status,
  host
}: {
  status: AccountStatus | null;
  host: DocumentHost | null;
}): JSX.Element {
  if (status === null) return <p className="status">Checking SuperDocs…</p>;

  const quota = status.quota;

  return (
    <p className="status">
      <span
        className={`dot ${status.configured && status.problem === undefined ? "dot--ok" : "dot--bad"}`}
      />
      {host === null ? "Connecting to the document" : host.label}
      {quota !== undefined && (
        <>
          {" · "}
          {quota.remaining.toLocaleString("en-US")} of {quota.monthlyLimit.toLocaleString("en-US")}{" "}
          SuperDocs operations left
        </>
      )}
    </p>
  );
}
