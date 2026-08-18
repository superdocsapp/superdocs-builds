import { NextResponse } from "next/server";
import { getJobStatus } from "@/lib/superdocs";

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ jobId: string }> },
) {
  const { jobId } = await params;
  try {
    const job = await getJobStatus(jobId);
    return NextResponse.json(job);
  } catch (err) {
    return NextResponse.json(
      { error: err instanceof Error ? err.message : "Failed to fetch job status" },
      { status: 502 },
    );
  }
}
