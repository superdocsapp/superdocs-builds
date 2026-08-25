import { forwardRef } from "react";
import { CheckCircle2, PenLine } from "lucide-react";

import { formatTime } from "../domain";

/**
 * Reviewer sign-off.
 *
 * Approval is the human gate the whole workflow turns on, and an approval with
 * nobody's name on it is not much of a gate. The name entered here is recorded
 * in the audit trail and written into the ServiceNow work note alongside the
 * document checksum, so the export can be traced back to the person who
 * accepted it.
 *
 * Once signed, the field is replaced by the attribution rather than left
 * editable: this is a record of what happened, not a setting.
 */
export const SignOff = forwardRef<
  HTMLInputElement,
  {
    approved: boolean;
    approvedAt: string | null;
    checksum: string | null;
    disabled: boolean;
    onChange: (value: string) => void;
    reviewer: string;
    signedBy: string | null;
  }
>(function SignOff({ approved, approvedAt, checksum, disabled, onChange, reviewer, signedBy }, ref) {
  if (approved) {
    return (
      <div className="signoff signed">
        <span className="signoff-icon" aria-hidden="true">
          <CheckCircle2 size={15} />
        </span>
        <div>
          <span className="eyebrow">Signed off</span>
          <strong>{signedBy || "Unattributed"}</strong>
          <span className="signoff-meta">
            {approvedAt ? `at ${formatTime(approvedAt)}` : ""}
            {checksum ? ` · checksum ${checksum}` : ""}
          </span>
        </div>
      </div>
    );
  }

  return (
    <div className="signoff">
      <span className="signoff-icon" aria-hidden="true">
        <PenLine size={15} />
      </span>
      <div className="signoff-field">
        <label htmlFor="reviewer-name">Your name, for the record</label>
        <input
          autoComplete="name"
          disabled={disabled}
          id="reviewer-name"
          name="reviewer"
          onChange={(event) => onChange(event.target.value)}
          placeholder="e.g. A. Yendoti"
          ref={ref}
          spellCheck={false}
          type="text"
          value={reviewer}
        />
        <p>
          Recorded in the audit trail and written back to the ServiceNow change with the document
          checksum.
        </p>
      </div>
    </div>
  );
});
