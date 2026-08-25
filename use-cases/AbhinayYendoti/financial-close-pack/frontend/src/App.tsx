import {
  ArrowRight,
  Check,
  CheckCircle2,
  CircleDashed,
  Download,
  FileCheck2,
  FileText,
  Gauge,
  History,
  LayoutDashboard,
  LockKeyhole,
  LogOut,
  Menu,
  PackageCheck,
  Search,
  ShieldCheck,
  Sparkles,
  Trash2,
  Upload,
  Workflow,
  X
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, api, loadSession, saveBlob, storeSession } from "./lib/api";
import {
  cleanDetail,
  formatBytes,
  formatDate,
  formatEvent,
  formatPeriod,
  formatTime,
  formatTimestamp,
  statusLabel
} from "./lib/format";
import { ReadinessView, toReadinessView } from "./lib/readiness";
import { computeSteps, generationBlockReason, humanizeType, nextAction, routeBlockers } from "./lib/guidance";
import { AuditPage, ClosesPage, ExportsPage, TemplatesPage } from "./pages";
import type {
  AuditEvent,
  ChecklistItem,
  CloseDetail,
  DocumentItem,
  ExportStatus,
  GeneratedArtifact,
  GenerationJob,
  ReviewItem,
  Session,
  SignoffItem,
  SuperDocsLedger,
  Template
} from "./lib/types";

type Tab = "overview" | "documents" | "checklist" | "review" | "signoffs" | "pack" | "superdocs";

const tabs: Array<{ id: Tab; label: string; icon: typeof LayoutDashboard }> = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "documents", label: "Documents", icon: FileText },
  { id: "checklist", label: "Checklist", icon: CheckCircle2 },
  { id: "review", label: "Review", icon: ShieldCheck },
  { id: "signoffs", label: "Sign-offs", icon: FileCheck2 },
  { id: "pack", label: "Final Pack", icon: PackageCheck }
];

/**
 * Top-level destinations. These used to be five labels that all just switched the
 * workspace tab - two of them to the same one - so most of the bar looked broken.
 * Each is now a real page built from data the app already loads.
 */
type View = "workspace" | "closes" | "templates" | "audit" | "exports";

const navLinks: Array<{ label: string; view: View }> = [
  { label: "Workspace", view: "workspace" },
  { label: "Closes", view: "closes" },
  { label: "Templates", view: "templates" },
  { label: "Activity", view: "audit" },
  { label: "Exports", view: "exports" }
];

/**
 * The operations ledger is engineering evidence, not a product surface, so it is no
 * longer a tab. Append `?debug=1` to reach it when verifying the integration.
 */
/**
 * Generation polling.
 *
 * A live run uploads every source document and then waits on a real model edit, which
 * took ~70s in testing, so the old 700ms period issued well over a hundred requests for
 * one job. Two seconds is still responsive against a job measured in minutes.
 */
const JOB_POLL_INTERVAL_MS = 2000;
const JOB_POLL_MAX_FAILURES = 5;
/** Comfortably past the backend's own GENERATION_TIMEOUT_SECONDS (900s default). */
const JOB_POLL_TIMEOUT_MS = 16 * 60 * 1000;

function debugEnabled(): boolean {
  if (typeof window === "undefined") return false;
  return new URLSearchParams(window.location.search).has("debug");
}

/** The contract, in the order the close pack drives it. */
const CONTRACT_LABELS: Record<string, string> = {
  upload_document: "Upload source documents",
  send_edit_instruction: "Send edit instruction",
  approve_changes: "Approve proposed changes",
  export_document: "Export finished document"
};

function asApiError(error: unknown): ApiError {
  return error instanceof ApiError ? error : new ApiError(0, (error as Error)?.message ?? "Unexpected error");
}

function matches(query: string, ...fields: Array<string | null | undefined>): boolean {
  const needle = query.trim().toLowerCase();
  if (!needle) return true;
  return fields.some((field) => (field ?? "").toLowerCase().includes(needle));
}

/**
 * Supplied by the Clerk wrapper; absent in demo mode.
 *
 * The workspace below does not care which identity provider is live - it needs a session
 * with a token and an attributable user, a way to start signing in, and a way to drop the
 * session on a 401. Keeping that behind one object is what lets a single App serve both.
 */
export type AuthAdapter = {
  session: Session | null;
  signIn: () => void;
  signOut: () => void;
};

