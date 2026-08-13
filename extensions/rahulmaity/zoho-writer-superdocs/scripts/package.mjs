import { existsSync, mkdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import process from "node:process";
import AdmZip from "adm-zip";

const root = process.cwd();
const manifestPath = join(root, "app", "plugin-manifest.json");
const distPath = join(root, "dist");
const releasePath = join(root, "release");
const manifestText = readFileSync(manifestPath, "utf8");
const manifest = JSON.parse(manifestText);
const workspaceMode = process.argv.includes("--workspace");
const overlayPath =
  process.env.SIGMA_CONNECTOR_OVERLAY ??
  join(root, "config", "connector.workspace.json");
const modeName = workspaceMode ? "workspace" : "source";
const outputPath = join(
  releasePath,
  `zoho-writer-superdocs-${modeName}.zip`,
);

const assertNoSecrets = (value, path = "manifest") => {
  if (typeof value === "string") {
    if (/\bsk_[A-Za-z0-9_-]{12,}\b/.test(value) || /\bBearer\s+\S+/i.test(value)) {
      throw new Error(`Refusing credential-looking value at ${path}.`);
    }
    return;
  }
  if (Array.isArray(value)) {
    value.forEach((item, index) => assertNoSecrets(item, `${path}[${index}]`));
    return;
  }
  if (!value || typeof value !== "object") return;
  for (const [key, child] of Object.entries(value)) {
    if (
      /^(api_?key|access_?token|refresh_?token|client_?secret|password|secret|credentials?)$/i.test(
        key,
      )
    ) {
      throw new Error(`Refusing credential field at ${path}.${key}.`);
    }
    assertNoSecrets(child, `${path}.${key}`);
  }
};

assertNoSecrets(manifest);
if ("connectors" in manifest) {
  throw new Error("The checked-in source manifest must not contain connectors.");
}

if (workspaceMode) {
  if (!existsSync(overlayPath)) {
    throw new Error(
      `Workspace package requires ignored connector overlay: ${overlayPath}`,
    );
  }
  const overlay = JSON.parse(readFileSync(overlayPath, "utf8"));
  assertNoSecrets(overlay, "connectorOverlay");
  if (!Array.isArray(overlay.connectors) || overlay.connectors.length === 0) {
    throw new Error("Connector overlay must contain a non-empty connectors array.");
  }
  if (
    !overlay.connectors.some(
      (connector) => connector?.connectionLinkName === "superdocsapi",
    )
  ) {
    throw new Error("Connector overlay must define connectionLinkName superdocsapi.");
  }
  manifest.connectors = overlay.connectors;
}

// Sigma's ZIP importer requires plugin-manifest.json at archive root, but Writer
// resolves widget url/icon/logo relative to app/. Both constraints hold at once,
// so manifest paths stay app-relative while assets ship under app/.
mkdirSync(releasePath, { recursive: true });
const zip = new AdmZip();
zip.addFile(
  "plugin-manifest.json",
  Buffer.from(`${JSON.stringify(manifest, null, 2)}\n`),
);
zip.addLocalFolder(distPath, "app");
zip.writeZip(outputPath);

const packaged = new AdmZip(outputPath);
const entries = new Set(packaged.getEntries().map((entry) => entry.entryName));
const widget = manifest.modules?.widgets?.[0];
const required = [
  "plugin-manifest.json",
  ...[widget?.url, widget?.icon, widget?.logo]
    .filter((value) => typeof value === "string")
    .map((value) => `app/${value}`),
].filter((value) => typeof value === "string");

for (const entry of required) {
  if (!entries.has(entry)) {
    throw new Error(`Sigma package is missing manifest target: ${entry}`);
  }
}
if ([...entries].some((entry) => entry.includes(".env"))) {
  throw new Error("Sigma package must not contain environment files.");
}
if ([...entries].some((entry) => entry.endsWith("connector.workspace.json"))) {
  throw new Error("Sigma package must not contain the connector overlay file.");
}
if (!entries.has("app/index.html")) {
  throw new Error("Sigma package is missing app/index.html.");
}
const validatedManifest = JSON.parse(
  packaged.readAsText("plugin-manifest.json"),
);
for (const packagedWidget of validatedManifest.modules?.widgets ?? []) {
  for (const field of ["url", "icon", "logo"]) {
    if (packagedWidget[field]?.startsWith("app/")) {
      throw new Error(
        `Widget ${field} must be relative to app/, not prefixed with app/.`,
      );
    }
  }
}
if (workspaceMode !== Array.isArray(validatedManifest.connectors)) {
  throw new Error("Packaged connector mode does not match the requested mode.");
}

console.log(
  workspaceMode
    ? `Created workspace-specific Sigma bundle: ${outputPath}`
    : `Created source import bundle (not directly installable): ${outputPath}`,
);
console.log(`Validated ${entries.size} packaged files.`);
