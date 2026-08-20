"use client";

// This flat route is superseded by /w/[workspaceId]/update -- every action
// in the rebuilt app is scoped to a workspace now. Kept as a redirect
// (rather than deleted, which this sandbox would not permit) so an old
// bookmark lands somewhere useful instead of a stale screen.

import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function UpdateRedirect() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/");
  }, [router]);
  return <div className="empty">Redirecting to your workspaces...</div>;
}
