import { useWizard } from "@/context/WizardContext";
import { ProgressStepper, type StepperStep } from "@/components/stepper/ProgressStepper";

export function WizardStepper({ currentId }: { currentId: string }) {
  const { isResumeReady, isJdReady, isCompanyReady } = useWizard();

  const steps: StepperStep[] = [
    { id: "resume", label: "Upload Resume", href: "/upload", done: isResumeReady },
    {
      id: "jd",
      label: "Job Description",
      href: "/job-description",
      done: isJdReady,
    },
    {
      id: "company",
      label: "Company Search",
      href: "/company",
      done: isCompanyReady,
    },
  ];

  return <ProgressStepper steps={steps} currentId={currentId} />;
}
