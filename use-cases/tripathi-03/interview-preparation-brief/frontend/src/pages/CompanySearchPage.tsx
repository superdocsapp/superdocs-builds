import { FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Building2, Search } from "lucide-react";

import { LoadingOverlay } from "@/components/loading/LoadingSpinner";
import { WizardStepper } from "@/components/stepper/WizardStepper";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useWizard } from "@/context/WizardContext";
import { useCreateBrief, useUploadDocuments } from "@/hooks/useBriefApi";
import { saveHistoryItem } from "@/lib/history";
import { stripHtml } from "@/lib/utils";

export function CompanySearchPage() {
  const navigate = useNavigate();
  const { draft, setCompany, isResumeReady, isJdReady, resetDraft } = useWizard();
  const uploadMutation = useUploadDocuments();
  const createBriefMutation = useCreateBrief();
  const [error, setError] = useState<string | null>(null);

  const loading = uploadMutation.isPending || createBriefMutation.isPending;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);

    if (!draft.resumeFile) {
      setError("Please re-upload your resume on the previous step.");
      return;
    }
    const jdText = draft.jobDescriptionText.trim() || stripHtml(draft.jobDescriptionHtml);
    if (jdText.length < 40) {
      setError("Job description is too short.");
      return;
    }
    if (!draft.companyName.trim()) {
      setError("Company name is required.");
      return;
    }

    try {
      const form = new FormData();
      form.append("resume", draft.resumeFile);
      form.append("company_name", draft.companyName.trim());
      form.append("job_description_text", jdText);
      if (draft.companyUrl.trim()) form.append("company_url", draft.companyUrl.trim());

      const uploaded = await uploadMutation.mutateAsync(form);
      const brief = await createBriefMutation.mutateAsync(uploaded.session_id);

      saveHistoryItem({
        brief_id: brief.brief_id,
        session_id: brief.session_id,
        company_name: uploaded.company_name,
        status: brief.status,
        created_at: new Date().toISOString(),
      });

      resetDraft();
      navigate(`/reports/${brief.brief_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to generate brief");
    }
  }

  return (
    <div className="space-y-2">
      {loading && <LoadingOverlay label="Uploading & starting LangGraph workflow…" />}
      <WizardStepper currentId="company" />
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Building2 className="h-5 w-5 text-primary" />
            Company Search
          </CardTitle>
          <CardDescription>
            Enter the target company. We’ll research public context for overview and company-specific questions.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={onSubmit} className="space-y-5">
            <div>
              <Label htmlFor="companyName">Company name</Label>
              <div className="relative">
                <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  id="companyName"
                  className="pl-9"
                  placeholder="e.g. Stripe, Notion, Infosys"
                  value={draft.companyName}
                  onChange={(e) => setCompany(e.target.value, draft.companyUrl)}
                  required
                />
              </div>
            </div>

            <div>
              <Label htmlFor="companyUrl">Company website (optional)</Label>
              <Input
                id="companyUrl"
                placeholder="https://company.com"
                value={draft.companyUrl}
                onChange={(e) => setCompany(draft.companyName, e.target.value)}
              />
            </div>

            {error && <p className="text-sm text-destructive">{error}</p>}

            <div className="flex flex-wrap justify-between gap-3">
              <Link to="/job-description">
                <Button type="button" variant="outline">
                  Back
                </Button>
              </Link>
              <Button
                type="submit"
                disabled={
                  loading ||
                  !draft.companyName.trim() ||
                  !isJdReady ||
                  (!isResumeReady && !draft.resumeFile)
                }
              >
                Generate Interview Report
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
