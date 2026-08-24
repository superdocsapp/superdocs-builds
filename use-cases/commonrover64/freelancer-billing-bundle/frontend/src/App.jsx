import "./App.css";
import { useState } from "react";
import ClientEngagementSelector from "./components/ClientEngagementselector.jsx";
import DocumentGenerator from "./components/DocumentGenerator.jsx";
// import CreateClientForm from "./components/CreateClientForm.jsx";

function App() {
    const [selection, setSelection] = useState(null);

    return (
        <div style={{ maxWidth: 900, margin: "0 auto", padding: "2rem" }}>
            <h1>Freelancer Billing Bundle</h1>

            <div className="step-label">
                Step 1, choose client and engagement
            </div>
            <div className="card">
                <ClientEngagementSelector onSelect={setSelection} />
            </div>

            {selection && (
                <>
                    <div className="step-label">
                        Step 2, generate and review documents
                    </div>
                    <DocumentGenerator {...selection} />
                </>
            )}
        </div>
    );
}

export default App;
