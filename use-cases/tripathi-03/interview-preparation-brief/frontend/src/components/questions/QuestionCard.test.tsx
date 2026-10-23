import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { QuestionCard } from "@/components/questions/QuestionCard";
import { ProgressStepper } from "@/components/stepper/ProgressStepper";

describe("QuestionCard", () => {
  it("shows evidence badge for answered questions", () => {
    render(
      <QuestionCard
        index={1}
        question="Explain FastAPI DI"
        answer="Use Depends()"
        hasEvidence
        evidenceSpans={["Built payment APIs with FastAPI"]}
        variant="answer"
      />,
    );
    expect(screen.getByText(/Explain FastAPI DI/i)).toBeInTheDocument();
    expect(screen.getByText(/Evidence/i)).toBeInTheDocument();
    expect(screen.getByText(/Built payment APIs with FastAPI/i)).toBeInTheDocument();
  });

  it("shows no-evidence badge when hasEvidence is false", () => {
    render(
      <QuestionCard
        question="Design a rate limiter"
        answer="No evidence found."
        hasEvidence={false}
        variant="answer"
      />,
    );
    expect(screen.getByText(/No evidence/i)).toBeInTheDocument();
  });
});

describe("ProgressStepper", () => {
  it("renders wizard steps with links", () => {
    render(
      <MemoryRouter>
        <ProgressStepper
          currentId="jd"
          steps={[
            { id: "resume", label: "Upload Resume", href: "/upload", done: true },
            { id: "jd", label: "Job Description", href: "/job-description" },
            { id: "company", label: "Company Search", href: "/company" },
          ]}
        />
      </MemoryRouter>,
    );
    expect(screen.getByText("Job Description")).toBeInTheDocument();
    expect(screen.getByText("Upload Resume")).toBeInTheDocument();
    expect(screen.getByText("Company Search")).toBeInTheDocument();
  });
});
