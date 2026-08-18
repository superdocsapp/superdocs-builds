import { NextResponse } from "next/server";
import { exportDocument } from "@/lib/superdocs";

interface ExportRequestBody {
  sessionId: string;
  filename?: string;
}

export async function POST(req: Request) {
  const body = (await req.json()) as ExportRequestBody;

  if (!body.sessionId) {
    return NextResponse.json({ error: "sessionId is required" }, { status: 400 });
  }

  try {
    const { blob, contentType } = await exportDocument({
      sessionId: body.sessionId,
      filename: body.filename ?? "reference-letter",
    });

    return new NextResponse(blob, {
      status: 200,
      headers: {
        "Content-Type": contentType,
        "Content-Disposition": `attachment; filename="${body.filename ?? "reference-letter"}.docx"`,
      },
    });
  } catch (err) {
    return NextResponse.json(
      { error: err instanceof Error ? err.message : "Failed to export document" },
      { status: 502 },
    );
  }
}
