"use client";

import { useState, type ReactNode } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  FileStack,
  TriangleAlert,
} from "lucide-react";
import type { ReturnShippingPayer } from "@/domain";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";
import { AppHeader } from "./shell";
import {
  ListField,
  NumberField,
  SelectField,
  TextAreaField,
  TextField,
  ToggleField,
} from "./fields";
import type { IntakeFormState } from "./intake";

const RETURN_PAYER_OPTIONS = [
  { value: "customer", label: "Customer" },
  { value: "merchant", label: "Merchant" },
] as const;

type StepId = "company" | "store" | "commitments" | "privacy";

const STEPS: readonly {
  id: StepId;
  label: string;
  title: string;
  description: string;
}[] = [
  {
    id: "company",
    label: "Company",
    title: "Who is publishing these policies?",
    description:
      "Identity and contact facts appear in all four documents, so they are only entered once.",
  },
  {
    id: "store",
    label: "Store",
    title: "How the store operates",
    description:
      "Trading facts that shape the Terms of Service and the Returns Policy.",
  },
  {
    id: "commitments",
    label: "Returns & warranty",
    title: "What you promise the customer",
    description:
      "The return window and warranty duration are shared facts: changing one later updates every document that states it.",
  },
  {
    id: "privacy",
    label: "Privacy",
    title: "What you collect and why",
    description:
      "Data-handling facts used to draft the Privacy Policy.",
  },
];

export function IntakeView({
  value,
  error,
  canCancel,
  onChange,
  onGenerate,
  onCancel,
}: {
  value: IntakeFormState;
  error: string | null;
  canCancel: boolean;
  onChange: (next: IntakeFormState) => void;
  onGenerate: () => void;
  onCancel: () => void;
}) {
  const [stepIndex, setStepIndex] = useState(0);
  const step = STEPS[stepIndex];
  const isLastStep = stepIndex === STEPS.length - 1;

  return (
    <div className="flex min-h-screen flex-col">
      <AppHeader context="Guided intake">
        {canCancel ? (
          <Button variant="quiet" size="sm" onClick={onCancel}>
            Back to workspace
          </Button>
        ) : null}
      </AppHeader>

      <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-8 sm:px-6 sm:py-12">
        <div className="grid gap-8 lg:grid-cols-[13rem_minmax(0,1fr)] lg:gap-12">
          <StepNavigator
            current={stepIndex}
            onSelect={setStepIndex}
          />

          <form
            className="min-w-0"
            onSubmit={(event) => {
              event.preventDefault();
              if (isLastStep) {
                onGenerate();
              } else {
                setStepIndex((index) => Math.min(index + 1, STEPS.length - 1));
              }
            }}
          >
            <p className="text-[13px] font-medium text-accent">
              Step {stepIndex + 1} of {STEPS.length}
            </p>
            <h1 className="mt-2 text-2xl font-semibold tracking-tight text-ink text-balance">
              {step.title}
            </h1>
            <p className="mt-2 max-w-xl text-sm leading-relaxed text-muted">
              {step.description}
            </p>

            <Separator className="my-7" />

            <div className="grid grid-cols-1 gap-x-5 gap-y-6 sm:grid-cols-2">
              {step.id === "company" ? <CompanyStep value={value} onChange={onChange} /> : null}
              {step.id === "store" ? <StoreStep value={value} onChange={onChange} /> : null}
              {step.id === "commitments" ? (
                <CommitmentsStep value={value} onChange={onChange} />
              ) : null}
              {step.id === "privacy" ? <PrivacyStep value={value} onChange={onChange} /> : null}
            </div>

            {error ? (
              <div
                role="alert"
                className="mt-8 flex items-start gap-2.5 rounded-[var(--radius-card)] border border-danger-line bg-danger-soft px-3.5 py-3 text-[13px] leading-relaxed text-danger"
              >
                <TriangleAlert className="mt-0.5 size-4 shrink-0" />
                <span>{error}</span>
              </div>
            ) : null}

            <div className="mt-8 flex items-center justify-between gap-3 border-t border-line pt-6">
              <Button
                type="button"
                variant="quiet"
                disabled={stepIndex === 0}
                onClick={() => setStepIndex((index) => Math.max(index - 1, 0))}
              >
                <ArrowLeft />
                Back
              </Button>

              {isLastStep ? (
                <Button type="submit" variant="primary" size="lg">
                  <FileStack />
                  Generate policy set
                </Button>
              ) : (
                <Button type="submit" variant="primary">
                  Continue
                  <ArrowRight />
                </Button>
              )}
            </div>
          </form>
        </div>
      </main>
    </div>
  );
}

