import React, { useState, useEffect } from 'react';
import { Navbar } from './components/Navbar';
import { ClientBatchList } from './components/ClientBatchList';
import { AgentPipelineViewer } from './components/AgentPipelineViewer';
import { SuperDocsEditor } from './components/SuperDocsEditor';
import { FillableOrganizerView } from './components/FillableOrganizerView';
import { YearEndLetterView } from './components/YearEndLetterView';
import { MissingItemsFollowUp } from './components/MissingItemsFollowUp';
import { PrintExportModal } from './components/PrintExportModal';
import { TaxLawDatabaseModal } from './components/TaxLawDatabaseModal';
import { UploadClientModal } from './components/UploadClientModal';
import { BatchRunCheckpoint, ClientBatchRecord, AgentStage } from './types';

export default function App() {
  const [checkpoint, setCheckpoint] = useState<BatchRunCheckpoint | null>(null);
  const [activeTab, setActiveTab] = useState<'batch' | 'editor' | 'pipeline' | 'followup' | 'organizer' | 'letter'>('batch');
  const [selectedClient, setSelectedClient] = useState<ClientBatchRecord | null>(null);

  // Modals state
  const [isExportOpen, setIsExportOpen] = useState(false);
  const [exportType, setExportType] = useState<'organizer' | 'letter'>('letter');
  const [isLawDbOpen, setIsLawDbOpen] = useState(false);
  const [isUploadOpen, setIsUploadOpen] = useState(false);

  // Load checkpoint on mount
  useEffect(() => {
    fetchCheckpoint();
  }, []);

  // Reset scroll position to the top whenever the active view changes.
  // Without this, navigating from a scrolled-down view (e.g. the bottom of a
  // Letter) back to Client Batch kept the old scroll offset, dropping the user
  // into the middle of the batch list instead of at the top. Also reset when a
  // different client is selected, since that swaps the content entirely.
  useEffect(() => {
    window.scrollTo({ top: 0, behavior: 'auto' });
  }, [activeTab, selectedClient?.id]);

  const fetchCheckpoint = async () => {
    try {
      const res = await fetch('/api/checkpoint');
      const data = await res.json();
      setCheckpoint(data);
      if (data.clientRecords && data.clientRecords.length > 0 && !selectedClient) {
        setSelectedClient(data.clientRecords[0]);
      }
    } catch (err) {
      console.error('Failed to fetch engine checkpoint:', err);
    }
  };

  const handleRunStage = async (stage: AgentStage) => {
    try {
      const res = await fetch('/api/batch/run-stage', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ stage })
      });
      const data = await res.json();
      setCheckpoint(data);
      if (selectedClient) {
        const updated = data.clientRecords.find((c: ClientBatchRecord) => c.id === selectedClient.id);
        if (updated) setSelectedClient(updated);
      }
    } catch (err) {
      console.error('Run stage error:', err);
    }
  };

  const handleRunAll = async () => {
    try {
      const res = await fetch('/api/batch/run-all', { method: 'POST' });
      const data = await res.json();
      setCheckpoint(data);
      if (selectedClient) {
        const updated = data.clientRecords.find((c: ClientBatchRecord) => c.id === selectedClient.id);
        if (updated) setSelectedClient(updated);
      }
    } catch (err) {
      console.error('Run pipeline error:', err);
    }
  };

  // Clear the batch-wide review gate in one action by deciding every
  // still-pending diff across all clients. The per-client review UI can leave
  // other clients pending, which holds the gate; this releases it without
  // hunting through every client tab. Reflects the decided count back so the
  // pipeline viewer can confirm exactly what happened.
  const handleApproveAllRemaining = async (status: 'approved' | 'rejected' = 'approved') => {
    try {
      const res = await fetch('/api/documents/approve-all', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status })
      });
      const data = await res.json();
      if (data.checkpoint) {
        setCheckpoint(data.checkpoint);
        if (selectedClient) {
          const updated = data.checkpoint.clientRecords.find((c: ClientBatchRecord) => c.id === selectedClient.id);
          if (updated) setSelectedClient(updated);
        }
      }
      return data.decidedCount as number;
    } catch (err) {
      console.error('Approve-all error:', err);
    }
  };

  const handleReset = async () => {
    try {
      const res = await fetch('/api/checkpoint/reset', { method: 'POST' });
      const data = await res.json();
      setCheckpoint(data);
      if (data.clientRecords && data.clientRecords.length > 0) {
        setSelectedClient(data.clientRecords[0]);
      }
    } catch (err) {
      console.error('Reset error:', err);
    }
  };

  const handleSelectClient = (client: ClientBatchRecord, tab: 'organizer' | 'letter' | 'diffs') => {
    setSelectedClient(client);
    if (tab === 'diffs') setActiveTab('editor');
    else if (tab === 'organizer') setActiveTab('organizer');
    else if (tab === 'letter') setActiveTab('letter');
  };

  const handleApproveDiff = async (diffId: string) => {
    if (!selectedClient) return;
    try {
      const res = await fetch('/api/documents/approve-diff', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          clientRecordId: selectedClient.id,
          diffId,
          status: 'approved'
        })
      });
      const data = await res.json();
      if (data.checkpoint) {
        setCheckpoint(data.checkpoint);
        const updated = data.checkpoint.clientRecords.find((c: ClientBatchRecord) => c.id === selectedClient.id);
        if (updated) setSelectedClient(updated);
      }
    } catch (err) {
      console.error('Approve diff error:', err);
    }
  };

  const handleRejectDiff = async (diffId: string) => {
    if (!selectedClient) return;
    try {
      const res = await fetch('/api/documents/approve-diff', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          clientRecordId: selectedClient.id,
          diffId,
          status: 'rejected'
        })
      });
      const data = await res.json();
      if (data.checkpoint) {
        setCheckpoint(data.checkpoint);
        const updated = data.checkpoint.clientRecords.find((c: ClientBatchRecord) => c.id === selectedClient.id);
        if (updated) setSelectedClient(updated);
      }
    } catch (err) {
      console.error('Reject diff error:', err);
    }
  };

  const handleSendChatEditInstruction = async (instruction: string) => {
    if (!selectedClient) return;
    try {
      const res = await fetch('/api/documents/chat-edit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          documentTitle: `${selectedClient.clientName} Tax Letter`,
          instruction,
          currentContent: selectedClient.yearEndLetter.overview,
          clientRecordId: selectedClient.id
        })
      });
      const data = await res.json();
      if (data.checkpoint) {
        setCheckpoint(data.checkpoint);
        const updated = data.checkpoint.clientRecords.find((c: ClientBatchRecord) => c.id === selectedClient.id);
        if (updated) setSelectedClient(updated);
      }
    } catch (err) {
      console.error('Chat edit instruction error:', err);
    }
  };

  const handleUpdateDocStatus = async (
    docId: string,
    status: 'received' | 'outstanding' | 'waived',
    fileName?: string
  ) => {
    if (!selectedClient) return;
    try {
      const res = await fetch('/api/documents/update-doc-status', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          clientRecordId: selectedClient.id,
          docId,
          status,
          fileName
        })
      });
      const data = await res.json();
      if (data.checkpoint) {
        setCheckpoint(data.checkpoint);
        const updated = data.checkpoint.clientRecords.find((c: ClientBatchRecord) => c.id === selectedClient.id);
        if (updated) setSelectedClient(updated);
      }
    } catch (err) {
      console.error('Update doc status error:', err);
    }
  };

  const handleDraftFollowUp = async (record: ClientBatchRecord) => {
    const outstanding = record.organizer.flatMap((sec) =>
      sec.requiredDocuments.filter((d) => d.status === 'outstanding').map((d) => d.docName)
    );
    const received = record.organizer.flatMap((sec) =>
      sec.requiredDocuments.filter((d) => d.status === 'received').map((d) => d.docName)
    );

    try {
      const res = await fetch('/api/documents/followup-letter', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          clientName: record.clientName,
          segment: record.segment,
          outstandingItems: outstanding,
          receivedItems: received,
          clientRecordId: record.id
        })
      });
      const data = await res.json();
      if (data.followUpLetter) {
        fetchCheckpoint();
      }
    } catch (err) {
      console.error('Draft follow-up error:', err);
    }
  };

  const handleUploadReturn = async (file: File | null, rawText: string) => {
    const formData = new FormData();
    if (file) formData.append('file', file);
    if (rawText) formData.append('rawText', rawText);

    try {
      const res = await fetch('/api/documents/upload', {
        method: 'POST',
        body: formData
      });
      const data = await res.json();
      if (data.checkpoint) {
        setCheckpoint(data.checkpoint);
        if (data.record) setSelectedClient(data.record);
      }
    } catch (err) {
      console.error('Upload return error:', err);
    }
  };

  const triggerExportModal = (type: 'organizer' | 'letter') => {
    setExportType(type);
    setIsExportOpen(true);
  };

  if (!checkpoint) {
    return (
      <div className="min-h-screen bg-slate-950 text-white flex items-center justify-center">
        <div className="text-center space-y-3">
          <div className="w-10 h-10 border-4 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto" />
          <p className="text-sm text-slate-400 font-mono">Initializing SuperDocs Tax Engine...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 font-sans selection:bg-blue-500 selection:text-white">
      <Navbar
        checkpoint={checkpoint}
        activeTab={
          activeTab === 'organizer' || activeTab === 'letter' ? 'batch' : activeTab
        }
        setActiveTab={(tab) => setActiveTab(tab)}
        onReset={handleReset}
        onOpenLawDb={() => setIsLawDbOpen(true)}
        onOpenUpload={() => setIsUploadOpen(true)}
      />

      <main className="pb-16">
        {activeTab === 'batch' && (
          <ClientBatchList
            records={checkpoint.clientRecords}
            onSelectClient={handleSelectClient}
            onRunBatch={handleRunAll}
            onOpenUpload={() => setIsUploadOpen(true)}
          />
        )}

        {activeTab === 'editor' && selectedClient && (
          <SuperDocsEditor
            selectedClient={selectedClient}
            onApproveDiff={handleApproveDiff}
            onRejectDiff={handleRejectDiff}
            onSendChatEditInstruction={handleSendChatEditInstruction}
            onExport={triggerExportModal}
          />
        )}

        {activeTab === 'pipeline' && (
          <AgentPipelineViewer
            checkpoint={checkpoint}
            onRunStage={handleRunStage}
            onRunAll={handleRunAll}
            onReset={handleReset}
            onApproveAllRemaining={handleApproveAllRemaining}
          />
        )}

        {activeTab === 'followup' && (
          <MissingItemsFollowUp
            records={checkpoint.clientRecords}
            onDraftFollowUp={handleDraftFollowUp}
          />
        )}

        {activeTab === 'organizer' && selectedClient && (
          <FillableOrganizerView
            client={selectedClient}
            onUpdateDocStatus={handleUpdateDocStatus}
            onExport={() => triggerExportModal('organizer')}
          />
        )}

        {activeTab === 'letter' && selectedClient && (
          <YearEndLetterView
            client={selectedClient}
            onExport={() => triggerExportModal('letter')}
          />
        )}
      </main>

      {/* Modals */}
      <PrintExportModal
        isOpen={isExportOpen}
        onClose={() => setIsExportOpen(false)}
        client={selectedClient}
        exportType={exportType}
        onExported={(cp) => cp && setCheckpoint(cp)}
      />

      <TaxLawDatabaseModal
        isOpen={isLawDbOpen}
        onClose={() => setIsLawDbOpen(false)}
      />

      <UploadClientModal
        isOpen={isUploadOpen}
        onClose={() => setIsUploadOpen(false)}
        onUpload={handleUploadReturn}
      />
    </div>
  );
}
