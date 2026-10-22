import { Link, useLocation, Outlet, useNavigate } from "react-router-dom";
import { FolderKanban, Search, Settings, Shield, Sparkles, CheckCircle2, Command } from "lucide-react";
import { clsx } from "clsx";
import { ThemeToggle } from "@/components/ThemeToggle";
import { useEffect } from "react";

interface NavItem {
  label: string;
  path: string;
  icon: React.ElementType;
  badge?: string;
}

const navItems: NavItem[] = [
  { label: "Packets", path: "/", icon: FolderKanban },
  { label: "Packet Search", path: "/search", icon: Search },
  { label: "System Diagnostics", path: "/settings", icon: Settings },
];

export function Layout() {
  const location = useLocation();
  const navigate = useNavigate();

  // Keyboard shortcut listener: Cmd/Ctrl + K opens search
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        navigate("/search");
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [navigate]);

  const getPageTitle = () => {
    if (location.pathname === "/") return "Litigation Exhibit Packets";
    if (location.pathname.startsWith("/packets")) return "Packet Studio Workspace";
    if (location.pathname === "/search") return "E-Discovery Search Intelligence";
    if (location.pathname === "/settings") return "System Diagnostics";
    return "Litigation Suite";
  };

  return (
    <div className="flex h-screen w-screen overflow-hidden dark:bg-slate-950 bg-slate-50 dark:text-slate-100 text-slate-900 transition-colors duration-200">
      {/* Primary Sidebar */}
      <aside className="w-64 shrink-0 dark:bg-slate-900/95 bg-white dark:border-slate-800/80 border-slate-200 border-r flex flex-col justify-between backdrop-blur-xl z-30 transition-colors duration-200 shadow-sm">
        {/* Brand Header */}
        <div className="p-5 border-b dark:border-slate-800/80 border-slate-200 flex items-center gap-3">
          <div className="h-10 w-10 rounded-xl bg-gradient-to-tr from-sky-500 via-indigo-500 to-indigo-600 flex items-center justify-center text-white shadow-lg shadow-indigo-500/25">
            <Shield className="h-5 w-5" />
          </div>
          <div>
            <div className="font-display font-bold text-sm tracking-tight dark:text-white text-slate-900">
              SuperDocs<span className="text-sky-500">.</span>Legal
            </div>
            <p className="text-[11px] font-mono dark:text-slate-400 text-slate-500">
              Bates & Privilege Suite
            </p>
          </div>
        </div>

        {/* Navigation Section */}
        <nav className="flex-1 px-3 py-4 space-y-1.5 overflow-y-auto">
          <div className="px-3 py-1.5 text-[11px] font-semibold uppercase tracking-wider dark:text-slate-400 text-slate-500">
            Workspace
          </div>
          {navItems.map((item) => {
            const isActive = location.pathname === item.path;
            const Icon = item.icon;
            return (
              <Link
                key={item.path}
                to={item.path}
                className={clsx(
                  "flex items-center justify-between px-3 py-2.5 rounded-xl text-sm font-medium transition-all duration-150 group",
                  isActive
                    ? "dark:bg-gradient-to-r dark:from-sky-600/20 dark:to-indigo-600/20 dark:text-sky-400 dark:border-sky-500/30 bg-sky-50 text-sky-700 border border-sky-200 shadow-sm"
                    : "dark:text-slate-400 dark:hover:bg-slate-800/60 dark:hover:text-slate-200 text-slate-600 hover:bg-slate-100 hover:text-slate-900"
                )}
              >
                <div className="flex items-center gap-3">
                  <Icon className={clsx("h-4 w-4 transition-colors", isActive ? "text-sky-500" : "dark:text-slate-400 text-slate-500 group-hover:text-slate-900 dark:group-hover:text-slate-200")} />
                  <span>{item.label}</span>
                </div>
                {item.badge && (
                  <span className={clsx(
                    "text-[10px] font-mono px-1.5 py-0.5 rounded",
                    isActive
                      ? "dark:bg-sky-500/20 dark:text-sky-300 bg-sky-100 text-sky-700"
                      : "dark:bg-slate-800 dark:text-slate-400 bg-slate-100 text-slate-600"
                  )}>
                    {item.badge}
                  </span>
                )}
              </Link>
            );
          })}
        </nav>

        {/* Theme & System Capabilities Footer */}
        <div className="p-4 border-t dark:border-slate-800/80 border-slate-200/80 dark:bg-slate-950/40 bg-slate-50/50 space-y-3">
          <ThemeToggle className="w-full justify-between" id="sidebar-theme-toggle" />
          
          <div className="flex items-center justify-between text-xs dark:text-slate-400 text-slate-500 pt-1">
            <span className="flex items-center gap-1.5">
              <Sparkles className="h-3.5 w-3.5 text-indigo-500" />
              <span>SuperDocs HITL</span>
            </span>
            <span className="text-[10px] font-mono dark:bg-indigo-500/10 dark:text-indigo-300 dark:border-indigo-500/20 bg-indigo-50 text-indigo-700 border border-indigo-200 px-1.5 py-0.5 rounded">
              v1.0
            </span>
          </div>
          <div className="text-[11px] dark:text-slate-400 text-slate-500 text-center font-mono">
            SHA-256 Verified Packet Core
          </div>
        </div>
      </aside>

      {/* Main Workspace Area with Header Navbar */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* Top Navbar */}
        <header className="h-14 shrink-0 dark:bg-slate-900/80 bg-white/80 dark:border-slate-800/80 border-slate-200/80 border-b backdrop-blur-md px-6 flex items-center justify-between gap-4 z-20 transition-colors duration-200">
          <div className="flex items-center gap-3 min-w-0">
            <span className="text-sm font-semibold tracking-tight dark:text-slate-100 text-slate-900 truncate font-display">
              {getPageTitle()}
            </span>
            <span className="hidden sm:inline-flex items-center gap-1 text-[11px] px-2.5 py-0.5 rounded-full dark:bg-sky-950/60 dark:text-sky-400 dark:border-sky-800/50 bg-sky-50 text-sky-700 border border-sky-200 font-mono">
              <CheckCircle2 className="h-3 w-3 text-sky-500" />
              Cryptographic Engine
            </span>
          </div>

          <div className="flex items-center gap-3 shrink-0">
            {/* Quick Search trigger shortcut */}
            <Link
              to="/search"
              className="hidden md:flex items-center gap-2 px-3 py-1.5 text-xs rounded-xl dark:bg-slate-800/80 bg-slate-100 dark:text-slate-400 text-slate-500 dark:hover:text-slate-200 hover:text-slate-800 border dark:border-slate-700/60 border-slate-200 transition-all duration-150 hover:shadow-sm"
              title="Search Exhibits & OCR Content (⌘K)"
            >
              <Search className="h-3.5 w-3.5" />
              <span>Search Evidence...</span>
              <kbd className="hidden lg:inline-flex items-center gap-0.5 text-[10px] font-mono dark:bg-slate-900 bg-white px-1.5 py-0.5 rounded border dark:border-slate-700 border-slate-200 shadow-sm">
                <Command className="h-2.5 w-2.5" />K
              </kbd>
            </Link>

            <div className="h-4 w-px dark:bg-slate-800 bg-slate-200 hidden md:block" />

            {/* Prominent Navbar Theme Toggle Button */}
            <div className="flex items-center gap-2">
              <ThemeToggle size="sm" showLabel={true} id="navbar-theme-toggle" />
            </div>

            <div className="h-4 w-px dark:bg-slate-800 bg-slate-200 hidden sm:block" />

            <div className="hidden sm:flex items-center gap-2">
              <div className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse shadow-glow-emerald" />
              <span className="text-xs font-mono dark:text-slate-400 text-slate-500">API: Connected</span>
            </div>
          </div>
        </header>

        {/* Content Area with Outlet */}
        <main className="flex-1 overflow-y-auto min-w-0 dark:bg-slate-950 bg-slate-50 transition-colors duration-200">
          <Outlet />
        </main>
      </div>
    </div>
  );
}