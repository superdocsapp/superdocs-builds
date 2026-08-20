"use client";

import { Menu, X, User, Search } from "lucide-react";
import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { cn } from "@/lib/utils";
import { seedDemo } from "@/lib/api/submittals";
import { useToast } from "@/components/ui/Toast";
import { PROJECT_ID, PROJECT_NAME } from "@/lib/constants";
import { ProjectAssistantModal } from "./ProjectAssistantModal";

const mobileNav = [
  { href: "/overview", label: "Overview" },
  { href: "/projects", label: "Projects" },
  { href: "/register", label: "Register" },
  { href: "/transmittals", label: "Transmittals" },
  { href: "/reports", label: "Reports" },
  { href: "/how-it-works", label: "How It Works" },
  { href: "/settings", label: "Settings" },
];

export function Header() {
  const pathname = usePathname();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [assistantOpen, setAssistantOpen] = useState(false);
  const reviewer = process.env.NEXT_PUBLIC_DEV_REVIEWER ?? "Reviewer";
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const seedMutation = useMutation({
    mutationFn: () => seedDemo(PROJECT_ID),
    onSuccess: (data) => {
      toast({
        title: "Demo data seeded.",
        description: `${data.items_count} submittals created.`,
        variant: "success",
      });
      queryClient.invalidateQueries({ queryKey: ["register"] });
      queryClient.invalidateQueries({ queryKey: ["overdue"] });
    },
    onError: (err: Error) => {
      toast({
        title: "Seed failed.",
        description: err.message,
        variant: "error",
      });
    },
  });

  return (
    <>
      <header className="sticky top-0 z-30 flex h-14 items-center border-b border-slate-200 bg-white px-4 gap-3">
        {/* Mobile logo */}
        <Link href="/overview" className="flex items-center gap-2 lg:hidden">
          <span className="flex h-6 w-6 items-center justify-center rounded bg-slate-800 text-[10px] font-bold text-white">
            SF
          </span>
          <span className="text-sm font-semibold text-slate-900">SubmittalFlow</span>
        </Link>

        {/* Project identifier — desktop */}
        <div className="hidden lg:flex items-center gap-2 text-sm">
          <span className="font-medium text-slate-700">{PROJECT_NAME}</span>
          <span className="text-slate-300">·</span>
          <span className="font-mono text-xs text-slate-400">{PROJECT_ID}</span>
        </div>

        <div className="flex-1" />

        {/* Search button */}
        <button
          onClick={() => setAssistantOpen(true)}
          className="inline-flex items-center gap-1.5 rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
          aria-label="Open search and project assistant"
        >
          <Search className="h-3.5 w-3.5" />
          <span className="hidden sm:inline">Search</span>
        </button>

        {/* Seed Demo Dataset */}
        <button
          onClick={() => seedMutation.mutate()}
          disabled={seedMutation.isPending}
          className="inline-flex items-center gap-1.5 rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 disabled:opacity-50"
          title="Seed demo dataset: Scenario A (Flooring), Scenario B (Fire Doors), Overdue item"
        >
          {seedMutation.isPending ? "Seeding…" : "Seed Demo"}
        </button>

        {/* Reviewer */}
        <div className="hidden items-center gap-2 text-sm text-slate-500 lg:flex pl-2 border-l border-slate-200">
          <User className="h-4 w-4" aria-hidden />
          <span className="text-xs">{reviewer}</span>
        </div>

        {/* Mobile menu toggle */}
        <button
          className="ml-2 rounded p-1.5 text-slate-500 hover:bg-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 lg:hidden"
          onClick={() => setMobileOpen((v) => !v)}
          aria-expanded={mobileOpen}
          aria-label={mobileOpen ? "Close navigation menu" : "Open navigation menu"}
        >
          {mobileOpen ? (
            <X className="h-5 w-5" aria-hidden />
          ) : (
            <Menu className="h-5 w-5" aria-hidden />
          )}
        </button>

        {/* Mobile nav overlay */}
        {mobileOpen && (
          <div className="absolute inset-x-0 top-14 z-40 border-b border-slate-200 bg-white shadow-md lg:hidden">
            <nav aria-label="Mobile navigation">
              <ul className="py-2 px-3 space-y-0.5">
                {mobileNav.map(({ href, label }) => {
                  const active = pathname === href || pathname.startsWith(href + "/");
                  return (
                    <li key={href}>
                      <Link
                        href={href}
                        onClick={() => setMobileOpen(false)}
                        className={cn(
                          "block rounded-md px-3 py-2 text-sm transition-colors",
                          active
                            ? "bg-slate-100 text-slate-900 font-medium"
                            : "text-slate-600 hover:bg-slate-50",
                        )}
                        aria-current={active ? "page" : undefined}
                      >
                        {label}
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </nav>
          </div>
        )}
      </header>

      <ProjectAssistantModal
        open={assistantOpen}
        onClose={() => setAssistantOpen(false)}
      />
    </>
  );
}
