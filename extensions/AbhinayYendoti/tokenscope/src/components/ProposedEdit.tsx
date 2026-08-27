import type { ProposedChange } from "../../shared/types.js";

/**
 * The proposed rewrite, before it is anything more than a proposal.
 *
 * SuperDocs is asked in `ask_every_time` mode, so at this point the document is
 * untouched and this is a suggestion sitting in a job. The UI says so plainly,
 * because a panel that shows new text next to old text is easy to mistake for a
 * panel showing a change that has already happened.
 */
export function ProposedEdit({
  change,
  applied,
  applying,
  onApply
}: {
  change: ProposedChange;
  applied: boolean;
  applying: boolean;
  onApply: () => void;
}): JSX.Element {
  return (
    <article className={`edit ${applied ? "edit--applied" : ""}`}>
      <header className="edit__header">
        <h3>{applied ? "Applied to the document" : "Proposed rewrite"}</h3>
        {!applied && <span className="edit__pending">Not applied yet</span>}
      </header>

      <div className="edit__panes">
        <div className="edit__pane">
          <div className="edit__pane-label">Original</div>
          <p className="edit__text edit__text--old">{change.oldText}</p>
        </div>
        <div className="edit__pane">
          <div className="edit__pane-label">Rewritten</div>
          <p className="edit__text edit__text--new">{change.newText}</p>
        </div>
      </div>

      {change.explanation.length > 0 && <p className="edit__why">{change.explanation}</p>}

      {applied ? (
        <p className="edit__applied-note">
          The rewrite replaced the original text in the document, and was approved through SuperDocs
          so the session and the document agree on what happened.
        </p>
      ) : (
        <button
          type="button"
          className="button button--primary"
          onClick={onApply}
          disabled={applying}
        >
          {applying ? "Applying…" : "Apply to document"}
        </button>
      )}
    </article>
  );
}

/** A change that landed outside the selection. Shown, never offered for apply. */
export function OutOfScopeEdit({ change }: { change: ProposedChange }): JSX.Element {
  return (
    <article className="edit edit--out-of-scope">
      <header className="edit__header">
        <h3>Change outside your selection</h3>
        <span className="edit__pending">Will not be applied</span>
      </header>
      <p className="edit__text edit__text--old">{change.oldText}</p>
      <p className="edit__why">
        SuperDocs proposed this edit to text you did not select. TokenScope does not offer it,
        because a surgical edit that quietly touches something else is not a surgical edit.
      </p>
    </article>
  );
}