function StepNavigator({
  current,
  onSelect,
}: {
  current: number;
  onSelect: (index: number) => void;
}) {
  return (
    <nav aria-label="Intake steps" className="lg:sticky lg:top-24 lg:self-start">
      <ol className="flex gap-1 overflow-x-auto pb-1 lg:block lg:space-y-0.5 lg:overflow-visible lg:pb-0">
        {STEPS.map((step, index) => {
          const active = index === current;
          const complete = index < current;
          return (
            <li key={step.id}>
              <button
                type="button"
                aria-current={active ? "step" : undefined}
                onClick={() => onSelect(index)}
                className={cn(
                  "flex w-full items-center gap-2.5 whitespace-nowrap rounded-[var(--radius-control)] px-2.5 py-2 text-left text-[13px] font-medium transition-colors duration-150",
                  active
                    ? "bg-surface text-ink shadow-[0_1px_2px_rgb(23_23_27/0.05)] ring-1 ring-line"
                    : "text-muted hover:bg-surface/70 hover:text-ink",
                )}
              >
                <span
                  aria-hidden="true"
                  className={cn(
                    "grid size-5 shrink-0 place-items-center rounded-full text-[11px] font-semibold tabular-nums transition-colors duration-150",
                    active && "bg-accent text-white",
                    complete && "bg-ok-soft text-ok",
                    !active && !complete && "bg-line text-muted",
                  )}
                >
                  {complete ? <Check className="size-3" /> : index + 1}
                </span>
                {step.label}
              </button>
            </li>
          );
        })}
      </ol>

      <p className="mt-5 hidden max-w-[13rem] text-xs leading-relaxed text-faint lg:block">
        Prefilled with Northstar Goods. Every fact you enter becomes part of one
        canonical profile behind all four documents.
      </p>
    </nav>
  );
}

type StepProps = {
  value: IntakeFormState;
  onChange: (next: IntakeFormState) => void;
};

function Wide({ children }: { children: ReactNode }) {
  return <div className="sm:col-span-2">{children}</div>;
}

function GroupLabel({ children }: { children: ReactNode }) {
  return (
    <div className="sm:col-span-2 pt-1">
      <p className="text-[11px] font-semibold uppercase tracking-[0.09em] text-faint">
        {children}
      </p>
    </div>
  );
}

function CompanyStep({ value, onChange }: StepProps) {
  return (
    <>
      <TextField
        label="Legal name"
        value={value.company.legalName}
        onChange={(legalName) => patchCompany(value, onChange, { legalName })}
      />
      <TextField
        label="Website"
        type="url"
        value={value.company.website}
        onChange={(website) => patchCompany(value, onChange, { website })}
      />
      <TextField
        label="Support email"
        type="email"
        value={value.company.supportEmail}
        onChange={(supportEmail) =>
          patchCompany(value, onChange, { supportEmail })
        }
      />
      <TextField
        label="Effective date"
        type="date"
        value={value.company.effectiveDate}
        onChange={(effectiveDate) =>
          patchCompany(value, onChange, { effectiveDate })
        }
      />
      <Wide>
        <TextField
          label="Governing jurisdiction"
          hint="Named in the Terms of Service governing-law section."
          value={value.company.governingJurisdiction}
          onChange={(governingJurisdiction) =>
            patchCompany(value, onChange, { governingJurisdiction })
          }
        />
      </Wide>

      <GroupLabel>Mailing address</GroupLabel>
      <Wide>
        <TextField
          label="Street address"
          value={value.company.mailingAddress.line1}
          onChange={(line1) => patchAddress(value, onChange, { line1 })}
        />
      </Wide>
      <TextField
        label="City"
        value={value.company.mailingAddress.city}
        onChange={(city) => patchAddress(value, onChange, { city })}
      />
      <TextField
        label="Region"
        value={value.company.mailingAddress.region}
        onChange={(region) => patchAddress(value, onChange, { region })}
      />
      <TextField
        label="Postal code"
        value={value.company.mailingAddress.postalCode}
        onChange={(postalCode) => patchAddress(value, onChange, { postalCode })}
      />
      <TextField
        label="Country"
        value={value.company.mailingAddress.country}
        onChange={(country) => patchAddress(value, onChange, { country })}
      />
    </>
  );
}

function StoreStep({ value, onChange }: StepProps) {
  return (
    <>
      <NumberField
        label="Minimum customer age"
        unit="years"
        value={value.store.minimumCustomerAge}
        onChange={(minimumCustomerAge) =>
          patchStore(value, onChange, { minimumCustomerAge })
        }
      />
      <TextField
        label="Payment processor"
        value={value.store.paymentProcessor}
        onChange={(paymentProcessor) =>
          patchStore(value, onChange, { paymentProcessor })
        }
      />
      <Wide>
        <ListField
          label="Shipping regions"
          value={value.store.shippingRegions}
          onChange={(shippingRegions) =>
            patchStore(value, onChange, { shippingRegions })
          }
        />
      </Wide>
    </>
  );
}

