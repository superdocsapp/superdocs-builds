import Link from "next/link";
import { ArrowRight } from "lucide-react";

export const metadata = { title: "How It Works" };

const WORKFLOW_STEPS = [
  {
    number: "01",
    title: "Build the Submittal Register",
    body: "DocTask reads specification requirements and creates a list of required submissions. Each register item records what must be submitted, which specification section it comes from, who is responsible for providing it, the required format, and the specification revision.",
  },
  {
    number: "02",
    title: "Receive a Submittal",
    body: 'When contractor product information arrives, update the register status to "Received". This records that the submission has been received and is ready for comparison.',
  },
  {
    number: "03",
    title: "Compare Against Specification",
    body: 'DocTask compares submitted product data against the applicable specification. Each comparison produces a finding showing: the requirement, the submitted value, specification evidence, submission evidence, and whether it is a Match or Deviation.',
  },
  {
    number: "04",
    title: "Human Review",
    body: "A reviewer makes the final decision on each finding. Options are Approve, Reject, or Request Clarification. The reviewer can add a comment. Review decisions are permanent — a finding cannot be reviewed twice. Automated comparison informs the reviewer; it does not replace them.",
  },
  {
    number: "05",
    title: "Update the Register",
    body: "Once all findings are reviewed, the register status reflects the outcome. A submittal can be Reviewed with full compliance, or Reviewed with a deviation that was approved.",
  },
  {
    number: "06",
    title: "Build a Transmittal",
    body: "DocTask packages the reviewed submittal into a transmittal packet containing: a cover sheet, the submittal content, the applicable specification extract, the comparison findings, and all reviewer comments.",
  },
  {
    number: "07",
    title: "Edit with SuperDocs",
    body: "If the transmittal document needs changes, the reviewer submits an edit instruction. SuperDocs proposes specific changes to the document. These proposed changes are shown to the reviewer before anything is applied.",
  },
  {
    number: "08",
    title: "Approve and Export",
    body: "The reviewer approves or rejects the proposed changes. Only after approval can the transmittal be exported as a final DOCX file. Exported transmittals are immutable.",
  },
];

const TERMS = [
  {
    term: "Submittal",
    definition:
      "Product information or documentation submitted by a contractor or supplier to demonstrate compliance with project specification requirements.",
  },
  {
    term: "Specification",
    definition:
      "The technical document defining project requirements. Each section covers a specific product or work type (e.g. 09 65 00 covers resilient flooring).",
  },
  {
    term: "Finding",
    definition:
      "A specific comparison between one specification requirement and the corresponding submitted product value. A finding is either a Match or a Deviation.",
  },
  {
    term: "Deviation",
    definition:
      "A submitted value that does not meet the requirement stated in the specification. A deviation does not automatically fail — a reviewer must decide whether to approve or reject it.",
  },
  {
    term: "Match",
    definition:
      "A submitted value that satisfies the specification requirement. Still requires human review to become part of the official record.",
  },
  {
    term: "Register",
    definition:
      "The master list of all required submissions for a project. Each row represents one required submittal with its status, responsible party, and specification reference.",
  },
  {
    term: "Register Status",
    definition:
      "Tracks where a submittal is in the submission lifecycle: Not Received → Received → Under Review → Reviewed (or Overdue).",
  },
  {
    term: "Technical Status",
    definition:
      "The outcome of the technical review: Pending, Pending Review, Reviewed — Compliant, or Reviewed — Deviation. Separate from register status.",
  },
  {
    term: "Transmittal",
    definition:
      "A formal document package containing the reviewed submittal findings, evidence, and reviewer decisions. Transmitted to the project record.",
  },
  {
    term: "Specification Revision",
    definition:
      "Specifications can be revised (e.g. Rev 02 → Rev 03). The register item is updated rather than duplicated, so SUB-001 remains SUB-001 across revisions.",
  },
];

