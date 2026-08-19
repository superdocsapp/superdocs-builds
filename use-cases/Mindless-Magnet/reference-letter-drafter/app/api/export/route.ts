import { NextResponse } from "next/server";
import { exportDocument } from "@/lib/superdocs";
import { errorResponse, badRequest } from "@/lib/server/respond";

/** Strip anything that could escape the Content-Disposition header. */
function safeFilename(input: string | undefined): string {
  const base = (input ?? "reference-letter")
    .normalize("NFKD")
    .replace(/[^a-zA-Z0-9._-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 100);
  return base || "reference-letter";
}

export async function POST(req: Request) {
  let body: { sessionId?: string; filename?: string };
  try {
    body = await req.json();
  } catch {
    return badRequest("Send a JSON body with sessionId.");
  }

  if (!body.sessionId) return badRequest("sessionId is required.");

  const filename = safeFilename(body.filename);

  try {
    const { body: bytes, contentType, warnings } = await exportDocument({
      sessionId: body.sessionId,
      filename,
    });

    return new NextResponse(bytes, {
      status: 200,
      headers: {
        "Content-Type": contentType,
        "Content-Disposition": `attachment; filename="${filename}.docx"`,
        // Surfaced rather than swallowed: a fidelity warning on an export the
        // user is about to send to an admissions office is worth knowing.
        "X-Export-Warning-Count": String(warnings.length),
      },
    });
  } catch (err) {
    return errorResponse(err, "Exporting the letter");
  }
}
