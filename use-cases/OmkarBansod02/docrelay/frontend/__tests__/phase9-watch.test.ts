// @vitest-environment jsdom

import { act, createElement, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.hoisted(() => {
  process.env.NEXT_PUBLIC_GOOGLE_OAUTH_CLIENT_ID = "picker-test-client";
  process.env.NEXT_PUBLIC_GOOGLE_PICKER_API_KEY = "picker-test-key";
  process.env.NEXT_PUBLIC_GOOGLE_CLOUD_PROJECT_NUMBER = "123456789";
});

const routerPush = vi.fn();

vi.mock("next/navigation", () => ({
  usePathname: () => "/watch",
  useRouter: () => ({ push: routerPush }),
}));

vi.mock("next/link", () => ({
  default: ({
    children,
    href,
    ...props
  }: {
    children: ReactNode;
    href: string;
  } & Record<string, unknown>) => createElement("a", { href, ...props }, children),
}));

vi.mock("../app/lib/api", () => ({
  getAuthorizeUrl: vi.fn((profile?: string) => (
    profile === "watch"
      ? "http://localhost:8000/api/v1/google/oauth/authorize?profile=watch"
      : "http://localhost:8000/api/v1/google/oauth/authorize"
  )),
  getConnections: vi.fn(),
  listWatches: vi.fn(),
  listWatchRules: vi.fn(),
  listWatchScans: vi.fn(),
  listWatchScanItems: vi.fn(),
  listWatchRuns: vi.fn(),
  triggerWatchScan: vi.fn(),
  configureWatch: vi.fn(),
  configureWatchRule: vi.fn(),
  updateWatchSchedule: vi.fn(),
  verifyWriteAuthorization: vi.fn(),
}));

import {
  configureWatch,
  getAuthorizeUrl,
  getConnections,
  listWatchRules,
  listWatchRuns,
  listWatchScanItems,
  listWatchScans,
  listWatches,
  triggerWatchScan,
  type RunSummary,
  type WatchRoot,
  type WatchRule,
  type WatchScan,
  type WatchScanItem,
} from "../app/lib/api";
import { WatchWorkspace } from "../app/components/watch-workspace";
import {
  peekQueuedRecentDocument,
  takeQueuedRecentDocument,
} from "../app/lib/conversation";
import {
  actionableWatchRuns,
  exactFilePickMatches,
  scanProgressLabel,
  scheduleLabel,
  watchDocumentAction,
  watchDocumentSelection,
} from "../app/lib/watch-state";

const mockedGetConnections = vi.mocked(getConnections);
const mockedConfigureWatch = vi.mocked(configureWatch);
const mockedListWatches = vi.mocked(listWatches);
const mockedListWatchRules = vi.mocked(listWatchRules);
const mockedListWatchScans = vi.mocked(listWatchScans);
const mockedListWatchScanItems = vi.mocked(listWatchScanItems);
const mockedListWatchRuns = vi.mocked(listWatchRuns);
const mockedTriggerWatchScan = vi.mocked(triggerWatchScan);

function runSummary(overrides: Partial<RunSummary> = {}): RunSummary {
  return {
    run_id: "run-1",
    watch_id: "watch-1",
    originating_scan_id: "scan-1",
    source_id: "source-1",
    provider_file_id: "file-vendor",
    document_name: "Vendor Agreement",
    instruction: "Update the master agreement when an amendment changes terms.",
    proposal_count: 2,
    provider_version: "5",
    source_revision_id: "rev-5",
    matched_rule_id: "rule-1",
    matched_rule_version: 1,
    workflow_state: "AWAITING_REVIEW",
    review_status: "AWAITING_DECISIONS",
    write_authorization_status: null,
    dry_run_status: "NOT_REQUESTED",
    write_back_status: "AWAITING_REVIEW",
    verification_status: null,
    last_error_code: null,
    conflict: null,
    ready_for_dry_run: false,
    ready_for_write_back: false,
    export: null,
    started_at: null,
    created_at: "2026-08-14T11:59:00Z",
    updated_at: "2026-08-14T12:00:00Z",
    finished_at: null,
    duration_ms: null,
    external_effect_count: 0,
    external_effect_attempt_count: 0,
    external_effects_unknown: 0,
    superdocs_usage: {},
    ...overrides,
  };
}

function watchRoot(overrides: Partial<WatchRoot> = {}): WatchRoot {
  return {
    watch_id: "watch-1",
    connection_id: "conn-1",
    root_folder_id: "folder-contracts",
    root_name: "Contracts",
    enabled: true,
    schedule: "interval",
    interval_seconds: 3600,
    timezone: "UTC",
    last_scan_at: "2026-08-14T12:00:00Z",
    last_successful_scan_at: "2026-08-14T12:00:00Z",
    next_scan_at: "2026-08-14T13:00:00Z",
    last_scan_status: "SUCCEEDED",
    last_error_code: null,
    ...overrides,
  };
}

const rule: WatchRule = {
  rule_id: "rule-1",
  watch_id: "watch-1",
  folder_id: "folder-amendments",
  folder_name: "Amendments",
  version: 1,
  instruction: "Update the master agreement when an amendment changes terms.",
  instruction_sha256: "abc",
  enabled: true,
  precedence: "nearest_enabled_ancestor",
};

const scan: WatchScan = {
  scan_id: "scan-1",
  watch_id: "watch-1",
  trigger: "MANUAL",
  status: "SUCCEEDED",
  claim_generation: 1,
  started_at: "2026-08-14T12:00:00Z",
  completed_at: "2026-08-14T12:01:00Z",
  discovered_count: 2,
  changed_count: 1,
  unchanged_count: 1,
  enqueued_count: 1,
  skipped_count: 0,
  failed_count: 0,
  failure_code: null,
};

function scanItem(overrides: Partial<WatchScanItem> = {}): WatchScanItem {
  return {
    provider_file_id: "file-vendor",
    provider_version: "5",
    name: "Vendor Agreement",
    mime_type: "application/vnd.google-apps.document",
    ancestor_folder_ids: ["folder-contracts"],
    discovery_kind: "CHANGED",
    outcome: "ENQUEUED",
    reason_code: null,
    matched_rule_id: "rule-1",
    matched_rule_version: 1,
    run_id: "run-1",
    ...overrides,
  };
}

async function flushEffects() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
}

