"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { IconBook } from "./icons";

// v2 has no single global campaign anymore -- Review/Export/Coherence all
// live inside a campaign's own workspace (/campaigns/[id], as tabs), not as
// top-level routes. The only fixed top-level destination is the campaign
// list/home.
export default function NavTabs() {
  const pathname = usePathname();
  const active = pathname === "/";
  return (
    <nav className="tabs">
      <Link href="/" className={active ? "active" : ""}>
        <IconBook size={14} />
        Campaigns
      </Link>
    </nav>
  );
}
