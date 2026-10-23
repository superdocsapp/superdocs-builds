import { CheckCircle2, CircleHelp, XCircle } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

type QuestionCardProps = {
  index?: number;
  question: string;
  answer?: string;
  hasEvidence?: boolean;
  evidenceSpans?: string[];
  variant?: "question" | "answer" | "company";
  className?: string;
};

export function QuestionCard({
  index,
  question,
  answer,
  hasEvidence,
  evidenceSpans = [],
  variant = "question",
  className,
}: QuestionCardProps) {
  return (
    <Card className={cn("animate-fade-in", className)}>
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between gap-3">
          <CardTitle className="text-base font-semibold leading-snug">
            {typeof index === "number" ? `${index}. ` : ""}
            {question}
          </CardTitle>
          {variant === "answer" && (
            <Badge variant={hasEvidence ? "success" : "warning"}>
              {hasEvidence ? (
                <span className="inline-flex items-center gap-1">
                  <CheckCircle2 className="h-3 w-3" /> Evidence
                </span>
              ) : (
                <span className="inline-flex items-center gap-1">
                  <XCircle className="h-3 w-3" /> No evidence
                </span>
              )}
            </Badge>
          )}
          {variant === "company" && (
            <Badge variant="outline">
              <span className="inline-flex items-center gap-1">
                <CircleHelp className="h-3 w-3" /> Company
              </span>
            </Badge>
          )}
        </div>
      </CardHeader>
      {(answer || evidenceSpans.length > 0) && (
        <CardContent className="space-y-3">
          {answer && (
            <p className="whitespace-pre-wrap text-sm leading-relaxed text-foreground/90">{answer}</p>
          )}
          {evidenceSpans.length > 0 && (
            <div className="rounded-lg bg-muted/50 p-3">
              <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Resume evidence
              </p>
              <ul className="space-y-1 text-xs text-muted-foreground">
                {evidenceSpans.map((span) => (
                  <li key={span.slice(0, 48)} className="line-clamp-3">
                    “{span}”
                  </li>
                ))}
              </ul>
            </div>
          )}
        </CardContent>
      )}
    </Card>
  );
}
