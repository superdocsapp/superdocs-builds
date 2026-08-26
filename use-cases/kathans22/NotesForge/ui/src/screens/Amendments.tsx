import { RunPanel } from "../components/RunPanel";
import type { Artifacts } from "../useArtifacts";
import type { AmendmentBatch, VersionStore } from "../types";

function consentStatusFor(store: VersionStore, clientId: string, templateId: string, version: string): string {
  const record = store.client_versions.find(
    (r) => r.client_id === clientId && r.template_id === templateId && r.version === version,
  );
  if (!record) return "unknown";
  return record.consented_on ? `consented ${record.consented_on}` : "PENDING";
}

function StructuredBatch({ batch, versions }: { batch: Extract<AmendmentBatch, { structured: true }>; versions: VersionStore }) {
  const { event } = batch;
  return (
    <div className="panel" style={{ background: "var(--bg)" }}>
      <h2>
        {event.requirement_id} <span className="pill">{event.kind}</span>
      </h2>
      <p className="panel-note" style={{ margin: "-0.4rem 0 0.7rem" }}>
        Effective {event.effective_from} · affects template(s) {event.scope.affected_template_ids.join(", ")} ·{" "}
        {event.scope.affected_client_ids.length} client(s) in scope
      </p>

      {event.notices.map((n) => (
        <div key={n.client_id} className="evidence-line" style={{ marginBottom: "0.7rem" }}>
          <span className="loc">
            {n.client_id} — {n.client_name} · {n.previous_version} → {n.new_version} ·{" "}
            <span
              className={`status-badge ${
                consentStatusFor(versions, n.client_id, n.template_id, n.new_version).startsWith("PENDING")
                  ? "STALE"
                  : "EVIDENCED"
              }`}
            >
              {consentStatusFor(versions, n.client_id, n.template_id, n.new_version)}
            </span>
          </span>
          <strong>Previous:</strong> {n.previous_text}
          {"\n\n"}
          <strong>New:</strong> {n.new_text}
          {"\n\n"}
          <strong>Did not change:</strong> {n.what_did_not_change.join(" ")}
        </div>
      ))}
    </div>
  );
}

function RawBatch({ batch }: { batch: Extract<AmendmentBatch, { structured: false }> }) {
  return (
    <div className="panel" style={{ background: "var(--bg)" }}>
      <h2>
        {batch.requirement_id} <span className="pill">notices only (no structured record)</span>
      </h2>
      <p className="panel-note" style={{ margin: "-0.4rem 0 0.7rem" }}>
        Effective {batch.effective_from ?? "unknown"} · {batch.notices_raw.length} notice(s) — this batch predates
        the structured event.json record, so its notices are shown verbatim below rather than reconstructed.
      </p>
      {batch.notices_raw.map((n) => (
        <details key={n.client_id} style={{ marginBottom: "0.5rem" }}>
          <summary style={{ cursor: "pointer", fontWeight: 600 }}>{n.client_id}</summary>
          <div className="evidence-line">{n.content}</div>
        </details>
      ))}
    </div>
  );
}

export function Amendments({ data, reload }: { data: Artifacts; reload: () => void }) {
  const { amendments, versions } = data;

  return (
    <div className="panel">
      <h2>Amendment events</h2>
      <p className="panel-note">
        {amendments.length} amendment batch(es) on file, from state/amendments/ · consent status is read from
        state/versions.json, not tracked separately here.
      </p>

      <RunPanel
        command="amend"
        label="Detect and apply amendment (RIA-AI-01 → config/requirements-v2.yaml)"
        onDone={reload}
      />

      {amendments.length === 0 && (
        <p className="state-message">No amendments on file yet — run the amendment check above.</p>
      )}

      {amendments.map((batch) =>
        batch.structured ? (
          <StructuredBatch key={batch.event_dir} batch={batch} versions={versions} />
        ) : (
          <RawBatch key={batch.event_dir} batch={batch} />
        ),
      )}
    </div>
  );
}
