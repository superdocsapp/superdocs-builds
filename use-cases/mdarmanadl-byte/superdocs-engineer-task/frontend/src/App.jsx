import { useState } from "react";

import Home from "./pages/Home";
import FreightClaim from "./pages/FreightClaim";
import EmailContract from "./pages/EmailContract";
import "./App.css";
function App() {
  const [page, setPage] = useState("editor");

  return (
    <div>
      <nav
        style={{
          height: "58px",
          display: "flex",
          alignItems: "center",
          gap: "10px",
          padding: "0 20px",
          borderBottom: "1px solid #e2e8f0",
          background: "white",
        }}
      >
        <button
          onClick={() => setPage("editor")}
          style={navButton(page === "editor")}
        >
          Document Editor
        </button>

        <button
          onClick={() => setPage("freight")}
          style={navButton(page === "freight")}
        >
          Freight Claim
        </button>

        <button
          onClick={() => setPage("email")}
          style={navButton(page === "email")}
        >
          Email → Contract
        </button>
      </nav>

      {page === "editor" && <Home />}

      {page === "freight" && <FreightClaim />}

      {page === "email" && <EmailContract />}
    </div>
  );
}

function navButton(active) {
  return {
    padding: "8px 14px",
    border: "none",
    borderRadius: "8px",
    background: active ? "#2563eb" : "#f1f5f9",
    color: active ? "white" : "#334155",
    cursor: "pointer",
    fontWeight: "600",
  };
}

export default App;
