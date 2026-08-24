"use client";

import { useCallback, useEffect, useState, type ReactNode } from "react";

import { Skeleton } from "@/components/ui/skeleton";

import type { GoogleConnection } from "../lib/api";
import { getAuthorizeUrl, getConnections } from "../lib/api";
import { browserPickerTokenManager } from "../google-drive/picker-token";
import {
  extractSelectedFile,
  mapPickerFailure,
  type SelectedDriveFile,
} from "../lib/import-state";
import { ICON_STROKE, icons } from "@/lib/icons";
import { cn } from "@/lib/utils";
import { Button } from "./ui";
import { GoogleDriveMark } from "./brand";

const GOOGLE_CLIENT_ID = process.env.NEXT_PUBLIC_GOOGLE_OAUTH_CLIENT_ID ?? "";
const PICKER_API_KEY = process.env.NEXT_PUBLIC_GOOGLE_PICKER_API_KEY ?? "";
const CLOUD_PROJECT_NUMBER = process.env.NEXT_PUBLIC_GOOGLE_CLOUD_PROJECT_NUMBER ?? "";
const DRIVE_FILE_SCOPE = "https://www.googleapis.com/auth/drive.file";

let gapiLoadPromise: Promise<void> | null = null;
let gisLoadPromise: Promise<void> | null = null;

function loadGapiScript(): Promise<void> {
  if (gapiLoadPromise) return gapiLoadPromise;
  gapiLoadPromise = new Promise((resolve, reject) => {
    if (window.gapi) { resolve(); return; }
    const s = document.createElement("script");
    s.src = "https://apis.google.com/js/api.js";
    s.async = true;
    s.onload = () => resolve();
    s.onerror = () => reject(new Error("Failed to load Google API script"));
    document.head.appendChild(s);
  });
  return gapiLoadPromise;
}

function loadGisScript(): Promise<void> {
  if (gisLoadPromise) return gisLoadPromise;
  gisLoadPromise = new Promise((resolve, reject) => {
    if (window.google?.accounts?.oauth2) { resolve(); return; }
    const s = document.createElement("script");
    s.src = "https://accounts.google.com/gsi/client";
    s.async = true;
    s.onload = () => resolve();
    s.onerror = () => reject(new Error("Failed to load Google Identity Services"));
    document.head.appendChild(s);
  });
  return gisLoadPromise;
}

function loadPickerLibrary(): Promise<void> {
  return new Promise((resolve, reject) => {
    if (window.google?.picker) { resolve(); return; }
    if (!window.gapi) { reject(new Error("GAPI not loaded")); return; }
    window.gapi.load("picker", () => {
      if (window.google?.picker) resolve();
      else reject(new Error("Picker library failed to initialize"));
    });
  });
}

