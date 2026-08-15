type RowValue = string | number | boolean | Date | null;

type RosterRow = {
  rowNumber: number;
  values: Record<string, RowValue>;
};

type TemplateDefinition = {
  id: string;
  name: string;
  aliases: string[];
  keywords: string[];
  fileName: string;
};

type RoutingResult = {
  templateId: string;
  templateName: string;
  confidence: number;
  method: "configured" | "dynamic" | "exact" | "alias" | "keyword" | "general";
};

type DynamicTemplateRecord = {
  profile: string;
  templateId: string;
  templateName: string;
};

type GenerationResult = {
  rowNumber: number;
  status: "success" | "failed";
  idempotencyKey?: string;
  templateId?: string;
  documentUrl?: string;
  emailed?: boolean;
  emailError?: string;
  error?: string;
};

type JobState = {
  jobId: string;
  spreadsheetId: string;
  sheetName: string;
  outputColumn: number;
  status: "preview" | "running" | "completed" | "failed" | "cancelled";
  startRow: number;
  nextRow: number;
  endRow: number;
  totalRows: number;
  completedRows: number;
  currentRow?: number;
  currentAction?: string;
  lastCompletedRow?: number;
  emailEnabled: boolean;
  updatedAt: number;
  results: GenerationResult[];
};
