import React, { useState, useEffect } from 'react';
import { X } from 'lucide-react';

import { API_BASE } from '../api';

export function SettingsModal({ onClose }) {
  const [clients, setClients] = useState([]);
  const [configs, setConfigs] = useState([]);
  
  // Forms
  const [clientName, setClientName] = useState('');
  const [clientRoot, setClientRoot] = useState('');
  
  const [selectedClient, setSelectedClient] = useState('');
  const [folderPath, setFolderPath] = useState('');
  const [treatment, setTreatment] = useState('');

  const fetchSettings = async () => {
    try {
      const [resClients, resConfigs] = await Promise.all([
        fetch(`${API_BASE}/clients`),
        fetch(`${API_BASE}/folder-configs`)
      ]);
      if (resClients.ok) setClients(await resClients.json());
      if (resConfigs.ok) setConfigs(await resConfigs.json());
    } catch (e) {
      console.error(e);
    }
  };

  useEffect(() => {
    fetchSettings();
  }, []);

  const handleCreateClient = async (e) => {
    e.preventDefault();
    try {
      const res = await fetch(`${API_BASE}/clients`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: clientName, dropbox_folder_root: clientRoot })
      });
      if (res.ok) {
        setClientName('');
        setClientRoot('');
        fetchSettings();
      }
    } catch (e) {
      console.error(e);
    }
  };

  const handleCreateConfig = async (e) => {
    e.preventDefault();
    if (!selectedClient) return alert('Select a client');
    try {
      const res = await fetch(`${API_BASE}/folder-configs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          client_id: selectedClient,
          dropbox_folder_path: folderPath,
          treatment: treatment,
          instruction_text: {
            normalize: 'Normalize this document to the studio template. Keep meaning, fix structure and headings.',
            summarize: 'Write a short companion brief of this document for the studio, citing the source sections.',
            respond: 'Draft the studio standard response document based on this file.',
          }[treatment],
          output_naming_pattern: '{basename}.superdocs.{treatment}{ext}',
          enabled: true,
          preview_mode: false,
          debounce_seconds: 30,
          operation_budget_per_hour: 20
        })
      });
      if (res.ok) {
        setFolderPath('');
        setTreatment('');
        fetchSettings();
      }
    } catch (e) {
      console.error(e);
    }
  };

  return (
    <div className="modal-overlay">
      <div className="modal-content">
        <div className="modal-header">
          <h2>Nominate Folders & Settings</h2>
          <button className="close-btn" onClick={onClose}><X size={20} /></button>
        </div>
        
        <div className="modal-body">
          <div className="settings-section">
            <h3>1. Create Client</h3>
            <form onSubmit={handleCreateClient} className="settings-form">
              <input type="text" placeholder="Client Name" value={clientName} onChange={e => setClientName(e.target.value)} required />
              <input type="text" placeholder="Dropbox Root (e.g. /Clients/Acme)" value={clientRoot} onChange={e => setClientRoot(e.target.value)} required />
              <button type="submit" className="btn-primary">Create Client</button>
            </form>
          </div>

          <div className="settings-section">
            <h3>2. Nominate Folder</h3>
            <form onSubmit={handleCreateConfig} className="settings-form">
              <select value={selectedClient} onChange={e => setSelectedClient(e.target.value)} required>
                <option value="">Select Client...</option>
                {clients.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
              <input type="text" placeholder="Folder Path (e.g. /Clients/Acme/Input)" value={folderPath} onChange={e => setFolderPath(e.target.value)} required />
              <select value={treatment} onChange={e => setTreatment(e.target.value)} required>
                <option value="">Select treatment...</option>
                <option value="normalize">Normalize to studio template</option>
                <option value="summarize">Companion brief</option>
                <option value="respond">Standard response document</option>
              </select>
              <button type="submit" className="btn-primary">Nominate Folder</button>
            </form>
          </div>

          <div className="settings-section">
            <h3>Configured Folders</h3>
            {configs.length === 0 ? <p className="text-secondary text-sm">No folders configured yet.</p> : (
              <ul className="config-list">
                {configs.map(c => (
                  <li key={c.id}>
                    <strong>{c.dropbox_folder_path}</strong> - {c.treatment}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
