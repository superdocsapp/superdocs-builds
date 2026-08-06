import { useEffect, useMemo } from "react";
import { Link, useParams } from "react-router-dom";

import { SkillGapCharts } from "@/components/charts/SkillGapCharts";
import { ReportExportButtons } from "@/components/export/ReportExportButtons";
import { SuperDocsExportPanel } from "@/components/export/SuperDocsExportPanel";
import { LoadingSpinner, SkeletonBlock } from "@/components/loading/LoadingSpinner";
import { QuestionCard } from "@/components/questions/QuestionCard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { useBrief, useBriefStatus } from "@/hooks/useBriefApi";
import { upsertHistoryFromBrief, updateHistoryStatus } from "@/lib/history";
import { formatDate } from "@/lib/utils";

const STEP_ORDER = [
  "ResumeParser",
  "JDParser",
  "CompanyResearch",
  "SkillGapAnalysis",
  "QuestionGeneration",
  "AnswerGeneration",
  "InterviewPreparationReport",
];

function stepProgress(step?: string | null, status?: string) {
  if (status === "completed") return 100;
  if (!step) return 8;
  const idx = STEP_ORDER.findIndex((s) => s.toLowerCase() === step.toLowerCase());
  if (idx < 0) return 15;
  return Math.round(((idx + 1) / STEP_ORDER.length) * 100);
}

