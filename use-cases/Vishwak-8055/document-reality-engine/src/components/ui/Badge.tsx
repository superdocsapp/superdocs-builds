import type { ReactNode } from "react";
import clsx from "clsx";
import type {
  ActionStatus,
  DocumentStatus,
  EvidenceStrength,
  RequirementStatus,
  RiskLevel,
  RiskStatus,
  VerificationStatus,
} from "../../types/domain";

export type Tone = "verified" | "warning" | "critical" | "neutral" | "trust";

const TONE_CLASSES: Record<Tone, string> = {
  verified: "bg-verified-soft text-verified border-verified/20",
  warning: "bg-warning-soft text-warning border-warning/20",
  critical: "bg-critical-soft text-critical border-critical/20",
  neutral: "bg-neutral-soft text-text-secondary border-line-strong",
  trust: "bg-trust-soft text-trust border-trust/20",
};

export function Badge({ tone = "neutral", children, className }: { tone?: Tone; children: ReactNode; className?: string }) {
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs font-medium leading-5 whitespace-nowrap",
        TONE_CLASSES[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

export function verificationTone(status: VerificationStatus): Tone {
  switch (status) {
    case "Verified":
      return "verified";
    case "Partially Supported":
      return "warning";
    case "Contradicted":
      return "critical";
    case "Needs Review":
    case "Unverified":
      return "neutral";
  }
}

export function requirementTone(status: RequirementStatus): Tone {
  switch (status) {
    case "Satisfied":
      return "verified";
    case "Warning":
      return "warning";
    case "Failed":
      return "critical";
  }
}

export function riskLevelTone(level: RiskLevel): Tone {
  switch (level) {
    case "Low":
      return "verified";
    case "Medium":
      return "warning";
    case "High":
    case "Critical":
      return "critical";
  }
}

export function riskStatusTone(status: RiskStatus): Tone {
  switch (status) {
    case "Open":
      return "warning";
    case "Mitigated":
      return "verified";
    case "Accepted":
      return "neutral";
  }
}

export function documentStatusTone(status: DocumentStatus): Tone {
  switch (status) {
    case "Draft":
      return "neutral";
    case "In Review":
      return "warning";
    case "Approved":
    case "Published":
      return "verified";
    case "Deprecated":
      return "critical";
  }
}

export function actionStatusTone(status: ActionStatus): Tone {
  switch (status) {
    case "Open":
      return "neutral";
    case "In Progress":
      return "warning";
    case "Done":
      return "verified";
  }
}

export function evidenceStrengthTone(strength: EvidenceStrength): Tone {
  switch (strength) {
    case "Strong":
      return "verified";
    case "Moderate":
      return "warning";
    case "Weak":
      return "critical";
  }
}

export function VerificationBadge({ status }: { status: VerificationStatus }) {
  return <Badge tone={verificationTone(status)}>{status}</Badge>;
}

export function RequirementBadge({ status }: { status: RequirementStatus }) {
  return <Badge tone={requirementTone(status)}>{status}</Badge>;
}

export function RiskLevelBadge({ level }: { level: RiskLevel }) {
  return (
    <Badge tone={riskLevelTone(level)} className={level === "Critical" ? "ring-2 ring-critical/30 ring-offset-1 ring-offset-paper-0" : undefined}>
      {level}
    </Badge>
  );
}

export function RiskStatusBadge({ status }: { status: RiskStatus }) {
  return <Badge tone={riskStatusTone(status)}>{status}</Badge>;
}

export function DocumentStatusBadge({ status }: { status: DocumentStatus }) {
  return <Badge tone={documentStatusTone(status)}>{status}</Badge>;
}

export function ActionStatusBadge({ status }: { status: ActionStatus }) {
  return <Badge tone={actionStatusTone(status)}>{status}</Badge>;
}

export function EvidenceStrengthBadge({ strength }: { strength: EvidenceStrength }) {
  return <Badge tone={evidenceStrengthTone(strength)}>{strength}</Badge>;
}
