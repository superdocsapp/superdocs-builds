import { Link } from "react-router-dom";

import { RichTextEditor } from "@/components/editor/RichTextEditor";
import { WizardStepper } from "@/components/stepper/WizardStepper";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useWizard } from "@/context/WizardContext";

export function JobDescriptionPage() {
  const { draft, setJobDescription, isJdReady, isResumeReady } = useWizard();

  return (
    <div className="space-y-2">
      <WizardStepper currentId="jd" />
      <Card>
        <CardHeader>
          <CardTitle>Paste Job Description</CardTitle>
          <CardDescription>
            Paste the JD or type it here. Formatting is optional — plain text works too.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <RichTextEditor
            value={draft.jobDescriptionHtml}
            onChange={setJobDescription}
          />
          <div className="flex flex-wrap justify-between gap-3">
            <Link to="/upload">
              <Button variant="outline">Back</Button>
            </Link>
            <Link to="/company">
              <Button disabled={!isJdReady || (!isResumeReady && !draft.resumeFile)}>
                Continue
              </Button>
            </Link>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
