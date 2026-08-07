"""Optional CrewAI crew for the exhibit engine.

The whole build is automatable without any external AI (the deterministic
analyst in :mod:`proposals`), but when a CrewAI install *and* a model API key are
available, a two-agent crew takes over the analysis:

    OrderPlanner  — sequences the evidence pile to follow the brief's argument.
    CoverWriter   — writes each exhibit's "what it proves" cover line.

Everything is optional: ``available()`` reports whether the crew can run, and
the CLI only hands the CoverWriter to the analyst when it can.
"""

from __future__ import annotations

import os

from .proposals import CoverWriter


def available() -> bool:
    """True when crewai is installed and a model API key is configured."""
    if not _api_key():
        return False
    try:
        import crewai  # noqa: F401
    except ImportError:
        return False
    return True


def make_cover_writer(model: str | None = None) -> CoverWriter | None:
    """Build a CoverWriter that runs the CoverWriter agent, or None if unavailable."""
    key = _api_key()
    if not key:
        return None
    try:
        from crewai import Agent, Crew, LLM, Task
    except ImportError:
        return None

    llm = LLM(model=model or "gemini/gemini-2.5-flash", api_key=key)
    writer = Agent(
        role="Immigration paralegal cover-page writer",
        goal=(
            "Write one concise sentence stating what each exhibit proves, "
            "grounded only in the exhibit's own content."
        ),
        backstory=(
            "You draft the numbered cover pages for a visa support filing. Each "
            "cover page names the exhibit and states, in one sentence, what it "
            "establishes. You never invent facts not in the exhibit text."
        ),
        llm=llm,
        verbose=False,
    )
    crew = Crew(agents=[writer], tasks=[], verbose=False)  # tasks added per call

    def write(title: str, content: str) -> str:
        task = Task(
            description=(
                f"Exhibit title: {title}\n"
                f"Exhibit content:\n{content[:4000]}\n\n"
                "Write exactly one sentence of cover-page text stating what "
                "this exhibit proves. Start with 'Evidences ...' or "
                "'Establishes ...'."
            ),
            expected_output="One sentence of cover-page text.",
            agent=writer,
        )
        result = crew.kickoff(tasks=[task])
        return result.raw.strip() if result and result.raw else ""

    return write


def _api_key() -> str | None:
    """The model API key, from the obvious environment variables. Only used for
    the optional crew; the SuperDocs flow uses the SuperDocs key instead."""
    for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        val = os.environ.get(var)
        if val:
            return val
    return None
