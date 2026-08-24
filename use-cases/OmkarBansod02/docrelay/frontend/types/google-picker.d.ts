/**
 * Minimal type declarations for Google Picker API and Google Identity Services
 * used by DocRelay's Picker integration. These cover only the subset we use.
 */

declare namespace google.picker {
  // String literal constants instead of const enum for isolatedModules compatibility
  type ActionType = "cancel" | "error" | "loaded" | "picked";
  type ResponseKey = "action" | "docs";
  type DocumentKey = "id" | "name" | "mimeType" | "url";
  type ViewIdType = "all" | "documents" | "spreadsheets";
  type FeatureType = "navHidden" | "multiselectEnabled";

  // Namespaced constants as objects
  const Action: {
    readonly CANCEL: "cancel";
    readonly ERROR: "error";
    readonly LOADED: "loaded";
    readonly PICKED: "picked";
  };

  const Response: {
    readonly ACTION: "action";
    readonly DOCUMENTS: "docs";
  };

  const Document: {
    readonly ID: "id";
    readonly NAME: "name";
    readonly MIME_TYPE: "mimeType";
    readonly URL: "url";
  };

  const ViewId: {
    readonly DOCS: "all";
    readonly DOCUMENTS: "documents";
    readonly SPREADSHEETS: "spreadsheets";
  };

  const Feature: {
    readonly NAV_HIDDEN: "navHidden";
    readonly MULTISELECT_ENABLED: "multiselectEnabled";
  };

  interface PickerDocument {
    id: string;
    name: string;
    mimeType: string;
    url: string;
  }

  interface ResponseObject {
    action: ActionType;
    docs?: PickerDocument[];
  }

  class DocsView {
    constructor(viewId?: ViewIdType);
    setMimeTypes(mimeTypes: string): DocsView;
    setMode(mode: unknown): DocsView;
    setIncludeFolders(included: boolean): DocsView;
    setSelectFolderEnabled(enabled: boolean): DocsView;
  }

  class PickerBuilder {
    addView(viewOrId: ViewIdType | DocsView): PickerBuilder;
    setOAuthToken(token: string): PickerBuilder;
    setDeveloperKey(key: string): PickerBuilder;
    setAppId(appId: string): PickerBuilder;
    setCallback(callback: (data: ResponseObject) => void): PickerBuilder;
    setOrigin(origin: string): PickerBuilder;
    enableFeature(feature: FeatureType): PickerBuilder;
    disableFeature(feature: FeatureType): PickerBuilder;
    setTitle(title: string): PickerBuilder;
    build(): Picker;
  }

  interface Picker {
    setVisible(visible: boolean): void;
    dispose(): void;
  }
}

declare namespace google.accounts.oauth2 {
  interface TokenClientConfig {
    client_id: string;
    scope: string;
    callback: ((response: TokenResponse) => void) | string;
    error_callback?: (error: { type: string; message?: string }) => void;
  }

  interface TokenResponse {
    access_token: string;
    token_type: string;
    expires_in: number;
    scope: string;
    error?: string;
    error_description?: string;
  }

  interface TokenClient {
    requestAccessToken(config?: { prompt?: string }): void;
    callback: ((response: TokenResponse) => void) | string;
  }

  function initTokenClient(config: TokenClientConfig): TokenClient;

  function revoke(token: string, callback?: () => void): void;
}

declare namespace gapi {
  function load(libraries: string, callback: () => void): void;
}

interface Window {
  google?: {
    picker?: typeof google.picker;
    accounts?: {
      oauth2?: typeof google.accounts.oauth2;
    };
  };
  gapi?: typeof gapi;
}
