import type { Intake, Purpose, StrengthBand } from "./types";

/**
 * Server-side intake validation.
 *
 * The form validates too, but the form is not the boundary: /api/draft is a
 * public HTTP endpoint that spends money on every call. Validating only in the
 * browser means anyone with curl can burn the operation budget with an empty
 * body, and means a malformed intake reaches the prompt builder where the
 * failure is much harder to read.
 *
 * Hand-written rather than a schema library. It is sixty lines, it produces
 * error text a human can act on, and it keeps the dependency list short.
 */

const BANDS: StrengthBand[] = ["strong", "solid", "mixed", "reluctant"];
const PURPOSES: Purpose[] = ["graduate_school", "job", "fellowship_or_award", "other"];
const LENGTHS: Intake["lengthPreference"][] = ["brief", "standard", "detailed"];

const MAX_FIELD = 4000;
const MAX_EVIDENCE_ITEMS = 20;

export type ValidationResult =
  | { ok: true; value: Intake }
  | { ok: false; errors: string[]; fieldErrors: Record<string, string> };

export function validateIntake(input: unknown): ValidationResult {
  const errors: string[] = [];
  const fieldErrors: Record<string, string> = {};

  const fail = (field: string, message: string) => {
    fieldErrors[field] = message;
    errors.push(message);
  };

  if (!input || typeof input !== "object") {
    return { ok: false, errors: ["The intake must be an object."], fieldErrors: {} };
  }
  const raw = input as Record<string, unknown>;

  const text = (field: string, label: string, required: boolean, max = MAX_FIELD): string => {
    const value = raw[field];
    if (typeof value !== "string") {
      if (required) fail(field, `${label} is required.`);
      return "";
    }
    const trimmed = value.trim();
    if (required && !trimmed) fail(field, `${label} is required.`);
    if (trimmed.length > max) {
      fail(field, `${label} is longer than ${max} characters. Trim it and resubmit.`);
      return trimmed.slice(0, max);
    }
    return trimmed;
  };

  const writerName = text("writerName", "Your name", true, 200);
  const writerEmail = text("writerEmail", "Your email", false, 320);
  const writerRole = text("writerRole", "Your role", true, 300);
  const subjectName = text("subjectName", "The subject's name", true, 200);
  const subjectRole = text("subjectRole", "The subject's role", true, 300);
  const relationship = text("relationship", "How you know them", true);
  const reservations = text("reservations", "Reservations", false);
  const toneNotes = text("toneNotes", "Tone notes", false);
  const purposeOther = text("purposeOther", "Purpose", false, 300);

  if (writerEmail && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(writerEmail)) {
    fail("writerEmail", "That email address does not look valid. It is optional; clear it or fix it.");
  }

  const months = raw.relationshipDurationMonths;
  const relationshipDurationMonths =
    typeof months === "number" && Number.isFinite(months) ? Math.floor(months) : NaN;
  if (!Number.isFinite(relationshipDurationMonths) || relationshipDurationMonths < 0) {
    fail("relationshipDurationMonths", "How long you have known them must be a number of months, zero or more.");
  } else if (relationshipDurationMonths > 720) {
    fail("relationshipDurationMonths", "That is over sixty years. Check the number of months.");
  }

  const strengthBand = raw.strengthBand as StrengthBand;
  if (!BANDS.includes(strengthBand)) {
    fail("strengthBand", `Pick a strength band. One of: ${BANDS.join(", ")}.`);
  }

  const purpose = raw.purpose as Purpose;
  if (!PURPOSES.includes(purpose)) {
    fail("purpose", `Pick a purpose. One of: ${PURPOSES.join(", ")}.`);
  }
  if (purpose === "other" && !purposeOther) {
    fail("purposeOther", "You chose 'other' as the purpose, so describe it.");
  }

  const lengthPreference = raw.lengthPreference as Intake["lengthPreference"];
  if (!LENGTHS.includes(lengthPreference)) {
    fail("lengthPreference", `Pick a length. One of: ${LENGTHS.join(", ")}.`);
  }

  const rawEvidence = Array.isArray(raw.evidence) ? raw.evidence : [];
  if (rawEvidence.length > MAX_EVIDENCE_ITEMS) {
    fail("evidence", `At most ${MAX_EVIDENCE_ITEMS} evidence items.`);
  }

  const evidence = rawEvidence
    .slice(0, MAX_EVIDENCE_ITEMS)
    .map((item) => {
      const e = (item ?? {}) as Record<string, unknown>;
      return {
        claim: typeof e.claim === "string" ? e.claim.trim().slice(0, MAX_FIELD) : "",
        evidence: typeof e.evidence === "string" ? e.evidence.trim().slice(0, MAX_FIELD) : "",
      };
    })
    .filter((item) => item.claim || item.evidence);

  // A claim with no support behind it is exactly what this tool exists to stop.
  const unsupported = evidence.filter((item) => item.claim && !item.evidence);
  if (unsupported.length > 0) {
    fail(
      "evidence",
      `${unsupported.length} claim(s) have nothing supporting them. Add the specific thing that happened, or remove the claim.`,
    );
  }

  // A reluctant or mixed letter with no reservations stated is almost always a
  // form filled in without reading it, and it produces a letter that cannot
  // possibly read as lukewarm.
  if ((strengthBand === "reluctant" || strengthBand === "mixed") && !reservations) {
    fail(
      "reservations",
      "You chose a band that is not a clear recommendation, but stated no reservations. Say what holds you back; the letter cannot read as measured without it.",
    );
  }

  if (errors.length > 0) return { ok: false, errors, fieldErrors };

  return {
    ok: true,
    value: {
      writerName,
      writerEmail,
      writerRole,
      subjectName,
      subjectRole,
      relationship,
      relationshipDurationMonths,
      purpose,
      purposeOther: purposeOther || undefined,
      strengthBand,
      evidence,
      reservations,
      toneNotes: toneNotes || undefined,
      lengthPreference,
      templateId: typeof raw.templateId === "string" ? raw.templateId : undefined,
    },
  };
}
