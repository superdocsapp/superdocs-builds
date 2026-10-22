import { useState } from 'react';
import { DiffView, WholeDocumentView } from '../components/DiffView.jsx';
import { useDecisionTimer } from '../useDecisionTimer.js';

/**
 * The four condition views. All share one timer hook (useDecisionTimer) so a
 * measured difference between conditions cannot be an artefact of four
 * different timing implementations.
 *
 * Presentation factor:
 *   batch      -- every change on screen at once, decided in any order,
 *                 submitted together
 *   sequential -- one change at a time, forced order, no going back
 *
 * Granularity factor:
 *   section -- the changed chunk alone, before/after
 *   whole   -- the same diff, highlighted in place inside the full document
 *
 * Nothing here has any access to ground truth: the API never sends it
 * (GROUND_TRUTH_SAFETY.md GT-1). There is deliberately no "correct" styling,
 * no score, and no feedback after a decision.
 */

function ChangeBody({ change, granularity, documentHtml }) {
  return granularity === 'whole' ? (
    <WholeDocumentView documentHtml={documentHtml} change={change} />
  ) : (
    <DiffView change={change} />
  );
}

function DecisionButtons({ onDecide, disabled, current }) {
  return (
    <div className="decision-buttons">
      <button
        type="button"
        className={current === 'approve' ? 'approve chosen' : 'approve'}
        disabled={disabled}
        onClick={() => onDecide('approve')}
      >
        Approve
      </button>
      <button
        type="button"
        className={current === 'reject' ? 'reject chosen' : 'reject'}
        disabled={disabled}
        onClick={() => onDecide('reject')}
      >
        Reject
      </button>
    </div>
  );
}

/** batch_section and batch_whole. */
export function BatchView({ batch, condition, granularity, onDecision, onComplete }) {
  const ids = batch.changes.map((c) => c.id);
  const { stop, engageRef } = useDecisionTimer(ids);
  const [decisions, setDecisions] = useState({});

  const decide = (change, verdict) => {
    const timing = stop(change.id);
    if (!timing) return; // already decided; a double click records nothing
    setDecisions((prev) => ({ ...prev, [change.id]: verdict }));
    onDecision({
      reviewer_change_id: change.id,
      decision: verdict,
      shown_at: timing.shownAt,
      engaged_at: timing.engagedAt,
      decided_at: timing.decidedAt,
      condition,
    });
  };

  const remaining = batch.changes.length - Object.keys(decisions).length;

  return (
    <div className="view batch-view">
      <p className="instructions">
        Review each proposed change and approve or reject it. You may work in any
        order. Submit when you have decided on all of them.
      </p>
      {batch.changes.map((change, i) => (
        // engageRef starts THIS change's clock when it is first reached, not
        // when the batch rendered -- see PROGRESS.md A18.
        <section key={change.id} className="change-card" ref={engageRef(change.id)}>
          <header>
            <span className="change-index">Change {i + 1}</span>
            <span className="change-op">{change.operation}</span>
          </header>
          {change.ai_explanation && <p className="explanation">{change.ai_explanation}</p>}
          <ChangeBody
            change={change}
            granularity={granularity}
            documentHtml={batch.document_html}
          />
          <DecisionButtons
            onDecide={(verdict) => decide(change, verdict)}
            disabled={Boolean(decisions[change.id])}
            current={decisions[change.id]}
          />
        </section>
      ))}
      <footer className="batch-footer">
        <button type="button" disabled={remaining > 0} onClick={onComplete}>
          {remaining > 0 ? `${remaining} change(s) left` : 'Submit all decisions'}
        </button>
      </footer>
    </div>
  );
}

/** sequential_section and sequential_whole. */
export function SequentialView({ batch, condition, granularity, onDecision, onComplete }) {
  const [index, setIndex] = useState(0);
  const change = batch.changes[index];

  // Only the visible change is being timed, which is the whole point of the
  // sequential condition. Engagement and render coincide here, so the two
  // timing measures agree -- that equality is asserted in timing.test.js.
  const { stop, engageRef } = useDecisionTimer(change ? [change.id] : []);

  if (!change) {
    return (
      <div className="view sequential-view">
        <p>All changes reviewed.</p>
        <button type="button" onClick={onComplete}>
          Finish
        </button>
      </div>
    );
  }

  const decide = (verdict) => {
    const timing = stop(change.id);
    if (!timing) return;
    onDecision({
      reviewer_change_id: change.id,
      decision: verdict,
      shown_at: timing.shownAt,
      engaged_at: timing.engagedAt,
      decided_at: timing.decidedAt,
      condition,
    });
    setIndex((i) => i + 1);
  };

  return (
    <div className="view sequential-view">
      <p className="instructions">
        Review this change and decide. You will not be able to return to it.
      </p>
      <p className="progress">
        Change {index + 1} of {batch.changes.length}
      </p>
      <section className="change-card" ref={engageRef(change.id)}>
        <header>
          <span className="change-op">{change.operation}</span>
        </header>
        {change.ai_explanation && <p className="explanation">{change.ai_explanation}</p>}
        <ChangeBody
          change={change}
          granularity={granularity}
          documentHtml={batch.document_html}
        />
        <DecisionButtons onDecide={decide} disabled={false} current={undefined} />
      </section>
    </div>
  );
}

/** Route a condition string to its view. */
export function ConditionView({ batch, condition, onDecision, onComplete }) {
  const [presentation, granularity] = condition.split('_');
  const Component = presentation === 'sequential' ? SequentialView : BatchView;
  return (
    <Component
      batch={batch}
      condition={condition}
      granularity={granularity}
      onDecision={onDecision}
      onComplete={onComplete}
    />
  );
}
