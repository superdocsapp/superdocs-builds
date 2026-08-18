import { Lock, RotateCcw, Scale, ShieldCheck, type LucideIcon } from "lucide-react";
import type { PolicyDocumentType } from "@/domain";
import { POLICY_DOCUMENT_TITLES } from "@/documents/spec";

/** Short labels used inside sentences and compact chrome. */
export const DOCUMENT_LABELS: Record<PolicyDocumentType, string> = {
  terms: "Terms",
  privacy: "Privacy",
  warranty: "Warranty",
  returns: "Returns",
};

/** Full document titles, matching the rendered documents themselves. */
export const DOCUMENT_TITLES = POLICY_DOCUMENT_TITLES;

export const DOCUMENT_ICONS: Record<PolicyDocumentType, LucideIcon> = {
  terms: Scale,
  privacy: Lock,
  warranty: ShieldCheck,
  returns: RotateCcw,
};
