import { Route, Routes } from 'react-router-dom';
import Nav from './Nav';
import Integrity from './Integrity';
import Countries from './Countries';
import Generate from './Generate';
import Packs from './Packs';
import Amend from './Amend';

function App() {
  return (
    <>
      <Nav />
      <Routes>
        <Route path="/" element={<Integrity />} />
        <Route path="/countries" element={<Countries />} />
        <Route path="/generate" element={<Generate />} />
        <Route path="/packs" element={<Packs />} />
        <Route path="/amend" element={<Amend />} />
      </Routes>
    </>
  );
}

export default App;
