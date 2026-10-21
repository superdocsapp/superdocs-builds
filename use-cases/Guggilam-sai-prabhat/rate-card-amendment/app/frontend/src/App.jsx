import { useState } from "react";
import Intake from "./screens/Intake.jsx";
import Dashboard from "./screens/Dashboard.jsx";
import Review from "./screens/Review.jsx";
import Results from "./screens/Results.jsx";
import "./App.css";

const SCREENS = {
  INTAKE: "intake",
  DASHBOARD: "dashboard",
  REVIEW: "review",
  RESULTS: "results",
};

export default function App() {
  const [screen, setScreen] = useState(SCREENS.INTAKE);
  const [run, setRun] = useState(null);
  const [activeCaseId, setActiveCaseId] = useState(null);
  const [lastExport, setLastExport] = useState(null);

  return (
    <div className="app">
      <header className="app-header">
        <h2>Rate-Card Amendment Propagation</h2>
        <nav>
          {Object.values(SCREENS).map((s) => (
            <span key={s} className={s === screen ? "nav-item active" : "nav-item"}>
              {s}
            </span>
          ))}
        </nav>
      </header>

      {screen === SCREENS.INTAKE && (
        <Intake
          onRunCreated={(created) => {
            setRun(created);
            setScreen(SCREENS.DASHBOARD);
          }}
        />
      )}

      {screen === SCREENS.DASHBOARD && run && (
        <Dashboard
          run={run}
          onOpenReview={(caseId) => {
            setActiveCaseId(caseId);
            setScreen(SCREENS.REVIEW);
          }}
        />
      )}

      {screen === SCREENS.REVIEW && run && activeCaseId && (
        <Review
          run={run}
          caseId={activeCaseId}
          onBack={() => setScreen(SCREENS.DASHBOARD)}
          onExported={(exportResult) => {
            setLastExport(exportResult);
            setScreen(SCREENS.RESULTS);
          }}
        />
      )}

      {screen === SCREENS.RESULTS && run && (
        <Results run={run} lastExport={lastExport} onBack={() => setScreen(SCREENS.DASHBOARD)} />
      )}
    </div>
  );
}
