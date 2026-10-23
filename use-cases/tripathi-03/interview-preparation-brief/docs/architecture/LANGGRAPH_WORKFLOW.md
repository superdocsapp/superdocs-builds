# LangGraph Workflow

## Chain

```
ResumeParser
    ↓
JDParser
    ↓
CompanyResearch
    ↓
SkillGapAnalysis
    ↓
QuestionGeneration
    ↓
AnswerGeneration
    ↓
InterviewPreparationReport
```

## Shared state

All nodes read/write `BriefState` (`app/agents/state.py`).

## Node contract

Each node implements `BaseNode`:

1. **Input** — Pydantic model (`app/agents/contracts.py`)
2. **Validation** — `validate_input` / `validate_output`
3. **Execute** — business logic
4. **Output** — Pydantic model merged back into state

## Anti-hallucination

`AnswerGeneration` retrieves **resume-only** chunks.

If evidence is missing:

```
No evidence found.
```

Never fabricate resume facts.

## Files

| File | Role |
|------|------|
| `agents/base.py` | BaseNode contract |
| `agents/contracts.py` | Input/Output models |
| `agents/state.py` | Shared TypedDict state |
| `agents/graph.py` | LangGraph wiring |
| `agents/nodes/*.py` | Independent node implementations |
| `agents/runner.py` | Background execution + persistence |
