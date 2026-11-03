import { useEffect, useState } from "react";
import Sidebar from "./components/Sidebar.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import Documents from "./pages/Documents.jsx";
import FileDetail from "./pages/FileDetail.jsx";
import ReviewQueuePage from "./pages/ReviewQueue.jsx";
import Templates from "./pages/Templates.jsx";
import { api, getApiKey, setApiKey, AuthError } from "./api.js";

export default function App() {
  const [page, setPage] = useState("dashboard");
  const [openFileId, setOpenFileId] = useState(null);
  const [connected, setConnected] = useState(true);
  const [needsKey, setNeedsKey] = useState(false);
  const [pendingCount, setPendingCount] = useState(0);
  const [seeding, setSeeding] = useState(false);
  const [keyDraft, setKeyDraft] = useState(getApiKey());

  const refreshCounts = () => {
    api
      .reviews()
      .then((r) => {
        setConnected(true);
        setNeedsKey(false);
        setPendingCount(r.pending.length);
      })
      .catch((e) => {
        if (e instanceof AuthError) {
          setNeedsKey(true);
        } else {
          setConnected(false);
        }
      });
  };

  useEffect(() => {
    refreshCounts();
    const id = setInterval(refreshCounts, 8000);
    return () => clearInterval(id);
  }, [page, openFileId, seeding]);

  const openFile = (fileId) => {
    setOpenFileId(fileId);
    setPage("file-detail");
  };

  const seedDemo = async () => {
    setSeeding(true);
    try {
      await api.seedDemo();
    } catch {
      /* already seeded, disabled in this deployment, or no fake client
         -- either way, refresh and let the page reflect real state. */
    } finally {
      setSeeding(false);
    }
  };

  const saveKey = (e) => {
    e.preventDefault();
    setApiKey(keyDraft.trim());
    refreshCounts();
  };

  if (needsKey) {
    return (
      <div className="shell" style={{ alignItems: "center", justifyContent: "center" }}>
        <form className="ledger-card" style={{ maxWidth: 380, width: "100%" }} onSubmit={saveKey}>
          <h2 style={{ fontFamily: "var(--font-display)", marginTop: 0 }}>API key required</h2>
          <p style={{ fontSize: 13, color: "#5a5346" }}>
            This deployment requires an API key. Enter the key issued for this workflow's
            <code style={{ margin: "0 4px" }}>WORKFLOW_API_KEYS</code> — it's kept in this tab's
            session storage only, never sent anywhere but this API.
          </p>
          <input
            className="search-input"
            style={{ width: "100%", marginBottom: 12, color: "var(--ink-on-paper)", background: "#fff" }}
            type="password"
            placeholder="API key"
            value={keyDraft}
            onChange={(e) => setKeyDraft(e.target.value)}
            autoFocus
          />
          <button className="btn btn-primary" type="submit">
            Connect
          </button>
        </form>
      </div>
    );
  }

  let content;
  if (page === "dashboard") {
    content = <Dashboard onOpenFile={openFile} onSeedDemo={seedDemo} seeding={seeding} />;
  } else if (page === "documents") {
    content = <Documents onOpenFile={openFile} />;
  } else if (page === "file-detail") {
    content = <FileDetail fileId={openFileId} onBack={() => setPage("documents")} onDecided={refreshCounts} />;
  } else if (page === "review") {
    content = <ReviewQueuePage onOpenFile={openFile} onDecided={refreshCounts} />;
  } else if (page === "templates") {
    content = <Templates />;
  }

  return (
    <div className="shell">
      <Sidebar
        active={page === "file-detail" ? "documents" : page}
        onNavigate={setPage}
        counts={{ pendingReviews: pendingCount }}
        connected={connected}
      />
      <main className="main">{content}</main>
    </div>
  );
}
