import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { App } from "./App";
import { RunProvider } from "./runs/RunContext";
import { RunActivityProvider } from "./runs/RunActivityContext";
import { NotificationProvider } from "./notifications/NotificationContext";
import "./index.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <NotificationProvider>
        <RunProvider>
          <RunActivityProvider>
            <App />
          </RunActivityProvider>
        </RunProvider>
      </NotificationProvider>
    </BrowserRouter>
  </StrictMode>
);