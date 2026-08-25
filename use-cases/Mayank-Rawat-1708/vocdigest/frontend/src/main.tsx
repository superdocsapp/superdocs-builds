/**
 * @file src/main.tsx
 * @description React entry point. Mounts the app inside a router.
 * @flow createRoot -> BrowserRouter -> App
 * @dependencies react-dom/client, react-router-dom
 */
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>,
);
