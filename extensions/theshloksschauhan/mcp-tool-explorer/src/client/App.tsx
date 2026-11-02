import { useEffect, useMemo, useState, type FormEvent } from "react";
import { filterTools } from "../shared/tools.js";
import { createDraft, submissionFromDraft, type Draft } from "../shared/schema.js";
import type { FieldError, PublicConfig, ToolCallPayload, ToolDescriptor } from "../shared/types.js";
import { ApiError, callTool, closeSession, fetchConfig, fetchTools, openSession } from "./api.js";
import { JsonView } from "./JsonView.js";
import { SchemaForm } from "./SchemaForm.js";

type SessionState = {
  id: string;
  server: { name?: string; version?: string; protocolVersion?: string; instructions?: string };
};

type StoredDraft = {
  key: string;
  draft: Draft;
};

export function App() {
  const [config, setConfig] = useState<PublicConfig | null>(null);
  const [configError, setConfigError] = useState<string | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [session, setSession] = useState<SessionState | null>(null);
  const [tools, setTools] = useState<ToolDescriptor[]>([]);
  const [query, setQuery] = useState("");
  const [selectedName, setSelectedName] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, StoredDraft>>({});
  const [errors, setErrors] = useState<FieldError[]>([]);
  const [status, setStatus] = useState<string>("Not connected");
  const [busy, setBusy] = useState<"connect" | "tools" | "call" | null>(null);
  const [banner, setBanner] = useState<string | null>(null);
  const [output, setOutput] = useState<ToolCallPayload | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [expandResult, setExpandResult] = useState(false);

  useEffect(() => {
    fetchConfig()
      .then(setConfig)
      .catch(() => setConfigError("The explorer server is not responding."));
  }, []);

  const visible = useMemo(() => filterTools(tools, query), [tools, query]);
  const selected = tools.find((tool) => tool.name === selectedName) ?? null;
  const schemaKey = selected ? `${selected.name}:${JSON.stringify(selected.inputSchema)}` : "";
  const draft = selected ? drafts[selected.name]?.draft ?? createDraft(selected.inputSchema) : null;

  useEffect(() => {
    if (!selected) return;
    setDrafts((current) => {
      const existing = current[selected.name];
      if (existing?.key === schemaKey) return current;
      return { ...current, [selected.name]: { key: schemaKey, draft: createDraft(selected.inputSchema) } };
    });
  }, [selected, schemaKey]);

  async function connect() {
    setBusy("connect");
    setBanner(null);
    setFailure(null);
    try {
      const opened = await openSession(config?.auth === "server" ? undefined : apiKey.trim());
      setSession({ id: opened.sessionId, server: opened.server });
      setStatus("Loading tools");
      setBusy("tools");
      const listed = await fetchTools(opened.sessionId);
      setTools(listed.tools);
      setSelectedName(listed.tools[0]?.name ?? null);
      setStatus(`Connected · ${listed.tools.length} tools`);
    } catch (error) {
      setSession(null);
      setTools([]);
      setStatus("Not connected");
      setBanner(error instanceof Error ? error.message : "Could not connect.");
    } finally {
      setBusy(null);
    }
  }

  async function refreshTools() {
    if (!session) return;
    setBusy("tools");
    setBanner(null);
    try {
      const listed = await fetchTools(session.id);
      setTools(listed.tools);
      setSelectedName((current) =>
        current && listed.tools.some((tool) => tool.name === current) ? current : listed.tools[0]?.name ?? null,
      );
      setStatus(`Connected · ${listed.tools.length} tools`);
    } catch (error) {
      setBanner(error instanceof Error ? error.message : "Could not refresh tools.");
    } finally {
      setBusy(null);
    }
  }

  async function disconnect() {
    const current = session;
    setSession(null);
    setTools([]);
    setSelectedName(null);
    setOutput(null);
    setStatus("Not connected");
    if (current) await closeSession(current.id).catch(() => undefined);
  }

  async function execute(event: FormEvent) {
    event.preventDefault();
    if (!session || !selected || !draft) return;
    const submission = submissionFromDraft(selected.inputSchema, draft);
    if (!submission.ok) {
      setErrors(submission.errors);
      setFailure("Fix the fields below before executing.");
      setOutput(null);
      return;
    }
    setErrors([]);
    setFailure(null);
    setBusy("call");
    const started = performance.now();
    try {
      const result = await callTool(session.id, selected.name, submission.value);
      setOutput(result);
      setStatus(result.toolError ? "Tool returned an error" : `Completed in ${result.durationMs} ms`);
    } catch (error) {
      setOutput(null);
      if (error instanceof ApiError) {
        setErrors(error.payload.error.details ?? []);
        setFailure(error.message);
        if (error.payload.error.kind === "session") {
          setSession(null);
          setTools([]);
          setStatus("Session ended");
        }
      } else {
        setFailure(error instanceof Error ? error.message : "Execution failed.");
      }
      setStatus(`Failed after ${Math.round(performance.now() - started)} ms`);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="app">
      <header className="topbar">
        <div>
          <p className="eyebrow">SuperDocs</p>
          <h1>MCP Tool Explorer</h1>
        </div>
        <p className="status">{busy === "call" ? "Executing" : status}</p>
      </header>

      <section className="connect">
        <div>
          <p className="label">MCP endpoint</p>
          <p className="endpoint">{config?.mcpEndpoint ?? configError ?? "Loading…"}</p>
          <p className="muted">Streamable HTTP. Tools and schemas come from the server at connect time.</p>
        </div>
        {config?.auth === "client" ? (
          <label className="key-field">
            API key
            <input
              type="password"
              autoComplete="off"
              spellCheck={false}
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
              placeholder="sk_…"
            />
          </label>
        ) : (
          <p className="muted key-note">Using the server-side API key. It is not sent to the browser.</p>
        )}
        <div className="connect-actions">
          {session ? (
            <>
              <button type="button" onClick={() => void refreshTools()} disabled={busy !== null}>
                Refresh tools
              </button>
              <button type="button" className="secondary" onClick={() => void disconnect()} disabled={busy !== null}>
                Disconnect
              </button>
            </>
          ) : (
            <button type="button" onClick={() => void connect()} disabled={busy !== null || !config}>
              {busy === "connect" || busy === "tools" ? "Connecting…" : "Connect"}
            </button>
          )}
        </div>
      </section>
      {banner ? (
        <p className="banner" role="alert">
          {banner}
        </p>
      ) : null}
      {session?.server.instructions ? (
        <details className="instructions">
          <summary>Server instructions</summary>
          <pre>{session.server.instructions}</pre>
        </details>
      ) : null}

      <main className="workspace">
        <aside className="tool-list">
          <label>
            Search tools
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Filter by name or description" />
          </label>
          <p className="muted count">
            {session ? `${visible.length} of ${tools.length}` : "Connect to discover tools"}
          </p>
          <ul>
            {visible.map((tool) => (
              <li key={tool.name}>
                <button
                  type="button"
                  className={tool.name === selectedName ? "tool active" : "tool"}
                  aria-pressed={tool.name === selectedName}
                  onClick={() => {
                    setSelectedName(tool.name);
                    setErrors([]);
                    setFailure(null);
                  }}
                >
                  <span className="tool-name">{tool.name}</span>
                  {tool.description ? <span className="tool-desc">{tool.description}</span> : null}
                </button>
              </li>
            ))}
          </ul>
        </aside>

        <section className="editor">
          {selected && draft ? (
            <form onSubmit={(event) => void execute(event)}>
              <h2>{selected.title || selected.name}</h2>
              {selected.title ? <p className="tool-id">{selected.name}</p> : null}
              <p className="description">{selected.description || "No description returned by the server."}</p>
              {failure ? (
                <p className="banner" role="alert">
                  {failure}
                </p>
              ) : null}
              <SchemaForm
                schema={selected.inputSchema}
                draft={draft}
                errors={errors}
                onChange={(next) => setDrafts((current) => ({ ...current, [selected.name]: { key: schemaKey, draft: next } }))}
              />
              <details className="raw-schema">
                <summary>Input schema</summary>
                <JsonView value={selected.inputSchema} />
              </details>
              <button type="submit" disabled={busy !== null}>
                {busy === "call" ? "Executing…" : "Execute"}
              </button>
            </form>
          ) : (
            <div className="empty">
              <h2>No tool selected</h2>
              <p className="muted">Connect, then choose a tool. The form is built from that tool's input schema.</p>
            </div>
          )}
        </section>

        <section className="output" aria-live="polite">
          <div className="output-head">
            <h2>Result</h2>
            {output ? (
              <button type="button" className="secondary" onClick={() => setExpandResult((value) => !value)}>
                {expandResult ? "Collapse" : "Expand all"}
              </button>
            ) : null}
          </div>
          {output ? (
            <>
              <p className={output.toolError ? "status bad" : "status good"}>
                {output.toolError ? "Tool error" : "Success"} · {output.durationMs} ms
              </p>
              <h3>Request</h3>
              <JsonView value={output.request} expandAll={expandResult} />
              <div className="output-head">
                <h3>Response</h3>
                <button
                  type="button"
                  className="secondary"
                  onClick={() => void navigator.clipboard.writeText(JSON.stringify(output.result, null, 2))}
                >
                  Copy JSON
                </button>
              </div>
              <JsonView value={output.result} expandAll={expandResult} />
            </>
          ) : (
            <p className="muted">Execution status, the arguments sent, and the MCP response appear here.</p>
          )}
        </section>
      </main>
    </div>
  );
}