export default function HowItWorksPage() {
  return (
    <div className="mx-auto max-w-3xl px-6 py-8 space-y-10">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">How DocTask Works</h1>
        <p className="mt-2 text-base text-slate-600 leading-relaxed">
          DocTask is a construction submittal review platform. It helps project engineers and
          document controllers track required submissions, review submitted product information
          against specifications, and produce transmittal packets — with humans making every
          important decision.
        </p>
      </div>

      {/* Visual workflow */}
      <section aria-labelledby="workflow-heading">
        <h2 id="workflow-heading" className="text-sm font-semibold uppercase tracking-wide text-slate-500 mb-4">
          Workflow Overview
        </h2>
        <div className="rounded-lg border border-slate-200 bg-white px-6 py-5">
          <ol className="relative space-y-0">
            {[
              "Specification",
              "Submittal Register",
              "Incoming Submittal",
              "AI Comparison",
              "Human Review ← authoritative",
              "Transmittal Packet",
              "SuperDocs Edit",
              "Human Approval",
              "DOCX Export",
            ].map((step, i, arr) => (
              <li key={step} className="flex items-start gap-3">
                <div className="flex flex-col items-center">
                  <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-blue-100 text-[10px] font-bold text-blue-700 mt-0.5">
                    {i + 1}
                  </span>
                  {i < arr.length - 1 && (
                    <div className="w-px flex-1 bg-slate-200 my-1" style={{ minHeight: 16 }} aria-hidden />
                  )}
                </div>
                <p className={`pb-3 text-sm ${step.includes("authoritative") ? "font-semibold text-slate-900" : "text-slate-700"}`}>
                  {step.replace(" ← authoritative", "")}
                  {step.includes("authoritative") && (
                    <span className="ml-2 text-xs font-normal text-blue-600 bg-blue-50 rounded px-1.5 py-0.5">
                      authoritative
                    </span>
                  )}
                </p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      {/* Step-by-step */}
      <section aria-labelledby="steps-heading">
        <h2 id="steps-heading" className="text-sm font-semibold uppercase tracking-wide text-slate-500 mb-4">
          Step by Step
        </h2>
        <div className="space-y-4">
          {WORKFLOW_STEPS.map(({ number, title, body }) => (
            <div
              key={number}
              className="rounded-lg border border-slate-200 bg-white px-5 py-4 flex gap-4"
            >
              <span className="shrink-0 text-2xl font-bold text-slate-200 tabular-nums leading-none mt-0.5">
                {number}
              </span>
              <div>
                <h3 className="font-semibold text-slate-900 mb-1">{title}</h3>
                <p className="text-sm text-slate-600 leading-relaxed">{body}</p>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Terminology */}
      <section aria-labelledby="terms-heading">
        <h2 id="terms-heading" className="text-sm font-semibold uppercase tracking-wide text-slate-500 mb-4">
          Terminology
        </h2>
        <dl className="space-y-3">
          {TERMS.map(({ term, definition }) => (
            <div
              key={term}
              className="rounded-lg border border-slate-200 bg-white px-5 py-3.5"
            >
              <dt className="text-sm font-semibold text-slate-800 mb-1">{term}</dt>
              <dd className="text-sm text-slate-600 leading-relaxed">{definition}</dd>
            </div>
          ))}
        </dl>
      </section>

      {/* CTA */}
      <div className="rounded-lg border border-blue-200 bg-blue-50 px-5 py-4 flex items-center justify-between gap-4 flex-wrap">
        <div>
          <p className="text-sm font-semibold text-blue-800">Ready to get started?</p>
          <p className="text-xs text-blue-600 mt-0.5">
            Open the Submittal Register to see all required submissions.
          </p>
        </div>
        <Link
          href="/register"
          className="inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
        >
          Open Register <ArrowRight className="h-4 w-4" aria-hidden />
        </Link>
      </div>
    </div>
  );
}
