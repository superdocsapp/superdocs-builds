/**
 * @file src/App.tsx
 * @description Application shell: navbar with dark-mode toggle plus the route table.
 * @flow theme preference read from localStorage on mount and applied to <html> ->
 *   routes render the five pages
 * @dependencies react-router-dom, lucide-react
 */
import { useEffect, useState } from "react";
import { Link, Route, Routes, useLocation } from "react-router-dom";
import { FileText, Moon, Sun, Plus } from "lucide-react";
import clsx from "clsx";
import Dashboard from "./pages/Dashboard";
import Upload from "./pages/Upload";
import RunDetail from "./pages/RunDetail";
import ApprovalGate from "./pages/ApprovalGate";
import DigestPreview from "./pages/DigestPreview";

export default function App() {
  const [dark, setDark] = useState(() => localStorage.getItem("vd-theme") === "dark");
  const location = useLocation();

  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    localStorage.setItem("vd-theme", dark ? "dark" : "light");
  }, [dark]);

  return (
    <div className="min-h-screen">
      <nav className="sticky top-0 z-20 backdrop-blur-md bg-white/80 dark:bg-slate-950/80 border-b border-slate-200 dark:border-slate-800">
        <div className="max-w-6xl mx-auto px-6 h-14 flex items-center gap-6">
          <Link to="/" className="flex items-center gap-2 font-semibold">
            <FileText className="w-5 h-5 text-accent" />
            VocDigest
          </Link>
          <Link
            to="/"
            className={clsx("text-sm transition hover:text-accent",
              location.pathname === "/" ? "text-accent font-medium" : "text-slate-600 dark:text-slate-400")}
          >
            Runs
          </Link>
          <div className="flex-1" />
          <Link to="/upload" className="btn-primary text-sm py-1.5">
            <Plus className="w-4 h-4" /> New run
          </Link>
          <button
            onClick={() => setDark((v) => !v)}
            className="p-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 transition"
            aria-label="Toggle dark mode"
          >
            {dark ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
          </button>
        </div>
      </nav>

      <main className="max-w-6xl mx-auto px-6 py-8">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/upload" element={<Upload />} />
          <Route path="/runs/:runId" element={<RunDetail />} />
          <Route path="/runs/:runId/approve" element={<ApprovalGate />} />
          <Route path="/runs/:runId/digest" element={<DigestPreview />} />
        </Routes>
      </main>
    </div>
  );
}
