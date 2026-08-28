import * as React from "react";
import { createRoot } from "react-dom/client";

declare function acquireVsCodeApi(): {
  postMessage: (msg: Record<string, unknown>) => void;
  getState: () => Record<string, unknown> | undefined;
  setState: (s: Record<string, unknown>) => void;
};

interface Change {
  change_id: string;
  operation: string;
  chunk_id: string;
  old_html: string;
  new_html: string;
  ai_explanation?: string;
  decision?: boolean | null;
}

interface Warning {
  code: string;
  message: string;
}

interface Quota {
  tier: string;
  monthly_limit: number;
  used: number;
  remaining: number;
  resets_at?: string;
}

interface AuthStatus {
  hasKey: boolean;
  error?: string;
  quota?: Quota;
}

interface WriteBackOutcome {
  applied: number;
  total: number;
  unresolved: number;
}

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  timestamp: number;
  changes?: Change[];
  response?: string;
  approvedIds?: string[];
  applied?: WriteBackOutcome | null;
  pending?: boolean;
  error?: string;
}

type Phase =
  | "ready"
  | "uploading"
  | "uploaded"
  | "editing"
  | "awaiting"
  | "completed"
  | "exporting"
  | "error";

const vscode = acquireVsCodeApi();
const stored = (vscode.getState() ?? {}) as {
  messages?: ChatMessage[];
  projectDir?: string | null;
  sessionId?: string;
};

let nextId = 0;
const uid = () => `m${Date.now().toString(36)}${(nextId++).toString(36)}`;

