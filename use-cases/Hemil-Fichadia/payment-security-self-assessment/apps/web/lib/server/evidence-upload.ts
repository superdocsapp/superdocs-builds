import type { ExtractedEvidenceDocument } from "@payment-security-self-assessment/evidence";

export const MAX_UPLOAD_FILES = 3;
export const MAX_UPLOAD_FILE_BYTES = 100_000;

export interface UploadFileMetadata {
  name: string;
  size: number;
  type: string;
}

export interface TextEvidenceFile extends UploadFileMetadata {
  text(): Promise<string>;
}

export class EvidenceUploadError extends Error {
  constructor(message: string) {
    super(message);
  }
}

export function validateEvidenceFiles(files: readonly UploadFileMetadata[]): void {
  if (files.length === 0) throw new EvidenceUploadError("Select at least one plain-text evidence file.");
  if (files.length > MAX_UPLOAD_FILES) throw new EvidenceUploadError(`Upload at most ${MAX_UPLOAD_FILES} files.`);

  for (const file of files) {
    if (!file.name.toLowerCase().endsWith(".txt") || (file.type && file.type !== "text/plain")) {
      throw new EvidenceUploadError("Only plain-text (.txt) files are supported.");
    }
    if (file.size > MAX_UPLOAD_FILE_BYTES) {
      throw new EvidenceUploadError("Each evidence file must be 100 KB or smaller.");
    }
  }
}

export async function extractTextEvidenceFiles(
  files: readonly TextEvidenceFile[],
): Promise<ExtractedEvidenceDocument[]> {
  validateEvidenceFiles(files);
  return Promise.all(
    files.map(async (file, index) => ({
      id: `upload-${index + 1}`,
      name: file.name,
      text: await file.text(),
    })),
  );
}
