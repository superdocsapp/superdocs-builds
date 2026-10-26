import { Routes, Route } from "react-router-dom";
import { Layout } from "./components/Layout";
import { ReviewPage } from "./pages/ReviewPage";
import { DocumentsPage } from "./pages/DocumentsPage";
import { RunLogsPage } from "./pages/RunLogsPage";

export function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<ReviewPage />} />
        <Route path="documents" element={<DocumentsPage />} />
        <Route path="runs/:runId/logs" element={<RunLogsPage />} />
      </Route>
    </Routes>
  );
}