import { NextResponse } from "next/server";
import { getUsage } from "@/lib/superdocs";

export async function GET() {
  // getUsage never throws: the meter being unreadable must not block a draft.
  return NextResponse.json(await getUsage());
}
