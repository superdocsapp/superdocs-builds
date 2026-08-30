import { useEffect, useState } from "react";
import { Outlet } from "react-router-dom";
import { Menu, Search, User } from "lucide-react";
import { Sidebar, SidebarContent } from "./Sidebar";
import { Drawer } from "../ui/Drawer";
import { ToastViewport } from "../ui/Toast";
import { CommandPalette } from "../command-center/CommandPalette";
import { useAppStore } from "../../store/appStore";
import { CURRENT_USER } from "../../data/constants";

export function AppShell() {
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const toggleCommandPalette = useAppStore((s) => s.toggleCommandPalette);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        toggleCommandPalette();
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [toggleCommandPalette]);

  return (
    <div className="flex h-screen overflow-hidden bg-paper-50">
      <a
        href="#main-content"
        className="sr-only rounded-md bg-trust px-3 py-2 text-sm font-medium text-white focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[100]"
      >
        Skip to content
      </a>

      <Sidebar />

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-3 border-b border-line bg-paper-0 px-4 py-3 md:px-6">
          <button
            className="rounded-md p-1.5 text-text-secondary transition-colors hover:bg-paper-100 md:hidden"
            onClick={() => setMobileNavOpen(true)}
            aria-label="Open navigation"
          >
            <Menu className="h-5 w-5" aria-hidden="true" />
          </button>

          <button
            onClick={toggleCommandPalette}
            className="flex max-w-md flex-1 items-center gap-2 rounded-md border border-line bg-paper-50 px-3 py-1.5 text-left text-sm text-text-tertiary transition-colors hover:border-line-strong"
          >
            <Search className="h-4 w-4 shrink-0" aria-hidden="true" />
            <span className="truncate">Search documents, claims, evidence…</span>
            <kbd className="font-numeric ml-auto hidden shrink-0 rounded border border-line-strong bg-paper-0 px-1.5 py-0.5 text-[10px] sm:inline">⌘K</kbd>
          </button>

          <div className="ml-auto flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-trust-soft text-trust" title={CURRENT_USER}>
            <User className="h-4 w-4" aria-hidden="true" />
          </div>
        </header>

        <main id="main-content" className="flex-1 overflow-y-auto">
          <Outlet />
        </main>
      </div>

      <Drawer open={mobileNavOpen} onClose={() => setMobileNavOpen(false)} title="Navigation">
        <div className="h-full bg-ink-950">
          <SidebarContent onNavigate={() => setMobileNavOpen(false)} />
        </div>
      </Drawer>

      <CommandPalette />
      <ToastViewport />
    </div>
  );
}
