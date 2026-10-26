from .finder import FindingOutput


class Proposer:
    def __init__(self, llm):
        self.llm = llm

    def propose_fix(self, finding: FindingOutput) -> FindingOutput:
        if not finding.proposed_old or not finding.proposed_new:
            finding.proposed_old = finding.evidence_quote or ""
            finding.proposed_new = finding.proposed_new or ""
        return finding