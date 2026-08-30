import clsx from "clsx";
import type { VerificationStatus } from "../../types/domain";

/**
 * The cross-cutting verification grammar used for claims, requirements, and
 * risk factors: a SOLID dot means something has been evaluated, and the hue
 * carries the result. A HOLLOW ring means it hasn't been evaluated yet — the
 * shape itself says "unknown," independent of color. This is deliberately
 * used everywhere a claim or finding's trust state is shown, so a hollow
 * ring always means the same thing across the whole product.
 */
const DOT_STYLES: Record<VerificationStatus, { solid: boolean; className: string }> = {
  Verified: { solid: true, className: "bg-verified" },
  "Partially Supported": { solid: true, className: "bg-warning" },
  Contradicted: { solid: true, className: "bg-critical" },
  "Needs Review": { solid: false, className: "border-warning" },
  Unverified: { solid: false, className: "border-neutral" },
};

export function VerificationDot({ status, size = "md" }: { status: VerificationStatus; size?: "sm" | "md" }) {
  const style = DOT_STYLES[status];
  const dimension = size === "sm" ? "h-2 w-2" : "h-2.5 w-2.5";
  return (
    <span
      role="img"
      aria-label={status}
      title={status}
      className={clsx(
        "inline-block shrink-0 rounded-full",
        dimension,
        style.solid ? style.className : clsx("border-2 border-dashed bg-transparent", style.className),
      )}
    />
  );
}
