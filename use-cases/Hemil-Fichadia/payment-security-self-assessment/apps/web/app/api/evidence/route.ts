import { classifyExtractedEvidence } from "@payment-security-self-assessment/evidence";
import {
  EvidenceUploadError,
  extractTextEvidenceFiles,
} from "@/lib/server/evidence-upload";

export const runtime = "nodejs";

export async function POST(request: Request) {
  try {
    const formData = await request.formData();
    const files = formData.getAll("files");
    if (!files.every((value) => value instanceof File)) {
      throw new EvidenceUploadError("Uploaded evidence must be files.");
    }

    const documents = await extractTextEvidenceFiles(files);
    const facts = classifyExtractedEvidence(documents);
    return Response.json({ files: documents.map(({ id, name }) => ({ id, name })), facts });
  } catch (error) {
    const message = error instanceof EvidenceUploadError ? error.message : "Unable to process evidence files.";
    return Response.json({ error: message }, { status: 400 });
  }
}
