import { NextResponse } from "next/server";
import { listTemplates, uploadTemplate } from "@/lib/superdocs";

export async function GET() {
  try {
    const templates = await listTemplates();
    return NextResponse.json({ templates });
  } catch (err) {
    return NextResponse.json(
      { error: err instanceof Error ? err.message : "Failed to list templates" },
      { status: 502 },
    );
  }
}

export async function POST(req: Request) {
  const form = await req.formData();
  const file = form.get("file");

  if (!(file instanceof File)) {
    return NextResponse.json({ error: "file is required" }, { status: 400 });
  }

  try {
    const template = await uploadTemplate(file);
    return NextResponse.json(template);
  } catch (err) {
    return NextResponse.json(
      { error: err instanceof Error ? err.message : "Failed to upload template" },
      { status: 502 },
    );
  }
}
