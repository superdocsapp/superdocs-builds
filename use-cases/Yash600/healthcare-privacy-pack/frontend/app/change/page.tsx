"use client";

// Superseded by /w/[workspaceId]/update. Kept as a redirect since this
// sandbox can't delete the file outright.

import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function ChangeRedirect() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/");
  }, [router]);
  return <div className="empty">Redirecting to your workspaces...</div>;
}
