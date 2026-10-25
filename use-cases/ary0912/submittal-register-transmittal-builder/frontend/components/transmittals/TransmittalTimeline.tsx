import { CheckCircle2, Circle } from "lucide-react";
import type { TransmittalStatus } from "@/lib/api/types";

const STEPS: { status: TransmittalStatus; label: string }[] = [
  { status: "UPLOADED", label: "Uploaded to SuperDocs" },
  { status: "PROCESSING_EDIT", label: "Edit Requested" },
  { status: "AWAITING_APPROVAL", label: "Awaiting Approval" },
  { status: "EDIT_APPROVED", label: "Edit Approved" },
  { status: "EXPORTED", label: "Exported" },
];

const ORDER: TransmittalStatus[] = [
  "DRAFT",
  "UPLOADED",
  "PROCESSING_EDIT",
  "AWAITING_APPROVAL",
  "EDIT_APPROVED",
  "EDIT_REJECTED",
  "EXPORTED",
];

export function TransmittalTimeline({ status }: { status: TransmittalStatus }) {
  const currentIdx = ORDER.indexOf(status);

  return (
    <div className="rounded-lg border border-slate-200 bg-white px-5 py-4">
      <p className="mb-4 text-xs font-semibold uppercase tracking-wide text-slate-500">
        Workflow Progress
      </p>
      <ol className="flex flex-col gap-2 sm:flex-row sm:gap-0 sm:items-center" aria-label="Transmittal workflow steps">
        {STEPS.map(({ status: stepStatus, label }, idx) => {
          const stepIdx = ORDER.indexOf(stepStatus);
          const done = currentIdx >= stepIdx && status !== "EDIT_REJECTED";
          const active = currentIdx === stepIdx;
          const rejected = status === "EDIT_REJECTED" && stepStatus === "AWAITING_APPROVAL";

          return (
            <li key={stepStatus} className="flex items-center gap-2 sm:flex-1 sm:flex-col sm:text-center">
              <div className="flex items-center gap-2 sm:flex-col sm:gap-1.5">
                <span
                  className={`flex h-6 w-6 items-center justify-center rounded-full border-2 text-xs font-bold transition-colors ${
                    done
                      ? "border-green-500 bg-green-500 text-white"
                      : rejected
                      ? "border-red-400 bg-red-50 text-red-500"
                      : active
                      ? "border-blue-500 bg-blue-50 text-blue-600"
                      : "border-slate-200 bg-white text-slate-300"
                  }`}
                  aria-hidden
                >
                  {done ? <CheckCircle2 className="h-3.5 w-3.5" /> : <Circle className="h-3.5 w-3.5" />}
                </span>
                <span
                  className={`text-xs ${
                    done ? "text-green-700 font-medium" : active ? "text-blue-700 font-medium" : "text-slate-400"
                  }`}
                >
                  {label}
                </span>
              </div>
              {idx < STEPS.length - 1 && (
                <div
                  className={`hidden sm:block flex-1 h-0.5 mx-1 ${
                    currentIdx > stepIdx ? "bg-green-400" : "bg-slate-200"
                  }`}
                  aria-hidden
                />
              )}
            </li>
          );
        })}
      </ol>

      {status === "EDIT_REJECTED" && (
        <p className="mt-3 text-xs text-red-600 font-medium">
          Edit was rejected. You may request a new edit.
        </p>
      )}
    </div>
  );
}
