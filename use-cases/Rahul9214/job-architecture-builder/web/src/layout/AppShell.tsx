import { useCallback, useEffect, useRef, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { EvidenceDialog } from "../components/EvidenceDialog";
import { IconCollapse, IconDocs, IconExpand, IconMark, IconMenu } from "../components/icons";
import { MobileNavDrawer } from "../components/MobileNavDrawer";
import { SidebarNavItem } from "../components/SidebarNavItem";
import { Tooltip } from "../components/Tooltip";
import { Select } from "../components/Select";
import { useCorpus } from "../corpus";
import { EvidenceProvider } from "../evidence";
import { useMediaQuery } from "../hooks/useMediaQuery";
import { PRIMARY_LINKS, SIDEBAR_STORAGE_KEY, currentNavLabel } from "../nav";

function readCollapsed(): boolean {
  try {
    return window.localStorage.getItem(SIDEBAR_STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

function persistCollapsed(value: boolean) {
  try {
    window.localStorage.setItem(SIDEBAR_STORAGE_KEY, value ? "1" : "0");
  } catch {
    /* private mode / quota */
  }
}

export function AppShell() {
  const { corpora, corpusId, setCorpusId, analyzed, analyze, loading, error } = useCorpus();
  const current = corpora.find((item) => item.corpus_id === corpusId);
  const isMobile = useMediaQuery("(max-width: 768px)");
  const location = useLocation();
  const hamburgerRef = useRef<HTMLButtonElement>(null);
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const sectionLabel = currentNavLabel(location.pathname);

  const closeMobile = useCallback(() => {
    setMobileOpen(false);
    hamburgerRef.current?.focus();
  }, []);

  const openEvidence = useCallback(() => setEvidenceOpen(true), []);

  useEffect(() => {
    setMobileOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    if (!isMobile) setMobileOpen(false);
  }, [isMobile]);

  function toggleCollapsed() {
    setCollapsed((currentState) => {
      const next = !currentState;
      persistCollapsed(next);
      return next;
    });
  }

  const collapseLabel = collapsed ? "Expand navigation" : "Collapse navigation";

  const corpusSelect = (
    <div className="select-field">
      <Select
        id="corpus"
        label="Organization"
        hideLabel={isMobile}
        layout={isMobile ? "stack" : "inline"}
        value={corpusId}
        options={corpora.map((item) => ({
          id: item.corpus_id,
          label: item.organization,
        }))}
        onChange={setCorpusId}
      />
    </div>
  );

  const meta = (
    <p className="corpus-meta">
      {current ? `${current.role_count} source roles · titles never determine level` : "Select a corpus to begin."}
    </p>
  );

  return (
    <EvidenceProvider openEvidence={openEvidence}>
      <div className={`app-shell${collapsed ? " is-collapsed" : ""}${isMobile ? " is-mobile" : ""}`}>
        {!isMobile ? (
          <aside className={`sidebar${collapsed ? " is-collapsed" : ""}`}>
            <div className="brand">
              <IconMark />
              <p className="brand-text">
                Job architecture
                <span>Reviewer workspace</span>
              </p>
            </div>
            <nav className="nav sidebar-main scroll-hidden" aria-label="Primary">
              {PRIMARY_LINKS.map((item) => (
                <SidebarNavItem key={item.to} {...item} collapsed={collapsed} />
              ))}
            </nav>
            <div className="sidebar-footer">
              <Tooltip text="Evidence docs" enabled={collapsed}>
                <button type="button" className="nav-item" aria-label="Evidence docs" onClick={openEvidence}>
                  <IconDocs />
                  <span className="nav-label">Evidence docs</span>
                </button>
              </Tooltip>
            </div>
            <div className="sidebar-toggle-anchor">
              <Tooltip text={collapseLabel} enabled>
                <button
                  type="button"
                  className="sidebar-toggle"
                  aria-label={collapseLabel}
                  aria-expanded={!collapsed}
                  onClick={toggleCollapsed}
                >
                  {collapsed ? <IconExpand /> : <IconCollapse />}
                </button>
              </Tooltip>
            </div>
          </aside>
        ) : null}
        <div className="workspace">
          <header className="topbar">
            {isMobile ? (
              <>
                <div className="topbar-row1">
                  <button
                    ref={hamburgerRef}
                    type="button"
                    className="icon-btn hamburger-btn"
                    aria-label={mobileOpen ? "Close navigation" : "Open navigation"}
                    aria-expanded={mobileOpen}
                    aria-controls="mobile-nav-title"
                    onClick={() => setMobileOpen((open) => !open)}
                  >
                    <IconMenu />
                  </button>
                  <p className="topbar-title">
                    Job architecture
                    <span>{sectionLabel}</span>
                  </p>
                  <span className={`chip ${analyzed ? "good" : "warn"}`}>
                    {analyzed ? "analyzed" : "not analyzed"}
                  </span>
                </div>
                <div className="topbar-row2">
                  {corpusSelect}
                  <button type="button" className="primary analyze-btn" onClick={() => void analyze()} disabled={loading}>
                    Analyze corpus
                  </button>
                </div>
                {meta}
              </>
            ) : (
              <>
                <div className="topbar-start">
                  {corpusSelect}
                  {meta}
                </div>
                <div className="actions topbar-end">
                  <span className={`chip ${analyzed ? "good" : "warn"}`}>
                    {analyzed ? "analyzed" : "not analyzed"}
                  </span>
                  <button type="button" className="primary" onClick={() => void analyze()} disabled={loading}>
                    Analyze corpus
                  </button>
                </div>
              </>
            )}
          </header>
          <main className="content">
            {error ? (
              <div className="error" role="alert">
                {error}
              </div>
            ) : null}
            <div className="page">
              <Outlet />
            </div>
          </main>
        </div>
        {isMobile ? (
          <MobileNavDrawer
            open={mobileOpen}
            onClose={closeMobile}
            onOpenEvidence={() => {
              setMobileOpen(false);
              setEvidenceOpen(true);
            }}
          />
        ) : null}
        <EvidenceDialog open={evidenceOpen} onClose={() => setEvidenceOpen(false)} />
      </div>
    </EvidenceProvider>
  );
}
