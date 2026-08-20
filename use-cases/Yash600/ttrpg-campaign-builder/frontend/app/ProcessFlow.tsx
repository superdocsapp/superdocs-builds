// app/ProcessFlow.tsx -- animated, centered pipeline diagram for the
// homepage. Replaces the old static 5-card "how it works" grid (see
// globals.css's "process flow" section for the animation/layout rules).
//
// Each node is tagged SUPERDOCS or THIS APP so the diagram also answers
// "where is SuperDocs actually used" instead of just being decorative:
//   1. Create   -> SuperDocs: every document is uploaded via
//                  client.upload_document_base64 (see main.py's
//                  _create_document_with_version).
//   2. Link     -> This app: a DocumentLink row with a plain
//                  synced_version_number int, no SuperDocs call at all.
//   3. AI edits -> SuperDocs: client.chat_async proposes the edit; nothing
//                  is applied until POST /documents/{id}/versions/{v}/approve.
//   4. Stale links surface -> This app: comparing synced_version_number
//                  against the target's live active version number --
//                  integer equality, no SuperDocs call, no LLM judgment.
//   5. Export  -> SuperDocs: client.export() bundles each document via
//                  SuperDocs' own export endpoint into the zip.
import { IconBook, IconLayers, IconSparkle, IconLinkBroken, IconDownload, IconCloud } from "./icons";

const NODES = [
  { title: "You create", desc: "Write or import the Bible, characters, NPCs, locations.", Icon: IconBook, via: "superdocs" as const },
  { title: "You link", desc: "Draw the connections that matter -- you decide what's linked.", Icon: IconLayers, via: "local" as const },
  { title: "AI edits, on request", desc: "Ask via chat. Nothing applies until you approve it.", Icon: IconSparkle, via: "superdocs" as const },
  { title: "Stale links surface", desc: "Every linking document gets flagged -- a version-number check.", Icon: IconLinkBroken, via: "local" as const },
  { title: "Export, coherent", desc: "The whole campaign bundles into one cross-referenced set.", Icon: IconDownload, via: "superdocs" as const },
];

export default function ProcessFlow() {
  return (
    <div className="process-flow">
      <div className="process-flow-heading">How a campaign moves through the system</div>
      <div className="process-flow-track">
        <div className="process-flow-line">
          <div className="process-flow-pulse" />
        </div>
        {NODES.map(({ title, desc, Icon, via }, i) => (
          <div className="process-flow-node" key={title} style={{ animationDelay: `${i * 0.05}s` }}>
            <div className="process-flow-icon" style={{ animationDelay: `${(i * 7) / NODES.length}s` }}>
              <Icon size={24} />
            </div>
            <div className="process-flow-title">{title}</div>
            <div className="process-flow-desc">{desc}</div>
            <span className={`process-flow-tag ${via}`}>
              {via === "superdocs" ? (
                <>
                  <IconCloud size={11} /> SuperDocs
                </>
              ) : (
                "This app"
              )}
            </span>
          </div>
        ))}
      </div>
      <div className="process-flow-legend">
        <span>
          <IconCloud size={12} /> SuperDocs -- document storage, AI edits, export
        </span>
        <span>This app -- linking &amp; staleness detection on top</span>
      </div>
    </div>
  );
}
