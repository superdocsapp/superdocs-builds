"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { IconSparkle, IconFileText, IconEyeCheck, IconDownload } from "./icons";

const TABS = (workspaceId: string) => [
  { href: `/w/${workspaceId}/update`, label: "Update", Icon: IconSparkle },
  { href: `/w/${workspaceId}/report`, label: "Report", Icon: IconFileText },
  { href: `/w/${workspaceId}/review`, label: "Review", Icon: IconEyeCheck },
  { href: `/w/${workspaceId}/export`, label: "Export", Icon: IconDownload },
];

export default function NavTabs({ workspaceId }: { workspaceId: string }) {
  const pathname = usePathname();
  const tabs = TABS(workspaceId);
  return (
    <nav className="tabs">
      {tabs.map(({ href, label, Icon }) => {
        const active = pathname.startsWith(href);
        return (
          <Link key={href} href={href} className={active ? "active" : ""}>
            <Icon size={14} /> {label}
          </Link>
        );
      })}
    </nav>
  );
}
