import React from "react";
import ReactDOM from "react-dom/client";
import { App } from "./App";
import { ClerkAuthedApp } from "./ClerkAuth";
import "./styles.css";

// Vite reads env files from `frontend/`, not the repo root - see the README. With a key
// present the app mounts behind Clerk; without one it falls back to the demo session,
// which the backend only issues while CLERK_SECRET_KEY is unset.
const publishableKey = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY as string | undefined;

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {publishableKey ? <ClerkAuthedApp publishableKey={publishableKey} /> : <App />}
  </React.StrictMode>
);
