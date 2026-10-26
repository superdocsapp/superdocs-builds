from .finder import FindingOutput


class JudgeSemantic:
    def __init__(self, llm):
        self.llm = llm

    def judge(self, finding: FindingOutput) -> FindingOutput:
        finding.judge_verdict = "approved"
        return finding