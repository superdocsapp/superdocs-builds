import { useEffect, useState } from 'react';
import { api } from './api.js';
import { ConditionView } from './views/ConditionViews.jsx';

/**
 * Session shell: consent, then each assigned condition in turn, then done.
 *
 * Consent is a gate, not a formality -- PLAN.md.pdf section 8 lists
 * "participants informed and consenting" as a requirement, so the study cannot
 * start without it and the reviewer is told what is recorded before deciding.
 */
export default function App() {
  const [reviewerId, setReviewerId] = useState('');
  const [consented, setConsented] = useState(false);
  const [assignment, setAssignment] = useState(null);
  const [step, setStep] = useState(0);
  const [batch, setBatch] = useState(null);
  const [error, setError] = useState('');

  const current = assignment?.[step];

  useEffect(() => {
    if (!current) return;
    setBatch(null);
    api
      .getBatch(current.batch_id, current.condition)
      .then(setBatch)
      .catch((e) => setError(String(e)));
  }, [current?.batch_id, current?.condition]);

  const begin = async () => {
    try {
      const session = await api.startSession(reviewerId.trim());
      setAssignment(session.assignment);
      setStep(0);
    } catch (e) {
      setError(String(e));
    }
  };

  const recordDecision = async (partial) => {
    try {
      await api.recordDecision({
        reviewer_id: reviewerId.trim(),
        batch_id: current.batch_id,
        ...partial,
      });
    } catch (e) {
      // A lost decision is unrecoverable data, so surface it rather than
      // letting the reviewer carry on believing it was saved.
      setError(`Decision not saved: ${e}`);
    }
  };

  if (error) {
    return (
      <main className="app">
        <h1>Something went wrong</h1>
        <pre className="error">{error}</pre>
        <button type="button" onClick={() => setError('')}>
          Dismiss
        </button>
      </main>
    );
  }

  if (!assignment) {
    return (
      <main className="app">
        <h1>AI change review study</h1>
        <section className="consent">
          <h2>Before you start</h2>
          <p>
            You will review changes an AI proposed to a fictional contract and
            decide whether to approve or reject each one. There are no trick
            questions and no time limit.
          </p>
          <p>What is recorded: your decisions, and how long each one took.</p>
          <p>
            What is not recorded: anything identifying you. Your reviewer id is a
            label such as R1 and is published with the raw timings; your name is
            not.
          </p>
          <p>
            You can stop at any point by closing the tab. Decisions made before
            then are kept unless you ask for them to be removed.
          </p>
          <p>
            Some proposed changes are good and some are not. You are not being
            tested, and results are never reported per person.
          </p>
          <label className="consent-check">
            <input
              type="checkbox"
              checked={consented}
              onChange={(e) => setConsented(e.target.checked)}
            />
            I have read the above and agree to take part.
          </label>
        </section>
        <label>
          Reviewer id
          <input
            value={reviewerId}
            onChange={(e) => setReviewerId(e.target.value)}
            placeholder="R1"
          />
        </label>
        <button type="button" disabled={!consented || !reviewerId.trim()} onClick={begin}>
          Start
        </button>
      </main>
    );
  }

  if (step >= assignment.length) {
    return (
      <main className="app">
        <h1>Finished</h1>
        <p>Thank you. Your decisions have been recorded.</p>
        <p>
          Debrief: some of the changes you reviewed were deliberately flawed.
          How many, and which, is withheld during the study so that knowing the
          proportion cannot influence your judgement.
        </p>
      </main>
    );
  }

  if (!batch) {
    return (
      <main className="app">
        <p>Loading…</p>
      </main>
    );
  }

  return (
    <main className="app">
      <header className="session-header">
        <span>
          Part {step + 1} of {assignment.length}
        </span>
        <span className="doc-title">{batch.document_title}</span>
      </header>
      <ConditionView
        key={`${current.batch_id}:${current.condition}`}
        batch={batch}
        condition={current.condition}
        onDecision={recordDecision}
        onComplete={() => setStep((s) => s + 1)}
      />
    </main>
  );
}
