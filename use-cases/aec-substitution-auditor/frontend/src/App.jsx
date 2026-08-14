import React from 'react';
import SubstitutionAuditor from './components/SubstitutionAuditor';

function App() {
  return (
    <div className="flex flex-col h-screen overflow-hidden bg-[#16171d]">
      <SubstitutionAuditor API_BASE="http://localhost:8000/api/substitution" />
    </div>
  );
}

export default App;
