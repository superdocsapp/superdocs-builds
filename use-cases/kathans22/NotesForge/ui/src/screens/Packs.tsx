import { RunPanel } from "../components/RunPanel";
import type { Artifacts } from "../useArtifacts";
import type { CoverageStatus } from "../types";

function fileLabel(path: string): string {
  const parts = path.split(/[\\/]/);
  return parts[parts.length - 1] ?? path;
}

/**
 * exportedFiles holds the CLI's own absolute filesystem paths (whatever
 * host it ran on) — not something a browser can link to. `npm run sync`
 * separately copies ../out/ into ui/public/out/, which Vite serves at the
 * site root, so the actual download URL is just /out/<client_id>/<filename>.
 */
function downloadUrl(clientId: string, path: string): string {
  return `/out/${encodeURIComponent(clientId)}/${encodeURIComponent(fileLabel(path))}`;
}

export function Packs({ data, reload }: { data: Artifacts; reload: () => void }) {
  const { packs } = data;

  return (
    <div className="panel">
      <h2>Generated packs</h2>
      <p className="panel-note">
        {packs.packs.length} pack(s) on file
        {packs.generated_at ? ` · manifest from ${new Date(packs.generated_at).toLocaleString()}` : ""} · each
        section's status is what state/coverage.json found at draft time, cited by requirement.
      </p>

      <RunPanel command="generate" label="Generate all packs" onDone={reload} />

      {packs.packs.length === 0 && (
        <p className="state-message">No packs on file yet — run the generator above.</p>
      )}

      {packs.packs.map((p) => {
        const counts: Partial<Record<CoverageStatus, number>> = {};
        for (const s of p.plannedSections) counts[s.status] = (counts[s.status] ?? 0) + 1;

        return (
          <div key={p.client_id} className="panel" style={{ background: "var(--bg)" }}>
            <h2 style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
              <span>
                {p.client_id} — {p.client_name}
              </span>
              <span className={`status-badge ${p.verified ? "EVIDENCED" : "MISSING"}`}>
                {p.verified ? "verified" : "unverified"}
              </span>
            </h2>
            <p className="panel-note" style={{ margin: "-0.4rem 0 0.7rem" }}>
              {p.title} · generated {new Date(p.generated_at).toLocaleString()}
            </p>

            <div style={{ marginBottom: "0.7rem" }}>
              {p.plannedSections.map((s) => (
                <span key={s.requirement_id} className={`status-badge ${s.status}`} style={{ marginRight: "0.4rem" }}>
                  {s.requirement_id}
                </span>
              ))}
            </div>

            <h4 style={{ margin: "0 0 0.3rem", fontSize: "0.82rem" }}>Downloads</h4>
            {p.exportedFiles.length === 0 ? (
              <p className="panel-note">Not exported — run with export enabled (the default).</p>
            ) : (
              <ul style={{ margin: 0, paddingLeft: "1.1rem", fontSize: "0.82rem" }}>
                {p.exportedFiles.map((f) => (
                  <li key={f} className="mono">
                    <a href={downloadUrl(p.client_id, f)} download>
                      {fileLabel(f)}
                    </a>
                  </li>
                ))}
              </ul>
            )}

            <p className="draft-banner">
              DRAFT FOR PROFESSIONAL REVIEW — this pack is generated from source notes and does not
              constitute compliance advice or certification.
            </p>
          </div>
        );
      })}
    </div>
  );
}
