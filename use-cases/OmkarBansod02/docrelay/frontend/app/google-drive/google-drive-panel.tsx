"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { browserPickerTokenManager } from "./picker-token";

// ---------------------------------------------------------------------------
// Configuration from public environment variables
// ---------------------------------------------------------------------------

const API_BASE_URL = process.env.NEXT_PUBLIC_DOCRELAY_API_URL ?? "http://localhost:8000";
const GOOGLE_CLIENT_ID = process.env.NEXT_PUBLIC_GOOGLE_OAUTH_CLIENT_ID ?? "";
const PICKER_API_KEY = process.env.NEXT_PUBLIC_GOOGLE_PICKER_API_KEY ?? "";
const CLOUD_PROJECT_NUMBER = process.env.NEXT_PUBLIC_GOOGLE_CLOUD_PROJECT_NUMBER ?? "";
const DRIVE_FILE_SCOPE = "https://www.googleapis.com/auth/drive.file";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ConnectionStatus = "PENDING" | "CONNECTED" | "DISCONNECTED" | "REAUTH_REQUIRED" | "INVALID";

interface GoogleConnection {
  connection_id: string;
  provider: "GOOGLE";
  status: ConnectionStatus;
  granted_scopes: string[];
  last_validated_at: string | null;
  disconnected_at: string | null;
}

interface ConnectionsResponse {
  oauth_configured: boolean;
  selected_scopes: string[];
  connections: GoogleConnection[];
}

interface SelectedFile {
  fileId: string;
  name: string;
  mimeType: string;
}

interface SourceRegistrationResult {
  source: {
    source_id: string;
    provider_file_id: string;
    name: string;
    mime_type: string;
  };
  baseline: {
    capture_id: string;
    revision_id: string;
    native_canonical_sha256: string;
    docx_sha256: string;
    docx_size_bytes: number;
  };
}

type PanelState =
  | { kind: "loading" }
  | { kind: "unconfigured" }
  | { kind: "no_connection" }
  | { kind: "connected"; connection: GoogleConnection }
  | { kind: "error"; message: string };

type PickerState =
  | { kind: "idle" }
  | { kind: "loading_scripts" }
  | { kind: "authorizing" }
  | { kind: "open" }
  | { kind: "registering"; file: SelectedFile }
  | { kind: "success"; file: SelectedFile; result: SourceRegistrationResult }
  | { kind: "rejected"; file: SelectedFile; errorCode: string; message: string }
  | { kind: "error"; message: string };

// ---------------------------------------------------------------------------
// Script loading utilities
// ---------------------------------------------------------------------------

let gapiLoadPromise: Promise<void> | null = null;
let gisLoadPromise: Promise<void> | null = null;

function loadGapiScript(): Promise<void> {
  if (gapiLoadPromise) return gapiLoadPromise;
  gapiLoadPromise = new Promise((resolve, reject) => {
    if (window.gapi) {
      resolve();
      return;
    }
    const script = document.createElement("script");
    script.src = "https://apis.google.com/js/api.js";
    script.async = true;
    script.defer = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("Failed to load Google API script"));
    document.head.appendChild(script);
  });
  return gapiLoadPromise;
}

function loadGisScript(): Promise<void> {
  if (gisLoadPromise) return gisLoadPromise;
  gisLoadPromise = new Promise((resolve, reject) => {
    if (window.google?.accounts?.oauth2) {
      resolve();
      return;
    }
    const script = document.createElement("script");
    script.src = "https://accounts.google.com/gsi/client";
    script.async = true;
    script.defer = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("Failed to load Google Identity Services"));
    document.head.appendChild(script);
  });
  return gisLoadPromise;
}

