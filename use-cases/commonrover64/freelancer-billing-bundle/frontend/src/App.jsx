import { useState } from "react";
import ClientEngagementSelector from "./components/ClientEngagementselector.jsx";

function App() {
    const [engagementId, setEngagementId] = useState(null);

    return (
        <div>
            <h1>Freelancer Billing Bundle</h1>
            <ClientEngagementSelector onSelect={setEngagementId} />
            {engagementId && <p>Selected engagement id: {engagementId}</p>}
        </div>
    );
}

export default App;
