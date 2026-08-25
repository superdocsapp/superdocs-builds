import { useEffect, useRef } from "react";
import { Activity, Radio } from "lucide-react";

import { describeActivity, formatTime, htmlToPlainText, type ActivityEvent } from "../domain";

/**
 * What SuperDocs is doing, as it does it.
 *
 * These are the model's own progress messages, forwarded from its SSE stream.
 * Without them the editing step is a spinner for a minute and a half; with them
 * it reads as a system working through a document.
 */
export function AgentFeed({
  events,
  live,
  status
}: {
  events: ActivityEvent[];
  live: boolean;
  status: string | null;
}) {
  const endRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "nearest" });
  }, [events.length]);

  return (
    <section className="panel feed-panel" data-tour="feed">
      <div className="panel-heading">
        <div className="panel-title">
          <span className="panel-icon">
            <Activity size={19} />
          </span>
          <div>
            <span className="eyebrow">SuperDocs Activity</span>
            <h2>Live agent feed</h2>
          </div>
        </div>
        <span className={`status-pill ${live ? "live" : ""}`}>
          {live && <Radio className="pulse" size={11} />}
          {live ? "streaming" : status ?? "idle"}
        </span>
      </div>

      <div className="feed-list">
        {events.length === 0 && (
          <p className="feed-empty">
            Progress from SuperDocs appears here while it drafts — the sections it reads, the
            passages it rewrites, and each batch it puts up for review.
          </p>
        )}

        {events.map((event, index) => (
          <article className={`feed-line ${event.type}`} key={`${event.sequence}-${index}`}>
            <span className="feed-time">{formatTime(event.at) || "—"}</span>
            <div>
              <span className="feed-kind">{describeActivity(event)}</span>
              <p>{summarise(event.content)}</p>
            </div>
          </article>
        ))}
        <div ref={endRef} />
      </div>
    </section>
  );
}

/**
 * Summaries are pure functions of the event text, and the same events re-render
 * on every state push for the life of a run. A `document_sync` event carries
 * the whole document, so re-parsing it each time is the one place this feed can
 * get expensive on a long edit.
 */
const summaries = new Map<string, string>();
const SUMMARY_CACHE_LIMIT = 500;

function summarise(content: string) {
  const cached = summaries.get(content);
  if (cached !== undefined) return cached;

  const value = computeSummary(content);

  // Bounded so a very long run cannot grow this without limit.
  if (summaries.size >= SUMMARY_CACHE_LIMIT) summaries.clear();
  summaries.set(content, value);

  return value;
}

/**
 * Some events carry a whole document or a JSON batch. Those are rendered as a
 * one-line note rather than dumped into the feed.
 */
function computeSummary(content: string) {
  const text = content.trim();

  if (text.startsWith("{") || text.startsWith("[")) {
    try {
      const parsed = JSON.parse(text);
      const count = parsed?.batch_total ?? parsed?.changes?.length;
      return count ? `Put ${count} change${count === 1 ? "" : "s"} up for review.` : "Structured update.";
    } catch {
      return "Structured update.";
    }
  }

  if (text.startsWith("<")) {
    const plain = htmlToPlainText(text);
    return `Synced the document outline (${plain.split(/\s+/).length} words).`;
  }

  return text.length > 220 ? `${text.slice(0, 220)}…` : text;
}
