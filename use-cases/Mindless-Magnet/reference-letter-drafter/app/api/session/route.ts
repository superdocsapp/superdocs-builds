import { NextResponse } from "next/server";
import { uploadStarterDocument } from "@/lib/superdocs";

export async function POST() {
  const sessionId = `ref-letter-${crypto.randomUUID()}`;
  try {
    const upload = await uploadStarterDocument(sessionId);
    return NextResponse.json({ sessionId, upload });
  } catch (err) {
    return NextResponse.json(
      { error: err instanceof Error ? err.message : "Failed to start session" },
      { status: 502 },
    );
  }
}