function CommitmentsStep({ value, onChange }: StepProps) {
  return (
    <>
      <GroupLabel>Returns</GroupLabel>
      <NumberField
        label="Return window"
        unit="days"
        value={value.returns.windowDays}
        onChange={(windowDays) => patchReturns(value, onChange, { windowDays })}
      />
      <NumberField
        label="Refund processing"
        unit="days"
        value={value.returns.processingDays}
        onChange={(processingDays) =>
          patchReturns(value, onChange, { processingDays })
        }
      />
      <SelectField
        label="Return shipping paid by"
        value={value.returns.returnShippingPayer}
        options={RETURN_PAYER_OPTIONS}
        onChange={(returnShippingPayer) =>
          patchReturns(value, onChange, {
            returnShippingPayer: returnShippingPayer as ReturnShippingPayer,
          })
        }
      />
      <TextField
        label="Refund method"
        value={value.returns.refundMethod}
        onChange={(refundMethod) =>
          patchReturns(value, onChange, { refundMethod })
        }
      />
      <Wide>
        <TextAreaField
          label="Return condition"
          value={value.returns.eligibleCondition}
          onChange={(eligibleCondition) =>
            patchReturns(value, onChange, { eligibleCondition })
          }
        />
      </Wide>
      <Wide>
        <ListField
          label="Final-sale exceptions"
          value={value.returns.finalSaleExceptions}
          onChange={(finalSaleExceptions) =>
            patchReturns(value, onChange, { finalSaleExceptions })
          }
        />
      </Wide>

      <GroupLabel>Warranty</GroupLabel>
      <NumberField
        label="Warranty duration"
        unit="months"
        value={value.warranty.durationMonths}
        onChange={(durationMonths) =>
          patchWarranty(value, onChange, { durationMonths })
        }
      />
      <TextField
        label="Covered defects"
        value={value.warranty.coveredDefects}
        onChange={(coveredDefects) =>
          patchWarranty(value, onChange, { coveredDefects })
        }
      />
      <Wide>
        <TextAreaField
          label="Warranty exclusions"
          value={value.warranty.exclusions}
          onChange={(exclusions) =>
            patchWarranty(value, onChange, { exclusions })
          }
        />
      </Wide>
      <Wide>
        <TextAreaField
          label="How to claim warranty"
          value={value.warranty.claimMethod}
          onChange={(claimMethod) =>
            patchWarranty(value, onChange, { claimMethod })
          }
        />
      </Wide>
    </>
  );
}

function PrivacyStep({ value, onChange }: StepProps) {
  return (
    <>
      <Wide>
        <ListField
          label="Data collected"
          value={value.privacy.collectedDataCategories}
          onChange={(collectedDataCategories) =>
            patchPrivacy(value, onChange, { collectedDataCategories })
          }
        />
      </Wide>
      <Wide>
        <ListField
          label="Use purposes"
          value={value.privacy.purposes}
          onChange={(purposes) => patchPrivacy(value, onChange, { purposes })}
        />
      </Wide>
      <Wide>
        <ListField
          label="Processors and services"
          value={value.privacy.processors}
          onChange={(processors) =>
            patchPrivacy(value, onChange, { processors })
          }
        />
      </Wide>
      <Wide>
        <TextField
          label="Retention"
          value={value.privacy.retentionSummary}
          onChange={(retentionSummary) =>
            patchPrivacy(value, onChange, { retentionSummary })
          }
        />
      </Wide>
      <Wide>
        <div className="grid gap-2 sm:grid-cols-2">
          <ToggleField
            label="Analytics"
            description="Disclosed as an analytics purpose"
            checked={value.privacy.analyticsEnabled}
            onChange={(analyticsEnabled) =>
              patchPrivacy(value, onChange, { analyticsEnabled })
            }
          />
          <ToggleField
            label="Marketing"
            description="Disclosed as a marketing purpose"
            checked={value.privacy.marketingEnabled}
            onChange={(marketingEnabled) =>
              patchPrivacy(value, onChange, { marketingEnabled })
            }
          />
        </div>
      </Wide>
    </>
  );
}

function patchCompany(
  value: IntakeFormState,
  onChange: (next: IntakeFormState) => void,
  patch: Partial<IntakeFormState["company"]>,
) {
  onChange({ ...value, company: { ...value.company, ...patch } });
}

function patchAddress(
  value: IntakeFormState,
  onChange: (next: IntakeFormState) => void,
  patch: Partial<IntakeFormState["company"]["mailingAddress"]>,
) {
  onChange({
    ...value,
    company: {
      ...value.company,
      mailingAddress: { ...value.company.mailingAddress, ...patch },
    },
  });
}

function patchStore(
  value: IntakeFormState,
  onChange: (next: IntakeFormState) => void,
  patch: Partial<IntakeFormState["store"]>,
) {
  onChange({ ...value, store: { ...value.store, ...patch } });
}

function patchReturns(
  value: IntakeFormState,
  onChange: (next: IntakeFormState) => void,
  patch: Partial<IntakeFormState["returns"]>,
) {
  onChange({ ...value, returns: { ...value.returns, ...patch } });
}

function patchWarranty(
  value: IntakeFormState,
  onChange: (next: IntakeFormState) => void,
  patch: Partial<IntakeFormState["warranty"]>,
) {
  onChange({ ...value, warranty: { ...value.warranty, ...patch } });
}

function patchPrivacy(
  value: IntakeFormState,
  onChange: (next: IntakeFormState) => void,
  patch: Partial<IntakeFormState["privacy"]>,
) {
  onChange({ ...value, privacy: { ...value.privacy, ...patch } });
}
