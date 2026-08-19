"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { sanitizeHtml } from "@/lib/sanitizeHtml";

/**
 * The whole letter, rendered from SuperDocs' actual HTML through DOMPurify —
 * the one place in this app that uses `dangerouslySetInnerHTML` (see
 * lib/sanitizeHtml.ts for why it's safe here specifically: the per-change
 * diff cards stay plain-text word diffs, which is the better review tool for
 * content edits; this view exists so formatting-only changes — spacing,
 * emphasis — are actually visible, which a text diff can never show.
 *
 * `final` is true once the job is `completed`: the HTML is the committed
 * document. Before that it is the proposed letter reconstructed from the
 * current batch's `new_html`, which is a preview, not yet written.
 */
export function LetterPreview({ html, final }: { html: string; final: boolean }) {
  // Open by default — a new user scanning the review page for "where's the
  // letter" should see it immediately, not a button that reveals it.
  const [open, setOpen] = useState(true);

  if (!html.trim()) return null;

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between gap-3 space-y-0 pb-3">
        <CardTitle className="text-sm font-medium">
          {final ? "Full letter" : "Full letter — preview, not yet written"}
        </CardTitle>
        <Button variant="ghost" size="sm" onClick={() => setOpen((v) => !v)}>
          {open ? "Hide" : "Show"}
        </Button>
      </CardHeader>
      {open && (
        <CardContent>
          <div
            className="text-sm leading-relaxed [&_p]:mb-3 last:[&_p]:mb-0"
            dangerouslySetInnerHTML={{ __html: sanitizeHtml(html) }}
          />
        </CardContent>
      )}
    </Card>
  );
}
