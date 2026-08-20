"use client";

// Superseded by /w/[workspaceId]/update, which now combines submitting an
// update and reviewing pending proposed changes on one screen. Kept as a
// redirect since this sandbox can't delete the file outright.

import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function ReviewRedirect() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/");
  }, [router]);
  return <div className="empty">Redirecting to your workspaces...</div>;
}
