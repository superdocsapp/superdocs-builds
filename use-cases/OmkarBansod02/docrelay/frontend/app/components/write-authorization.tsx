"use client";

import { FileKey2, FileText, ShieldCheck } from "lucide-react";
import { useCallback, useState } from "react";
import { browserPickerTokenManager } from "../google-drive/picker-token";
import { verifyWriteAuthorization } from "../lib/api";
import type { DocumentIdentityData } from "./document-identity";
import { DocumentIdentity } from "./document-identity";
import { Button, InlineNotice, StateMark } from "./ui";
import { WorkflowProgress } from "./workflow-progress";

const GOOGLE_CLIENT_ID = process.env.NEXT_PUBLIC_GOOGLE_OAUTH_CLIENT_ID ?? "";
const PICKER_API_KEY = process.env.NEXT_PUBLIC_GOOGLE_PICKER_API_KEY ?? "";
const CLOUD_PROJECT_NUMBER = process.env.NEXT_PUBLIC_GOOGLE_CLOUD_PROJECT_NUMBER ?? "";
const DRIVE_FILE_SCOPE = "https://www.googleapis.com/auth/drive.file";

let gapiLoadPromise: Promise<void> | null = null;
let gisLoadPromise: Promise<void> | null = null;

export function WriteAuthorization({
  runId,
  providerFileId,
  document,
  onAuthorized,
}: {
  runId: string;
  providerFileId: string;
  document: DocumentIdentityData;
  onAuthorized: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const authorize = useCallback(async () => {
    if (busy) return;
    if (!GOOGLE_CLIENT_ID || !PICKER_API_KEY || !CLOUD_PROJECT_NUMBER) {
      setError("Frontend Google configuration is incomplete.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await Promise.all([loadGapiScript(), loadGisScript()]);
      await loadPickerLibrary();
      const token = await browserPickerTokenManager.getToken(
        (prompt) => new Promise<{ accessToken: string; expiresIn: number }>((resolve, reject) => {
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
            error_callback: (reason) => reject(new Error(reason.message || "OAuth popup was closed or denied")),
          });
          client.requestAccessToken({ prompt });
        }),
      );

      const view = new window.google!.picker!.DocsView();
      view.setMimeTypes("application/vnd.google-apps.document");
      const picker = new window.google!.picker!.PickerBuilder()
        .addView(view)
        .setOAuthToken(token)
        .setDeveloperKey(PICKER_API_KEY)
        .setAppId(CLOUD_PROJECT_NUMBER)
        .setOrigin(window.location.origin)
        .setTitle(`Authorize ${document.name}`)
        .setCallback((data: google.picker.ResponseObject) => {
          if (data.action === "cancel") {
            setBusy(false);
            return;
          }
          if (data.action !== "picked" || !data.docs?.length) {
            setBusy(false);
            return;
          }
          const pickedId = data.docs[0].id;
          if (pickedId !== providerFileId) {
            setError(`Choose ${document.name}. DocRelay will not transfer permission from another file.`);
            setBusy(false);
            return;
          }
          void verifyWriteAuthorization(runId, pickedId)
            .then(onAuthorized)
            .catch((reason) => setError(reason instanceof Error ? reason.message : "Exact-file authorization failed."))
            .finally(() => setBusy(false));
        })
        .build();
      picker.setVisible(true);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Google Picker could not be opened.");
      setBusy(false);
    }
  }, [busy, document.name, onAuthorized, providerFileId, runId]);

  return (
    // A safety checkpoint, not an error: same editorial surfaces as the rest of
    // the product, with the authorization action as the single focal point.
    <div className="bg-background">
      <DocumentIdentity document={document} />
      <WorkflowProgress current="Safety check" />
      <div className="px-6 py-9 sm:px-8 lg:px-10 lg:py-12">
        <div className="mx-auto w-full max-w-[640px]">
          <div className="text-center">
            <span className="mx-auto grid size-10 place-items-center rounded-[9px] bg-info-soft text-info" aria-hidden="true">
              <FileKey2 className="size-5" />
            </span>
            <h1 className="type-hero-title mt-5">Authorize this exact document</h1>
            <p className="type-hero-body mx-auto mt-3 max-w-[34rem]">
              DocRelay can read this watched document, but Google requires an explicit selection
              before it can write to the file.
            </p>
          </div>

          <div className="surface-section mt-8 px-6 py-6 shadow-[var(--shadow-raised)] sm:px-8">
            <div className="flex items-start gap-3">
              <span className="grid size-9 shrink-0 place-items-center rounded-[9px] bg-surface-muted text-muted" aria-hidden="true">
                <FileText className="size-[18px]" strokeWidth={1.75} />
              </span>
              <div className="min-w-0 flex-1">
                <p className="truncate text-[14.5px] font-semibold tracking-[-0.018em] text-ink">{document.name}</p>
                <p className="type-caption mt-0.5">Google Docs</p>
              </div>
            </div>

            <div className="mt-5 space-y-3.5 border-t border-border-light pt-5">
              <div className="flex items-center gap-3"><StateMark state="complete" /><span className="text-[13.5px] text-ink">Read access already verified</span></div>
              <div className="flex items-center gap-3"><StateMark state="current" /><span className="text-[13.5px] text-ink">Exact file selection required</span></div>
              <div className="flex items-center gap-3"><StateMark /><span className="text-[13.5px] text-ink">Safe write-back remains guarded</span></div>
            </div>

            {error ? <div className="mt-5"><InlineNotice tone="warning">{error}</InlineNotice></div> : null}

            <Button busy={busy} onClick={() => void authorize()} className="mt-6 h-[38px] w-full px-5">
              {busy ? "Opening Google Drive…" : "Authorize exact file"}
            </Button>
            <p className="type-caption mt-4 border-t border-border-light pt-4">
              Google Picker must return the same Drive file ID. Choosing any other document is rejected.
            </p>
          </div>

          <p className="type-caption mt-5 flex items-center justify-center gap-2 text-center">
            <ShieldCheck className="size-4 shrink-0 text-accent" aria-hidden="true" />
            The approved proposal and safety evidence are preserved. Picker tokens stay memory-only.
          </p>
        </div>
      </div>
    </div>
  );
}

function loadGapiScript(): Promise<void> {
  if (gapiLoadPromise) return gapiLoadPromise;
  gapiLoadPromise = new Promise((resolve, reject) => {
    if (window.gapi) { resolve(); return; }
    const script = document.createElement("script");
    script.src = "https://apis.google.com/js/api.js";
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("Failed to load Google API script"));
    document.head.appendChild(script);
  });
  return gapiLoadPromise;
}

function loadGisScript(): Promise<void> {
  if (gisLoadPromise) return gisLoadPromise;
  gisLoadPromise = new Promise((resolve, reject) => {
    if (window.google?.accounts?.oauth2) { resolve(); return; }
    const script = document.createElement("script");
    script.src = "https://accounts.google.com/gsi/client";
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("Failed to load Google Identity Services"));
    document.head.appendChild(script);
  });
  return gisLoadPromise;
}

function loadPickerLibrary(): Promise<void> {
  return new Promise((resolve, reject) => {
    if (window.google?.picker) { resolve(); return; }
    if (!window.gapi) { reject(new Error("GAPI not loaded")); return; }
    window.gapi.load("picker", () => window.google?.picker ? resolve() : reject(new Error("Picker library failed to initialize")));
  });
}
