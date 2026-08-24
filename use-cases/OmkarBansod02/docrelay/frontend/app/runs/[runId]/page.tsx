import { RunDetailWorkspace } from "../../components/run-detail-workspace";

export default async function RunDetailPage({ params }: { params: Promise<{ runId: string }> }) {
  const { runId } = await params;
  return <RunDetailWorkspace runId={runId} />;
}
