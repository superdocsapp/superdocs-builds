import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./styles.css";

/** Office.js must be ready before anything touches `Word`, and the pane must
 * still render if it never becomes ready — a task pane that stays blank because
 * a CDN script was slow is indistinguishable, to the person looking at it, from
 * an add-in that is broken. `detectHost()` inside the app handles both. */
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