function loadPickerLibrary(): Promise<void> {
  return new Promise((resolve, reject) => {
    if (window.google?.picker) {
      resolve();
      return;
    }
    if (!window.gapi) {
      reject(new Error("GAPI not loaded"));
      return;
    }
    window.gapi.load("picker", () => {
      if (window.google?.picker) {
        resolve();
      } else {
        reject(new Error("Picker library failed to initialize"));
      }
    });
  });
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function GoogleDrivePanel() {
  const [panelState, setPanelState] = useState<PanelState>({ kind: "loading" });
  const [pickerState, setPickerState] = useState<PickerState>({ kind: "idle" });

  const panelStateRef = useRef(panelState);
  useEffect(() => {
    panelStateRef.current = panelState;
  });

  // Fetch backend connection status
  useEffect(() => {
    const controller = new AbortController();

    async function fetchConnections() {
      try {
        const response = await fetch(`${API_BASE_URL}/api/v1/google/connections`, {
          cache: "no-store",
          signal: controller.signal,
        });
        if (!response.ok) {
          setPanelState({ kind: "error", message: "Failed to fetch connection status" });
          return;
        }
        const data = (await response.json()) as ConnectionsResponse;
        if (!data.oauth_configured) {
          setPanelState({ kind: "unconfigured" });
          return;
        }
        const active = data.connections.find((c) => c.status === "CONNECTED");
        if (active) {
          setPanelState({ kind: "connected", connection: active });
        } else {
          setPanelState({ kind: "no_connection" });
        }
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") return;
        setPanelState({ kind: "error", message: "Could not reach the DocRelay API" });
      }
    }

    void fetchConnections();
    return () => controller.abort();
  }, []);

  const handleConnect = useCallback(() => {
    // Navigate to external backend OAuth endpoint (not a Next.js page)
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination
    window.location.assign(`${API_BASE_URL}/api/v1/google/oauth/authorize`);
  }, []);

  const registerSource = useCallback(
    async (file: SelectedFile) => {
      const current = panelStateRef.current;
      if (current.kind !== "connected") return;
      const connectionId = current.connection.connection_id;

      setPickerState({ kind: "registering", file });

      try {
        const response = await fetch(
          `${API_BASE_URL}/api/v1/google/connections/${connectionId}/sources`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ file_id: file.fileId }),
          }
        );

        if (response.ok) {
          const result = (await response.json()) as SourceRegistrationResult;
          setPickerState({ kind: "success", file, result });
        } else {
          const errorBody = await response.json().catch(() => null);
          const errorCode =
            (errorBody as { error?: { code?: string } } | null)?.error?.code ?? "UNKNOWN";
          const message =
            (errorBody as { error?: { message?: string } } | null)?.error?.message ??
            "Source registration failed";
          setPickerState({ kind: "rejected", file, errorCode, message });
        }
      } catch {
        setPickerState({
          kind: "error",
          message: "Could not reach the backend to register the source",
        });
      }
    },
    []
  );

  const handlePickerCallback = useCallback(
    (data: google.picker.ResponseObject) => {
      if (data.action === "cancel") {
        setPickerState({ kind: "idle" });
        return;
      }

      if (data.action === "picked") {
        const docs = data.docs;
        if (!docs || docs.length === 0) {
          setPickerState({ kind: "idle" });
          return;
        }
        const doc = docs[0];
        const file: SelectedFile = {
          fileId: doc.id,
          name: doc.name,
          mimeType: doc.mimeType,
        };
        void registerSource(file);
      }
    },
    [registerSource]
  );

  const openPicker = useCallback(async () => {
    if (!GOOGLE_CLIENT_ID || !PICKER_API_KEY || !CLOUD_PROJECT_NUMBER) {
      setPickerState({
        kind: "error",
        message: "Frontend Google configuration is incomplete. Check environment variables.",
      });
      return;
    }

    try {
      setPickerState({ kind: "loading_scripts" });

      await Promise.all([loadGapiScript(), loadGisScript()]);
      await loadPickerLibrary();

      const token = await browserPickerTokenManager.getToken(
        (prompt) => {
          setPickerState({ kind: "authorizing" });

          return new Promise<{
            accessToken: string;
            expiresIn: number;
          }>((resolve, reject) => {
            const tokenClient = window.google!.accounts!.oauth2!.initTokenClient({
              client_id: GOOGLE_CLIENT_ID,
              scope: DRIVE_FILE_SCOPE,
              callback: (response) => {
                if (response.error) {
                  reject(new Error(response.error_description || response.error));
                  return;
                }
                resolve({
                  accessToken: response.access_token,
                  expiresIn: response.expires_in,
                });
              },
              error_callback: (error) => {
                reject(new Error(error.message || "OAuth popup was closed or denied"));
              },
            });
            tokenClient.requestAccessToken({ prompt });
          });
        },
      );

      setPickerState({ kind: "open" });

      // Build and show Picker
      const docsView = new window.google!.picker!.DocsView();
      docsView.setMimeTypes(
        "application/vnd.google-apps.document,application/vnd.google-apps.spreadsheet"
      );

      const picker = new window.google!.picker!.PickerBuilder()
        .addView(docsView)
        .setOAuthToken(token)
        .setDeveloperKey(PICKER_API_KEY)
        .setAppId(CLOUD_PROJECT_NUMBER)
        .setOrigin(window.location.origin)
        .setTitle("Select a Google document for DocRelay")
        .setCallback(handlePickerCallback)
        .build();

      picker.setVisible(true);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Picker failed to open";
      if (message.includes("popup_closed") || message.includes("access_denied")) {
        setPickerState({ kind: "idle" });
      } else {
        setPickerState({ kind: "error", message });
      }
    }
  }, [handlePickerCallback]);

  const resetPicker = useCallback(() => {
    setPickerState({ kind: "idle" });
  }, []);

  // -------------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------------

  return (
    <section className="drive-panel">
      <div className="panel-header">
        <h2>Google Drive</h2>
        <ConnectionBadge state={panelState} />
      </div>

      {panelState.kind === "loading" && <p className="panel-message">Checking connection…</p>}

      {panelState.kind === "unconfigured" && (
        <p className="panel-message">
          Google OAuth is not configured on the backend. Set the required environment variables.
        </p>
      )}

      {panelState.kind === "error" && (
        <p className="panel-message panel-error">{panelState.message}</p>
      )}

      {panelState.kind === "no_connection" && (
        <div className="panel-actions">
          <button className="btn btn-primary" onClick={handleConnect}>
            Connect Google
          </button>
        </div>
      )}

      {panelState.kind === "connected" && (
        <div className="panel-actions">
          <button
            className="btn btn-primary"
            onClick={openPicker}
            disabled={
              pickerState.kind !== "idle" &&
              pickerState.kind !== "success" &&
              pickerState.kind !== "rejected" &&
              pickerState.kind !== "error"
            }
          >
            Select Google document
          </button>
          <PickerStatus state={pickerState} onReset={resetPicker} />
        </div>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function ConnectionBadge({ state }: { state: PanelState }) {
  let label: string;
  let className: string;

  switch (state.kind) {
    case "loading":
      label = "Checking";
      className = "status status-checking";
      break;
    case "connected":
      label = "Connected";
      className = "status status-ready";
      break;
    case "no_connection":
      label = "Not connected";
      className = "status status-unavailable";
      break;
    case "unconfigured":
      label = "Unconfigured";
      className = "status status-unavailable";
      break;
    case "error":
      label = "Error";
      className = "status status-unavailable";
      break;
  }

  return <span className={className}>{label}</span>;
}

function PickerStatus({ state, onReset }: { state: PickerState; onReset: () => void }) {
  switch (state.kind) {
    case "idle":
      return null;
    case "loading_scripts":
      return <p className="picker-status">Loading Google libraries…</p>;
    case "authorizing":
      return <p className="picker-status">Waiting for authorization…</p>;
    case "open":
      return <p className="picker-status">Picker is open — select a file.</p>;
    case "registering":
      return (
        <p className="picker-status">
          Registering <strong>{state.file.name}</strong>…
        </p>
      );
    case "success":
      return (
        <div className="picker-result picker-success">
          <p>
            <strong>Document authorized</strong>
          </p>
          <p>DocRelay can now validate this source.</p>
          <dl>
            <dt>Name</dt>
            <dd>{state.file.name}</dd>
            <dt>MIME type</dt>
            <dd>{state.result.source.mime_type}</dd>
            <dt>Revision</dt>
            <dd>
              <code>{state.result.baseline.revision_id}</code>
            </dd>
            <dt>DOCX size</dt>
            <dd>{state.result.baseline.docx_size_bytes.toLocaleString()} bytes</dd>
          </dl>
          <button className="btn btn-secondary" onClick={onReset}>
            Select another document
          </button>
        </div>
      );
    case "rejected":
      return (
        <div className="picker-result picker-rejected">
          <p>
            <strong>Source rejected</strong>
          </p>
          <p>
            {state.file.name} ({state.file.mimeType})
          </p>
          <p className="picker-error-detail">
            {state.errorCode}: {state.message}
          </p>
          <button className="btn btn-secondary" onClick={onReset}>
            Try another document
          </button>
        </div>
      );
    case "error":
      return (
        <div className="picker-result picker-error-box">
          <p className="panel-error">{state.message}</p>
          <button className="btn btn-secondary" onClick={onReset}>
            Dismiss
          </button>
        </div>
      );
  }
}
