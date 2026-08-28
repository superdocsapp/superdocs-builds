import { useState, useEffect } from "react";
import type { QueueItem } from "@/types/review";
import { PayloadView } from "./PayloadView";
import { CitationList } from "./CitationList";
import { SourceLocationTable } from "./SourceLocationTable";
import { ProvenancePanel } from "./ProvenancePanel";
import { DecisionControls } from "./DecisionControls";

export interface DetailPanelProps {
  item: QueueItem | null;
  onDecide: (decision: "approved" | "rejected", justification: string) => void;
  isSubmitting: boolean;
}

/**
 * Detail panel composing PayloadView, CitationList, SourceLocationTable,
 * and DecisionControls. Shows a placeholder when no item is selected.
 * Slides in from the right on selection with a transform + opacity transition.
 */
export function DetailPanel({ item, onDecide, isSubmitting }: DetailPanelProps) {
  const [isVisible, setIsVisible] = useState(false);

  useEffect(() => {
    if (item) {
      // Small delay to trigger CSS transition
      const frame = requestAnimationFrame(() => setIsVisible(true));
      return () => cancelAnimationFrame(frame);
    } else {
      setIsVisible(false);
    }
  }, [item?.id]);

  if (item === null) {
    return (
      <div
        className="flex h-full items-center justify-center bg-surface-base"
        aria-label="Detail panel"
      >
        <div className="text-center">
          <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-white/[0.03] border border-white/[0.06]">
            <svg className="h-5 w-5 text-white/20" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m5.231 13.481L15 17.25m-4.5-15H5.625c-.621 0-1.125.504-1.125 1.125v16.5c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
            </svg>
          </div>
          <p className="text-sm text-white/30">Select an item to review</p>
        </div>
      </div>
    );
  }

  return (
    <div
      className={`flex h-full flex-col overflow-y-auto bg-surface-base transition-all duration-300 ${
        isVisible ? "opacity-100 translate-x-0" : "opacity-0 translate-x-4"
      }`}
      aria-label="Detail panel"
    >
      {/* Radial gradient overlay for depth */}
      <div className="absolute inset-0 pointer-events-none bg-[radial-gradient(ellipse_at_top,rgba(99,102,241,0.05),transparent_50%)]" aria-hidden="true" />

      {/* Content */}
      <div className="relative flex flex-col gap-6 p-4 flex-1">
        <PayloadView item={item} />
        <ProvenancePanel item={item} />
        <CitationList citations={item.payload.source_citations} />
        <SourceLocationTable citations={item.payload.source_citations} />

        {/* Decision area pinned to bottom with stronger visual weight */}
        <div className="mt-auto pt-4">
          <DecisionControls
            item={item}
            onDecide={onDecide}
            isSubmitting={isSubmitting}
          />
        </div>
      </div>
    </div>
  );
}
