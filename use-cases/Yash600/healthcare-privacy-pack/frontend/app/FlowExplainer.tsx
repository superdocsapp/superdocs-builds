"use client";

// FlowExplainer.tsx -- shown in the workspace Preview panel whenever
// nothing is selected, instead of a plain "select something" line. Walks
// through the real pipeline in the exact order it actually executes,
// naming which engine handles each step -- SuperDocs (SUPERDOCS_API_KEY),
// Groq (GROQ_API_KEY), or purely local code with no external call at all.
// This is descriptive of the real main.py flow, not a marketing diagram:
// see the file-level comments next to each step for the exact function.

import { useEffect, useRef, useState } from "react";
import {
  IconUpload,
  IconLayers,
  IconWorkflow,
  IconDatabase,
  IconSparkle,
  IconEyeCheck,
  IconRefresh,
  IconDownload,
} from "./icons";

type Engine = "superdocs" | "groq" | "local";

const ENGINE_LABEL: Record<Engine, string> = {
  superdocs: "SuperDocs API",
  groq: "Groq LLM",
  local: "Local -- no API call",
};

const STEPS: { title: string; engine: Engine; desc: string; Icon: any }[] = [
  {
    title: "Upload policies & procedures",
    engine: "superdocs",
    desc:
      "The very first place SUPERDOCS_API_KEY gets used. Each file goes to SuperDocs' upload endpoint, which parses it and hands back real HTML with a stable chunk ID on every paragraph, heading, and table.",
    Icon: IconUpload,
  },
  {
    title: "Sections detected",
    engine: "local",
    desc:
      "That chunked HTML is split into numbered sections (§1, §2...) entirely in this app's own code -- pure parsing against the chunk IDs SuperDocs just assigned, no external call.",
    Icon: IconLayers,
  },
  {
    title: "Analyze References",
    engine: "groq",
    desc:
      "The one step that talks to an LLM directly instead of SuperDocs. Every policy section is sent to Groq (GROQ_API_KEY) alongside its grouped procedure's sections, and comes back with confidence-scored matches.",
    Icon: IconWorkflow,
  },
  {
    title: "Validate",
    engine: "local",
    desc:
      "Pass/fail checks run against what's already stored in this app's own database -- comparing section hashes and reference status. No external call at all.",
    Icon: IconDatabase,
  },
  {
    title: "Request an update",
    engine: "superdocs",
    desc:
      "Your plain-language instruction is sent to SuperDocs as a chat/async job -- SUPERDOCS_API_KEY again, this time to actually draft the proposed edit.",
    Icon: IconSparkle,
  },
  {
    title: "Review & approve",
    engine: "superdocs",
    desc:
      "Approving sends your decision back to SuperDocs, which applies the edit -- then SuperDocs is called once more to fetch the document's real updated content.",
    Icon: IconEyeCheck,
  },
  {
    title: "Auto-propagate",
    engine: "superdocs",
    desc:
      "If a policy section just changed, every procedure that references it gets its own independent SuperDocs chat/async job automatically -- no LLM call, no manual re-request.",
    Icon: IconRefresh,
  },
  {
    title: "Export",
    engine: "superdocs",
    desc:
      "Exporting one document or the whole pack calls SuperDocs' export endpoint -- the only SuperDocs call in this whole flow that's never billed.",
    Icon: IconDownload,
  },
];

export function FlowExplainer() {
  // Steps reveal as they're actually scrolled into view, not all at once on
  // mount -- with 8 steps in a panel this tall, an on-mount-only animation
  // means anything past the fold has already finished animating (i.e. sits
  // there fully opaque) by the time you scroll down to it, which is what
  // read as "static". Using IntersectionObserver instead means each step
  // genuinely animates in the moment it enters your view, however you got
  // there -- and it fires every time this component mounts, so switching
  // back to this empty state re-plays it instead of it only ever working
  // the first time.
  const containerRef = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState<Set<number>>(new Set());

  useEffect(() => {
    const els = containerRef.current?.querySelectorAll<HTMLElement>("[data-step-index]");
    if (!els || els.length === 0) return;

    if (typeof IntersectionObserver === "undefined") {
      setVisible(new Set(STEPS.map((_, i) => i)));
      return;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        setVisible((prev) => {
          let changed = false;
          const next = new Set(prev);
          for (const entry of entries) {
            if (entry.isIntersecting) {
              const idx = Number((entry.target as HTMLElement).dataset.stepIndex);
              if (!next.has(idx)) {
                next.add(idx);
                changed = true;
              }
              observer.unobserve(entry.target);
            }
          }
          return changed ? next : prev;
        });
      },
      { threshold: 0.3, rootMargin: "0px 0px -10% 0px" }
    );
    els.forEach((el) => observer.observe(el));
    return () => observer.disconnect();
  }, []);

  return (
    <div className="flow-explainer" ref={containerRef}>
      <div className="flow-explainer-head">
        <h2 style={{ marginTop: 0 }}>How a compliance pack moves through the system</h2>
        <p className="muted" style={{ marginTop: -4 }}>
          Select a policy or procedure on the left to preview it -- or scroll through the full pipeline below first,
          in the order it actually runs.
        </p>
      </div>
      <div className="flow-timeline">
        {STEPS.map((step, i) => (
          <div
            className={`flow-step ${visible.has(i) ? "in-view" : ""}`}
            key={step.title}
            data-step-index={i}
            style={{ transitionDelay: visible.has(i) ? `${(i % 4) * 60}ms` : "0ms" }}
          >
            <div className={`flow-step-marker ${step.engine}`}>
              <step.Icon size={17} />
            </div>
            <div className="flow-step-body">
              <div className="flow-step-title-row">
                <span className="flow-step-num">{i + 1}</span>
                <h3>{step.title}</h3>
                <span className={`flow-engine-badge ${step.engine}`}>{ENGINE_LABEL[step.engine]}</span>
              </div>
              <p>{step.desc}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
