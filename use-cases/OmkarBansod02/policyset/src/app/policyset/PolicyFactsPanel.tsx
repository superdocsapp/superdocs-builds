"use client";

import { ArrowRight, ArrowRightLeft, TriangleAlert } from "lucide-react";
import { DEPENDENCY_REGISTRY, type PolicyProfile } from "@/domain";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import { DOCUMENT_TITLES } from "./document-meta";

const RETURN_WINDOW_DOCUMENTS = DEPENDENCY_REGISTRY["returns.windowDays"];

type FactGroup = {
  title: string;
  facts: readonly { label: string; value: string }[];
};

/**
 * The canonical facts behind the document set. Presented as quiet grouped rows
 * so it reads as a source of truth without competing with the document.
 */
export function PolicyFactsPanel({
  profile,
  returnWindowInput,
  disabled,
  proposeError,
  onReturnWindowInputChange,
  onProposeReturnWindow,
}: {
  profile: PolicyProfile;
  returnWindowInput: string;
  disabled: boolean;
  proposeError: string | null;
  onReturnWindowInputChange: (value: string) => void;
  onProposeReturnWindow: () => void;
}) {
  const groups = factGroups(profile);
  const currentWindow = profile.returns.windowDays;
  const parsedInput = Number(returnWindowInput);
  const hasDelta =
    returnWindowInput.trim() !== "" &&
    Number.isFinite(parsedInput) &&
    parsedInput !== currentWindow;

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-line px-5 py-4">
        <h2 className="text-[13px] font-semibold text-ink">Policy facts</h2>
        <p className="mt-1 text-xs leading-relaxed text-muted">
          Canonical values behind all four documents.
        </p>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto pb-6">
        {groups.map((group) => (
          <section key={group.title}>
            <h3 className="px-5 pb-1.5 pt-5 text-[11px] font-semibold uppercase tracking-[0.09em] text-faint">
              {group.title}
            </h3>
            <dl className="px-5">
              {group.facts.map((fact) => (
                <div
                  key={fact.label}
                  className="flex items-baseline justify-between gap-4 border-b border-line/70 py-2 last:border-b-0"
                >
                  <dt className="shrink-0 text-[13px] text-muted">
                    {fact.label}
                  </dt>
                  <dd
                    className="line-clamp-2 text-right text-[13px] text-ink"
                    title={fact.value}
                  >
                    {fact.value}
                  </dd>
                </div>
              ))}
            </dl>
          </section>
        ))}
      </div>

      <form
        className="border-t border-line bg-surface p-5"
        onSubmit={(event) => {
          event.preventDefault();
          onProposeReturnWindow();
        }}
      >
        <p className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-accent-ink">
          <ArrowRightLeft className="size-3" />
          Synchronized fact
        </p>
        <Label htmlFor="return-window-days" className="mt-2.5 block text-ink">
          Return window
        </Label>
        <p className="mt-1 text-xs leading-relaxed text-muted">
          Stated in the{" "}
          {RETURN_WINDOW_DOCUMENTS.map((documentType, index) => (
            <span key={documentType}>
              {index > 0 ? " and the " : ""}
              <span className="text-ink-soft">
                {DOCUMENT_TITLES[documentType]}
              </span>
            </span>
          ))}
          . Editing it proposes one change across both.
        </p>

        <div className="mt-3 flex items-center gap-2">
          <div className="relative w-[7.5rem] shrink-0">
            <Input
              id="return-window-days"
              type="number"
              min={1}
              step={1}
              inputMode="numeric"
              className="pr-12 tabular-nums"
              value={returnWindowInput}
              disabled={disabled}
              onChange={(event) => onReturnWindowInputChange(event.target.value)}
            />
            <span
              aria-hidden="true"
              className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-[13px] text-muted"
            >
              days
            </span>
          </div>
          <Button
            type="submit"
            variant="primary"
            className="flex-1"
            disabled={disabled || returnWindowInput.trim() === ""}
          >
            Propose update
          </Button>
        </div>

        <p
          className={cn(
            "mt-2.5 flex items-center gap-1.5 text-xs tabular-nums transition-colors duration-150",
            hasDelta ? "text-ink-soft" : "text-faint",
          )}
        >
          {hasDelta ? (
            <>
              <span className="text-muted">{currentWindow} days</span>
              <ArrowRight className="size-3 text-faint" />
              <span className="font-medium text-ink">{parsedInput} days</span>
            </>
          ) : (
            <>Current canonical value: {currentWindow} days</>
          )}
        </p>

        {proposeError ? (
          <p
            role="alert"
            className="mt-2.5 flex items-start gap-1.5 text-xs leading-relaxed text-danger"
          >
            <TriangleAlert className="mt-px size-3.5 shrink-0" />
            {proposeError}
          </p>
        ) : null}
      </form>
    </div>
  );
}

function factGroups(profile: PolicyProfile): readonly FactGroup[] {
  return [
    {
      title: "Company",
      facts: [
        { label: "Legal name", value: profile.company.legalName },
        { label: "Support", value: profile.company.supportEmail },
        { label: "Jurisdiction", value: profile.company.governingJurisdiction },
        { label: "Effective", value: profile.company.effectiveDate },
      ],
    },
    {
      title: "Store",
      facts: [
        {
          label: "Minimum age",
          value: `${profile.store.minimumCustomerAge} years`,
        },
        { label: "Payments", value: profile.store.paymentProcessor },
        {
          label: "Ships to",
          value: profile.store.shippingRegions.join(", "),
        },
      ],
    },
    {
      title: "Returns",
      facts: [
        {
          label: "Refund processing",
          value: `${profile.returns.processingDays} days`,
        },
        {
          label: "Return shipping",
          value:
            profile.returns.returnShippingPayer === "customer"
              ? "Paid by customer"
              : "Paid by merchant",
        },
        { label: "Refund method", value: profile.returns.refundMethod },
      ],
    },
    {
      title: "Warranty",
      facts: [
        {
          label: "Duration",
          value: `${profile.warranty.durationMonths} months`,
        },
        { label: "Covers", value: profile.warranty.coveredDefects },
      ],
    },
    {
      title: "Privacy",
      facts: [
        { label: "Retention", value: profile.privacy.retentionSummary },
        {
          label: "Analytics",
          value: profile.privacy.analyticsEnabled ? "Enabled" : "Disabled",
        },
        {
          label: "Marketing",
          value: profile.privacy.marketingEnabled ? "Enabled" : "Disabled",
        },
      ],
    },
  ];
}
