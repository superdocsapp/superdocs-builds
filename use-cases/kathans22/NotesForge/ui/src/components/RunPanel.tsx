import { useRef, useState } from "react";

interface RunPanelProps {
  command: string;
  label: string;
  onDone: () => void;
}

/**
 * A button that runs a real `compliance` CLI command through the dev
 * server's /api/run endpoint (see ../../vite-plugin-cli-runner.ts), streams
 * its output live, and calls onDone() (a useArtifacts `reload`) once the
 * run — and the sync that follows it — both finish.
 */
export function RunPanel({ command, label, onDone }: RunPanelProps) {
  const [running, setRunning] = useState(false);
  const [status, setStatus] = useState<"idle" | "ok" | "failed">("idle");
  const [lines, setLines] = useState<string[]>([]);
  const [expanded, setExpanded] = useState(false);
  const esRef = useRef<EventSource | null>(null);

  function start() {
    esRef.current?.close();
    setLines([]);
    setStatus("idle");
    setExpanded(true);
    setRunning(true);

    const es = new EventSource(`/api/run?cmd=${encodeURIComponent(command)}`);
    esRef.current = es;

    es.addEventListener("log", (event) => {
      const line = JSON.parse((event as MessageEvent<string>).data) as string;
      setLines((prev) => [...prev, line]);
    });

    es.addEventListener("done", (event) => {
      const result = JSON.parse((event as MessageEvent<string>).data) as string;
      setRunning(false);
      setStatus(result === "ok" ? "ok" : "failed");
      es.close();
      onDone();
    });

    es.onerror = () => {
      setRunning(false);
      setStatus("failed");
      es.close();
    };
  }

  return (
    <div className="run-panel">
      <div className="run-panel-row">
        <button type="button" className="run-button" onClick={start} disabled={running}>
          {running ? "Running…" : label}
        </button>
        {status === "ok" && <span className="status-badge EVIDENCED">done</span>}
        {status === "failed" && <span className="status-badge MISSING">failed — see log</span>}
        {lines.length > 0 && (
          <button type="button" className="run-toggle" onClick={() => setExpanded((e) => !e)}>
            {expanded ? "hide log" : "show log"}
          </button>
        )}
      </div>
      {expanded && lines.length > 0 && (
        <pre className="run-log">{lines.join("\n")}</pre>
      )}
    </div>
  );
}
