import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ApiError,
  api,
  type Catalogue,
  type Check,
  type Inspection,
  type InspectionRow,
  type Proposal,
} from "./api";
import {
  CheckList,
  ConfirmButton,
  Empty,
  ErrorNote,
  RailVerdict,
  SeverityTag,
  Skeleton,
} from "./components";
import { Flagged, ReportShape, WordDiff } from "./insight";

type Screen = "list" | "walk" | "gate" | "export";

/**
 * `stage` is an enum on the wire, and `in_review` is not a thing anyone says. The words are
 * here rather than in the API because they are how this interface talks about the flow, and
 * a second client is entitled to its own wording.
 */
const STAGE_WORDS: Record<string, string> = {
  draft: "still walking",
  prepared: "ready for review",
  in_review: "at the review gate",
  approved: "approved",
  exported: "exported",
};

function stageLabel(stage: string): string {
  return STAGE_WORDS[stage] ?? stage.replace(/_/g, " ");
}

/**
 * Confirmation for actions that would otherwise complete in silence — recording a finding,
 * accepting a photograph, sending decisions. It is announced politely as well as shown,
 * because the person using this is often not looking at the screen when it happens.
 */
function useToast(): [React.ReactNode, (message: string) => void] {
  const [message, setMessage] = useState<string | null>(null);
  useEffect(() => {
    if (!message) return;
    const t = setTimeout(() => setMessage(null), 3200);
    return () => clearTimeout(t);
  }, [message]);
  const node = message ? (
    <div className="toast" role="status" aria-live="polite">
      <span aria-hidden="true">✓</span>
      {message}
    </div>
  ) : null;
  return [node, setMessage];
}

/**
 * Where you are, in the address bar.
 *
 * `#/` is the list; `#/i/<id>/walk|review|export` is one inspection at one stage. Holding
 * this in React state alone meant a property could not be bookmarked, a reload dropped you
 * back at the list, and the browser's own back button did nothing — on a tool someone opens
 * on a phone, mid-job, on a bad connection. It is also how a reviewer gets sent straight to
 * the gate rather than "open the app and find 14 Alder Lane".
 *
 * Hash rather than history, because this is served as a static bundle and a path route would
 * need the server to rewrite unknown paths back to index.html.
 */
const SCREENS: Screen[] = ["walk", "gate", "export"];
const SCREEN_SLUGS: Record<Screen, string> = {
  list: "",
  walk: "walk",
  gate: "review",
  export: "export",
};

function readHash(): { screen: Screen; current: string | null } {
  const parts = window.location.hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  if (parts[0] !== "i" || !parts[1]) return { screen: "list", current: null };
  const screen = SCREENS.find((s) => SCREEN_SLUGS[s] === parts[2]) ?? "walk";
  return { screen, current: parts[1] };
}

function writeHash(screen: Screen, current: string | null): void {
  const next = screen === "list" || !current ? "#/" : `#/i/${current}/${SCREEN_SLUGS[screen]}`;
  if (window.location.hash !== next) window.location.hash = next;
}

