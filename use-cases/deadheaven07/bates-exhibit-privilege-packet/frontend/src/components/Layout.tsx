import { Outlet, Link, useLocation } from "react-router-dom";
import { FileText, FolderPlus, Search, Settings } from "lucide-react";
import { clsx } from "clsx";

export function Layout() {
  const location = useLocation();

  const navItems = [
    { path: "/", label: "Packets", icon: FileText },
    { path: "/search", label: "Search", icon: Search },
    { path: "/settings", label: "Settings", icon: Settings },
  ];

  return (
    <div className="flex h-screen bg-gray-50">
      <aside className="w-64 bg-white border-r border-gray-200 flex flex-col">
        <div className="p-4 border-b border-gray-200">
          <Link to="/" className="flex items-center gap-2 text-xl font-semibold text-primary-700">
            <FolderPlus className="h-6 w-6" />
            <span>Bates Packet Builder</span>
          </Link>
          <p className="text-xs text-gray-500 mt-1">E-Discovery Workspace</p>
        </div>

        <nav className="flex-1 p-3 space-y-1 overflow-y-auto">
          {navItems.map((item) => (
            <Link
              key={item.path}
              to={item.path}
              className={clsx(
                "flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors",
                location.pathname === item.path
                  ? "bg-primary-50 text-primary-700"
                  : "text-gray-600 hover:bg-gray-100 hover:text-gray-900"
              )}
            >
              <item.icon className="h-5 w-5" />
              {item.label}
            </Link>
          ))}
        </nav>

        <div className="p-3 border-t border-gray-200">
          <div className="text-xs text-gray-400 text-center">
            v0.1.0 | Phase 1 Foundation
          </div>
        </div>
      </aside>

      <main className="flex-1 overflow-auto">
        <Outlet />
      </main>
    </div>
  );
}