import { NavLink } from "react-router-dom";
import clsx from "clsx";
import { ClipboardCheck, FileText, History, LayoutDashboard, Search, ShieldAlert } from "lucide-react";
import { useAppStore } from "../../store/appStore";

const NAV_ITEMS = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/command-center", label: "Command Center", icon: Search, end: false },
  { to: "/documents", label: "Documents", icon: FileText, end: false },
  { to: "/reviews", label: "Reviews", icon: ClipboardCheck, end: false },
  { to: "/risks", label: "Risks", icon: ShieldAlert, end: false },
  { to: "/audit", label: "Audit", icon: History, end: false },
] as const;

export function SidebarContent({ onNavigate }: { onNavigate?: () => void }) {
  const toggleCommandPalette = useAppStore((s) => s.toggleCommandPalette);

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2.5 px-5 py-5">
        <div className="flex h-7 w-7 items-center justify-center rounded-md border border-white/15 text-sm font-bold text-text-on-ink">S</div>
        <div className="min-w-0">
          <p className="text-sm font-semibold tracking-tight text-text-on-ink">SuperDocs</p>
          <p className="truncate text-[11px] text-text-on-ink-dim">Document Reality Engine</p>
        </div>
      </div>

      <nav className="flex-1 space-y-0.5 px-3" aria-label="Primary">
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            onClick={onNavigate}
            className={({ isActive }) =>
              clsx(
                "flex items-center gap-2.5 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                isActive ? "bg-white/10 text-text-on-ink" : "text-text-on-ink-dim hover:bg-white/5 hover:text-text-on-ink",
              )
            }
          >
            <item.icon className="h-4 w-4" aria-hidden="true" />
            {item.label}
          </NavLink>
        ))}
      </nav>

      <div className="border-t border-white/10 p-3">
        <button
          onClick={() => {
            onNavigate?.();
            toggleCommandPalette();
          }}
          className="flex w-full items-center justify-between rounded-md border border-white/10 px-3 py-2 text-xs text-text-on-ink-dim transition-colors hover:bg-white/5 hover:text-text-on-ink"
        >
          <span className="flex items-center gap-2">
            <Search className="h-3.5 w-3.5" aria-hidden="true" />
            Ask SuperDocs
          </span>
          <kbd className="font-numeric rounded border border-white/15 px-1 text-[10px]">⌘K</kbd>
        </button>
      </div>
    </div>
  );
}

export function Sidebar() {
  return (
    <aside className="hidden w-60 shrink-0 bg-ink-950 md:block">
      <SidebarContent />
    </aside>
  );
}
