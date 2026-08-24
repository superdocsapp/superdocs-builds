"use client";

import { useState } from "react";
import { CornerDownLeft } from "lucide-react";
import type { SourceRegistration } from "../lib/api";
import { DocumentIdentity } from "./document-identity";
import { WorkflowProgress } from "./workflow-progress";
import { Button, StateMark } from "./ui";

export function InstructionComposer({
  source,
  submitting,
  onSubmit,
  onChangeSource,
}: {
  source: SourceRegistration;
  submitting: boolean;
  onSubmit: (instruction: string) => void;
  onChangeSource: () => void;
}) {
  const [instruction, setInstruction] = useState("");

  const canSubmit = instruction.trim().length > 0 && !submitting;

  return (
    <div>
      <DocumentIdentity
        document={{ name: source.source.name, revision: source.baseline.revision_id }}
        action={<button type="button" onClick={onChangeSource} className="min-h-11 px-2 text-[13px] font-medium text-accent hover:underline">Change source</button>}
      />
      <WorkflowProgress current="Instruction" />

      <div className="grid lg:grid-cols-[minmax(0,1fr)_290px]">
        <section className="px-5 py-10 sm:px-8 lg:px-10 lg:py-14">
          <div className="mx-auto max-w-[860px]">
            <h2 className="text-[30px] font-semibold tracking-[-0.04em] text-ink sm:text-[36px]">What do you want to change?</h2>
            <p className="mt-3 text-[15px] text-muted sm:text-[16px]">Describe the outcome. SuperDocs will prepare a proposal for review.</p>

            <div className="mt-8 grid min-h-[260px] grid-cols-[42px_minmax(0,1fr)] overflow-hidden rounded-lg border border-border bg-surface focus-within:border-info focus-within:ring-2 focus-within:ring-info/15">
              <div className="border-r border-border bg-surface-muted pt-4 text-center font-mono text-[12px] text-muted">1</div>
              <textarea
                id="instruction"
                aria-label="Document change instruction"
                value={instruction}
                onChange={(event) => setInstruction(event.target.value)}
                onKeyDown={(event) => {
                  if ((event.metaKey || event.ctrlKey) && event.key === "Enter" && canSubmit) onSubmit(instruction.trim());
                }}
                placeholder={'Change "45 days" to "30 days" and nothing else.'}
                disabled={submitting}
                className="min-h-[260px] w-full resize-y bg-surface px-4 py-4 font-mono text-[14px] leading-7 text-ink outline-none placeholder:text-muted/55 disabled:bg-surface-muted"
              />
            </div>

            <div className="mt-5 flex flex-wrap items-center gap-4">
              <Button onClick={() => canSubmit && onSubmit(instruction.trim())} disabled={!canSubmit} busy={submitting} className="min-w-[158px]">
                {submitting ? "Preparing…" : "Prepare change"}
              </Button>
              <span className="flex items-center gap-2 text-[13px] text-muted"><CornerDownLeft className="size-4" aria-hidden="true" />⌘ / Ctrl + Enter</span>
            </div>
          </div>
        </section>

        <aside className="border-t border-border px-5 py-8 sm:px-8 lg:border-l lg:border-t-0 lg:px-8 lg:py-14">
          <h2 className="text-[16px] font-semibold text-ink">Nothing writes without review</h2>
          <div className="mt-8 space-y-0">
            {["You approve every change", "Google revision is checked before write-back"].map((item, index) => (
              <div key={item} className="relative flex gap-3 pb-12 last:pb-0">
                {index === 0 ? <span className="absolute left-[9px] top-5 h-[calc(100%-20px)] border-l border-dashed border-muted/50" /> : null}
                <StateMark />
                <p className="text-[14px] leading-6 text-ink">{item}</p>
              </div>
            ))}
          </div>
        </aside>
      </div>
    </div>
  );
}
