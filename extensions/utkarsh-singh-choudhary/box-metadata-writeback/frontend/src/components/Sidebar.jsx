const NAV = [
  { key: "dashboard", label: "Dashboard" },
  { key: "documents", label: "Documents" },
  { key: "review", label: "Review Queue", countKey: "pendingReviews" },
  { key: "templates", label: "Retention Templates" },
];

export default function Sidebar({ active, onNavigate, counts, connected }) {
  return (
    <aside className="sidebar">
      <div className="wordmark">
        <div className="seal" />
        <div className="name">
          Ledger
          <small>Box Document Intelligence</small>
        </div>
      </div>
      <nav className="nav">
        {NAV.map((item) => (
          <button
            key={item.key}
            className={`nav-item ${active === item.key ? "active" : ""}`}
            onClick={() => onNavigate(item.key)}
          >
            {item.label}
            {item.countKey && counts?.[item.countKey] > 0 && (
              <span className="count">{counts[item.countKey]}</span>
            )}
          </button>
        ))}
      </nav>
      <div className="nav-footer">
        <div>
          <span className="conn-dot" style={{ background: connected ? undefined : "#c15c42" }} />
          {connected ? "Connected to Box workflow API" : "API unreachable"}
        </div>
        <div style={{ marginTop: 4 }}>documentIntelligence template</div>
      </div>
    </aside>
  );
}
