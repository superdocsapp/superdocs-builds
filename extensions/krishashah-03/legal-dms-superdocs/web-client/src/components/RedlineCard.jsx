import { useState } from "react";

function cleanHtml(html) {
  const div = document.createElement("div");
  div.innerHTML = html || "";
  // Strip <style>/<script> BEFORE reading textContent - otherwise their raw
  // content leaks into the visible text, which is the exact bug we just saw.
  div.querySelectorAll("style, script").forEach((el) => el.remove());
  return div;
}

function extractText(html) {
  return cleanHtml(html).textContent.trim();
}

function countWords(text) {
  return text ? text.split(/\s+/).filter(Boolean).length : 0;
}

function countSections(html) {
  return cleanHtml(html).querySelectorAll("h1, h2, h3, h4, h5, h6").length;
}

const OPERATION_LABELS = {
  create: "New section",
  edit: "Edit to existing text",
  update: "Update",
  delete: "Deletion",
};

export default function RedlineCard({ change, busy, onDecision }) {
  const [expanded, setExpanded] = useState(false);

  const newText = extractText(change.new_html);
  const oldText = extractText(change.old_html);
  const wordCount = countWords(newText);
  const sectionCount = countSections(change.new_html);
  const preview = newText.slice(0, 140) + (newText.length > 140 ? "…" : "");

  return (
    <div className="rounded-lg border border-slate/30 bg-white p-5">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-medium uppercase tracking-wide text-redline">
          {OPERATION_LABELS[change.operation] || change.operation || "Change"}
        </span>
        <span className="text-xs text-slate">
          {wordCount} word{wordCount !== 1 ? "s" : ""}
          {sectionCount > 0 ? ` · ${sectionCount} section${sectionCount !== 1 ? "s" : ""}` : ""}
        </span>
      </div>

      {change.ai_explanation && (
        <p className="text-sm font-medium text-ink mb-3">{change.ai_explanation}</p>
      )}

      {!expanded ? (
        <button
          onClick={() => setExpanded(true)}
          className="text-left w-full rounded border border-slate/20 bg-paper px-3 py-2 text-sm text-slate hover:border-slate/40"
        >
          {preview || "(no preview available)"}
          <span className="block mt-1 text-xs text-ink underline">Show full text</span>
        </button>
      ) : (
        <div className="rounded border border-slate/20 bg-paper px-3 py-3 text-sm font-doc leading-relaxed">
          {oldText && <p className="text-slate line-through mb-2">{oldText}</p>}
          {newText && <p className="text-redline underline whitespace-pre-wrap">{newText}</p>}
          <button
            onClick={() => setExpanded(false)}
            className="mt-2 text-xs text-ink underline"
          >
            Collapse
          </button>
        </div>
      )}

      <div className="mt-4 flex gap-2">
        <button
          onClick={() => onDecision(change, true)}
          disabled={busy}
          className="rounded bg-approve text-paper px-4 py-1.5 text-sm font-medium disabled:opacity-50"
        >
          Accept
        </button>
        <button
          onClick={() => onDecision(change, false)}
          disabled={busy}
          className="rounded border border-redline/50 text-redline px-4 py-1.5 text-sm font-medium disabled:opacity-50"
        >
          Reject
        </button>
      </div>
    </div>
  );
}