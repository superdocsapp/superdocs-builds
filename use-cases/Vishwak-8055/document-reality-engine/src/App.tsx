import { BrowserRouter, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/layout/AppShell";
import { NotFoundPage } from "./components/layout/NotFoundPage";
import { Dashboard } from "./components/dashboard/Dashboard";
import { DocumentsPage } from "./components/documents/DocumentsPage";
import { DocumentDetailPage } from "./components/document-detail/DocumentDetailPage";
import { ReviewsPage } from "./components/reviews/ReviewsPage";
import { RiskRegisterPage } from "./components/risks/RiskRegisterPage";
import { AuditPage } from "./components/audit/AuditPage";
import { CommandCenterPage } from "./components/command-center/CommandCenterPage";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<Dashboard />} />
          <Route path="documents" element={<DocumentsPage />} />
          <Route path="documents/:documentId" element={<DocumentDetailPage />} />
          <Route path="documents/:documentId/:tab" element={<DocumentDetailPage />} />
          <Route path="reviews" element={<ReviewsPage />} />
          <Route path="risks" element={<RiskRegisterPage />} />
          <Route path="audit" element={<AuditPage />} />
          <Route path="command-center" element={<CommandCenterPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