export function InterviewReportPage() {
  const { briefId } = useParams<{ briefId: string }>();
  const statusQuery = useBriefStatus(briefId);
  const briefQuery = useBrief(briefId);

  const status = statusQuery.data;
  const brief = briefQuery.data;
  const content = brief?.content;

  useEffect(() => {
    if (status?.status === "completed") {
      void briefQuery.refetch();
    }
  }, [status?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (status?.status) updateHistoryStatus(status.brief_id, status.status);
  }, [status?.status, status?.brief_id]);

  useEffect(() => {
    if (brief?.status === "completed") upsertHistoryFromBrief(brief);
  }, [brief]);

  const progress = useMemo(
    () => stepProgress(status?.current_step, status?.status || brief?.status),
    [status?.current_step, status?.status, brief?.status],
  );

  if (statusQuery.isError || briefQuery.isError) {
    return (
      <div className="space-y-4">
        <h1 className="font-display text-3xl font-bold">Interview Report</h1>
        <p className="text-destructive">
          {(statusQuery.error || briefQuery.error)?.message || "Failed to load brief"}
        </p>
        <Link to="/history">
          <Button variant="outline">Back to history</Button>
        </Link>
      </div>
    );
  }

  const running =
    !brief?.content &&
    status?.status !== "failed" &&
    brief?.status !== "failed";

  if (running) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="font-display text-3xl font-bold">Generating report</h1>
          <p className="mt-1 text-muted-foreground">
            Current step: {status?.current_step || "queued"}
          </p>
        </div>
        <Progress value={progress} />
        <LoadingSpinner label="LangGraph is building your evidence-grounded brief…" />
        <div className="grid gap-3 sm:grid-cols-2">
          <SkeletonBlock className="h-28" />
          <SkeletonBlock className="h-28" />
          <SkeletonBlock className="h-40 sm:col-span-2" />
        </div>
      </div>
    );
  }

  if (status?.status === "failed" || brief?.status === "failed") {
    return (
      <div className="space-y-4">
        <h1 className="font-display text-3xl font-bold">Generation failed</h1>
        <p className="text-destructive">{status?.error || "Unknown error"}</p>
        <Link to="/upload">
          <Button>Try again</Button>
        </Link>
      </div>
    );
  }

  if (!content || !brief) {
    return <LoadingSpinner label="Loading report…" />;
  }

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <Badge variant="success">Completed</Badge>
            <span className="text-xs text-muted-foreground">{formatDate(brief.created_at)}</span>
          </div>
          <h1 className="font-display text-3xl font-bold sm:text-4xl">{brief.company_name}</h1>
          <p className="mt-1 text-muted-foreground">Interview Preparation Report</p>
        </div>
        <div className="flex flex-col items-stretch gap-2 sm:items-end">
          {briefId && <ReportExportButtons briefId={briefId} />}
          <Link to="/upload">
            <Button variant="outline">New brief</Button>
          </Link>
        </div>
      </div>

      {briefId && <SuperDocsExportPanel briefId={briefId} />}

      <div id="interview-report" className="space-y-8 rounded-xl bg-background p-1">
        <section className="space-y-3">
          <h2 className="font-display text-2xl font-bold">Company Overview</h2>
          <p className="whitespace-pre-wrap text-foreground/90">{content.company_overview || "—"}</p>
        </section>

        <section className="space-y-3">
          <h2 className="font-display text-2xl font-bold">Role Summary</h2>
          <p className="whitespace-pre-wrap text-foreground/90">{content.role_summary || "—"}</p>
        </section>

        <section className="space-y-4">
          <h2 className="font-display text-2xl font-bold">Skill Gap Analysis</h2>
          <SkillGapCharts
            matching={content.matching_skills}
            missing={content.missing_skills}
            required={content.required_skills}
          />
          <div className="grid gap-4 md:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Matching skills</CardTitle>
              </CardHeader>
              <CardContent>
                <ul className="space-y-2 text-sm">
                  {content.matching_skills.length === 0 && <li>—</li>}
                  {content.matching_skills.map((s) => (
                    <li key={s.name}>
                      <span className="font-semibold">{s.name}</span>
                      {s.evidence ? (
                        <span className="text-muted-foreground"> — {s.evidence}</span>
                      ) : null}
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Missing skills</CardTitle>
              </CardHeader>
              <CardContent>
                <ul className="space-y-2 text-sm">
                  {content.missing_skills.length === 0 && <li>—</li>}
                  {content.missing_skills.map((s) => (
                    <li key={s.name}>{s.name}</li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          </div>
        </section>

        <section className="space-y-3">
          <h2 className="font-display text-2xl font-bold">Resume Improvements</h2>
          <ul className="list-disc space-y-1 pl-5 text-sm">
            {content.resume_improvements.length === 0 && <li>—</li>}
            {content.resume_improvements.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </section>

        <section className="space-y-4">
          <h2 className="font-display text-2xl font-bold">Likely Interview Questions</h2>
          <div className="grid gap-3">
            {content.likely_interview_questions.map((q, i) => (
              <QuestionCard key={q} index={i + 1} question={q} />
            ))}
          </div>
        </section>

        <section className="space-y-4">
          <h2 className="font-display text-2xl font-bold">Evidence-Backed Answers</h2>
          <div className="grid gap-3">
            {content.evidence_backed_answers.map((a, i) => (
              <QuestionCard
                key={a.question}
                index={i + 1}
                question={a.question}
                answer={a.answer}
                hasEvidence={a.has_evidence}
                evidenceSpans={a.evidence_spans}
                variant="answer"
              />
            ))}
          </div>
        </section>

        <section className="space-y-3">
          <h2 className="font-display text-2xl font-bold">Technical Topics to Revise</h2>
          <div className="flex flex-wrap gap-2">
            {content.technical_topics.length === 0 && <span>—</span>}
            {content.technical_topics.map((topic) => (
              <Badge key={topic} variant="outline">
                {topic}
              </Badge>
            ))}
          </div>
        </section>

        <section className="space-y-4">
          <h2 className="font-display text-2xl font-bold">Company-Specific Questions</h2>
          <div className="grid gap-3">
            {content.company_specific_questions.map((q, i) => (
              <QuestionCard key={q} index={i + 1} question={q} variant="company" />
            ))}
          </div>
        </section>

        <section className="space-y-4">
          <h2 className="font-display text-2xl font-bold">STAR Behavioural Answers</h2>
          <div className="grid gap-3">
            {content.star_answers.map((a) => (
              <Card key={a.question}>
                <CardHeader>
                  <CardTitle className="text-base">{a.question}</CardTitle>
                </CardHeader>
                <CardContent className="space-y-2 text-sm">
                  {!a.has_evidence ? (
                    <p>{a.note || "No evidence found."}</p>
                  ) : (
                    <>
                      <p>
                        <strong>Situation:</strong> {a.situation}
                      </p>
                      <p>
                        <strong>Task:</strong> {a.task}
                      </p>
                      <p>
                        <strong>Action:</strong> {a.action}
                      </p>
                      <p>
                        <strong>Result:</strong> {a.result}
                      </p>
                    </>
                  )}
                </CardContent>
              </Card>
            ))}
          </div>
        </section>

        <section className="space-y-4">
          <h2 className="font-display text-2xl font-bold">30-60-90 Day Roadmap</h2>
          <div className="grid gap-4 md:grid-cols-3">
            {content.roadmap.map((phase) => (
              <Card key={phase.phase}>
                <CardHeader>
                  <CardTitle className="text-base">Day {phase.phase}</CardTitle>
                </CardHeader>
                <CardContent className="space-y-3 text-sm">
                  <div>
                    <p className="font-semibold">Goals</p>
                    <ul className="mt-1 list-disc pl-4">
                      {phase.goals.map((g) => (
                        <li key={g}>{g}</li>
                      ))}
                    </ul>
                  </div>
                  <div>
                    <p className="font-semibold">Actions</p>
                    <ul className="mt-1 list-disc pl-4">
                      {phase.actions.map((a) => (
                        <li key={a}>{a}</li>
                      ))}
                    </ul>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
