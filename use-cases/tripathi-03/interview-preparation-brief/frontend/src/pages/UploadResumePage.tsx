import { Link } from "react-router-dom";

import { DragDropUpload } from "@/components/upload/DragDropUpload";
import { WizardStepper } from "@/components/stepper/WizardStepper";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useWizard } from "@/context/WizardContext";

export function UploadResumePage() {
  const { draft, setResume, isResumeReady } = useWizard();

  return (
    <div className="space-y-2">
      <WizardStepper currentId="resume" />
      <Card>
        <CardHeader>
          <CardTitle>Upload Resume</CardTitle>
          <CardDescription>
            Drop your PDF or DOCX resume. We’ll parse it and index evidence for grounded answers.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <DragDropUpload
            value={draft.resumeFile}
            fileName={draft.resumeFileName}
            onChange={setResume}
            label="Upload your resume"
          />
          <div className="flex justify-end gap-3">
            <Link to="/job-description">
              <Button disabled={!isResumeReady && !draft.resumeFile}>Continue</Button>
            </Link>
          </div>
          {!draft.resumeFile && draft.resumeFileName && (
            <p className="text-sm text-warning">
              Please re-select “{draft.resumeFileName}” — file handles can’t be restored after refresh.
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
