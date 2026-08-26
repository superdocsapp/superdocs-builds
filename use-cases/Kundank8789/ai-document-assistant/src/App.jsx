import { useState } from "react";
import EventData from "./pages/EventData";
import Sponsors from "./pages/Sponsors";
import Documents from "./pages/Documents";
import Sidebar from "./components/layout/Sidebar";
import Overview from "./pages/Overview";
import ReviewQueue from "./pages/ReviewQueue";

function App() {
  const [activePage, setActivePage] = useState("overview");

  return (
    <div className="min-h-screen bg-slate-50">
      <div className="flex">
        <Sidebar
          activePage={activePage}
          setActivePage={setActivePage}
        />

        <main className="min-h-screen flex-1 p-6 lg:p-10">
          {activePage === "overview" && <Overview />}

          {activePage === "event-data" && <EventData />}

          {activePage === "sponsors" && <Sponsors />}

          {activePage === "documents" && <Documents />}

          {activePage === "review" && <ReviewQueue />}

          {activePage !== "overview" &&
            activePage !== "event-data" &&
            activePage !== "sponsors" &&
            activePage !== "documents" &&
            activePage !== "review" && (
              <div className="flex min-h-[80vh] items-center justify-center">
                <div className="text-center">
                  <h2 className="text-2xl font-bold text-slate-800">
                    {activePage.replace("-", " ")}
                  </h2>

                  <p className="mt-2 text-slate-500">
                    This page will be built next.
                  </p>
                </div>
              </div>
            )}
        </main>
      </div>
    </div>
  );
}

export default App;