async function renderWatch() {
  const container = document.createElement("div");
  const root = createRoot(container);
  await act(async () => {
    root.render(createElement(WatchWorkspace));
  });
  await flushEffects();
  await flushEffects();
  return { container, root };
}

describe("watch presentation", () => {
  it("labels schedule from persisted interval data", () => {
    expect(scheduleLabel(true, 3600)).toBe("Every hour");
    expect(scheduleLabel(true, 21600)).toBe("Every 6 hours");
    expect(scheduleLabel(false, 3600)).toBe("Manual");
  });

  it("surfaces only documents that still need a person", () => {
    const pending = actionableWatchRuns([
      runSummary(),
      runSummary({
        run_id: "run-old",
        provider_file_id: "file-vendor",
        updated_at: "2026-08-14T10:00:00Z",
        workflow_state: "SUCCEEDED",
        review_status: "REVIEWED",
        write_back_status: "WRITE_VERIFIED",
        verification_status: "PASSED",
      }),
      runSummary({
        run_id: "run-verified",
        provider_file_id: "file-nda",
        document_name: "NDA",
        workflow_state: "SUCCEEDED",
        review_status: "REVIEWED",
        write_back_status: "WRITE_VERIFIED",
        verification_status: "PASSED",
      }),
    ]);
    expect(pending).toHaveLength(1);
    expect(pending[0].run_id).toBe("run-1");
  });

  it("keeps exact-file authorization as a required checkpoint", () => {
    const action = watchDocumentAction(runSummary({
      write_back_status: "WRITE_AUTHORIZATION_REQUIRED",
      write_authorization_status: "REQUIRED",
      review_status: "REVIEWED",
      workflow_state: "READY_TO_COMMIT",
    }));
    expect(action.kind).toBe("authorize");
    expect(action.statusLabel).toBe("Write access required");
    expect(action.detail).toContain("authorize this exact document");
    expect(exactFilePickMatches("file-vendor", "file-vendor")).toBe(true);
    expect(exactFilePickMatches("other-file", "file-vendor")).toBe(false);
  });

  it("opens the same document conversation, not a separate review surface", () => {
    expect(watchDocumentSelection(runSummary())).toEqual({
      fileId: "file-vendor",
      name: "Vendor Agreement",
      mimeType: "application/vnd.google-apps.document",
    });
  });

  it("does not invent scan percentages", () => {
    expect(scanProgressLabel({ ...scan, status: "RUNNING", discovered_count: 0, enqueued_count: 0, unchanged_count: 0 }, false)).toBe("Scanning…");
    expect(scanProgressLabel({ ...scan, status: "RUNNING", discovered_count: 4, enqueued_count: 0, unchanged_count: 0 }, false)).toBe("Scanning · 4 discovered");
    expect(scanProgressLabel(scan, false)).toBeNull();
  });
});

