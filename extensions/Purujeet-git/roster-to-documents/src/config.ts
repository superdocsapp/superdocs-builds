var CONFIG = {
  SUPERDOCS_BASE_URL: "https://api.superdocs.app",
  API_KEY_PROPERTY: "SUPERDOCS_API_KEY",
  OUTPUT_FOLDER_PROPERTY: "OUTPUT_FOLDER_ID",
  TEMPLATE_FOLDER_PROPERTY: "TEMPLATE_FOLDER_ID",
  TEMPLATE_PROPERTY: "ROSTER_TEMPLATE",
  JOB_PROPERTY_PREFIX: "ROSTER_JOB_",
  TEMPLATE_PREFIX: "ROSTER_TEMPLATE_",
  DYNAMIC_TEMPLATE_MAP_PROPERTY: "ROSTER_DYNAMIC_TEMPLATE_MAP",
  DEFAULT_OUTPUT_HEADER: "Document Link",
  DEFAULT_STATUS_HEADER: "Document Status",
  DEFAULT_TEMPLATE_HEADER: "Template Used",
  DEFAULT_IDEMPOTENCY_HEADER: "Document Idempotency Key",
  // Process one row per trigger so the sidebar can report each link as soon as it is written.
  DEFAULT_BATCH_SIZE: 1,
  MAX_ROWS_PER_JOB: 500,
  EMAIL_ENABLED_PROPERTY: "EMAIL_ENABLED"
};

function getScriptProperty(key: string): string {
  return PropertiesService.getScriptProperties().getProperty(key) || "";
}

function requireSuperDocsApiKey(): string {
  var key = getScriptProperty(CONFIG.API_KEY_PROPERTY);
  if (!key) {
    throw new Error("SUPERDOCS_API_KEY is not configured in Script Properties.");
  }
  return key;
}

function isEmailEnabledByDefault(): boolean {
  return getScriptProperty(CONFIG.EMAIL_ENABLED_PROPERTY).toLowerCase() === "true";
}
