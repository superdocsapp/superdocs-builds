import { EvidenceWorkflow } from "./evidence-workflow";

const workflow = [
  "Add evidence",
  "Inspect extracted facts",
  "Generate a grounded assessment",
  "Review the assessment draft",
];

export default function Home() {
  return (
    <main className="page-shell">
      <header className="hero">
        <p className="eyebrow">Early scaffold</p>
        <h1>Payment Security Self-Assessment</h1>
        <p className="hero-copy">
          Prepare the narrative portions of a payment-security self-assessment
          from your organisation&apos;s evidence.
        </p>
      </header>

      <section className="workflow" aria-labelledby="workflow-heading">
        <h2 id="workflow-heading">Assessment workflow</h2>
        <ol>
          {workflow.map((step, index) => (
            <li key={step}>
              <span aria-hidden="true">{index + 1}</span>
              {step}
            </li>
          ))}
        </ol>
      </section>

      <EvidenceWorkflow />
    </main>
  );
}
