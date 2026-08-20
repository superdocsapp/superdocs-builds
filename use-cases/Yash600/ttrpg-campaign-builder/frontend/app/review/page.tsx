"use client";

// Retired as a standalone route in v2. Reviewing a proposed edit (approve/
// reject) now happens directly on the document that has the pending
// version -- see app/documents/[id]/page.tsx -- because v2 supports many
// campaigns/documents at once rather than one global campaign, so there's
// no longer a single "the review queue" to land on.

export default function ReviewRedirectPage() {
  return (
    <div className="card" style={{ marginTop: 24 }}>
      <h2 style={{ marginTop: 0 }}>Review moved</h2>
      <p>
        Reviewing a proposed edit now happens on the document itself -- open the document from its campaign page and
        approve or reject the pending version there.
      </p>
      <a className="btn primary" href="/">
        Go to your campaigns
      </a>
    </div>
  );
}
