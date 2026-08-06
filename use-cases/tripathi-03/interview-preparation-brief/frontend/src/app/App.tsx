import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Navigate, Route, Routes, useParams } from "react-router-dom";

import { AppShell } from "@/components/layout/AppShell";
import { WizardProvider } from "@/context/WizardContext";
import { CompanySearchPage } from "@/pages/CompanySearchPage";
import { HistoryPage } from "@/pages/HistoryPage";
import { HomePage } from "@/pages/HomePage";
import { InterviewReportPage } from "@/pages/InterviewReportPage";
import { JobDescriptionPage } from "@/pages/JobDescriptionPage";
import { UploadResumePage } from "@/pages/UploadResumePage";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

function LegacyBriefRedirect() {
  const { briefId } = useParams<{ briefId: string }>();
  return <Navigate to={`/reports/${briefId}`} replace />;
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <WizardProvider>
        <AppShell>
          <Routes>
            <Route path="/" element={<HomePage />} />
            <Route path="/upload" element={<UploadResumePage />} />
            <Route path="/job-description" element={<JobDescriptionPage />} />
            <Route path="/company" element={<CompanySearchPage />} />
            <Route path="/reports/:briefId" element={<InterviewReportPage />} />
            <Route path="/history" element={<HistoryPage />} />
            <Route path="/briefs/:briefId" element={<LegacyBriefRedirect />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </AppShell>
      </WizardProvider>
    </QueryClientProvider>
  );
}
