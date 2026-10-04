import React, { useState, useEffect } from 'react';
import { X, UploadCloud } from 'lucide-react';

import { API_BASE } from '../api';

export function MockDropModal({ onClose, onWatchFolder }) {
  const [configs, setConfigs] = useState([]);
  const [selectedConfig, setSelectedConfig] = useState('');
  const [file, setFile] = useState(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [loadError, setLoadError] = useState('');

  useEffect(() => {
    fetch(`${API_BASE}/folder-configs`)
      .then(async (res) => {
        if (!res.ok) throw new Error(`API ${res.status}`);
        return res.json();
      })
      .then((data) => {
        const list = Array.isArray(data) ? data : [];
        setConfigs(list);
        if (list.length === 1) setSelectedConfig(list[0].id);
      })
      .catch((e) => {
        console.error(e);
        setLoadError('Cannot reach the API at localhost:8001. Start the backend first.');
      });
  }, []);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!selectedConfig || !file) {
      alert('Pick a watched folder and a file first.');
      return;
    }

    setIsSubmitting(true);
    const formData = new FormData();
    formData.append('folder_config_id', selectedConfig);
    formData.append('file', file);

    try {
      const res = await fetch(`${API_BASE}/mock-drop`, {
        method: 'POST',
        body: formData,
      });
      if (res.ok) {
        onClose();
      } else {
        const err = await res.json().catch(() => ({}));
        alert('Failed: ' + (err.detail || res.statusText || 'Unknown error'));
      }
    } catch (err) {
      console.error(err);
      alert('Error connecting to backend on port 8001');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="modal-overlay">
      <div className="modal-content" style={{ maxWidth: '400px' }}>
        <div className="modal-header">
          <h2>Simulate File Drop</h2>
          <button className="close-btn" onClick={onClose}><X size={20} /></button>
        </div>
        <div className="modal-body">
          {loadError && (
            <p className="text-secondary text-sm" style={{ marginBottom: '16px', color: 'var(--pain)' }}>
              {loadError}
            </p>
          )}

          {configs.length === 0 && !loadError ? (
            <>
              <p className="text-secondary text-sm" style={{ marginBottom: '16px' }}>
                Nothing to drop into yet. Nominate a folder first — this picker is empty until you do.
              </p>
              <button
                type="button"
                className="btn-primary"
                onClick={() => {
                  onClose();
                  onWatchFolder?.();
                }}
              >
                Watch a folder first
              </button>
            </>
          ) : (
            <>
              <p className="text-secondary text-sm" style={{ marginBottom: '16px' }}>
                Choose a watched folder, then a file. Both are required.
              </p>
              <form onSubmit={handleSubmit} className="settings-form">
                <select
                  value={selectedConfig}
                  onChange={(e) => setSelectedConfig(e.target.value)}
                  required
                >
                  <option value="">Select Target Folder...</option>
                  {configs.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.dropbox_folder_path} ({c.treatment})
                    </option>
                  ))}
                </select>
                <input
                  type="file"
                  onChange={(e) => setFile(e.target.files[0])}
                  required
                  style={{ border: '1px solid var(--border-color)', padding: '8px', borderRadius: '4px' }}
                />
                <button
                  type="submit"
                  className="btn-primary"
                  disabled={isSubmitting || !selectedConfig || !file}
                >
                  {isSubmitting ? 'Simulating...' : (
                    <>
                      <UploadCloud size={16} style={{ marginRight: '8px' }} /> Drop File
                    </>
                  )}
                </button>
              </form>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