export default function App() {
  const [catalogue, setCatalogue] = useState<Catalogue | null>(null);
  const [route, setRoute] = useState(readHash);
  const [fatal, setFatal] = useState<string | null>(null);
  const { screen, current } = route;

  // The address bar is the source of truth, so the back button works by construction rather
  // than by keeping a second history of our own in step with the browser's.
  useEffect(() => {
    const onHash = () => setRoute(readHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const go = useCallback((next: Screen, id: string | null) => {
    writeHash(next, id);
    setRoute({ screen: next, current: id });
  }, []);

  const load = useCallback(() => {
    setFatal(null);
    api
      .catalogue()
      .then(setCatalogue)
      .catch((e: ApiError) => setFatal(e.message));
  }, []);
  useEffect(load, [load]);

  return (
    <div className="shell">
      <header className="topbar">
        <span className="topbar__title">Inspection report builder</span>
        {current && screen !== "list" && (
          <button className="btn--quiet btn--small" onClick={() => go("list", null)}>
            All inspections
          </button>
        )}
        <span className="topbar__meta">Observational reporting · built on SuperDocs</span>
      </header>

      <main className="main">
        {fatal && <ErrorNote error={fatal} onRetry={load} />}
        {!catalogue && !fatal && <Skeleton />}
        {catalogue && !fatal && (
          <>
            {screen === "list" && (
              <InspectionList catalogue={catalogue} onOpen={(id) => go("walk", id)} />
            )}
            {screen !== "list" && current && (
              <InspectionWorkspace
                key={current}
                id={current}
                screen={screen}
                setScreen={(next) => go(next, current)}
                onDeleted={() => go("list", null)}
                catalogue={catalogue}
              />
            )}
          </>
        )}
      </main>
    </div>
  );
}

/* ------------------------------------------------------------------ list */

function InspectionList({
  catalogue,
  onOpen,
}: {
  catalogue: Catalogue;
  onOpen: (id: string) => void;
}) {
  const [rows, setRows] = useState<InspectionRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const refresh = useCallback(() => {
    setError(null);
    api
      .listInspections()
      .then(setRows)
      .catch((e: ApiError) => setError(e.message));
  }, []);
  useEffect(refresh, [refresh]);

  return (
    <>
      <div className="section-head">
        <h1>Inspections</h1>
        <span className="section-head__count">{rows ? `${rows.length} on file` : ""}</span>
        <div className="section-head__actions">
          <button className="btn--primary" onClick={() => setCreating((v) => !v)}>
            {creating ? "Cancel" : "New inspection"}
          </button>
        </div>
      </div>

      {creating && (
        <NewInspection
          catalogue={catalogue}
          onCreated={(id) => {
            setCreating(false);
            onOpen(id);
          }}
        />
      )}

      {error && <ErrorNote error={error} onRetry={refresh} />}
      {!rows && !error && <Skeleton rows={2} />}
      {rows?.length === 0 && (
        <Empty title="Nothing here yet">
          <p className="hint">
            Start an inspection, then walk the property system by system. Nothing is sent
            anywhere until you ask for the report.
          </p>
        </Empty>
      )}
      {rows && rows.length > 0 && (
        <div className="list">
          {rows.map((r, i) => (
            <button key={r.id} className="list__item" onClick={() => onOpen(r.id)}>
              <span className="list__index" aria-hidden="true">
                {String(i + 1).padStart(2, "0")}
              </span>
              <span className="list__main">
                <strong>{r.address_line}</strong>
                <span className="list__meta">
                  {r.city} · {r.inspected_on} · {r.finding_count}{" "}
                  {r.finding_count === 1 ? "finding" : "findings"} · {stageLabel(r.stage)}
                </span>
              </span>
              <span aria-hidden="true">›</span>
            </button>
          ))}
        </div>
      )}
    </>
  );
}

function NewInspection({
  catalogue,
  onCreated,
}: {
  catalogue: Catalogue;
  onCreated: (id: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const today = new Date().toISOString().slice(0, 10);

  return (
    <form
      className="panel stack"
      onSubmit={(e) => {
        e.preventDefault();
        const f = new FormData(e.currentTarget);
        setBusy(true);
        setError(null);
        api
          .createInspection({
            property: {
              address_line: String(f.get("address") ?? ""),
              city: String(f.get("city") ?? ""),
              postcode: String(f.get("postcode") ?? ""),
            },
            inspector: {
              name: String(f.get("inspector") ?? ""),
              licence_number: String(f.get("licence") ?? ""),
              firm_name: String(f.get("firm") ?? ""),
            },
            inspected_on: String(f.get("date") ?? today),
            template_key: String(f.get("format") ?? catalogue.formats[0]),
          })
          .then((r) => onCreated(r.id))
          .catch((e: ApiError) => setError(e.message))
          .finally(() => setBusy(false));
      }}
    >
      <h3>New inspection</h3>
      {error && <ErrorNote error={error} />}
      <div className="field-grid field-grid--2">
        <label>
          Property address
          <input name="address" required autoComplete="off" />
        </label>
        <label>
          Town or city
          <input name="city" required autoComplete="off" />
        </label>
        <label>
          Postcode
          <input name="postcode" autoComplete="off" />
        </label>
        <label>
          Date of inspection
          <input name="date" type="date" defaultValue={today} required />
        </label>
        <label>
          Inspector
          <input name="inspector" required autoComplete="off" />
        </label>
        <label>
          Licence number
          <input name="licence" autoComplete="off" />
        </label>
        <label>
          Firm
          <input name="firm" autoComplete="off" />
        </label>
        <label>
          Report format
          <select name="format" defaultValue={catalogue.formats[0]}>
            {catalogue.formats.map((f) => (
              <option key={f} value={f}>
                {f.replace(/_/g, " ")}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="row">
        <button className="btn--primary" type="submit" disabled={busy}>
          {busy ? "Creating…" : "Start inspection"}
        </button>
      </div>
    </form>
  );
}

/* ------------------------------------------------------------- workspace */

function InspectionWorkspace({
  id,
  screen,
  setScreen,
  onDeleted,
  catalogue,
}: {
  id: string;
  screen: Screen;
  setScreen: (s: Screen) => void;
  onDeleted: () => void;
  catalogue: Catalogue;
}) {
  const [inspection, setInspection] = useState<Inspection | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [toast, say] = useToast();

  const refresh = useCallback(() => {
    setError(null);
    return api
      .getInspection(id)
      .then(setInspection)
      .catch((e: ApiError) => setError(e.message));
  }, [id]);
  useEffect(() => {
    void refresh();
  }, [refresh]);

  if (error) return <ErrorNote error={error} onRetry={() => void refresh()} />;
  if (!inspection) return <Skeleton />;

  return (
    <>
      <div className="section-head">
        <h1>{inspection.property.address_line}</h1>
        <span className="section-head__count">
          {inspection.property.city} · {inspection.inspected_on}
        </span>
        <div className="section-head__actions">
          <ConfirmButton
            label="Delete inspection"
            question={`Delete ${inspection.property.address_line} and its ${inspection.findings.length} findings? This cannot be undone.`}
            confirm="Delete permanently"
            busy={deleting}
            onConfirm={() => {
              setDeleting(true);
              api
                .deleteInspection(id)
                .then(onDeleted)
                .catch((e: ApiError) => {
                  setError(e.message);
                  setDeleting(false);
                });
            }}
          />
        </div>
      </div>

      <div className="tabs" role="tablist">
        {(
          [
            ["walk", "The walk"],
            ["gate", "Review"],
            ["export", "Export"],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            role="tab"
            className="tab"
            aria-selected={screen === key}
            onClick={() => setScreen(key)}
          >
            {label}
          </button>
        ))}
      </div>

      {screen === "walk" && (
        <Walk
          inspection={inspection}
          catalogue={catalogue}
          onChanged={() => void refresh()}
          say={say}
        />
      )}
      {screen === "gate" && (
        <Gate id={id} catalogue={catalogue} onDecided={() => void refresh()} say={say} />
      )}
      {screen === "export" && <ExportPanel id={id} inspection={inspection} say={say} />}
      {toast}
    </>
  );
}

/* ------------------------------------------------------------------ walk */

function Walk({
  inspection,
  catalogue,
  onChanged,
  say,
}: {
  inspection: Inspection;
  catalogue: Catalogue;
  onChanged: () => void;
  say: (m: string) => void;
}) {
  const severityByKey = useMemo(
    () => new Map(catalogue.severities.map((s) => [s.key, s])),
    [catalogue.severities],
  );
  const [openSystem, setOpenSystem] = useState<string | null>(null);

  return (
    <div className="stack stack--sections">
      <ReportShape
        systems={catalogue.systems}
        severities={catalogue.severities}
        findings={inspection.findings}
      />
      <p className="hint">
        Findings are grouped by system in the report, in this order, whatever order you record
        them in.
      </p>
      {catalogue.systems.map((system, index) => {
        const findings = inspection.findings.filter((f) => f.system_key === system.key);
        return (
          <section className="ruled" key={system.key}>
            {/* The rail carries the section number and the count, the way a report's
                sections are numbered. The content sits beside it. */}
            <div className="ruled__rail">
              <span className="section-num">{String(index + 1).padStart(2, "0")}</span>
              <span className="section-head__count">
                {findings.length === 0 ? "none" : `${findings.length} recorded`}
              </span>
            </div>
            <div className="ruled__body">
              <div className="section-head">
                <h3>{system.name}</h3>
                <div className="section-head__actions">
                  <button
                    className="btn--small"
                    onClick={() => setOpenSystem(openSystem === system.key ? null : system.key)}
                  >
                    {openSystem === system.key ? "Close" : "Add finding"}
                  </button>
                </div>
              </div>

            {findings.map((f) => (
              <FindingCard
                key={f.id}
                finding={f}
                severity={severityByKey.get(f.severity_key)}
                onChanged={onChanged}
                say={say}
              />
            ))}

              {openSystem === system.key && (
                <NewFinding
                  inspectionId={inspection.id}
                  systemKey={system.key}
                  catalogue={catalogue}
                  onAdded={() => {
                    setOpenSystem(null);
                    onChanged();
                    say(`Finding recorded under ${system.name}.`);
                  }}
                />
              )}
            </div>
          </section>
        );
      })}
    </div>
  );
}

function FindingCard({
  finding,
  severity,
  onChanged,
  say,
}: {
  finding: Inspection["findings"][number];
  severity: Catalogue["severities"][number] | undefined;
  onChanged: () => void;
  say: (m: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  return (
    <div className="finding">
      <div className="finding__head">
        <SeverityTag severity={severity} />
        {finding.location && <span className="finding__where">{finding.location}</span>}
        <span className="finding__actions">
          <ConfirmButton
            label="Remove"
            question="Remove this finding and its photographs?"
            confirm="Remove"
            busy={busy}
            onConfirm={() => {
              setBusy(true);
              api
                .deleteFinding(finding.id)
                .then(() => {
                  onChanged();
                  say("Finding removed.");
                })
                .catch((err: ApiError) => setError(err.message))
                .finally(() => setBusy(false));
            }}
          />
        </span>
      </div>
      <p className="finding__note">{finding.observation}</p>
      {finding.plain_language && (
        <div className="notice notice--ok">
          <div className="notice__head">Approved rewrite, used in the report</div>
          <div>{finding.plain_language}</div>
        </div>
      )}
      {finding.recommendation && (
        <p className="hint">Recommended next step: {finding.recommendation}</p>
      )}

      {finding.photos.length > 0 && (
        <div className="thumbs">
          {finding.photos.map((p) => (
            <figure className="thumb-wrap" key={p.id}>
              <img
                className="thumb"
                src={api.photoUrl(p.id)}
                alt={p.caption || `Photograph for ${finding.location || "this finding"}`}
                loading="lazy"
              />
              <ConfirmButton
                label="Remove"
                question="Remove this photograph?"
                confirm="Remove"
                busy={busy}
                onConfirm={() => {
                  setBusy(true);
                  api
                    .deletePhoto(p.id)
                    .then(() => {
                      onChanged();
                      say("Photograph removed.");
                    })
                    .catch((err: ApiError) => setError(err.message))
                    .finally(() => setBusy(false));
                }}
              />
            </figure>
          ))}
        </div>
      )}

      {error && <ErrorNote error={error} />}
      <div className="row">
        <input
          ref={fileRef}
          type="file"
          accept="image/png,image/jpeg,image/webp,image/heic,image/heif,.heic,.heif"
          className="visually-hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (!file) return;
            setBusy(true);
            setError(null);
            api
              .addPhoto(finding.id, file)
              .then((r) => {
                onChanged();
                say(
                  r.stripped_exif
                    ? "Photograph added. Location data was removed."
                    : "Photograph added.",
                );
              })
              .catch((err: ApiError) => setError(err.message))
              .finally(() => {
                setBusy(false);
                if (fileRef.current) fileRef.current.value = "";
              });
          }}
        />
        <button className="btn--small" disabled={busy} onClick={() => fileRef.current?.click()}>
          {busy ? "Processing…" : "Add photograph"}
        </button>
        <span className="hint">Location data is removed before the photo is stored.</span>
      </div>
    </div>
  );
}

function NewFinding({
  inspectionId,
  systemKey,
  catalogue,
  onAdded,
}: {
  inspectionId: string;
  systemKey: string;
  catalogue: Catalogue;
  onAdded: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [verdict, setVerdict] = useState<{ clean: boolean; summary: string } | null>(null);

  // The rail's opinion while you type. Advisory here — an inspector may write whatever they
  // judge correct, and the rail only ever *blocks* text this system generated.
  useEffect(() => {
    if (note.trim().length < 12) {
      setVerdict(null);
      return;
    }
    const t = setTimeout(() => {
      api
        .checkPhrasing(note)
        .then((v) => setVerdict({ clean: v.clean, summary: v.summary }))
        .catch(() => setVerdict(null));
    }, 400);
    return () => clearTimeout(t);
  }, [note]);

  return (
    <form
      className="panel stack"
      onSubmit={(e) => {
        e.preventDefault();
        const f = new FormData(e.currentTarget);
        setBusy(true);
        setError(null);
        api
          .addFinding(inspectionId, {
            system_key: systemKey,
            severity_key: String(f.get("severity") ?? ""),
            location: String(f.get("location") ?? ""),
            observation: note,
            recommendation: String(f.get("recommendation") ?? ""),
          })
          .then(onAdded)
          .catch((err: ApiError) => setError(err.message))
          .finally(() => setBusy(false));
      }}
    >
      {error && <ErrorNote error={error} />}
      <div className="field-grid field-grid--2">
        <label>
          Severity
          <select name="severity" defaultValue={catalogue.severities[1]?.key} required>
            {catalogue.severities.map((s) => (
              <option key={s.key} value={s.key}>
                {s.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Location
          <input name="location" placeholder="North chimney" autoComplete="off" />
        </label>
      </div>
      <label>
        What you observed
        <textarea
          name="observation"
          required
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="S flashing gap ~2in @ chimney, staining below"
        />
      </label>
      {verdict && !verdict.clean && (
        <div className="notice">
          <div className="notice__head">Heads up — {verdict.summary}</div>
          <div className="hint">
            Your wording is kept exactly as written. This is only a note that the phrasing
            reads as a claim about the property rather than an observation.
          </div>
        </div>
      )}
      <label>
        Recommended next step
        <input
          name="recommendation"
          placeholder="Evaluation by a licensed roofing contractor."
          autoComplete="off"
        />
      </label>
      <div className="row">
        <button className="btn--primary" type="submit" disabled={busy || !note.trim()}>
          {busy ? "Saving…" : "Record finding"}
        </button>
      </div>
    </form>
  );
}

/* ------------------------------------------------------------------ gate */

function Gate({
  id,
  catalogue,
  onDecided,
  say,
}: {
  id: string;
  catalogue: Catalogue;
  onDecided: () => void;
  say: (m: string) => void;
}) {
  const [proposals, setProposals] = useState<Proposal[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [approvals, setApprovals] = useState<Record<string, boolean>>({});
  const [tier, setTier] = useState("core");
  const [ops, setOps] = useState<number | null>(null);
  // Which SuperDocs answered, and where the format came from. Both are shown rather than
  // assumed: a run against the fake must not look like a run against the service.
  const [provider, setProvider] = useState<string | null>(null);
  const [templateSource, setTemplateSource] = useState<string | null>(null);

  const load = useCallback(() => {
    setError(null);
    api
      .proposals(id)
      .then((r) => setProposals(r.proposals))
      .catch((e: ApiError) => setError(e.message));
  }, [id]);
  useEffect(load, [load]);

  /**
   * Follow a queued review to its end.
   *
   * The work runs on the server, so this is a poll rather than an await: closing the page or
   * reloading loses nothing, and coming back picks the job up again. `stopped` guards the
   * timer against a component that has gone away mid-review.
   */
  const watchJob = useCallback(
    (jobId: string) => {
      let stopped = false;
      const poll = () => {
        if (stopped) return;
        api
          .job(jobId)
          .then((job) => {
            if (stopped) return;
            if (job.state === "queued" || job.state === "running") {
              window.setTimeout(poll, 1200);
              return;
            }
            setBusy(null);
            if (job.result?.ops_remaining != null) setOps(job.result.ops_remaining);
            if (job.result?.provider) setProvider(job.result.provider);
            if (job.result?.template_source) setTemplateSource(job.result.template_source);
            if (job.state === "failed") {
              setError(job.error ?? "the review did not finish");
              return;
            }
            setApprovals({});
            api
              .proposals(id)
              .then((r) => {
                setProposals(r.proposals);
                const refused = r.proposals.filter((p) => !p.rail_clean).length;
                say(
                  refused === 0
                    ? `${r.proposals.length} rewrites proposed.`
                    : `${r.proposals.length} proposed, ${refused} refused by the language rail.`,
                );
              })
              .catch((e: ApiError) => setError(e.message));
          })
          .catch((e: ApiError) => {
            setBusy(null);
            setError(e.message);
          });
      };
      poll();
      return () => {
        stopped = true;
      };
    },
    [id, say],
  );

  // A review already running when this page loads — a reload, or a second tab — is picked
  // up rather than shown as an idle screen with a button that would be refused with a 409.
  useEffect(() => {
    let cancel: (() => void) | undefined;
    api
      .latestJob(id)
      .then((job) => {
        // Where the last run's format came from, and which SuperDocs answered, survive a
        // reload: they describe the proposals on screen, which also survived it.
        if (job.result?.provider) setProvider(job.result.provider);
        if (job.result?.template_source) setTemplateSource(job.result.template_source);
        if (job.state === "queued" || job.state === "running") {
          setBusy("prepare");
          cancel = watchJob(job.id ?? "");
        }
      })
      .catch(() => undefined);
    return () => cancel?.();
  }, [id, watchJob]);

  // Only a rail-clean proposal is anyone's to decide: a refusal is already settled and is
  // not offered as a choice.
  const undecided = (proposals ?? []).filter((p) => p.rail_clean && p.decision === "pending");
  const stillToDecide = undecided.filter(
    (p) => approvals[p.change_id] === undefined,
  ).length;
  const allDecided = (proposals ?? []).length > 0 && undecided.length === 0;

  return (
    <div className="stack stack--sections">
      <div className="card stack">
        <h3>Plain-language rewrite</h3>
        <p className="hint">
          SuperDocs rewrites each field note for someone who has never read an inspection
          report. Nothing is applied until you decide, and anything that reads as a
          certification is refused before it reaches you.
        </p>
        <div className="row row--controls">
          <label style={{ maxWidth: 220 }}>
            Precision
            <select value={tier} onChange={(e) => setTier(e.target.value)}>
              <option value="core">Standard</option>
              <option value="turbo">Fastest</option>
              <option value="pro">Careful</option>
              <option value="max">Most careful</option>
            </select>
          </label>
          <button
            className="btn--primary"
            disabled={busy !== null}
            onClick={() => {
              setBusy("prepare");
              setError(null);
              api
                .prepare(id, tier)
                .then((r) => watchJob(r.job_id))
                .catch((e: ApiError) => {
                  setError(e.message);
                  setBusy(null);
                });
            }}
          >
            {busy === "prepare" ? "Asking…" : "Propose rewrites"}
          </button>
          {/* `!== null` is not enough for a value that arrives as JSON: an absent field is
              undefined, which passes that test and then fails on the method call.

              Shown as a balance only when it is one. The offline fake counts down from an
              invented 10,000, and on screen that was indistinguishable from the real
              SuperDocs balance — a number nobody could tell was made up. */}
          {typeof ops === "number" && provider === "live" && (
            <span className="hint">{ops.toLocaleString()} operations left</span>
          )}
          {provider !== null && provider !== "live" && (
            <span className="hint">Offline stand-in — no operations charged</span>
          )}
        </div>
        {busy === "prepare" && (
          <p className="hint">
            Queued. A large report can take a minute or more, and it runs on the server —
            closing this page or reloading is safe, and the review will be here when you come
            back.
          </p>
        )}
        {/* The report is built on the document SuperDocs returns for the registered format.
            When it cannot be, that is said plainly rather than left to look the same. */}
        {templateSource !== null && (
          <p className="hint">
            {templateSource === "superdocs"
              ? "Report format loaded from SuperDocs for this run."
              : templateSource === "cache"
                ? "Report format from SuperDocs, held for this version of the format."
                : "SuperDocs could not be reached for the format — this report was built from the local copy."}
          </p>
        )}
      </div>

      {error && <ErrorNote error={error} onRetry={load} />}
      {busy === "prepare" && <Skeleton rows={2} />}
      {proposals?.length === 0 && !busy && (
        <Empty title="Nothing proposed yet">
          <p className="hint">Record your findings, then ask for the rewrites.</p>
        </Empty>
      )}

      {proposals?.map((p) => (
        <article className="proposal stack" key={p.change_id}>
          <div className="diff">
            <div className="diff__side diff__side--original">
              <span className="diff__label">What you wrote</span>
              <div className="diff__text">{p.before}</div>
            </div>
            <div className="diff__side diff__side--proposed">
              <span className="diff__label">
                {p.rail_clean ? "Proposed for the buyer — additions marked" : "Proposed — flagged wording marked"}
              </span>
              <div className={`diff__text${p.rail_clean ? "" : " diff__text--flagged"}`}>
                {p.rail_clean ? (
                  <WordDiff before={p.before} after={p.after} />
                ) : (
                  <Flagged text={p.after} breaches={p.breaches ?? []} />
                )}
              </div>
            </div>
          </div>
          <RailVerdict clean={p.rail_clean} breaches={p.breaches ?? []} />
          {p.rail_clean && (
            <div className="row">
              <button
                className={approvals[p.change_id] === true ? "btn--primary" : ""}
                aria-pressed={approvals[p.change_id] === true}
                onClick={() => setApprovals((a) => ({ ...a, [p.change_id]: true }))}
              >
                Use the rewrite
              </button>
              <button
                className={approvals[p.change_id] === false ? "btn--primary" : ""}
                aria-pressed={approvals[p.change_id] === false}
                onClick={() => setApprovals((a) => ({ ...a, [p.change_id]: false }))}
              >
                Keep my wording
              </button>
              {p.decision && p.decision !== "pending" && (
                <span className="hint">already {p.decision}</span>
            )}
            </div>
          )}
        </article>
      ))}

      {proposals && proposals.length > 0 && (
        <div className="card stack">
          <p className="hint">
            Decisions are sent together, because approving closes the round on SuperDocs&rsquo;
            side and it cannot be reopened.
          </p>
          <div className="row">
            <button
              className="btn--primary"
              disabled={busy !== null || allDecided || stillToDecide > 0}
              onClick={() => {
                setBusy("decide");
                setError(null);
                api
                  .decide(id, approvals)
                  .then((r) => {
                    setProposals(r.proposals);
                    onDecided();
                    const used = r.proposals.filter((p) => p.approved).length;
                    say(`Decisions sent. ${used} rewrite${used === 1 ? "" : "s"} applied.`);
                  })
                  .catch((e: ApiError) => setError(e.message))
                  .finally(() => setBusy(null));
              }}
            >
              {/* The button says why it is disabled. A greyed control with the reason in
                  small text beside it reads as "already done" — which is exactly how it was
                  misread in testing, by the person who commissioned it. */}
              {busy === "decide"
                ? "Sending…"
                : allDecided
                  ? "Decisions already applied"
                  : stillToDecide > 0
                    ? `Decide ${stillToDecide} more to apply`
                    : "Apply decisions"}
            </button>
            {stillToDecide > 0 && (
              <span className="hint">
                Choose <em>Use the rewrite</em> or <em>Keep my wording</em> on the
                {stillToDecide === 1 ? " one left" : ` ${stillToDecide} left`}. The rail&rsquo;s
                refusals are already decided and need nothing from you.
              </span>
            )}
            {allDecided && (
              <span className="hint">
                Sent. Approving closes the round, so this cannot be reopened — the export is
                next.
              </span>
            )}
          </div>
        </div>
      )}

      <details className="card">
        <summary>What the language rail refuses ({catalogue.rail_rules.length} rules)</summary>
        <div className="stack" style={{ marginTop: "0.7rem" }}>
          {catalogue.rail_rules.map((r) => (
            <div key={r.id}>
              <strong>{r.category}</strong> — {r.why} <em>{r.suggest}</em>
            </div>
          ))}
        </div>
      </details>
    </div>
  );
}

/* ---------------------------------------------------------------- export */

function ExportPanel({
  id,
  inspection,
  say,
}: {
  id: string;
  inspection: Inspection;
  say: (m: string) => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [checks, setChecks] = useState<Check[] | null>(null);
  const [verified, setVerified] = useState<boolean | null>(null);

  const photoCount = inspection.findings.reduce((n, f) => n + f.photos.length, 0);
  const systemsWithFindings = new Set(inspection.findings.map((f) => f.system_key)).size;
  const rewritten = inspection.findings.filter((f) => f.plain_language).length;

  const run = (fmt: "pdf" | "docx") => {
    setBusy(fmt);
    setError(null);
    api
      .exportReport(id, fmt)
      .then(({ blob, checks, verified }) => {
        setChecks(checks);
        setVerified(verified);
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `${inspection.property.address_line.replace(/\W+/g, "-").toLowerCase()}.${fmt}`;
        a.click();
        URL.revokeObjectURL(url);
        say(
          verified
            ? `${fmt.toUpperCase()} downloaded — every check passed.`
            : `${fmt.toUpperCase()} downloaded, but some checks failed. See below.`,
        );
      })
      .catch((e: ApiError) => setError(e.message))
      .finally(() => setBusy(null));
  };

  return (
    <div className="stack">
      <div className="card stack">
        <h3>Export the report</h3>
        <p className="hint">
          Findings are grouped by inspection system, most urgent first within each. Photographs
          are embedded in the file itself, so the report carries its own evidence.
        </p>

        {/* What is about to be produced, before it is produced. This is the last screen
            before a document goes to a buyer, and it was the one screen with nothing on it
            to check against. All of it is already known here — none of it costs a call. */}
        <dl className="tally">
          <div>
            <dt>Format</dt>
            <dd>{inspection.template_key.replace(/_/g, " ")}</dd>
          </div>
          <div>
            {/* Every system gets a section either way; this is how many have something in
                them. A system with nothing under it says so, which is the point. */}
            <dt>Systems with findings</dt>
            <dd>{systemsWithFindings}</dd>
          </div>
          <div>
            <dt>Findings</dt>
            <dd>{inspection.findings.length}</dd>
          </div>
          <div>
            <dt>Photographs</dt>
            <dd>{photoCount}</dd>
          </div>
          <div>
            <dt>Rewrites in use</dt>
            <dd>{rewritten} of {inspection.findings.length}</dd>
          </div>
        </dl>

        <div className="row">
          <button className="btn--primary" disabled={busy !== null} onClick={() => run("pdf")}>
            {busy === "pdf" ? "Building…" : "Download PDF"}
          </button>
          <button disabled={busy !== null} onClick={() => run("docx")}>
            {busy === "docx" ? "Building…" : "Download Word"}
          </button>
        </div>
      </div>

      {error && <ErrorNote error={error} />}
      {busy && <Skeleton rows={1} />}

      {checks && (
        <div className="card stack">
          <div className="section-head">
            <h3>What the exported file actually contains</h3>
            <span className="section-head__count">
              {verified ? "all checks passed" : "some checks failed"}
            </span>
          </div>
          <p className="hint">
            These are read back out of the finished file, not out of what was sent to build it.
          </p>
          <CheckList checks={checks} />
        </div>
      )}
    </div>
  );
}