describe("Watch workspace", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
    routerPush.mockReset();
    takeQueuedRecentDocument();
    mockedGetConnections.mockReset();
    mockedConfigureWatch.mockReset();
    mockedListWatches.mockReset();
    mockedListWatchRules.mockReset();
    mockedListWatchScans.mockReset();
    mockedListWatchScanItems.mockReset();
    mockedListWatchRuns.mockReset();
    mockedTriggerWatchScan.mockReset();
    mockedTriggerWatchScan.mockResolvedValue(scan);
  });

  it("refetches connection state and shows watch access as enabled", async () => {
    mockedGetConnections.mockResolvedValue({
      oauth_configured: true,
      selected_scopes: [],
      connections: [{
        connection_id: "conn-1",
        provider: "GOOGLE",
        status: "CONNECTED",
        granted_scopes: [],
        watch_authorized: true,
        last_validated_at: "2026-08-14T12:00:00Z",
        disconnected_at: null,
      }],
    });
    mockedListWatches.mockResolvedValue({ watches: [watchRoot()] });
    mockedListWatchRules.mockResolvedValue({ rules: [rule] });
    mockedListWatchScans.mockResolvedValue({ scans: [scan] });
    mockedListWatchScanItems.mockResolvedValue({ items: [scanItem(), scanItem({ provider_file_id: "file-privacy", name: "Privacy Policy", outcome: "UNCHANGED", run_id: null })] });
    mockedListWatchRuns.mockResolvedValue({ runs: [runSummary()] });

    const { container, root } = await renderWatch();

    expect(mockedGetConnections).toHaveBeenCalled();
    expect(container.textContent).toContain("Watch access enabled");
    expect(container.textContent).toContain("Contracts");
    expect(container.textContent).toContain("Amendments");
    expect(container.textContent).toContain("Update the master agreement when an amendment changes terms.");
    expect(container.textContent).toContain("Every hour");
    expect(container.textContent).not.toContain("https://www.googleapis.com/auth/drive.readonly");

    root.unmount();
  });

  it("ignores LOADED, then configures the folder returned by PICKED", async () => {
    const configuredWatch = watchRoot({
      watch_id: "watch-selected",
      root_folder_id: "folder-selected",
      root_name: "Selected folder",
      last_scan_at: null,
      last_successful_scan_at: null,
      last_scan_status: null,
    });
    mockedGetConnections.mockResolvedValue({
      oauth_configured: true,
      selected_scopes: [],
      connections: [{
        connection_id: "conn-1",
        provider: "GOOGLE",
        status: "CONNECTED",
        granted_scopes: [],
        watch_authorized: true,
        last_validated_at: "2026-08-14T12:00:00Z",
        disconnected_at: null,
      }],
    });
    mockedListWatches
      .mockResolvedValueOnce({ watches: [] })
      .mockResolvedValue({ watches: [configuredWatch] });
    mockedConfigureWatch.mockResolvedValue(configuredWatch);
    mockedListWatchRules.mockResolvedValue({ rules: [] });
    mockedListWatchScans.mockResolvedValue({ scans: [] });
    mockedListWatchRuns.mockResolvedValue({ runs: [] });

    let pickerCallback: ((data: google.picker.ResponseObject) => void) | undefined;
    class DocsView {
      setMimeTypes() { return this; }
      setIncludeFolders() { return this; }
      setSelectFolderEnabled() { return this; }
    }
    class PickerBuilder {
      addView() { return this; }
      setOAuthToken() { return this; }
      setDeveloperKey() { return this; }
      setAppId() { return this; }
      setOrigin() { return this; }
      setTitle() { return this; }
      setCallback(callback: (data: google.picker.ResponseObject) => void) {
        pickerCallback = callback;
        return this;
      }
      build() { return { setVisible: vi.fn() }; }
    }
    vi.stubGlobal("gapi", { load: vi.fn() });
    vi.stubGlobal("google", {
      accounts: {
        oauth2: {
          initTokenClient: (config: google.accounts.oauth2.TokenClientConfig) => ({
            callback: config.callback,
            requestAccessToken: () => {
              if (typeof config.callback === "function") {
                config.callback({
                  access_token: "picker-token",
                  token_type: "Bearer",
                  expires_in: 3600,
                  scope: "drive.readonly",
                });
              }
            },
          }),
        },
      },
      picker: { DocsView, PickerBuilder },
    });

    const { container, root } = await renderWatch();
    const choose = [...container.querySelectorAll("button")]
      .find((button) => button.textContent === "Choose folder");
    expect(choose).toBeTruthy();

    await act(async () => {
      choose?.click();
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(pickerCallback).toBeTypeOf("function");

    await act(async () => {
      pickerCallback?.({ action: "loaded" });
      await Promise.resolve();
    });
    expect(mockedConfigureWatch).not.toHaveBeenCalled();

    await act(async () => {
      pickerCallback?.({
        action: "picked",
        docs: [{
          id: "folder-selected",
          name: "Selected folder",
          mimeType: "application/vnd.google-apps.folder",
          url: "https://drive.google.com/drive/folders/folder-selected",
        }],
      });
      await Promise.resolve();
    });
    await flushEffects();
    await flushEffects();

    expect(mockedConfigureWatch).toHaveBeenCalledWith({
      connection_id: "conn-1",
      root_folder_id: "folder-selected",
      interval_seconds: 3600,
      enabled: true,
    });

    vi.unstubAllGlobals();
    root.unmount();
  });

  it("requests the watch OAuth profile and returns users to Watch", async () => {
    mockedGetConnections.mockResolvedValue({
      oauth_configured: true,
      selected_scopes: [],
      connections: [{
        connection_id: "conn-1",
        provider: "GOOGLE",
        status: "CONNECTED",
        granted_scopes: [],
        watch_authorized: false,
        last_validated_at: "2026-08-14T12:00:00Z",
        disconnected_at: null,
      }],
    });
    mockedListWatches.mockResolvedValue({ watches: [] });

    const assign = vi.fn();
    vi.stubGlobal("location", { assign });

    const { container, root } = await renderWatch();
    const enable = [...container.querySelectorAll("button")].find((button) => button.textContent?.includes("Enable Watch access"));
    expect(enable).toBeTruthy();

    await act(async () => {
      enable?.click();
    });

    expect(getAuthorizeUrl).toHaveBeenCalledWith("watch");
    expect(assign).toHaveBeenCalledWith("http://localhost:8000/api/v1/google/oauth/authorize?profile=watch");

    vi.unstubAllGlobals();
    root.unmount();
  });

  it("starts a scan through the existing Watch API", async () => {
    mockedGetConnections.mockResolvedValue({
      oauth_configured: true,
      selected_scopes: [],
      connections: [{
        connection_id: "conn-1",
        provider: "GOOGLE",
        status: "CONNECTED",
        granted_scopes: [],
        watch_authorized: true,
        last_validated_at: "2026-08-14T12:00:00Z",
        disconnected_at: null,
      }],
    });
    mockedListWatches.mockResolvedValue({ watches: [watchRoot()] });
    mockedListWatchRules.mockResolvedValue({ rules: [rule] });
    mockedListWatchScans.mockResolvedValue({ scans: [scan] });
    mockedListWatchScanItems.mockResolvedValue({ items: [scanItem()] });
    mockedListWatchRuns.mockResolvedValue({ runs: [runSummary()] });

    const { container, root } = await renderWatch();
    const scanButton = [...container.querySelectorAll("button")].find((button) => button.textContent === "Scan now");
    expect(scanButton).toBeTruthy();

    await act(async () => {
      scanButton?.click();
      await Promise.resolve();
    });
    await flushEffects();

    expect(mockedTriggerWatchScan).toHaveBeenCalledWith("watch-1");
    root.unmount();
  });

  it("opens a pending Watch document in the normal conversation", async () => {
    mockedGetConnections.mockResolvedValue({
      oauth_configured: true,
      selected_scopes: [],
      connections: [{
        connection_id: "conn-1",
        provider: "GOOGLE",
        status: "CONNECTED",
        granted_scopes: [],
        watch_authorized: true,
        last_validated_at: "2026-08-14T12:00:00Z",
        disconnected_at: null,
      }],
    });
    mockedListWatches.mockResolvedValue({ watches: [watchRoot()] });
    mockedListWatchRules.mockResolvedValue({ rules: [rule] });
    mockedListWatchScans.mockResolvedValue({ scans: [scan] });
    mockedListWatchScanItems.mockResolvedValue({ items: [scanItem()] });
    mockedListWatchRuns.mockResolvedValue({ runs: [runSummary()] });

    const { container, root } = await renderWatch();
    expect(container.textContent).toContain("Vendor Agreement");
    expect(container.textContent).toContain("2 proposed changes");
    expect(container.textContent).toContain("Needs review");

    const open = [...container.querySelectorAll("button")].find((button) => button.textContent === "Open conversation");
    expect(open).toBeTruthy();

    await act(async () => {
      open?.click();
    });

    expect(peekQueuedRecentDocument()).toEqual({
      fileId: "file-vendor",
      name: "Vendor Agreement",
      mimeType: "application/vnd.google-apps.document",
    });
    expect(routerPush).toHaveBeenCalledWith("/");
    root.unmount();
  });

  it("keeps exact-file write authorization explicit and does not treat it as an error", async () => {
    mockedGetConnections.mockResolvedValue({
      oauth_configured: true,
      selected_scopes: [],
      connections: [{
        connection_id: "conn-1",
        provider: "GOOGLE",
        status: "CONNECTED",
        granted_scopes: [],
        watch_authorized: true,
        last_validated_at: "2026-08-14T12:00:00Z",
        disconnected_at: null,
      }],
    });
    mockedListWatches.mockResolvedValue({ watches: [watchRoot()] });
    mockedListWatchRules.mockResolvedValue({ rules: [rule] });
    mockedListWatchScans.mockResolvedValue({ scans: [scan] });
    mockedListWatchScanItems.mockResolvedValue({ items: [scanItem()] });
    mockedListWatchRuns.mockResolvedValue({
      runs: [runSummary({
        write_back_status: "WRITE_AUTHORIZATION_REQUIRED",
        write_authorization_status: "REQUIRED",
        review_status: "REVIEWED",
        workflow_state: "READY_TO_COMMIT",
      })],
    });

    const { container, root } = await renderWatch();
    expect(container.textContent).toContain("Write access required");
    expect(container.textContent).toContain("authorize this exact document before write-back");
    expect(container.textContent).toContain("Authorize document");
    expect(container.textContent).not.toContain("workflow failure");
    expect([...container.querySelectorAll("button")].some((button) => button.textContent === "Authorize document")).toBe(true);
    root.unmount();
  });
});
