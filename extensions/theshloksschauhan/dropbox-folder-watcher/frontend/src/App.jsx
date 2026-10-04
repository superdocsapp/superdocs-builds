import React, { useState, useEffect } from 'react';
import { SettingsModal } from './components/SettingsModal';
import { MockDropModal } from './components/MockDropModal';
import { JobViewer } from './components/JobViewer';
import { API_BASE } from './api';

function App() {
  const [jobs, setJobs] = useState([]);
  const [folderConfigs, setFolderConfigs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isMockDropOpen, setIsMockDropOpen] = useState(false);
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [isPreviewMode, setIsPreviewMode] = useState(false);
  const [searchTerm, setSearchTerm] = useState('');
  const [selectedFolderId, setSelectedFolderId] = useState(null);

  const fetchData = async () => {
    try {
      const [jobsRes, foldersRes] = await Promise.all([
        fetch(`${API_BASE}/jobs?limit=100`),
        fetch(`${API_BASE}/folder-configs`)
      ]);
      
      if (jobsRes.ok) {
        const jobsData = await jobsRes.json();
        setJobs(jobsData);
      }
      if (foldersRes.ok) {
        const foldersData = await foldersRes.json();
        setFolderConfigs(foldersData);
      }
    } catch (e) {
      console.error('Failed to fetch data', e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
    fetch(`${API_BASE}/system/preview-mode`)
      .then(r => r.ok ? r.json() : null)
      .then(data => { if (data) setIsPreviewMode(data.enabled); })
      .catch(() => {});
    const interval = setInterval(fetchData, 5000);
    return () => clearInterval(interval);
  }, []);

  const togglePreviewMode = async () => {
    const next = !isPreviewMode;
    setIsPreviewMode(next);
    try {
      await fetch(`${API_BASE}/system/preview-mode`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: next }),
      });
    } catch (e) {
      console.error('Failed to update preview mode', e);
      setIsPreviewMode(!next);
    }
  };

  const getFolderStats = (config) => {
    const configJobs = jobs.filter(j => j.source_path.startsWith(config.dropbox_folder_path));
    const activeJobs = configJobs.filter(j => ['DISCOVERED', 'STABILIZING', 'QUEUED', 'PROCESSING', 'REVIEW_PENDING'].includes(j.status));
    const needsReview = configJobs.filter(j => j.status === 'REVIEW_PENDING').length;
    
    if (needsReview > 0) {
      return { status: 'needs', text: `${needsReview} need review`, count: activeJobs.length };
    } else if (activeJobs.length > 0) {
      return { status: 'processing', text: 'processing', count: activeJobs.length };
    } else {
      return { status: 'synced', text: 'up to date', count: 0 };
    }
  };

  const filteredFolders = folderConfigs.filter(config => 
    config.dropbox_folder_path.toLowerCase().includes(searchTerm.toLowerCase()) ||
    config.treatment.toLowerCase().includes(searchTerm.toLowerCase())
  );

  return (
    <div className="shell">
      <div className={`sidebar ${isSidebarOpen ? 'open' : ''}`}>
        <div className="side-brand">
          <div className="brand-mark">S</div>
          <div className="brand-txt">SuperDocs<span>Folder watcher</span></div>
        </div>

        <div className="side-mode">
          <div>
            <div className="mode-label">Preview mode</div>
            <div className="mode-sub">No-spend, nothing writes back</div>
          </div>
          <div 
            className="toggle" 
            style={{ 
              background: isPreviewMode ? 'var(--pain)' : '#cbd5e1', 
              transition: 'background 0.3s' 
            }}
            onClick={togglePreviewMode}
          >
            <div 
              style={{
                position: 'absolute',
                width: '13px',
                height: '13px',
                borderRadius: '50%',
                background: '#fff',
                top: '2px',
                left: isPreviewMode ? '15px' : '2px',
                transition: 'left 0.3s ease',
                boxShadow: '0 1px 3px rgba(0,0,0,0.3)'
              }}
            />
          </div>
        </div>

        <div className="side-section">Watched folders</div>
        <div className="folder-list">
          {filteredFolders.length === 0 && (
            <div style={{ padding: '10px', fontSize: '12px', color: 'var(--ink-faint)' }}>
              {searchTerm ? 'No folders match search.' : 'No folders watched yet.'}
            </div>
          )}
          {filteredFolders.map((config) => {
            const stats = getFolderStats(config);
            const folderName = config.dropbox_folder_path.split('/').pop() || config.dropbox_folder_path;
            const isActive = selectedFolderId === config.id;
            
            return (
              <div 
                key={config.id} 
                className={`folder-item ${isActive ? 'active' : ''}`}
                onClick={() => setSelectedFolderId(config.id)}
              >
                <div className={`folder-dot ${stats.status}`}></div>
                <div className="folder-info">
                  <div className="folder-name">{folderName}</div>
                  <div className="folder-meta">
                    <span className="treat-tag">{config.treatment}</span> {stats.text}
                  </div>
                </div>
                <div className="folder-count">{stats.count > 0 ? stats.count : '0'}</div>
              </div>
            );
          })}
        </div>

        <div className="side-foot">
          <b>{folderConfigs.length}</b> folders watched<br />
          Each client only ever sees their own outputs.
        </div>
      </div>

      {isSidebarOpen && (
        <div 
          style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, zIndex: 90, background: 'rgba(0,0,0,0.2)' }}
          onClick={() => setIsSidebarOpen(false)}
        />
      )}

      <div className="main">
        <div className="topbar">
          <button className="hamburger" onClick={() => setIsSidebarOpen(true)}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M3 12h18M3 6h18M3 18h18" />
            </svg>
          </button>
          <div className="search">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ color: 'var(--ink-faint)' }}>
              <circle cx="11" cy="11" r="7" />
              <path d="M21 21l-4-4" />
            </svg>
            <input 
              placeholder="Search folders or treatments..." 
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
            />
          </div>
          <div className="spacer"></div>
          <button className="btn-ghost-dev" onClick={() => setIsMockDropOpen(true)}>⚙ dev: seed sample drop</button>
          <button className="btn btn-primary" onClick={() => setIsSettingsOpen(true)}>＋ Watch a folder</button>
          <div className="profile"><div className="avatar"></div> Shlok</div>
        </div>

        <div className="canvas">
          {folderConfigs.length === 0 ? (
            <div className="empty-wrap">
              <div className="empty-eyebrow">Setup Guide</div>
              <div className="empty-title">Welcome to SuperDocs Console</div>
              <div className="empty-sub">
                Drop a file into this shared Dropbox folder, and it will be normalized to your
                studio template. It will be filed next to the original file and named consistently 
                without affecting unnecessary files.
              </div>

              <div className="flow">
                <div className="flow-card">
                  <div className="flow-num">01</div>
                  <div className="flow-icon a">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 4v12m0 0l-4-4m4 4l4-4M4 20h16" /></svg>
                  </div>
                  <div className="flow-title">Client drops a file</div>
                  <div className="flow-desc">Into their shared Dropbox folder, no other client can see it.</div>
                </div>
                <div className="flow-arrow">→</div>
                <div className="flow-card">
                  <div className="flow-num">02</div>
                  <div className="flow-icon b">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 3" /></svg>
                  </div>
                  <div className="flow-title">Treatment applies</div>
                  <div className="flow-desc">Normalized to template, summarised, or answered per folder.</div>
                </div>
                <div className="flow-arrow">→</div>
                <div className="flow-card">
                  <div className="flow-num">03</div>
                  <div className="flow-icon c">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M9 12l2 2 4-4" /><circle cx="12" cy="12" r="9" /></svg>
                  </div>
                  <div className="flow-title">Filed back beside it</div>
                  <div className="flow-desc">Consistent naming. Logged here. Never re-triggers itself.</div>
                </div>
              </div>

              <div className="empty-actions">
                <button className="btn btn-primary" onClick={() => setIsSettingsOpen(true)}>＋ Watch a folder</button>
              </div>
            </div>
          ) : selectedFolderId ? (
            <div style={{ padding: '32px' }}>
              {(() => {
                const selectedConfig = folderConfigs.find(c => c.id === selectedFolderId);
                const folderJobs = jobs.filter(j => j.source_path.startsWith(selectedConfig.dropbox_folder_path));
                
                if (folderJobs.length === 0) {
                  return (
                    <div className="empty-state">
                      <h2>No jobs yet</h2>
                      <p>Drop a file in <strong>{selectedConfig.dropbox_folder_path}</strong> to see it here.</p>
                    </div>
                  );
                }

                return folderJobs.map(job => (
                  <JobViewer 
                    key={job.id} 
                    job={job} 
                    onApprove={async (id) => {
                      await fetch(`${API_BASE}/jobs/${id}/approve`, { method: 'POST' });
                      fetchData();
                    }}
                    onReject={async (id) => {
                      await fetch(`${API_BASE}/jobs/${id}/reject`, { method: 'POST' });
                      fetchData();
                    }}
                  />
                ));
              })()}
            </div>
          ) : (
            <div className="empty-state" style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <div style={{ textAlign: 'center', color: 'var(--ink-faint)' }}>
                <h2>Select a folder</h2>
                <p>Choose a folder from the sidebar to view its jobs.</p>
              </div>
            </div>
          )}

          <div className="status-strip">
            <span>sync check: live</span>
            <span>{jobs.filter(j => ['DISCOVERED', 'STABILIZING', 'QUEUED'].includes(j.status)).length} jobs in queue</span>
            <span>{isPreviewMode ? 'Preview mode ON: safe' : 'Preview mode OFF: writes to dropbox'}</span>
          </div>
        </div>
      </div>

      {isSettingsOpen && <SettingsModal onClose={() => { setIsSettingsOpen(false); fetchData(); }} />}
      {isMockDropOpen && (
        <MockDropModal
          onClose={() => { setIsMockDropOpen(false); fetchData(); }}
          onWatchFolder={() => { setIsMockDropOpen(false); setIsSettingsOpen(true); }}
        />
      )}
    </div>
  );
}

export default App;