export function App({ auth }: { auth?: AuthAdapter } = {}) {
  // Only demo mode persists a session locally; with Clerk, Clerk owns the session and
  // rehydrating a stale copy from localStorage would fight it.
  const [demoSession, setDemoSession] = useState<Session | null>(() => (auth ? null : loadSession()));
  const session = auth ? auth.session : demoSession;
  const setSession = auth
    ? (next: Session | null) => {
        if (!next) auth.signOut();
      }
    : setDemoSession;
  const [close, setClose] = useState<CloseDetail | null>(null);
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [exportStatus, setExportStatus] = useState<ExportStatus | null>(null);
  const [ledger, setLedger] = useState<SuperDocsLedger | null>(null);
  const [artifacts, setArtifacts] = useState<GeneratedArtifact[]>([]);
  const [job, setJob] = useState<GenerationJob | null>(null);
  const [activeTab, setActiveTab] = useState<Tab>("overview");
  const [view, setView] = useState<View>("workspace");
  const [closes, setCloses] = useState<CloseDetail[]>([]);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [templateError, setTemplateError] = useState("");
  const [emptyAccount, setEmptyAccount] = useState(false);
  const [showDebug] = useState(debugEnabled);
  const [error, setError] = useState("");
  const [blockNotice, setBlockNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [query, setQuery] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [navOpen, setNavOpen] = useState(false);

  const token = session?.token ?? "";
  const readiness = useMemo(() => toReadinessView(close?.readiness), [close]);
  const closed = Boolean(close?.closed_at);
  const steps = useMemo(() => computeSteps(readiness, closed), [readiness, closed]);
  const guidance = useMemo(() => nextAction(readiness, closed), [readiness, closed]);

  const handleFailure = useCallback((error: unknown) => {
    const failure = asApiError(error);
    if (failure.status === 401) {
      storeSession(null);
      setSession(null);
      setClose(null);
      return;
    }
    setError(failure.message);
  }, []);

  const loadWorkspace = useCallback(
    async (preferredId?: string) => {
      if (!token) return;
      try {
        // The list is kept, not thrown away: it backs the Closes, Activity and Exports
        // pages, all of which are aggregations over whole close documents.
        const available = await api.listCloses(token);
        setCloses(available);

        const closeId = preferredId ?? available[0]?.id;
        if (!closeId) {
          setClose(null);
          setEmptyAccount(true);
          return;
        }
        setEmptyAccount(false);

        const [detail, trail, exported, superdocs, generated] = await Promise.all([
          api.getClose(token, closeId),
          api.getAudit(token, closeId),
          api.getExportStatus(token, closeId),
          api.getSuperDocs(token, closeId),
          api.getArtifacts(token, closeId)
        ]);

        setClose(detail);
        setAuditEvents(trail);
        setExportStatus(exported);
        setLedger(superdocs);
        setArtifacts(generated);
        setError("");
      } catch (failure) {
        handleFailure(failure);
      }
    },
    [token, handleFailure]
  );

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    api
      .listTemplates(token)
      .then((result) => {
        if (!cancelled) setTemplates(result);
      })
      .catch(() => {
        if (!cancelled) setTemplateError("Templates could not be loaded right now.");
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  useEffect(() => {
    if (token) void loadWorkspace();
  }, [token, loadWorkspace]);

  // Poll a running generation job.
  //
  // Three things this has to get right, each of which was previously wrong:
  //  - `setInterval` with an async callback overlaps requests whenever a response takes
  //    longer than the period. A chained timeout only schedules the next poll once the
  //    last one has settled.
  //  - Swallowing every error as "transient" meant an expired session produced an
  //    unbounded 401 flood, several times a second, that the user never saw. An auth
  //    failure is terminal for a poll loop, so it stops and surfaces.
  //  - A job that never settles has to be abandoned rather than polled forever.
  useEffect(() => {
    if (!close || !job || job.status !== "RUNNING") return;

    const closeId = close.id;
    const jobId = job.id;
    const startedAt = Date.now();
    let cancelled = false;
    let failures = 0;
    let timer = 0;

    const stop = (message?: string) => {
      setJob(null);
      if (message) setError(message);
    };

    const tick = async () => {
      if (cancelled) return;

      if (Date.now() - startedAt > JOB_POLL_TIMEOUT_MS) {
        stop("We lost track of that run. Reload the page to see where the close got to.");
        return;
      }

      try {
        const next = await api.getJob(token, closeId, jobId);
        if (cancelled) return;
        failures = 0;
        setJob(next);
        if (next.status !== "RUNNING") {
          void loadWorkspace(closeId);
          return;
        }
      } catch (failure) {
        if (cancelled) return;
        const apiFailure = asApiError(failure);
        if (apiFailure.status === 401 || apiFailure.status === 403) {
          stop();
          handleFailure(failure);
          return;
        }
        failures += 1;
        if (failures >= JOB_POLL_MAX_FAILURES) {
          stop("We lost contact while building the pack. Reload the page to see where it got to.");
          return;
        }
      }

      timer = window.setTimeout(tick, JOB_POLL_INTERVAL_MS);
    };

    timer = window.setTimeout(tick, JOB_POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [token, close, job, loadWorkspace, handleFailure]);

  // Clear a stale "close blocked" banner once the blockers are actually resolved.
  useEffect(() => {
    if (readiness.canClose) setBlockNotice("");
  }, [readiness.canClose]);

  /**
   * Re-read just the close after a mutation.
   *
   * `loadWorkspace` issues six requests - the close list, the close, the audit trail, the
   * export status, the operation ledger and the artifacts - and every checklist tick and
   * review decision was paying for all of them. `GET /closes/{id}` already carries the
   * documents, checklist, reviews, sign-offs, audit trail and readiness, so one request
   * covers everything a routine mutation can change.
   */
  const refreshClose = useCallback(
    async (closeId: string) => {
      const detail = await api.getClose(token, closeId);
      setClose(detail);
      setAuditEvents(detail.audit ?? []);
    },
    [token]
  );

  const run = useCallback(
    async (action: (closeId: string) => Promise<unknown>, options: { full?: boolean } = {}) => {
      if (!close || busy) return;
      setBusy(true);
      try {
        await action(close.id);
        setError("");
        // Generation, export and closing the period change the artifacts, the ledger and
        // the export record too, so those still need the wide reload.
        if (options.full) await loadWorkspace(close.id);
        else await refreshClose(close.id);
      } catch (failure) {
        handleFailure(failure);
      } finally {
        setBusy(false);
      }
    },
    [close, busy, loadWorkspace, refreshClose, handleFailure]
  );

  const signIn = useCallback(
    async (target: View = "workspace") => {
      setView(target);
      // With Clerk live, sign-in is Clerk's hosted flow; the backend refuses to mint a
      // demo session at all, so there is nothing to fall back to.
      if (auth) {
        setError("");
        auth.signIn();
        return;
      }
      try {
        const issued = await api.startDemoSession();
        const next: Session = { token: issued.token, user: issued.user };
        storeSession(next);
        setDemoSession(next);
        setError("");
      } catch (failure) {
        setError(asApiError(failure).message);
      }
    },
    [auth]
  );

  const startGeneration = useCallback(async () => {
    if (!close || busy) return;
    setBusy(true);
    try {
      const started = await api.generate(token, close.id);
      setJob(started);
      setError("");
      await loadWorkspace(close.id);
    } catch (failure) {
      const apiFailure = asApiError(failure);
      setError(
        apiFailure.blockers.length ? `${apiFailure.message} ${apiFailure.blockers.join(" • ")}` : apiFailure.message
      );
    } finally {
      setBusy(false);
    }
  }, [close, busy, token, loadWorkspace]);

  const exportPack = useCallback(async () => {
    if (!close || busy) return;
    setBusy(true);
    try {
      if (!close.exported) await api.createExport(token, close.id);
      const { blob, filename } = await api.downloadExport(token, close.id);
      saveBlob(blob, filename);
      setError("");
      await loadWorkspace(close.id);
    } catch (failure) {
      handleFailure(failure);
    } finally {
      setBusy(false);
    }
  }, [close, busy, token, loadWorkspace, handleFailure]);

  // The close gate is now decided by the backend, not by local state.
  const closePeriod = useCallback(async () => {
    if (!close || busy) return;
    setBusy(true);
    try {
      await api.closePeriod(token, close.id);
      setBlockNotice("");
      setError("");
      await loadWorkspace(close.id);
    } catch (failure) {
      const apiFailure = asApiError(failure);
      if (apiFailure.status === 409 && apiFailure.blockers.length) {
        setBlockNotice(apiFailure.blockers.join(" • "));
        await loadWorkspace(close.id);
      } else {
        handleFailure(apiFailure);
      }
    } finally {
      setBusy(false);
    }
  }, [close, busy, token, loadWorkspace, handleFailure]);

  const downloadArtifact = useCallback(
    async (artifact: GeneratedArtifact) => {
      if (!close) return;
      try {
        const { blob, filename } = await api.downloadArtifact(token, close.id, artifact.id, artifact.name);
        saveBlob(blob, filename);
      } catch (failure) {
        handleFailure(failure);
      }
    },
    [close, token, handleFailure]
  );

  const navigate = useCallback((tab: Tab) => {
    setActiveTab(tab);
    setView("workspace");
    setNavOpen(false);
  }, []);

  const goToView = useCallback((next: View) => {
    setView(next);
    setNavOpen(false);
    setQuery("");
  }, []);

  if (!session) {
    return <AuthScreen onSignIn={signIn} error={error} mode={auth ? "clerk" : "demo"} />;
  }

  const openClose = (closeId: string) => {
    setView("workspace");
    setActiveTab("overview");
    void loadWorkspace(closeId);
  };

  const downloadPackFor = async (closeId: string) => {
    setBusy(true);
    try {
      const file = await api.downloadExport(token, closeId);
      saveBlob(file.blob, file.filename);
    } catch (failure) {
      handleFailure(failure);
    } finally {
      setBusy(false);
    }
  };

  const nav = (
    <TopNav
      navOpen={navOpen}
      onToggleNav={() => setNavOpen((open) => !open)}
      onNavigate={goToView}
      activeView={view}
      user={session.user}
      onSignOut={() => {
        storeSession(null);
        setSession(null);
      }}
      query={query}
      onQuery={setQuery}
      searchOpen={searchOpen}
      onToggleSearch={() => {
        setSearchOpen((open) => !open);
        if (searchOpen) setQuery("");
      }}
    />
  );

  // The nav pages stand on their own; they do not need a close to be open.
  if (view !== "workspace") {
    return (
      <div className="shell">
        {nav}
        <main className="workspace">
          <section className="work-surface">
            {error && <div className="failure-band">{error}</div>}
            {view === "closes" && <ClosesPage closes={closes} activeCloseId={close?.id ?? null} onOpen={openClose} />}
            {view === "templates" && <TemplatesPage templates={templates} error={templateError} />}
            {view === "audit" && <AuditPage closes={closes} />}
            {view === "exports" && (
              <ExportsPage closes={closes} busy={busy} onOpen={openClose} onDownload={downloadPackFor} />
            )}
          </section>
        </main>
      </div>
    );
  }

  if (!close) {
    return (
      <div className="shell">
        {nav}
        <main className="workspace">
          <section className="work-surface">
            <div className="panel-flow">
              <div className="section-heading">
                <div>
                  <p className="eyebrow">
                    <span /> Workspace
                  </p>
                  <h2>
                    {emptyAccount
                      ? "You do not have a close yet"
                      : error
                        ? "We could not open this close"
                        : "Opening your close…"}
                  </h2>
                  <p className="page-lede">
                    {emptyAccount
                      ? "A close period will appear here as soon as one is created for your organisation."
                      : error
                        ? "Try again in a moment. Nothing has been changed."
                        : "One moment while we gather your documents and approvals."}
                  </p>
                </div>
              </div>
              {error && !emptyAccount && <div className="failure-band">{error}</div>}
            </div>
          </section>
        </main>
      </div>
    );
  }

  return (
    <div className="shell">
      {nav}
      <main className="workspace">
        <section className="hero-band">
          <div>
            <p className="eyebrow">
              <span /> {formatPeriod(close.period)} close
            </p>
            <h1>{close.entity}</h1>
            <p className="hero-copy">
              Collect your evidence, review every change, gather sign-offs and export the finished pack — in one place.
            </p>
          </div>
          <div className="readiness-orbit" aria-label={`${readiness.readiness}% ready`}>
            <svg viewBox="0 0 180 180" role="img">
              <title>{`Close readiness ${readiness.readiness} percent`}</title>
              <circle cx="90" cy="90" r="72" className="orbit-track" />
              <circle
                cx="90"
                cy="90"
                r="72"
                className="orbit-progress"
                pathLength="100"
                strokeDasharray={`${readiness.readiness} 100`}
              />
            </svg>
            <div>
              <strong>{readiness.readiness}%</strong>
              <span>ready</span>
            </div>
          </div>
        </section>

        <section className="app-grid">
          <aside className="side-rail">
            <div className="close-chip">Due {formatDate(close.due_date)}</div>
            {tabs.map((tab) => {
              const Icon = tab.icon;
              // Overview is the pack-building step, so it carries that step's state.
              const step = steps.find((candidate) => candidate.tab === tab.id);
              const classes = ["rail-item"];
              if (activeTab === tab.id) classes.push("active");
              if (step?.state === "current") classes.push("is-current");
              if (step?.state === "done") classes.push("is-done");
              return (
                <button className={classes.join(" ")} key={tab.id} onClick={() => navigate(tab.id)}>
                  {step?.state === "done" ? <Check size={18} /> : <Icon size={18} />}
                  <span className="rail-label">
                    {tab.label}
                    {step?.progress && <small>{step.progress}</small>}
                  </span>
                </button>
              );
            })}
            {showDebug && (
              <button
                className={activeTab === "superdocs" ? "rail-item active" : "rail-item"}
                onClick={() => navigate("superdocs")}
              >
                <Workflow size={18} />
                <span className="rail-label">Technical log</span>
              </button>
            )}
          </aside>

          <section className="work-surface">
            {error && <div className="failure-band">{error}</div>}

            {activeTab === "overview" && (
              <Overview
                steps={steps}
                guidance={guidance}
                onGo={navigate}
                readiness={readiness}
                job={job}
                busy={busy}
                closed={closed}
                events={auditEvents}
                onGenerate={startGeneration}
              />
            )}
            {activeTab === "documents" && (
              <Documents
                documents={close.documents}
                requiredTypes={close.required_document_types ?? []}
                missingTypes={close.readiness?.documents?.missing_types ?? []}
                readiness={readiness}
                query={query}
                busy={busy}
                closed={closed}
                onConfirm={(id, type) => run((closeId) => api.mapDocument(token, closeId, id, type))}
                onUpload={(file) => run((closeId) => api.uploadDocument(token, closeId, file))}
                onDelete={(id) => run((closeId) => api.deleteDocument(token, closeId, id))}
              />
            )}
            {activeTab === "checklist" && (
              <Checklist
                checklist={close.checklist}
                query={query}
                busy={busy}
                closed={closed}
                onToggle={(item) =>
                  run((closeId) =>
                    api.setChecklistStatus(
                      token,
                      closeId,
                      item.id,
                      item.status === "COMPLETE" ? "PENDING" : "COMPLETE"
                    )
                  )
                }
              />
            )}
            {activeTab === "review" && (
              <Review
                onGo={navigate}
                reviews={close.reviews}
                artifacts={artifacts}
                query={query}
                busy={busy}
                closed={closed}
                generated={readiness.generated}
                onDownloadArtifact={downloadArtifact}
                onDecision={(id, decision) =>
                  run((closeId) =>
                    decision === "approved"
                      ? api.approveReview(token, closeId, id)
                      : api.rejectReview(token, closeId, id)
                  )
                }
              />
            )}
            {activeTab === "signoffs" && (
              <Signoffs
                signoffs={close.signoffs}
                query={query}
                busy={busy}
                closed={closed}
                onApprove={(id) => run((closeId) => api.approveSignoff(token, closeId, id))}
              />
            )}
            {activeTab === "pack" && (
              <FinalPack
                close={close}
                exportStatus={exportStatus}
                readiness={readiness}
                blockNotice={blockNotice}
                busy={busy}
                onExport={exportPack}
                onClose={closePeriod}
              />
            )}
            {activeTab === "superdocs" && showDebug && (
              <SuperDocsPanel
                ledger={ledger}
                artifacts={artifacts}
                onDownloadArtifact={downloadArtifact}
              />
            )}
          </section>
        </section>
      </main>
    </div>
  );
}

function Logo() {
  return (
    <div className="brand" aria-label="CloseOrbit">
      <div className="logo-mark">
        <span className="logo-core">CO</span>
        <span className="logo-satellite" />
      </div>
      <span>CloseOrbit</span>
    </div>
  );
}

function TopNav({
  onNavigate,
  activeView,
  user,
  onSignOut,
  query,
  onQuery,
  searchOpen,
  onToggleSearch,
  navOpen,
  onToggleNav
}: {
  onNavigate: (view: View) => void;
  activeView?: View;
  user?: Session["user"] | null;
  onSignOut?: () => void;
  query?: string;
  onQuery?: (value: string) => void;
  searchOpen?: boolean;
  onToggleSearch?: () => void;
  navOpen?: boolean;
  onToggleNav?: () => void;
}) {
  return (
    <header className={navOpen ? "top-nav nav-open" : "top-nav"}>
      <Logo />
      <nav>
        {navLinks.map((link) => (
          <a
            key={link.label}
            href={`#${link.view}`}
            className={activeView === link.view ? "active" : undefined}
            aria-current={activeView === link.view ? "page" : undefined}
            onClick={(event) => {
              event.preventDefault();
              onNavigate(link.view);
            }}
          >
            {link.label}
          </a>
        ))}
      </nav>
      <div className="nav-actions">
        {searchOpen && onQuery && (
          <input
            className="nav-search"
            autoFocus
            value={query ?? ""}
            placeholder="Search this page"
            aria-label="Search this page"
            onChange={(event) => onQuery(event.target.value)}
          />
        )}
        {onToggleSearch && (
          <button className="icon-button" aria-label="Search" aria-expanded={Boolean(searchOpen)} onClick={onToggleSearch}>
            <Search size={18} />
          </button>
        )}
        {user && (
          <div className="user-chip" title={`${user.name} · ${user.role}`}>
            <span className="user-initials" aria-hidden="true">
              {user.name
                .split(" ")
                .map((part) => part.charAt(0))
                .slice(0, 2)
                .join("")
                .toUpperCase()}
            </span>
            <span className="user-meta">
              <strong>{user.name}</strong>
              <small>{user.role}</small>
            </span>
          </div>
        )}
        {onSignOut && (
          <button className="icon-button" aria-label="Sign out" title="Sign out" onClick={onSignOut}>
            <LogOut size={18} />
          </button>
        )}
        <button className="icon-button menu" aria-label="Menu" aria-expanded={Boolean(navOpen)} onClick={onToggleNav}>
          <Menu size={18} />
        </button>
      </div>
    </header>
  );
}

function AuthScreen({
  onSignIn,
  error,
  mode = "demo",
}: {
  onSignIn: (target?: View) => void;
  error: string;
  mode?: "clerk" | "demo";
}) {
  return (
    <main className="auth-screen">
      <TopNav onNavigate={(target) => onSignIn(target)} onToggleNav={() => onSignIn()} />
      <section className="auth-hero">
        <div>
          <p className="eyebrow">
            <span /> Financial close pack
          </p>
          <h1>Close with evidence, review, and sign-off in one place.</h1>
          <p>
            A focused workspace for finance controllers: every close backed by evidence, every change approved by a person.
          </p>
          <button className="primary-button" onClick={() => onSignIn()}>
            <LockKeyhole size={18} />
            {mode === "clerk" ? "Sign in" : "Continue demo"}
          </button>
          {error && <div className="failure-band">{error}</div>}
        </div>
        <div className="auth-orbit">
          <div className="portrait one">
            <Gauge size={54} />
          </div>
          <div className="portrait two">
            <FileCheck2 size={54} />
          </div>
          <div className="portrait three">
            <ShieldCheck size={54} />
          </div>
        </div>
      </section>
    </main>
  );
}

function Overview({
  readiness,
  job,
  busy,
  closed,
  events,
  steps,
  guidance,
  onGenerate,
  onGo
}: {
  readiness: ReadinessView;
  job: GenerationJob | null;
  busy: boolean;
  closed: boolean;
  events: AuditEvent[];
  steps: ReturnType<typeof computeSteps>;
  guidance: ReturnType<typeof nextAction>;
  onGenerate: () => void;
  onGo: (tab: Tab) => void;
}) {
  // Denominators come from the close template instead of being hardcoded to 8/7/3/3.
  const rows: Array<[string, string, Tab]> = [
    ["Documents", `${readiness.docsReady} / ${readiness.docsRequired}`, "documents"],
    ["Checklist", `${readiness.checklistDone} / ${readiness.checklistRequired}`, "checklist"],
    ["Review", `${readiness.reviewsResolved} / ${readiness.reviewsTotal}`, "review"],
    ["Sign-offs", `${readiness.signoffsDone} / ${readiness.signoffsRequired}`, "signoffs"]
  ];

  const stages = job?.stages ?? [];
  const completedStages = job ? (job.status === "SUCCEEDED" ? stages.length : job.stage_index) : -1;
  const blockers = routeBlockers(readiness.blockers);
  // `canGenerate` is the server's own precondition. It was previously computed, threaded
  // through the view model, and then read by nobody, so the button was always enabled and
  // the user only learned why it could not run after it failed.
  const blockedReason = generationBlockReason(readiness);
  const generateLabel = readiness.generated ? "Rebuild close pack" : "Build close pack";

  return (
    <div className="panel-flow">
      {!closed && guidance && (
        <div className="next-step">
          <div>
            <p className="eyebrow">
              <span /> Next step
            </p>
            <h3>{guidance.headline}</h3>
            <p>{guidance.detail}</p>
          </div>
          <button className="primary-button" onClick={() => onGo(guidance.tab)}>
            {guidance.action}
            <ArrowRight size={18} />
          </button>
        </div>
      )}

      <div className="section-heading">
        <div>
          <p className="eyebrow">
            <span /> Progress
          </p>
          <h2>Where this close stands</h2>
          <p className="page-lede">Work through these in order. Each one unlocks the next.</p>
        </div>
      </div>

      <ol className="step-track">
        {steps.map((step, index) => (
          <li className={`step ${step.state}`} key={step.tab + step.label}>
            <button onClick={() => onGo(step.tab)}>
              <span className="step-index">{step.state === "done" ? <Check size={16} /> : index + 1}</span>
              <span className="step-body">
                <strong>{step.label}</strong>
                <small>{step.state === "current" ? step.hint : step.progress}</small>
              </span>
            </button>
          </li>
        ))}
      </ol>

      <div className="metric-grid">
        {rows.map(([label, value, tab]) => (
          <button className="metric" key={label} onClick={() => onGo(tab)}>
            <span>{label}</span>
            <strong>{value}</strong>
            <ArrowRight size={18} />
          </button>
        ))}
      </div>

      <div className="blocker-band">
        <div>
          <p className="eyebrow">
            <span /> {closed ? "Status" : "Before you can close"}
          </p>
          <h3>{closed ? "Period closed" : readiness.canClose ? "Ready to close" : "A few things are outstanding"}</h3>
          {closed ? (
            <p>This period is closed. It is locked and can no longer be edited.</p>
          ) : readiness.canClose ? (
            <p>All required evidence and approvals are complete.</p>
          ) : (
            /* Every blocker, each linked to the tab that fixes it. Previously only the
               first was shown, as unlinked text, and the rest were discoverable only by
               attempting the close and being rejected. */
            <ul className="blocker-list">
              {blockers.map((blocker) => (
                <li key={blocker.text}>
                  <span>{blocker.text}</span>
                  <button className="link-button" onClick={() => onGo(blocker.tab)}>
                    {blocker.action}
                    <ArrowRight size={14} />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <div className="section-heading">
        <div>
          <p className="eyebrow">
            <span /> Close pack
          </p>
          <h3>{readiness.generated ? "Your draft pack is ready to review" : "Build the draft close pack"}</h3>
          <p className="page-lede">
            {readiness.generated
              ? "We drafted the pack from your evidence. Review the proposed changes before signing off."
              : "Once your documents and checklist are complete, we draft the pack for you."}
          </p>
        </div>
        <div className="action-with-reason">
          <button
            className="primary-button"
            onClick={onGenerate}
            disabled={busy || closed || Boolean(blockedReason)}
            title={blockedReason ?? undefined}
          >
            <Sparkles size={18} />
            {busy ? "Working…" : generateLabel}
          </button>
          {!closed && blockedReason && <small className="reason">{blockedReason}</small>}
        </div>
      </div>

      {job && job.status === "RUNNING" && (
        <p className="page-lede">This usually takes a minute or two. You can keep working while it runs.</p>
      )}
      {job && (
        <div className="stage-list">
          {stages.map((stage, index) => (
            <div className="stage-row" key={stage}>
              {completedStages > index ? (
                <CheckCircle2 size={18} />
              ) : completedStages === index ? (
                <CircleDashed size={18} />
              ) : (
                <span className="empty-dot" />
              )}
              <span>{stage}</span>
            </div>
          ))}
        </div>
      )}
      {job?.status === "FAILED" && (
        <div className="failure-band">
          We could not build the pack. Nothing was changed — please try again.
        </div>
      )}
      <AuditTimeline events={events} />
    </div>
  );
}

function Documents({
  documents,
  readiness,
  requiredTypes,
  missingTypes,
  query,
  busy,
  closed,
  onConfirm,
  onUpload,
  onDelete
}: {
  documents: DocumentItem[];
  readiness: ReadinessView;
  requiredTypes: string[];
  missingTypes: string[];
  query: string;
  busy: boolean;
  closed: boolean;
  onConfirm: (id: string, documentType: string | null) => void;
  onUpload: (file: File) => void;
  onDelete: (id: string) => void;
}) {
  const fileInput = useRef<HTMLInputElement>(null);
  const visible = documents.filter((doc) => matches(query, doc.filename, doc.document_type, doc.suggested_type));
  // A document whose filename matches no known pattern has no suggested type, and the
  // old single "confirm" button sent null, which the API always rejects. Picking the type
  // by hand is the only way out of that, so the picker is part of the row.
  const [chosen, setChosen] = useState<Record<string, string>>({});
  // Removing evidence is irreversible, so the row asks before it does it.
  const [confirming, setConfirming] = useState<string | null>(null);

  return (
    <div className="panel-flow">
      <div className="section-heading">
        <div>
          <p className="eyebrow">
            <span /> Step 1 · Documents
          </p>
          <h2>
            {readiness.docsReady} of {readiness.docsRequired} required documents ready
          </h2>
          <p className="page-lede">
            Upload each schedule your close needs, then tell us which one it is so it can be matched.
          </p>
        </div>
        <button className="primary-button" onClick={() => fileInput.current?.click()} disabled={busy || closed}>
          <Upload size={18} />
          Upload a document
        </button>
        <input
          ref={fileInput}
          type="file"
          hidden
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) onUpload(file);
            event.target.value = "";
          }}
        />
      </div>

      {missingTypes.length > 0 && (
        /* `missing_types` was fetched on every load and never rendered, so an empty
           Documents tab never said what it was waiting for. */
        <div className="hint-band">
          <strong>Still needed</strong>
          <div className="chip-row">
            {missingTypes.map((type) => (
              <span className="chip" key={type}>
                {humanizeType(type)}
              </span>
            ))}
          </div>
        </div>
      )}

      <div className="table-list">
        {visible.map((doc) => {
          const options = requiredTypes.length ? requiredTypes : [];
          const selection = chosen[doc.id] ?? doc.suggested_type ?? "";
          return (
            <div className="data-row" key={doc.id}>
              <FileText size={20} />
              <div>
                <strong>{doc.filename}</strong>
                <span>
                  {doc.document_type
                    ? humanizeType(doc.document_type)
                    : doc.suggested_type
                      ? `Looks like ${humanizeType(doc.suggested_type)} — confirm below`
                      : "Tell us what this is"}
                  {" • "}
                  {formatBytes(doc.size)}
                </span>
              </div>
              <div className="row-actions">
                {doc.status === "READY" ? (
                  <span className="status ready">Ready</span>
                ) : (
                  <>
                    <select
                      className="type-select"
                      aria-label={`Document type for ${doc.filename}`}
                      value={selection}
                      disabled={busy || closed}
                      onChange={(event) => setChosen((current) => ({ ...current, [doc.id]: event.target.value }))}
                    >
                      <option value="">Choose a type…</option>
                      {options.map((type) => (
                        <option value={type} key={type}>
                          {humanizeType(type)}
                        </option>
                      ))}
                    </select>
                    <button
                      className="secondary-button compact"
                      disabled={busy || closed || !selection}
                      title={selection ? undefined : "Choose a document type first"}
                      onClick={() => onConfirm(doc.id, selection)}
                    >
                      Save
                    </button>
                  </>
                )}
                {confirming === doc.id ? (
                  <>
                    <button
                      className="danger-button compact"
                      disabled={busy || closed}
                      onClick={() => {
                        onDelete(doc.id);
                        setConfirming(null);
                      }}
                    >
                      Remove it
                    </button>
                    <button className="link-button" onClick={() => setConfirming(null)}>
                      Keep
                    </button>
                  </>
                ) : (
                  <button
                    className="icon-button compact"
                    aria-label={`Remove ${doc.filename}`}
                    title={closed ? "This period is closed" : `Remove ${doc.filename}`}
                    disabled={busy || closed}
                    onClick={() => setConfirming(doc.id)}
                  >
                    <Trash2 size={16} />
                  </button>
                )}
              </div>
            </div>
          );
        })}
        {visible.length === 0 && (
          <div className="empty-state">
            <Upload size={22} />
            <div>
              <strong>{documents.length ? "Nothing matches your search" : "No documents yet"}</strong>
              <span>
                {documents.length
                  ? "Try a different word, or clear the search."
                  : "Upload your first schedule to get this close moving."}
              </span>
            </div>
            {!documents.length && (
              <button className="primary-button" onClick={() => fileInput.current?.click()} disabled={busy || closed}>
                <Upload size={18} /> Upload a document
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function Checklist({
  checklist,
  query,
  busy,
  closed,
  onToggle
}: {
  checklist: ChecklistItem[];
  query: string;
  busy: boolean;
  closed: boolean;
  onToggle: (item: ChecklistItem) => void;
}) {
  const visible = checklist.filter((item) => matches(query, item.title, item.owner, item.evidence));

  return (
    <div className="panel-flow">
      <div className="section-heading">
        <div>
          <p className="eyebrow">
            <span /> Close checklist
          </p>
          <h2>
            {checklist.filter((item) => item.status === "COMPLETE").length} / {checklist.length} complete
          </h2>
        </div>
      </div>
      <div className="table-list">
        {visible.map((item) => (
          <button
            className="data-row button-row"
            key={item.id}
            disabled={busy || closed}
            onClick={() => onToggle(item)}
          >
            {item.status === "COMPLETE" ? <CheckCircle2 size={20} /> : <CircleDashed size={20} />}
            <div>
              <strong>{item.title}</strong>
              <span>
                {item.completed_by ?? item.owner} • Evidence: {item.evidence}
              </span>
            </div>
            <span className={item.status === "COMPLETE" ? "status ready" : "status pending"}>
              {statusLabel(item.status)}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

function ArtifactList({
  artifacts,
  onDownload
}: {
  artifacts: GeneratedArtifact[];
  onDownload: (artifact: GeneratedArtifact) => void;
}) {
  if (artifacts.length === 0) return null;

  return (
    <div className="pack-list">
      {artifacts.map((artifact) => (
        <div className="data-row" key={artifact.id}>
          <FileText size={20} />
          <div>
            <strong>{artifact.name}</strong>
            <span>
              {artifact.description} • {formatBytes(artifact.size)} • {formatTimestamp(artifact.generated_at)}
            </span>
          </div>
          <button className="secondary-button" onClick={() => onDownload(artifact)}>
            <Download size={16} /> Open
          </button>
        </div>
      ))}
    </div>
  );
}

function Review({
  reviews,
  artifacts,
  query,
  busy,
  closed,
  generated,
  onDecision,
  onDownloadArtifact,
  onGo
}: {
  reviews: ReviewItem[];
  artifacts: GeneratedArtifact[];
  query: string;
  busy: boolean;
  closed: boolean;
  generated: boolean;
  onDecision: (id: string, status: "approved" | "rejected") => void;
  onDownloadArtifact: (artifact: GeneratedArtifact) => void;
  onGo: (tab: Tab) => void;
}) {
  const visible = reviews.filter((item) => matches(query, item.section, item.source_reference));
  const pending = reviews.filter((item) => item.status === "PENDING").length;

  return (
    <div className="panel-flow">
      <div className="section-heading">
        <div>
          <p className="eyebrow">
            <span /> Step 4 · Review
          </p>
          <h2>
            {!generated
              ? "Nothing to review yet"
              : pending === 0
                ? "Every change has been decided"
                : `${pending} change${pending === 1 ? "" : "s"} need your decision`}
          </h2>
          <p className="page-lede">
            {generated
              ? "Approve a change to include it in the pack, or reject it to leave it out. Rejected changes never reach the final document."
              : "Once you build the close pack, the proposed changes appear here for approval."}
          </p>
        </div>
      </div>
      {!generated && (
        <div className="empty-state">
          <Sparkles size={22} />
          <div>
            <strong>Build the pack first</strong>
            <span>We draft the changes from the evidence you have collected.</span>
          </div>
          <button className="primary-button" onClick={() => onGo("overview")}>
            Go to Overview <ArrowRight size={16} />
          </button>
        </div>
      )}
      {artifacts.length > 0 && (
        <>
          <p className="eyebrow">
            <span /> Supporting documents
          </p>
          <ArtifactList artifacts={artifacts} onDownload={onDownloadArtifact} />
        </>
      )}
      <div className="review-stack">
        {visible.map((item) => (
          <article className="review-item" key={item.id}>
            <div className="review-header">
              <div>
                <strong>{item.section}</strong>
                <span>
                  {item.source_reference ? `Based on ${item.source_reference}` : "No source cited"}
                  {item.reviewed_by ? ` • ${statusLabel(item.status)} by ${item.reviewed_by}` : ""}
                </span>
              </div>
              <span className={item.status === "PENDING" ? "status pending" : "status ready"}>
                {statusLabel(item.status)}
              </span>
            </div>
            <div className="diff-grid">
              <div>
                <small>Current</small>
                <p>{item.before_value}</p>
              </div>
              <div>
                <small>Proposed</small>
                <p>{item.after_value}</p>
              </div>
            </div>
            {item.superdocs_approval && (
              /* The approval receipt carries change ids, a request id and the adapter
                 mode. Those belong in the exported evidence bundle, not on screen. */
              <p className="superdocs-receipt">
                <Check size={14} /> Applied to the close pack
                {item.reviewed_by ? ` · approved by ${item.reviewed_by}` : ""}
                {item.reviewed_at ? ` · ${formatTimestamp(item.reviewed_at)}` : ""}
              </p>
            )}
            {item.error && (
              <div className="failure-band">
                This change could not be applied, so it is still pending. Nothing was lost — try approving it again.
              </div>
            )}
            {item.status === "PENDING" && !closed && (
              <div className="decision-row">
                <button className="secondary-button" disabled={busy} onClick={() => onDecision(item.id, "rejected")}>
                  <X size={16} /> Reject
                </button>
                <button className="primary-button" disabled={busy} onClick={() => onDecision(item.id, "approved")}>
                  <Check size={16} /> Approve
                </button>
              </div>
            )}
          </article>
        ))}
      </div>
    </div>
  );
}

function Signoffs({
  signoffs,
  query,
  busy,
  closed,
  onApprove
}: {
  signoffs: SignoffItem[];
  query: string;
  busy: boolean;
  closed: boolean;
  onApprove: (id: string) => void;
}) {
  const visible = signoffs.filter((item) => matches(query, item.role, item.person));

  return (
    <div className="panel-flow">
      <div className="section-heading">
        <div>
          <p className="eyebrow">
            <span /> Attributed approval
          </p>
          <h2>Required sign-offs</h2>
        </div>
      </div>
      <div className="signoff-grid">
        {visible.map((item) => (
          <div className="signoff" key={item.id}>
            <span>{item.role}</span>
            <strong>{item.person ?? "Unassigned"}</strong>
            <p>{item.status === "APPROVED" ? formatTimestamp(item.signed_at) : "Pending approval"}</p>
            {item.status === "PENDING" ? (
              <button className="primary-button" disabled={busy || closed} onClick={() => onApprove(item.id)}>
                <ShieldCheck size={16} /> Approve
              </button>
            ) : (
              <span className="status ready">Approved</span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function FinalPack({
  close,
  exportStatus,
  readiness,
  blockNotice,
  busy,
  onExport,
  onClose
}: {
  close: CloseDetail;
  exportStatus: ExportStatus | null;
  readiness: ReadinessView;
  blockNotice: string;
  busy: boolean;
  onExport: () => void;
  onClose: () => void;
}) {
  const closed = Boolean(close.closed_at);
  const exported = Boolean(exportStatus?.exported);
  const files = exportStatus?.export?.files ?? exportStatus?.planned_files ?? [];
  const [confirmClose, setConfirmClose] = useState(false);

  return (
    <div className="panel-flow">
      <div className="section-heading">
        <div>
          <p className="eyebrow">
            <span /> Final pack
          </p>
          <h2>
            {closed
              ? `${formatPeriod(close.period)} Close Closed`
              : readiness.canClose
                ? "Ready to close"
                : "Complete the gate to close"}
          </h2>
        </div>
        <button className="primary-button" onClick={onExport} disabled={busy || (closed && !exported)}>
          <Download size={18} />
          {exported ? "Download pack" : "Export pack"}
        </button>
      </div>
      <div className="pack-list">
        {files.map((file) => (
          <div className="data-row" key={file}>
            <FileCheck2 size={20} />
            <div>
              <strong>{file}</strong>
              <span>{exported ? "Exported and ready" : "Waiting for export"}</span>
            </div>
            <span className={exported ? "status ready" : "status pending"}>{exported ? "Ready" : "Pending"}</span>
          </div>
        ))}
      </div>
      {exportStatus?.superdocs_export && (
        <div className="timeline">
          <p className="eyebrow">
            <span /> Finished document
          </p>
          <div className="timeline-row">
            <PackageCheck size={16} />
            {exportStatus.superdocs_export.filename}
            {exportStatus.superdocs_export.size ? ` • ${formatBytes(exportStatus.superdocs_export.size)}` : ""}
          </div>
          <div className="timeline-row">
            Built from {exportStatus.superdocs_export.approved_change_ids.length} approved change
            {exportStatus.superdocs_export.approved_change_ids.length === 1 ? "" : "s"}. Included in the pack below.
          </div>
        </div>
      )}
      {exportStatus?.export && (
        <div className="timeline">
          <p className="eyebrow">
            <span /> Close pack
          </p>
          <div className="timeline-row">
            <History size={16} />
            {exportStatus.export.filename} • {formatBytes(exportStatus.export.size)} •{" "}
            {formatTimestamp(exportStatus.export.generated_at)}
          </div>
          <div className="timeline-row">
            Your record for this period: the finished document, every source document, the supporting memo,
            the checklist, the review decisions, the sign-off sheet and the full activity trail.
          </div>
        </div>
      )}
      {blockNotice && <div className="failure-band">{blockNotice}</div>}
      {!closed && (
        <p className="page-lede">
          Closing locks this period permanently. Nothing in it can be edited afterwards.
        </p>
      )}
      <button
        className="close-period-button"
        onClick={() => {
          if (closed) return;
          if (confirmClose) {
            onClose();
            setConfirmClose(false);
            return;
          }
          setConfirmClose(true);
        }}
        disabled={busy || closed || !readiness.canClose}
        title={readiness.canClose ? undefined : "Finish the outstanding items before closing"}
      >
        {closed ? "Period closed" : confirmClose ? "Yes, close this period" : "Close this period"}
      </button>
      {confirmClose && !closed && (
        <button className="link-button" onClick={() => setConfirmClose(false)}>
          Cancel
        </button>
      )}
    </div>
  );
}

function SuperDocsPanel({
  ledger,
  artifacts,
  onDownloadArtifact
}: {
  ledger: SuperDocsLedger | null;
  artifacts: GeneratedArtifact[];
  onDownloadArtifact: (artifact: GeneratedArtifact) => void;
}) {
  if (!ledger) {
    return (
      <div className="panel-flow">
        <div className="section-heading">
          <div>
            <p className="eyebrow">
              <span /> SuperDocs
            </p>
            <h2>Loading the operation ledger…</h2>
          </div>
        </div>
      </div>
    );
  }

  const { coverage, operations } = ledger;
  const superdocsExport = ledger.export;

  return (
    <div className="panel-flow">
      <div className="section-heading">
        <div>
          <p className="eyebrow">
            <span /> SuperDocs contract
          </p>
          <h2>{coverage.complete ? "All four operations exercised" : "Contract partially exercised"}</h2>
          <p className="hero-copy">
            Running in <strong>{ledger.mode}</strong> mode. Every adapter call this close has made is listed
            below, successes and failures alike. Mock mode issues the same calls through the same interface as
            live mode; only the transport differs.
          </p>
        </div>
      </div>

      <div className="pack-list">
        {coverage.operations.map((operation) => (
          <div className="data-row" key={operation.operation}>
            {operation.exercised ? <CheckCircle2 size={20} /> : <CircleDashed size={20} />}
            <div>
              <strong>{CONTRACT_LABELS[operation.operation] ?? operation.operation}</strong>
              <span>
                <code>{operation.operation}</code> • {operation.count} call
                {operation.count === 1 ? "" : "s"}
                {operation.failures > 0 ? ` • ${operation.failures} failed` : ""}
              </span>
            </div>
            <span className={operation.exercised ? "status ready" : "status pending"}>
              {operation.exercised ? "Exercised" : "Not yet"}
            </span>
          </div>
        ))}
      </div>

      {artifacts.length > 0 && (
        <>
          <p className="eyebrow">
            <span /> Supporting documents
          </p>
          <ArtifactList artifacts={artifacts} onDownload={onDownloadArtifact} />
        </>
      )}

      {superdocsExport && (
        <div className="timeline">
          <p className="eyebrow">
            <span /> SuperDocs exported document
          </p>
          <div className="timeline-row">
            <PackageCheck size={16} />
            {superdocsExport.filename}
            {superdocsExport.size ? ` • ${formatBytes(superdocsExport.size)}` : ""} •{" "}
            {superdocsExport.mode} mode • {superdocsExport.export_id ?? "no export id"}
          </div>
          {superdocsExport.note && <div className="timeline-row">{superdocsExport.note}</div>}
        </div>
      )}

      <p className="eyebrow">
        <span /> Operation ledger
      </p>
      <div className="pack-list superdocs-ledger">
        {operations.length === 0 && (
          <div className="data-row">
            <CircleDashed size={20} />
            <div>
              <strong>No SuperDocs calls yet</strong>
              <span>Generate the close pack to start the contract.</span>
            </div>
          </div>
        )}
        {operations.map((operation) => (
          <div className="data-row" key={operation.id}>
            {operation.status === "SUCCEEDED" ? <Check size={20} /> : <X size={20} />}
            <div>
              <strong>
                <code>{operation.operation}</code>
                {operation.detail ? ` — ${operation.detail}` : ""}
              </strong>
              <span>
                {formatTimestamp(operation.started_at)} • {operation.mode} • {operation.duration_ms}ms
                {operation.document_id ? ` • ${operation.document_id}` : ""}
                {operation.request_id ? ` • ${operation.request_id}` : ""}
                {operation.error ? ` • ${operation.error}` : ""}
              </span>
            </div>
            <span className={operation.status === "SUCCEEDED" ? "status ready" : "status pending"}>
              {statusLabel(operation.status)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function AuditTimeline({ events }: { events: AuditEvent[] }) {
  // Real events from the backend trail. This used to be five hardcoded strings that
  // were displayed no matter what the user had actually done.
  const recent = events.slice(-12);

  return (
    <div className="timeline">
      <p className="eyebrow">
        <span /> Recent activity
      </p>
      {recent.map((event) => {
        // Server-authored details carry job ids, byte counts and hash fragments; they
        // belong in the exported evidence bundle, not in the feed a controller reads.
        const detail = cleanDetail(event.detail);
        return (
          <div className="timeline-row" key={event.id}>
            <History size={16} />
            <div>
              <strong>
                {formatEvent(event.event)}
                {detail ? ` — ${detail}` : ""}
              </strong>
              <span>
                {event.actor} · {formatTimestamp(event.created_at)}
              </span>
            </div>
          </div>
        );
      })}
      {recent.length === 0 && (
        <div className="timeline-row">
          <History size={16} />
          <div>
            <strong>Nothing has happened yet</strong>
            <span>Actions you take in this close are recorded here.</span>
          </div>
        </div>
      )}
    </div>
  );
}
