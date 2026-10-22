import { Routes, Route } from "react-router-dom";
import { Layout } from "./components/Layout";
import { PacketList } from "./pages/PacketList";
import { PacketWorkspace } from "./pages/PacketWorkspace";
import { SearchPage } from "./pages/SearchPage";
import { SettingsPage } from "./pages/SettingsPage";
import { ToastProvider } from "./components/ui/use-toast";

function App() {
  return (
    <ToastProvider>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<PacketList />} />
          <Route path="/packets/:packetId" element={<PacketWorkspace />} />
          <Route path="/search" element={<SearchPage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Route>
      </Routes>
    </ToastProvider>
  );
}

export default App;