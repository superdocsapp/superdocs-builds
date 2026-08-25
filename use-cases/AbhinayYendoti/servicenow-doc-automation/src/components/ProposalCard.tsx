import { useState } from "react";
import { Check, HelpCircle, Loader2, RefreshCw, X } from "lucide-react";

import { describeVerdict, explainVerdict, htmlToPlainText, type ProposedChange } from "../domain";

/**
 * One proposed chunk change, with its verdict and the reason behind it.
 *
 * A blocked change cannot be approved — the button is disabled here and the
 * server refuses it regardless — so the card offers the way forward instead:
 * reject it, and have SuperDocs redo that section knowing what was wrong.
 */
export function ProposalCard({
  busy,
  disabled,
  onDecide,
  onReEdit,
  proposal
}: {
  busy: boolean;
  disabled: boolean;
  onDecide: (approved: boolean) => void;
  onReEdit?: () => void;
  proposal: ProposedChange;
}) {
  const [explaining, setExplaining] = useState(false);
  const { verification } = proposal;

  const before = htmlToPlainText(proposal.before);
  const after = htmlToPlainText(proposal.after);
  const blocked = verification.verdict === "blocked";

  return (
    <article className={`proposal ${verification.verdict}`}>
      <header>
        <span className="proposal-operation">{proposal.operation.replace(/_/g, " ")}</span>
        <span className={`verdict-pill ${verification.verdict}`}>
          {describeVerdict(verification.verdict)}
        </span>
        <button
          aria-label="Why this verdict?"
          className="icon-button"
          onClick={() => setExplaining((open) => !open)}
          type="button"
        >
          <HelpCircle size={14} />
        </button>
      </header>

      {explaining && <p className="proposal-explainer">{explainVerdict(verification.verdict)}</p>}

      {proposal.explanation && <p className="proposal-intent">{proposal.explanation}</p>}

      <div className="proposal-diff">
        {before && (
          <p className="diff-before">
            <span>Now</span>
            {truncate(before)}
          </p>
        )}
        <p className="diff-after">
          <span>Proposed</span>
          {truncate(after) || "(removed)"}
        </p>
      </div>

      {verification.findings.length > 0 && (
        <ul className="proposal-findings">
          {verification.findings.map((finding) => (
            <li className={finding.blocking ? "blocking" : ""} key={`${finding.field}-${finding.reason}`}>
              {finding.reason}
            </li>
          ))}
        </ul>
      )}

      {proposal.decided ? (
        <p className="proposal-decided">
          {proposal.decision ? <Check size={13} /> : <X size={13} />}
          {proposal.decision ? "Approved" : "Rejected"}
        </p>
      ) : (
        <div className="proposal-actions">
          <button
            className="secondary-button"
            disabled={disabled || blocked}
            onClick={() => onDecide(true)}
            title={blocked ? "This change rewrites a value ServiceNow owns" : undefined}
            type="button"
          >
            {busy ? <Loader2 className="spin" size={14} /> : <Check size={14} />}
            Approve
          </button>
          <button
            className="secondary-button danger"
            disabled={disabled}
            onClick={() => onDecide(false)}
            type="button"
          >
            <X size={14} />
            Reject
          </button>
          {onReEdit && proposal.chunkId && (
            <button
              className="ghost-button"
              disabled={disabled}
              onClick={onReEdit}
              title="Reject this, and ask SuperDocs to redo the section knowing what was wrong"
              type="button"
            >
              <RefreshCw size={14} />
              Reject &amp; redo
            </button>
          )}
        </div>
      )}
    </article>
  );
}

function truncate(value: string, limit = 260) {
  return value.length > limit ? `${value.slice(0, limit)}...` : value;
}
