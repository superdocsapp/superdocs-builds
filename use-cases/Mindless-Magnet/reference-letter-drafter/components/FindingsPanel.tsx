"use client";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { BANDS } from "@/lib/calibration/lexicon";
import type { AuditReport, CalibrationFinding } from "@/lib/types";

/**
 * The calibration audit, shown next to the proposed changes so the writer sees
 * both before the gate opens.
 *
 * Two things this panel is careful about. It never says "looks good" when a
 * check did not run, because a skipped check reading as a pass is how a
 * calibration tool becomes decoration. And it never offers to fix anything
 * automatically: the writer is the one signing the letter.
 */

const KIND_LABEL: Record<CalibrationFinding["kind"], string> = {
  band_violation: "Tone",
  unsupported_claim: "Unsupported",
  dropped_reservation: "Omission",
  injected_instruction: "Untrusted input",
};

function FindingRow({ finding }: { finding: CalibrationFinding }) {
  const tone =
    finding.severity === "high"
      ? "border-l-destructive"
      : finding.severity === "medium"
        ? "border-l-amber-500"
        : "border-l-muted-foreground/40";

  return (
    <li className={`border-l-2 py-3 pl-4 ${tone}`}>
      <div className="mb-1 flex flex-wrap items-center gap-2">
        <Badge variant="outline" className="text-[10px] uppercase tracking-wide">
          {KIND_LABEL[finding.kind]}
        </Badge>
        <span className="text-sm font-medium">{finding.title}</span>
      </div>
      <p className="text-muted-foreground text-sm">{finding.detail}</p>
      {finding.excerpt && (
        <p className="text-muted-foreground mt-2 border-l-2 border-muted pl-3 text-sm italic">
          {finding.excerpt}
        </p>
      )}
    </li>
  );
}

function CheckLine({ label, state }: { label: string; state: string }) {
  const ok = state === "ran";
  return (
    <li className="flex items-center justify-between gap-4 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className={ok ? "text-muted-foreground" : "text-amber-600 dark:text-amber-500"}>
        {ok ? "ran" : state === "unavailable" ? "not configured" : "failed"}
      </span>
    </li>
  );
}

export function FindingsPanel({
  report,
  loading,
}: {
  report: AuditReport | null;
  loading: boolean;
}) {
  if (loading) {
    return (
      <Card>
        <CardContent className="text-muted-foreground py-4 text-sm">
          Checking the draft against the band you declared…
        </CardContent>
      </Card>
    );
  }

  if (!report) return null;

  const verifierRan = report.checks.verifier === "ran";
  const clean = report.findings.length === 0;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base font-medium">
          Calibration check
          {report.inferredBand && (
            <span className="text-muted-foreground ml-2 text-sm font-normal">
              you declared {report.declaredBand}; a second reader read it as {report.inferredBand}
            </span>
          )}
        </CardTitle>
      </CardHeader>

      <CardContent className="flex flex-col gap-4">
        {clean ? (
          <p className="text-sm">
            {verifierRan
              ? `No findings. The letter reads consistently with "${BANDS[report.declaredBand].label}".`
              : `No findings from the checks that ran. The second-reader check did not run, so this is not a clean bill of health.`}
          </p>
        ) : (
          <ul className="flex flex-col gap-1">
            {report.findings.map((finding) => (
              <FindingRow key={finding.id} finding={finding} />
            ))}
          </ul>
        )}

        <div className="border-t pt-3">
          <p className="text-muted-foreground mb-2 text-xs uppercase tracking-wide">Checks performed</p>
          <ul className="flex flex-col gap-1">
            <CheckLine label="Banned phrases for this band" state={report.checks.lexicon} />
            <CheckLine label="Your reservations survived into the letter" state={report.checks.reservations} />
            <CheckLine label="Intake scanned for instructions aimed at the system" state={report.checks.injection} />
            <CheckLine label="Second reader inferred the band independently" state={report.checks.verifier} />
          </ul>
          {!verifierRan && report.verifierNote && (
            <p className="text-muted-foreground mt-2 text-xs">{report.verifierNote}</p>
          )}
          <p className="text-muted-foreground mt-3 text-xs">
            Nothing here has been changed for you. These are findings to act on: reject the changes that
            carry them, or approve them if you disagree.
          </p>
        </div>
      </CardContent>
    </Card>
  );
}
