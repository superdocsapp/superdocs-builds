import { AlertTriangle, ArrowRight, CheckCircle2, Loader2, Play } from "lucide-react";
import type { ReactNode } from "react";

import type { NextAction } from "../domain";

/**
 * The one thing to do next.
 *
 * The server decides this; the bar renders it. Everything else on the page can
 * be dense, because whatever else is on screen there is always exactly one
 * highlighted instruction and one button that carries it out.
 */
export function NextActionBar({
  action,
  busy,
  onAct,
  actionLabel
}: {
  action: NextAction | null;
  busy: boolean;
  onAct?: () => void;
  actionLabel?: string;
}) {
  if (!action) return null;

  const icons: Record<string, ReactNode> = {
    primary: <ArrowRight size={16} />,
    danger: <AlertTriangle size={16} />,
    success: <CheckCircle2 size={16} />,
    neutral: <Loader2 className="spin" size={16} />
  };

  return (
    <section className={`next-action ${action.tone}`} data-tour="next" role="status">
      <span className="next-icon" aria-hidden="true">
        {icons[action.tone]}
      </span>

      <div className="next-copy">
        <span className="eyebrow">Next step</span>
        <strong>{action.label}</strong>
        {action.detail && <p>{action.detail}</p>}
      </div>

      {onAct && (
        <button className="primary-button" disabled={busy} onClick={onAct} type="button">
          {busy ? <Loader2 className="spin" size={15} /> : <Play size={15} />}
          {actionLabel ?? action.label}
        </button>
      )}
    </section>
  );
}
