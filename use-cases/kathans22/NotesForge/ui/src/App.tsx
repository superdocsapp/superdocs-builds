import { useState } from "react";
import { Amendments } from "./screens/Amendments";
import { Clients } from "./screens/Clients";
import { Coverage } from "./screens/Coverage";
import { Packs } from "./screens/Packs";
import { Run } from "./screens/Run";
import { useArtifacts } from "./useArtifacts";

const TABS = ["COVERAGE", "CLIENTS", "PACKS", "AMENDMENTS", "RUN"] as const;
type Tab = (typeof TABS)[number];

export default function App() {
  const [tab, setTab] = useState<Tab>("COVERAGE");
  const { state: artifacts, reload } = useArtifacts();

  return (
    <>
      <header className="app-header">
        <h1>Meridian Advisory — Compliance Console</h1>
        <p className="app-subtitle">
          Reads the CLI's own run artifacts (state/*.json, out/). Every pack and notice is a draft for
          professional review, not a compliance certification.
        </p>
        <nav className="tab-bar" role="tablist">
          {TABS.map((t) => (
            <button key={t} type="button" role="tab" aria-selected={t === tab} onClick={() => setTab(t)}>
              {t}
            </button>
          ))}
        </nav>
      </header>

      <main className="app-main">
        {artifacts.status === "loading" && <p className="state-message">Loading run artifacts…</p>}
        {artifacts.status === "error" && (
          <p className="state-message error">
            {artifacts.message}
            <br />
            Run <code>npm run sync</code> in <code>ui/</code> after a compliance CLI command, then reload.
          </p>
        )}
        {artifacts.status === "ready" && (
          <>
            {tab === "COVERAGE" && <Coverage data={artifacts.data} reload={reload} />}
            {tab === "CLIENTS" && <Clients data={artifacts.data} reload={reload} />}
            {tab === "PACKS" && <Packs data={artifacts.data} reload={reload} />}
            {tab === "AMENDMENTS" && <Amendments data={artifacts.data} reload={reload} />}
            {tab === "RUN" && <Run data={artifacts.data} reload={reload} />}
          </>
        )}
      </main>
    </>
  );
}
