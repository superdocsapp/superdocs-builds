import { NavLink, Outlet } from "react-router-dom";
import { GlobalSearch } from "./GlobalSearch";
import { Icon } from "./Icon";
import { ToastStack } from "./ToastStack";
import { ActiveRunsPanel } from "./ActiveRunsPanel";

const NAV_ITEMS = [
  { to: "/", label: "Review", icon: "review" as const, end: true },
  { to: "/documents", label: "Documents", icon: "documents" as const },
];

export function Layout() {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <span className="brand-mark" aria-hidden="true">
            <Icon name="brand" size={18} />
          </span>
          <span className="brand-name">Drift Detector</span>
        </div>

        <GlobalSearch />

        <nav className="sidebar-nav">
          <span className="eyebrow sidebar-section-label">Workspace</span>
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) => `sidebar-link${isActive ? " sidebar-link-active" : ""}`}
            >
              <Icon name={item.icon} size={17} />
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="sidebar-footer">
          <span className="sidebar-footer-note">
            Made with{" "}
            <a
              className="superdocs-link"
              href="https://superdocs.app/?ref=drift-detector-app"
              target="_blank"
              rel="noreferrer noopener"
            >
              <img
                src="/mascot-master-1200.webp"
                alt=""
                className="superdocs-mascot"
                aria-hidden="true"
              />
              SuperDocs
            </a>
          </span>
        </div>
      </aside>

      <main className="main-panel">
        <div className="main-panel-inner card">
          <Outlet />
        </div>
      </main>

      <ToastStack />
      <ActiveRunsPanel />
    </div>
  );
}