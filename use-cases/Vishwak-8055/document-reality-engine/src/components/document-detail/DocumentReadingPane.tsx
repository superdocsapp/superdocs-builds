import type { Claim, SDDocument } from "../../types/domain";
import { VerificationDot } from "../ui/VerificationDot";

export function DocumentReadingPane({ document, onSelectClaim }: { document: SDDocument; onSelectClaim: (claimId: string) => void }) {
  const sections = [...document.sections].sort((a, b) => a.order - b.order);

  return (
    <div className="rounded-md border border-line bg-paper-0 p-5 sm:p-6">
      {sections.map((section) => {
        const claims = section.claimIds
          .map((id) => document.claims.find((c) => c.id === id))
          .filter((c): c is Claim => Boolean(c));

        return (
          <div key={section.id} className="mb-8 last:mb-0">
            <h3 className="font-serif text-base font-semibold text-text-primary">{section.heading}</h3>
            <div className="mt-2 space-y-3 font-serif text-[15px] leading-relaxed text-text-secondary">
              {section.body.split("\n\n").map((paragraph, index) => (
                <p key={index}>{paragraph}</p>
              ))}
            </div>
            {claims.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-1.5 border-t border-dashed border-line pt-3">
                {claims.map((claim) => (
                  <button
                    key={claim.id}
                    onClick={() => onSelectClaim(claim.id)}
                    className="flex max-w-[280px] items-center gap-1.5 rounded-md border border-line bg-paper-50 px-2 py-1 text-left text-xs text-text-secondary transition-colors hover:border-trust hover:bg-trust-soft hover:text-trust"
                  >
                    <VerificationDot status={claim.verificationStatus} size="sm" />
                    <span className="min-w-0 truncate">{claim.text}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
