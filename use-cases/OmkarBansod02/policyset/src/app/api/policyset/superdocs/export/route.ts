import { Buffer } from "node:buffer";

import {
  exportPolicyDocument,
  type PolicyDocumentExport,
} from "@/superdocs";
import {
  readJsonObject,
  requiredDocumentIds,
  requiredExportFormat,
  requiredPolicyDocumentType,
  requiredString,
  routeError,
} from "../http";

export const runtime = "nodejs";

export async function POST(request: Request) {
  try {
    const body = await readJsonObject(request);
    const result = await exportPolicyDocument({
      sessionId: requiredString(body, "sessionId"),
      documentType: requiredPolicyDocumentType(body.documentType),
      documentId: requiredString(body, "documentId"),
      documentIds: requiredDocumentIds(body.documentIds),
      format: requiredExportFormat(body.format),
      companyName: requiredString(body, "companyName"),
    });
    return buildPolicyExportResponse(result);
  } catch (error) {
    return routeError(error);
  }
}

export function buildPolicyExportResponse({
  artifact,
  filename,
}: PolicyDocumentExport): Response {
  const headers = new Headers({
    "Cache-Control": "no-store",
    "Content-Disposition": `attachment; filename="${filename}"`,
    "Content-Length": String(artifact.sizeBytes),
    "Content-Type": artifact.contentType,
    "X-Content-Type-Options": "nosniff",
    "X-SuperDocs-Export-Warning-Count": String(artifact.warnings.length),
  });
  if (artifact.warnings.length > 0) {
    headers.set(
      "X-SuperDocs-Export-Warnings",
      Buffer.from(JSON.stringify(artifact.warnings), "utf8").toString("base64url"),
    );
  }

  return new Response(Buffer.from(artifact.bytes), { status: 200, headers });
}
