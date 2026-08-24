export type SuperDocsOperation =
  | "edit"
  | "insert"
  | "delete";

export interface SuperDocsChange {
  changeId: string;
  operation: SuperDocsOperation;
  from?: number;
  to?: number;
  oldText?: string;
  newText?: string;
  explanation?: string;
}

export interface SuperDocsEditRequest {
  sessionId: string;
  documentHtml: string;
  instruction: string;
}

export interface SuperDocsEditResult {
  updatedHtml: string;
  changes: SuperDocsChange[];
  versionId?: string;
}

export interface SuperDocsClient {
  edit(
    request: SuperDocsEditRequest
  ): Promise<SuperDocsEditResult>;
}

export interface SuperDocsPluginState {
  isProcessing: boolean;
  error: string | null;
  lastChanges: SuperDocsChange[];
}