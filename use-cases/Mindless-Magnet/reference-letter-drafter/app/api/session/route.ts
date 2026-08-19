import { NextResponse } from "next/server";
import { uploadStarterDocument } from "@/lib/superdocs";
import { errorResponse } from "@/lib/server/respond";

export async function POST() {
  const sessionId = `ref-letter-${crypto.randomUUID()}`;
  try {
    const upload = await uploadStarterDocument(sessionId);
    return NextResponse.json({ sessionId, chunks: upload.chunks_count });
  } catch (err) {
    return errorResponse(err, "Starting a document session");
  }
}
