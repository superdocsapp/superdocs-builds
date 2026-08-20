"use client";

// Retired as a standalone route in v2. Export (and the coherence/validate
// check) now lives inside each campaign's own workspace -- see
// app/campaigns/[id]/page.tsx's "Coherence" tab and its "Export campaign"
// button -- since v2 supports many campaigns, not one global campaign to
// export.

export default function ExportRedirectPage() {
  return (
    <div className="card" style={{ marginTop: 24 }}>
      <h2 style={{ marginTop: 0 }}>Export moved</h2>
      <p>Export and the coherence check now live inside each campaign's own workspace.</p>
      <a className="btn primary" href="/">
        Go to your campaigns
      </a>
    </div>
  );
}
