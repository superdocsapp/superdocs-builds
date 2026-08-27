/** Small shared pieces. Kept together because there are few of them and they are all dumb. */

import { useEffect, useState } from "react";

import type { Breach, Check, Severity } from "./api";

export function SeverityTag({ severity }: { severity: Severity | undefined }) {
  if (!severity) return null;
  // The label is always present. Colour reinforces it and never carries it alone, so this
  // still reads correctly in greyscale, in bright sun, and to anyone colour-blind.
  return <span className={`sev sev--${severity.key}`}>{severity.label}</span>;
}

export function Skeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="stack" aria-busy="true" aria-live="polite">
      <span className="visually-hidden">Loading</span>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="card">
          <div className="stack">
            <div className="skeleton" style={{ width: "45%" }} />
            <div className="skeleton" style={{ width: "80%" }} />
          </div>
        </div>
      ))}
    </div>
  );
}

export function ErrorNote({ error, onRetry }: { error: string; onRetry?: () => void }) {
  return (
    <div className="error" role="alert">
      <div>{error}</div>
      {onRetry && (
        <div style={{ marginTop: "0.5rem" }}>
          <button className="btn--small" onClick={onRetry}>
            Try again
          </button>
        </div>
      )}
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <div className="card">
      <div className="empty">
        <h3>{title}</h3>
        {children}
      </div>
    </div>
  );
}

/** Why the rail refused something, in the words the rail itself carries. */
export function RailVerdict({ clean, breaches }: { clean: boolean; breaches: Breach[] }) {
  if (clean) {
    return (
      <div className="notice notice--ok">
        <div className="notice__head">Observational — may be approved</div>
        <div>Nothing in this wording states a condition, a guarantee or a prediction.</div>
      </div>
    );
  }
  return (
    <div className="notice notice--refused">
      <div className="notice__head">Refused by the language rail — cannot be approved</div>
      {breaches.map((b, i) => (
        <div key={i}>
          <code>{b.matched}</code> — {b.why} <em>{b.suggest}</em>
        </div>
      ))}
      <div className="hint">
        The inspector&rsquo;s own wording stays in the report instead.
      </div>
    </div>
  );
}

export function CheckList({ checks }: { checks: Check[] }) {
  return (
    <div className="checklist">
      {checks.map((c) => (
        <div key={c.name} className={`check ${c.passed ? "check--pass" : "check--fail"}`}>
          <span className="check__mark" aria-hidden="true">
            {c.passed ? "✓" : "✕"}
          </span>
          <span>
            <span className="visually-hidden">{c.passed ? "Passed:" : "Failed:"}</span>
            {c.name}
            {c.detail && <span className="check__detail"> — {c.detail}</span>}
          </span>
        </div>
      ))}
    </div>
  );
}


/**
 * A destructive action that asks first, then does it.
 *
 * Two-step rather than a `confirm()` dialog: the question appears where the action is, so a
 * misfire on a phone is caught by reading a sentence rather than by a modal appearing over
 * the thing you were looking at. It disarms itself after a few seconds, because a button
 * left armed is a trap for the next tap.
 *
 * Deliberately not red. Colour means severity in this product and nowhere else, so the
 * weight of a destructive action is carried by the words and by having to say it twice.
 */
export function ConfirmButton({
  label,
  question,
  confirm,
  onConfirm,
  busy = false,
  small = true,
}: {
  label: string;
  question: string;
  confirm: string;
  onConfirm: () => void;
  busy?: boolean;
  small?: boolean;
}) {
  const [armed, setArmed] = useState(false);

  useEffect(() => {
    if (!armed) return;
    const timer = window.setTimeout(() => setArmed(false), 6000);
    return () => window.clearTimeout(timer);
  }, [armed]);

  if (!armed) {
    return (
      <button
        className={small ? "btn--quiet btn--small" : "btn--quiet"}
        onClick={() => setArmed(true)}
        disabled={busy}
      >
        {label}
      </button>
    );
  }

  return (
    <span className="confirm" role="group">
      <span className="confirm__ask">{question}</span>
      <button className="btn--primary btn--small" onClick={onConfirm} disabled={busy}>
        {busy ? "Deleting…" : confirm}
      </button>
      <button className="btn--small" onClick={() => setArmed(false)} disabled={busy}>
        Keep it
      </button>
    </span>
  );
}