function AuthPanel({
  status,
  busy,
  onKey,
  onClear,
}: {
  status: AuthStatus | undefined;
  busy: boolean;
  onKey: (key: string) => void;
  onClear: () => void;
}) {
  const [key, setKey] = React.useState("");
  if (status?.hasKey) {
    return (
      <div className="auth authed">
        <div className="auth-head">
          <span className="dot" />
          <span>SuperDocs</span>
        </div>
        <div className="quota">
          {status.quota ? (
            <span className="badge">
              {status.quota.used}/{status.quota.monthly_limit} ops
            </span>
          ) : (
            <span className="badge">checking quota…</span>
          )}
        </div>
        <button className="ghost" onClick={onClear}>Sign out</button>
      </div>
    );
  }
  return (
    <div className="auth">
      <h2>SuperDocs account</h2>
      <p className="auth-help">
        LaTeX Bridge edits your paper through your SuperDocs agent. Sign up for a free key
        (500 ops/month) or paste an existing one.
      </p>
      <button className="signup" onClick={() => vscode.postMessage({ type: "openExternal", url: "https://use.superdocs.app" })}>
        Create free account
      </button>
      <div className="or">or</div>
      <label className="field">
        <span>API key (sk_…)</span>
        <input
          type="password"
          placeholder="sk_…"
          value={key}
          onChange={(e) => setKey(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && key.trim() && onKey(key.trim())}
        />
      </label>
      <button disabled={!key.trim() || busy} onClick={() => onKey(key.trim())}>
        {busy ? "Connecting…" : "Sign in"}
      </button>
      {status?.error && <div className="error-text">{status.error}</div>}
    </div>
  );
}

function App() {
  const [messages, setMessages] = React.useState<ChatMessage[]>(stored.messages ?? []);
  const [projectDir, setProjectDir] = React.useState<string | null>(stored.projectDir ?? null);
  const [sessionId, setSessionId] = React.useState<string>(stored.sessionId ?? "");
  const [chunksCount, setChunksCount] = React.useState(0);
  const [auth, setAuth] = React.useState<AuthStatus | undefined>(undefined);
  const [authBusy, setAuthBusy] = React.useState(false);
  const [phase, setPhase] = React.useState<Phase>("ready");
  const [input, setInput] = React.useState("");
  const [ingestWarnings, setIngestWarnings] = React.useState<Warning[]>([]);

  const listRef = React.useRef<HTMLDivElement>(null);
  const pendingId = React.useRef<string | null>(null);
  const queuedPrompt = React.useRef<string | null>(null);
  const projectDirRef = React.useRef<string | null>(projectDir);
  const sessionIdRef = React.useRef<string>(sessionId);
  const messagesRef = React.useRef<ChatMessage[]>(messages);

  const append = (m: ChatMessage) => {
    messagesRef.current = [...messagesRef.current, m];
    setMessages(messagesRef.current);
  };
  const upsert = (m: ChatMessage) => {
    const next = [...messagesRef.current];
    const i = next.findIndex((p) => p.id === m.id);
    if (i === -1) next.push(m);
    else next[i] = m;
    messagesRef.current = next;
    setMessages(next);
  };
  const updateMsg = (id: string, fn: (m: ChatMessage) => ChatMessage) => {
    const next = messagesRef.current.map((m) => (m.id === id ? fn(m) : m));
    messagesRef.current = next;
    setMessages(next);
  };

  React.useEffect(() => {
    vscode.setState({ messages, projectDir, sessionId });
  }, [messages, projectDir, sessionId]);

  React.useEffect(() => {
    listRef.current?.scrollTo?.({ top: listRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, phase]);

  React.useEffect(() => {
    const handler = (event: MessageEvent) => {
      const msg = event.data as Record<string, unknown>;
      switch (msg.type) {
        case "ready":
          vscode.postMessage({ type: "getAuthStatus" });
          vscode.postMessage({ type: "getWorkspaceProject" });
          break;
        case "authStatus":
          setAuth({ hasKey: !!msg.hasKey, error: msg.error as string | undefined, quota: msg.quota as Quota | undefined });
          setAuthBusy(false);
          break;
        case "workspaceProject":
          if (msg.path && !projectDirRef.current) {
            projectDirRef.current = msg.path as string;
            setProjectDir(msg.path as string);
          }
          break;
        case "projectOpened": {
          const path = (msg.path as string) ?? null;
          projectDirRef.current = path;
          setProjectDir(path);
          if (queuedPrompt.current && !sessionIdRef.current) {
            vscode.postMessage({ type: "createSession", projectDir: msg.path });
          }
          break;
        }
        case "sessionCreated": {
          sessionIdRef.current = msg.sessionId as string;
          setSessionId(msg.sessionId as string);
          setChunksCount((msg.chunksCount as number) ?? 0);
          setIngestWarnings((msg.warnings as Warning[]) ?? []);
          const w = (msg.warnings as Warning[]) ?? [];
          setPhase("uploaded");
          append({
            id: uid(),
            role: "assistant",
            text:
              `Project uploaded — ${msg.chunksCount ?? "?"} editable sections ready.` +
              (w.length > 0 ? ` (${w.length} ingest warning${w.length > 1 ? "s" : ""})` : ""),
            timestamp: Date.now(),
          });
          if (queuedPrompt.current) {
            const prompt = queuedPrompt.current;
            queuedPrompt.current = null;
            vscode.postMessage({ type: "requestEdit", message: prompt });
          }
          break;
        }
        case "sessionEvent":
        case "uploaded":
        case "awaiting_approval":
        case "approved":
        case "denied":
        case "failed":
        case "warnings":
        case "chat_started":
        case "waiting": {
          const evt = msg as unknown as {
            type: string;
            stage?: string;
            changes?: Change[];
            approvedIds?: string[];
            warnings?: Warning[];
          };
          if (evt.type === "uploaded") {
            setPhase(evt.stage === "parsed" ? "uploaded" : "uploading");
          } else if (evt.type === "awaiting_approval") {
            const id = pendingId.current ?? uid();
            pendingId.current = id;
            const incoming = (evt.changes ?? []).map((c) => ({ ...c, decision: null }));
            setPhase("awaiting");
            upsert({
              id,
              role: "assistant",
              text: "The AI proposed changes — review each one.",
              timestamp: Date.now(),
              changes: incoming,
              pending: true,
            });
          } else if (evt.type === "approved" || evt.type === "denied") {
            const ids = evt.approvedIds ?? [];
            if (pendingId.current) {
              updateMsg(pendingId.current, (m) => ({
                ...m,
                approvedIds: ids,
                pending: true,
              }));
            }
          } else if (evt.type === "warnings") {
            setIngestWarnings((prev) => [...prev, ...(evt.warnings ?? [])]);
          } else if (evt.type === "chat_started" || evt.type === "waiting") {
            const id = pendingId.current ?? uid();
            pendingId.current = id;
            setPhase("editing");
            upsert({
              id,
              role: "assistant",
              text: "AI is drafting edits…",
              timestamp: Date.now(),
              pending: true,
            });
          }
          break;
        }
        case "editStarted":
          setPhase("editing");
          break;
        case "editCompleted": {
          const id = pendingId.current ?? uid();
          pendingId.current = null;
          setPhase("completed");
          upsert({
            id,
            role: "assistant",
            text: "",
            timestamp: Date.now(),
            response: (msg.response as string) ?? "",
            pending: false,
          });
          break;
        }
        case "decisionsSubmitted":
          if (pendingId.current) {
            updateMsg(pendingId.current, (m) => ({ ...m, pending: false, changes: m.changes?.map((c) => ({ ...c, decision: c.decision ?? false })) }));
          }
          break;
        case "writeBackResult": {
          const out = { applied: msg.applied as number, total: msg.total as number, unresolved: msg.unresolved as number };
          if (pendingId.current) updateMsg(pendingId.current, (m) => ({ ...m, applied: out }));
          break;
        }
        case "exportCompleted": {
          setPhase("completed");
          const w = (msg.warnings as Warning[]) ?? [];
          append({
            id: uid(),
            role: "assistant",
            text:
              (msg.saved ? `Exported .docx to ${msg.path}` : "Export cancelled") +
              (w.length > 0 ? ` — ${w.length} export warning${w.length > 1 ? "s" : ""}` : ""),
            timestamp: Date.now(),
          });
          break;
        }
        case "error": {
          const id = pendingId.current ?? uid();
          pendingId.current = null;
          setPhase("error");
          upsert({
            id,
            role: "assistant",
            text: "",
            timestamp: Date.now(),
            error: (msg.message as string) ?? "Unknown error",
            pending: false,
          });
          break;
        }
        default:
          break;
      }
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, []);

  const decide = (changeId: string, approved: boolean) => {
    if (!pendingId.current) return;
    updateMsg(pendingId.current, (m) => ({
      ...m,
      changes: m.changes?.map((c) => (c.change_id === changeId ? { ...c, decision: approved } : c)),
    }));
  };

  const submitDecisions = () => {
    if (!pendingId.current) return;
    const m = messagesRef.current.find((mm) => mm.id === pendingId.current);
    if (!m?.changes) return;
    const decisions = m.changes
      .filter((c) => c.decision !== null)
      .map((c) => ({ changeId: c.change_id, approved: !!c.decision }));
    if (decisions.length === 0) return;
    vscode.postMessage({ type: "submitDecisions", decisions });
    updateMsg(pendingId.current, (mm) => ({
      ...mm,
      changes: mm.changes?.map((c) => ({ ...c, decision: c.decision ?? false })),
      pending: false,
    }));
  };

  const writeBack = (m: ChatMessage) => {
    const approved = (m.changes ?? []).filter((c) => c.decision === true || (m.approvedIds ?? []).includes(c.change_id));
    if (approved.length === 0) return;
    vscode.postMessage({
      type: "writeBack",
      changes: approved.map((c) => ({
        changeId: c.change_id,
        chunkId: c.chunk_id,
        oldHtml: c.old_html,
        newHtml: c.new_html,
      })),
    });
    updateMsg(m.id, (mm) => ({ ...mm, applied: null }));
  };

  const send = () => {
    const text = input.trim();
    if (!text || !auth?.hasKey) return;
    if (phase === "uploading" || phase === "editing" || phase === "awaiting") return;
    setInput("");
    append({ id: uid(), role: "user", text, timestamp: Date.now() });
    if (!sessionIdRef.current) {
      queuedPrompt.current = text;
      if (!projectDirRef.current) {
        vscode.postMessage({ type: "openProject" });
      } else {
        vscode.postMessage({ type: "createSession", projectDir: projectDirRef.current });
      }
    } else {
      vscode.postMessage({ type: "requestEdit", message: text });
    }
  };

  const busy = phase === "uploading" || phase === "editing" || phase === "awaiting" || authBusy;

  return (
    <div className="app">
      <header>
        <div className="header-row">
          <h1>LaTeX Bridge</h1>
          <span className={`badge phase-${phase}`}>{phase}</span>
        </div>
        <div className="header-row meta">
          {projectDir && (
            <span className="badge project" title={projectDir}>
              {projectDir.split("/").pop()}
            </span>
          )}
          {sessionId && <span className="badge">{chunksCount || "?"} sections</span>}
        </div>
      </header>

      <AuthPanel
        status={auth}
        busy={authBusy}
        onKey={(key) => {
          setAuthBusy(true);
          vscode.postMessage({ type: "setApiKey", key });
        }}
        onClear={() => {
          setAuthBusy(true);
          vscode.postMessage({ type: "clearApiKey" });
        }}
      />

      {!auth?.hasKey ? (
        <div className="locked">
          <p>Sign in above to chat-edit your paper and write approved edits back to your .tex sources.</p>
        </div>
      ) : (
        <>
          {!projectDir && (
            <div className="locked">
              <p>No LaTeX project detected in this workspace — pick a folder.</p>
              <button onClick={() => vscode.postMessage({ type: "openProject" })}>Choose project…</button>
            </div>
          )}

          {ingestWarnings.length > 0 && (
            <div className="warnings">
              <h2>Ingest warnings</h2>
              {ingestWarnings.map((w, i) => (
                <div key={i} className="warning">
                  <code>{w.code}</code> — {w.message}
                </div>
              ))}
            </div>
          )}

          <div className="chat-list" ref={listRef}>
            {messages.length === 0 && (
              <div className="empty">
                <h2>Edit your LaTeX paper with AI</h2>
                <p>
                  Ask for changes in natural language — the AI proposes section-precise edits
                  that you review before anything touches your sources.
                </p>
              </div>
            )}
            {messages.map((m) => (
              <div key={m.id} className={`msg ${m.role}`}>
                <div className="bubble">
                  <p className="msg-text">{m.text}</p>
                  {m.response && (
                    <div className="response">
                      <h3>AI response</h3>
                      <p>{m.response}</p>
                    </div>
                  )}
                  {m.changes && m.changes.length > 0 && (
                    <div className="review">
                      <h3>Review proposed changes</h3>
                      {m.changes.map((c) => (
                        <div key={c.change_id} className="card">
                          <div className="card-head">
                            <span>{c.operation} · {c.chunk_id.slice(0, 8)}</span>
                            {c.ai_explanation && <div className="explain">{c.ai_explanation}</div>}
                          </div>
                          <div className="diff">
                            <div className="diff-old" dangerouslySetInnerHTML={{ __html: c.old_html }} />
                            <div className="arrow">→</div>
                            <div className="diff-new" dangerouslySetInnerHTML={{ __html: c.new_html }} />
                          </div>
                          <div className="decide">
                            <button
                              className={c.decision === true ? "accepted" : ""}
                              onClick={() => decide(c.change_id, true)}
                            >
                              Accept
                            </button>
                            <button
                              className={c.decision === false ? "denied" : ""}
                              onClick={() => decide(c.change_id, false)}
                            >
                              Deny
                            </button>
                          </div>
                        </div>
                      ))}
                      <button
                        className="submit"
                        disabled={!m.changes.some((c) => c.decision !== null) || m.pending === false}
                        onClick={submitDecisions}
                      >
                        Submit decisions
                      </button>
                    </div>
                  )}
                  {m.applied !== undefined && (
                    <div className={`applied ${m.applied && m.applied.unresolved > 0 ? "warn" : ""}`}>
                      {m.applied === null
                        ? "Writing back to .tex…"
                        : m.applied.applied > 0
                          ? `Applied ${m.applied.applied}/${m.applied.total} edits to your .tex sources` +
                            (m.applied.unresolved > 0 ? ` — ${m.applied.unresolved} could not be located` : "")
                          : m.applied.unresolved > 0
                            ? `${m.applied.unresolved} edit(s) could not be located in the .tex sources`
                            : "Nothing to write back."}
                    </div>
                  )}
                  {!m.applied && m.pending === false && m.changes && m.changes.length > 0 && (
                    <button className="submit" onClick={() => writeBack(m)}>
                      Write back approved edits to .tex
                    </button>
                  )}
                  {m.pending && <div className="spinner" />}
                  {m.error && <div className="error-text">{m.error}</div>}
                </div>
              </div>
            ))}
          </div>
        </>
      )}

      <div className="composer">
        <textarea
          placeholder={auth?.hasKey ? "Ask for an edit — e.g. expand the abstract to two sentences…" : "Sign in to chat"}
          value={input}
          disabled={!auth?.hasKey}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
          rows={2}
        />
        <div className="composer-row">
          <button
            className="export-btn"
            disabled={!sessionId || phase === "exporting"}
            onClick={() => vscode.postMessage({ type: "exportDocx", filename: "" })}
            title="Export .docx (A4)"
          >
            Export .docx
          </button>
          <button disabled={!input.trim() || !auth?.hasKey || busy} onClick={send}>
            Send
          </button>
        </div>
      </div>
    </div>
  );
}

const root = document.getElementById("root");
if (root) createRoot(root).render(<App />);
