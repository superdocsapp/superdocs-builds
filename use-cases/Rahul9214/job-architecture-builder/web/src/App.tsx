import { Navigate, Route, Routes } from "react-router-dom";
import { CorpusProvider } from "./corpus";
import { AppShell } from "./layout/AppShell";
import { ArchitecturePage } from "./pages/ArchitecturePage";
import { ExceptionsPage } from "./pages/ExceptionsPage";
import { ExportPage } from "./pages/ExportPage";
import { FrameworkPage } from "./pages/FrameworkPage";
import { ImpactPage } from "./pages/ImpactPage";
import { OverviewPage } from "./pages/OverviewPage";
import { ProfilesPage } from "./pages/ProfilesPage";
import { ReviewPage } from "./pages/ReviewPage";
import { SourcesPage } from "./pages/SourcesPage";

export function App() {
  return (
    <CorpusProvider>
      <Routes>
        <Route element={<AppShell />}>
          <Route path="/" element={<OverviewPage />} />
          <Route path="/sources" element={<SourcesPage />} />
          <Route path="/architecture" element={<ArchitecturePage />} />
          <Route path="/exceptions" element={<ExceptionsPage />} />
          <Route path="/framework" element={<FrameworkPage />} />
          <Route path="/profiles" element={<ProfilesPage />} />
          <Route path="/impact" element={<ImpactPage />} />
          <Route path="/review" element={<ReviewPage />} />
          <Route path="/export" element={<ExportPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </CorpusProvider>
  );
}