export function SourceChooser({
  initialConnection,
  onDocumentPicked,
  onConnectionChange,
}: {
  initialConnection: GoogleConnection | null;
  onDocumentPicked: (conn: GoogleConnection, file: SelectedDriveFile) => void;
  onConnectionChange: (conn: GoogleConnection | null) => void;
}) {
  const [connection, setConnection] = useState<GoogleConnection | null>(initialConnection);
  const [loading, setLoading] = useState(true);
  const [apiUnavailable, setApiUnavailable] = useState(false);
  const [oauthConfigured, setOauthConfigured] = useState(true);
  const [pickerBusy, setPickerBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadWorkspace = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setApiUnavailable(false);
    setError(null);
    try {
      const data = await getConnections(signal);
      if (signal?.aborted) return;
      if (!data.oauth_configured) {
        setOauthConfigured(false);
        setConnection(null);
        onConnectionChange(null);
        return;
      }
      setOauthConfigured(true);
      const active = data.connections.find((item) => item.status === "CONNECTED") ?? null;
      setConnection(active);
      onConnectionChange(active);
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      if (err instanceof Error && err.name === "AbortError") return;
      setApiUnavailable(true);
      setConnection(null);
      onConnectionChange(null);
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, [onConnectionChange]);

  useEffect(() => {
    const controller = new AbortController();
    queueMicrotask(() => void loadWorkspace(controller.signal));
    return () => controller.abort();
  }, [loadWorkspace]);

  const handleConnect = useCallback(() => {
    window.location.assign(getAuthorizeUrl());
  }, []);

  const openPicker = useCallback(async () => {
    if (!connection || pickerBusy) return;
    if (!GOOGLE_CLIENT_ID || !PICKER_API_KEY || !CLOUD_PROJECT_NUMBER) {
      setError("Google Drive is not fully configured in this environment.");
      return;
    }
    setPickerBusy(true);
    setError(null);
    try {
      await Promise.all([loadGapiScript(), loadGisScript()]);
      await loadPickerLibrary();

      const token = await browserPickerTokenManager.getToken(
        (prompt) => new Promise<{ accessToken: string; expiresIn: number }>(
          (resolve, reject) => {
            const client = window.google!.accounts!.oauth2!.initTokenClient({
              client_id: GOOGLE_CLIENT_ID,
              scope: DRIVE_FILE_SCOPE,
              callback: (response) => {
                if (response.error) {
                  reject(new Error(response.error_description || response.error));
                  return;
                }
                resolve({ accessToken: response.access_token, expiresIn: response.expires_in });
              },
              error_callback: (err) => {
                reject(new Error(err.message || "OAuth popup was closed or denied"));
              },
            });
            client.requestAccessToken({ prompt });
          },
        ),
      );

      const docsView = new window.google!.picker!.DocsView();
      docsView.setMimeTypes("application/vnd.google-apps.document");

      const picker = new window.google!.picker!.PickerBuilder()
        .addView(docsView)
        .setOAuthToken(token)
        .setDeveloperKey(PICKER_API_KEY)
        .setAppId(CLOUD_PROJECT_NUMBER)
        .setOrigin(window.location.origin)
        .setTitle("Select a Google document")
        .setCallback((data: google.picker.ResponseObject) => {
          if (data.action === "cancel") {
            setPickerBusy(false);
            return;
          }
          const file = extractSelectedFile(data);
          if (file) {
            setPickerBusy(false);
            onDocumentPicked(connection, file);
            return;
          }
          setPickerBusy(false);
        })
        .build();
      picker.setVisible(true);
    } catch (err) {
      const mapped = mapPickerFailure(err);
      if (mapped) setError(mapped);
      setPickerBusy(false);
    }
  }, [connection, pickerBusy, onDocumentPicked]);

  const notices = (
    <>
      {apiUnavailable ? (
        <InlineStatus
          title="DocRelay API is unavailable"
          description="Start the backend or try again."
          action={
            <Button variant="secondary" onClick={() => void loadWorkspace()} className="h-8 px-2.5">
              Retry
            </Button>
          }
        />
      ) : null}

      {!apiUnavailable && !oauthConfigured ? (
        <InlineStatus
          title="Google Drive is not configured"
          description="OAuth is not available on this backend."
        />
      ) : null}

      {error ? <InlineStatus title="Could not open Google Drive" description={error} /> : null}
    </>
  );

  return (
    <section className="flex h-full min-h-full flex-col bg-background">
      <header className="chrome-rail">
        <h1 className="type-chrome-title">Workspace</h1>
        <DriveConnectionStatus connected={Boolean(connection)} loading={loading} />
      </header>

      {/* The application's starting state, not a landing page: one left-aligned
          editorial column balanced in the canvas, carrying a single focal
          control. Nothing here is framed that does not need framing. */}
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto flex min-h-full w-full max-w-[568px] flex-col justify-center px-6 pt-12 pb-16 lg:pb-20">
          <h2 className="type-hero-title text-balance">Start with a document</h2>
          <p className="type-hero-body mt-3.5 max-w-[29rem] text-pretty">
            Connect a Google Doc and let DocRelay prepare reviewed, verifiable changes.
          </p>

          <div className="mt-8 flex w-full flex-col gap-3 lg:mt-9">
            {notices}
            <DriveSelector
              loading={loading}
              connected={Boolean(connection)}
              busy={pickerBusy}
              onConnect={handleConnect}
              onChoose={() => void openPicker()}
            />
          </div>

          {/* The guarantee, stated once as a quiet caption rather than as three
              instructional columns. */}
          <ul className="mt-5 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[12.5px] leading-5 text-muted-soft">
            {[
              "Revision frozen before any edit",
              "You approve each change",
              "Write backed up and verified",
            ].map((fact, index) => (
              <li key={fact} className="flex items-center gap-2.5">
                {index > 0 ? (
                  <span className="size-[3px] shrink-0 rounded-full bg-border" aria-hidden="true" />
                ) : null}
                {fact}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}

/** Shared geometry for every state of the selector, so nothing shifts. */
const SELECTOR_SHELL =
  "flex w-full flex-col items-stretch gap-3.5 rounded-[14px] border p-4 text-left"
  + " sm:flex-row sm:items-center sm:gap-4 sm:py-3.5 sm:pr-3.5 sm:pl-[18px]";

/**
 * The product's one focal action.
 *
 * A single selection row rather than a large onboarding card: Drive's own mark
 * states the source, the type states the action, and the accent control on the
 * right is the only filled surface on the screen. Depth is one restrained
 * shadow that tightens slightly under the pointer — the row never lifts.
 */
function DriveSelector({
  loading,
  connected,
  busy,
  onConnect,
  onChoose,
}: {
  loading: boolean;
  connected: boolean;
  busy: boolean;
  onConnect: () => void;
  onChoose: () => void;
}) {
  if (loading) return <SelectorSkeleton />;

  const identity = (
    <span className="flex min-w-0 flex-1 items-center gap-3.5">
      <GoogleDriveMark className="h-[26px] w-[29px]" />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[16px] leading-[1.3] font-semibold tracking-[-0.024em] text-foreground">
          {connected ? "Choose a Google Doc" : "Connect Google Drive"}
        </span>
        <span className="mt-[3px] block text-[12.75px] leading-[1.45] text-muted">
          {connected
            ? "Opens the Google Drive picker. Google Docs only."
            : "Authorize once — DocRelay only reads the documents you pick."}
        </span>
      </span>
    </span>
  );

  if (!connected) {
    return (
      <div className={cn(SELECTOR_SHELL, "border-border bg-surface shadow-[var(--shadow-raised)]")}>
        {identity}
        <Button onClick={onConnect} className="h-[36px] shrink-0 px-4">
          Connect
        </Button>
      </div>
    );
  }

  return (
    <button
      type="button"
      onClick={onChoose}
      disabled={busy}
      aria-busy={busy}
      className={cn(
        SELECTOR_SHELL,
        "group/selector border-border bg-surface shadow-[var(--shadow-raised)]",
        "transition-[border-color,box-shadow] duration-[var(--motion-duration-lg)] ease-[var(--motion-ease)]",
        "hover:border-muted-soft/40 hover:shadow-[0_1px_2px_rgb(23_26_24/0.05),0_10px_24px_-14px_rgb(23_26_24/0.16)]",
        "focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/25 focus-visible:outline-none",
        "disabled:pointer-events-none",
      )}
    >
      {identity}
      <span
        className={cn(
          "type-button inline-flex h-[36px] shrink-0 items-center justify-center gap-1.5 rounded-[9px] px-4",
          "bg-primary text-primary-foreground shadow-[var(--shadow-subtle)]",
          "transition-colors duration-[var(--motion-duration)] ease-[var(--motion-ease)]",
          busy ? "opacity-85" : "group-hover/selector:bg-primary-hover",
        )}
      >
        {busy ? (
          <icons.refresh className="size-3.5 animate-spin" strokeWidth={ICON_STROKE} aria-hidden="true" />
        ) : null}
        {busy ? "Opening…" : "Browse Drive"}
      </span>
    </button>
  );
}

/** Compact inline status surface — deliberately quieter than a full banner. */
function InlineStatus({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div
      role="status"
      className="flex w-full items-start gap-2.5 rounded-[12px] border border-border bg-surface px-3.5 py-3 shadow-[var(--shadow-subtle)]"
    >
      <icons.warning
        className="mt-px size-4 shrink-0 text-warning"
        strokeWidth={ICON_STROKE}
        aria-hidden="true"
      />
      <div className="min-w-0 flex-1">
        <p className="text-[13.25px] font-medium text-foreground">{title}</p>
        <p className="mt-0.5 text-[12.75px] leading-[1.55] text-muted">{description}</p>
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  );
}

function DriveConnectionStatus({
  connected,
  loading,
}: {
  connected: boolean;
  loading: boolean;
}) {
  return (
    <p className="inline-flex items-center gap-1.5 text-[12.75px] whitespace-nowrap text-muted">
      <span
        className={cn(
          "size-1.5 shrink-0 rounded-full",
          connected ? "bg-success" : loading ? "bg-muted-soft live-dot" : "bg-border",
        )}
        aria-hidden="true"
      />
      Google Drive
      <span className="text-muted-soft">·</span>
      {connected ? "Connected" : loading ? "Checking…" : "Not connected"}
    </p>
  );
}

/** Same shell, same height: the row never resizes when the check resolves. */
function SelectorSkeleton() {
  return (
    <div
      className={cn(SELECTOR_SHELL, "border-border-light bg-surface")}
      aria-hidden="true"
    >
      <span className="flex min-w-0 flex-1 items-center gap-3.5">
        <Skeleton className="size-[26px] shrink-0 rounded-[7px]" />
        <span className="min-w-0 flex-1">
          <Skeleton className="h-[15px] w-[11rem]" />
          <Skeleton className="mt-2 h-3 w-[16rem] max-w-full" />
        </span>
      </span>
      <Skeleton className="h-[36px] w-[7.5rem] shrink-0 rounded-[9px]" />
    </div>
  );
}
