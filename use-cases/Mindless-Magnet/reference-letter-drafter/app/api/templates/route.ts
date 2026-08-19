import { NextResponse } from "next/server";
import { listTemplates, uploadTemplate } from "@/lib/superdocs";
import { errorResponse, badRequest } from "@/lib/server/respond";

const MAX_TEMPLATE_BYTES = 10 * 1024 * 1024;
const ALLOWED = new Set([
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "application/pdf",
  "text/html",
  "text/plain",
  "text/markdown",
]);

export async function GET() {
  try {
    return NextResponse.json({ templates: await listTemplates() });
  } catch (err) {
    return errorResponse(err, "Listing your templates");
  }
}

export async function POST(req: Request) {
  const form = await req.formData().catch(() => null);
  const file = form?.get("file");

  if (!(file instanceof File)) return badRequest("Attach a file under the 'file' field.");
  if (file.size === 0) return badRequest("That file is empty.");
  if (file.size > MAX_TEMPLATE_BYTES) {
    return badRequest(`That file is ${(file.size / 1024 / 1024).toFixed(1)}MB. The limit is 10MB.`);
  }
  if (file.type && !ALLOWED.has(file.type)) {
    return badRequest(`Templates must be .docx, .pdf, .html, .txt or .md. That file is ${file.type}.`);
  }

  try {
    return NextResponse.json(await uploadTemplate(file));
  } catch (err) {
    return errorResponse(err, "Uploading your template");
  }
}
