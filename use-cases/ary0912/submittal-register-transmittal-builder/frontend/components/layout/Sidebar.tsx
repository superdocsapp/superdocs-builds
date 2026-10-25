"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  FileStack,
  SendHorizonal,
  BarChart3,
  HelpCircle,
  Settings,
  FolderKanban,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { PROJECT_ID, PROJECT_NAME } from "@/lib/constants";

const nav = [
  { href: "/overview", label: "Overview", icon: LayoutDashboard },
  { href: "/projects", label: "Projects", icon: FolderKanban },
  { href: "/register", label: "Register", icon: FileStack },
  { href: "/transmittals", label: "Transmittals", icon: SendHorizonal },
  { href: "/reports", label: "Reports", icon: BarChart3 },
];

const secondary = [
  { href: "/how-it-works", label: "How It Works", icon: HelpCircle },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function Sidebar() {
  const pathname = usePathname();

  function isActive(href: string) {
    return pathname === href || pathname.startsWith(href + "/");
  }

  return (
    <aside className="hidden w-56 shrink-0 flex-col border-r border-slate-200 bg-white lg:flex">
      {/* Logo */}
      <div className="flex h-14 items-center border-b border-slate-200 px-5">
        <Link
          href="/overview"
          className="flex items-center gap-2.5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 rounded"
        >
          <span className="flex h-7 w-7 items-center justify-center rounded-md bg-slate-800 text-[11px] font-bold text-white tracking-tight">
            SF
          </span>
          <div>
            <p className="text-sm font-semibold text-slate-900 leading-none">
              SubmittalFlow
            </p>
            <p className="text-[10px] text-slate-400 leading-none mt-0.5">
              {PROJECT_ID}
            </p>
          </div>
        </Link>
      </div>

      {/* Primary Nav */}
      <nav className="flex-1 overflow-y-auto py-4 px-2" aria-label="Main navigation">
        <ul className="space-y-0.5" role="list">
          {nav.map(({ href, label, icon: Icon }) => {
            const active = isActive(href);
            return (
              <li key={href}>
                <Link
                  href={href}
                  className={cn(
                    "flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors",
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500",
                    active
                      ? "bg-slate-100 text-slate-900 font-medium"
                      : "text-slate-600 hover:bg-slate-50 hover:text-slate-900",
                  )}
                  aria-current={active ? "page" : undefined}
                >
                  <Icon className="h-4 w-4 shrink-0" aria-hidden />
                  {label}
                </Link>
              </li>
            );
          })}
        </ul>

        {/* Secondary Nav */}
        <div className="mt-6 border-t border-slate-100 pt-4">
          <ul className="space-y-0.5" role="list">
            {secondary.map(({ href, label, icon: Icon }) => {
              const active = isActive(href);
              return (
                <li key={href}>
                  <Link
                    href={href}
                    className={cn(
                      "flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors",
                      "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500",
                      active
                        ? "bg-slate-100 text-slate-900 font-medium"
                        : "text-slate-500 hover:bg-slate-50 hover:text-slate-700",
                    )}
                    aria-current={active ? "page" : undefined}
                  >
                    <Icon className="h-4 w-4 shrink-0" aria-hidden />
                    {label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      </nav>

      {/* Project info */}
      <div className="border-t border-slate-200 px-4 py-3 space-y-0.5">
        <p className="text-xs font-medium text-slate-700">
          {PROJECT_NAME}
        </p>
        <p className="text-[11px] text-slate-400">
          {PROJECT_ID}
        </p>
      </div>
    </aside>
  );
}
