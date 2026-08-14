import React, { useState, useEffect, useRef } from 'react';
import { CheckCircle2, AlertTriangle, FileText, ArrowRight, Download, RefreshCw, X, Upload } from 'lucide-react';
import AuditorSidebar from './AuditorSidebar';
import * as api from '../services/api.service';

export default function SubstitutionAuditor({ API_BASE }) {
  const [specFile, setSpecFile] = useState(null);
  const [cutsheetFile, setCutsheetFile] = useState(null);
  const [scheduleFile, setScheduleFile] = useState(null);
  
  const [isUploading, setIsUploading] = useState(false);
  const [isCommitting, setIsCommitting] = useState(false);
  const [runs, setRuns] = useState([]);
  const [activeRunId, setActiveRunId] = useState(null);
  const [activeRun, setActiveRun] = useState(null);
  const [downloadUrls, setDownloadUrls] = useState(null);
  
  const pollIntervalRef = useRef(null);

  // Fetch runs list on mount
  useEffect(() => {
    fetchRunsList();
    return () => {
      if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
    };
  }, []);

  // Poll details of active run
  useEffect(() => {
    if (activeRunId) {
      fetchRunDetails();
      pollIntervalRef.current = setInterval(fetchRunDetails, 2000);
    } else {
      if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
      setActiveRun(null);
      setDownloadUrls(null);
    }
    return () => {
      if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
    };
  }, [activeRunId]);

  const fetchRunsList = async () => {
    try {
      const data = await api.getRunsList(API_BASE);
      setRuns(data);
    } catch (e) {
      console.error("Failed to fetch runs list", e);
    }
  };

  const fetchRunDetails = async () => {
    if (!activeRunId) return;
    try {
      const data = await api.getRunDetails(API_BASE, activeRunId);
      setActiveRun(data);
      if (['awaiting_approval', 'approved', 'rejected', 'failed'].includes(data.status)) {
        if (pollIntervalRef.current) {
          clearInterval(pollIntervalRef.current);
        }
      }
    } catch (e) {
      console.error("Error polling substitution run details", e);
    }
  };

  const handleStartAnalysis = async () => {
    if (!specFile || !cutsheetFile || !scheduleFile) {
      alert("Please select all three required documents first.");
      return;
    }

    setIsUploading(true);
    try {
      const data = await api.startSubstitutionAnalysis(API_BASE, specFile, cutsheetFile, scheduleFile);
      setActiveRunId(data.id);
      fetchRunsList();
    } catch (e) {
      alert(`Analysis failed to start: ${e.message}`);
    } finally {
      setIsUploading(false);
    }
  };

  const handleApprove = async () => {
    if (!activeRunId) return;
    setIsCommitting(true);
    try {
      const data = await api.approveRun(API_BASE, activeRunId);
      setDownloadUrls({
        spec: data.spec_download_url,
        schedule: data.schedule_download_url
      });
      fetchRunDetails();
      fetchRunsList();
    } catch (e) {
      alert(`Approval failed: ${e.message}`);
    } finally {
      setIsCommitting(false);
    }
  };

  const handleReject = async () => {
    if (!activeRunId) return;
    if (!window.confirm("Are you sure you want to reject this substitution? This will discard all staged changes.")) return;
    setIsCommitting(true);
    try {
      await api.rejectRun(API_BASE, activeRunId);
      fetchRunDetails();
      fetchRunsList();
    } catch (e) {
      alert(`Rejection failed: ${e.message}`);
    } finally {
      setIsCommitting(false);
    }
  };

  const renderStatusBadge = (status) => {
    const styles = {
      uploading: 'bg-blue-950/30 border border-blue-500/30 text-blue-400',
      analyzing: 'bg-amber-950/30 border border-amber-500/30 text-amber-400 animate-pulse',
      awaiting_approval: 'bg-purple-950/30 border border-purple-500/30 text-purple-400 status-pulse-anim',
      approved: 'bg-emerald-950/30 border border-emerald-500/30 text-emerald-400',
      rejected: 'bg-rose-950/30 border border-rose-500/30 text-rose-400',
      failed: 'bg-red-950/30 border border-red-500/30 text-red-400'
    };
    return (
      <span className={`px-3 py-1 rounded-full text-xs font-semibold uppercase tracking-wider ${styles[status] || 'bg-gray-800 text-gray-400'}`}>
        {status.replace('_', ' ')}
      </span>
    );
  };

  return (
    <div className="flex flex-1 min-h-0 overflow-hidden text-gray-300">
      <AuditorSidebar 
        specFile={specFile} setSpecFile={setSpecFile}
        cutsheetFile={cutsheetFile} setCutsheetFile={setCutsheetFile}
        scheduleFile={scheduleFile} setScheduleFile={setScheduleFile}
        isUploading={isUploading}
        handleStartAnalysis={handleStartAnalysis}
        runs={runs}
        activeRunId={activeRunId} setActiveRunId={setActiveRunId}
        setDownloadUrls={setDownloadUrls}
      />

      <main className="flex-1 p-8 flex flex-col gap-8 overflow-y-auto bg-primary">
        {!activeRun ? (
          <div className="flex-1 flex flex-col items-center justify-center text-center p-12 bg-cardbg border border-borderDark rounded-2xl max-w-4xl mx-auto my-12 shadow-xl animate-fade-in">
            <FileText size={64} className="text-gray-500 mb-6 animate-pulse" />
            <h2 className="font-display text-2xl font-bold text-white mb-2">AEC Product Substitution Auditor</h2>
            <p className="text-sm text-gray-400 max-w-md mb-8">
              Analyze contractor product substitutions by comparing alternative manufacturer cut sheets against master specification sections. Update schedules and specs together upon architect approval.
            </p>
            <div className="flex items-center gap-4 bg-secondary border border-borderDark rounded-xl p-4 text-xs text-gray-400 text-left max-w-md">
              <Upload className="text-accentGold w-6 h-6 shrink-0" />
              <span>To get started, select your Specification Section, Contractor Cutsheet, and project Finish Schedule in the sidebar and click <b>Analyze Substitution</b>.</span>
            </div>
          </div>
        ) : (
          <div className="flex flex-col gap-8 animate-fade-in">
            {/* Header / Active Run Status Banner */}
            <div className="bg-cardbg border border-borderDark rounded-2xl p-6 shadow-md flex justify-between items-center">
              <div>
                <span className="text-[10px] font-mono text-gray-500">RUN: {activeRun.id}</span>
                <h2 className="font-display text-xl font-bold text-white mt-1">Substitution Audit Process</h2>
              </div>
              <div className="flex items-center gap-4">
                {renderStatusBadge(activeRun.status)}
                {activeRunId && (
                  <button 
                    onClick={() => setActiveRunId(null)} 
                    className="px-3 py-1.5 border border-borderDark bg-secondary rounded-lg text-xs font-semibold text-gray-400 hover:text-white cursor-pointer transition"
                  >
                    Close Run
                  </button>
                )}
              </div>
            </div>

            {/* Stages Tracker */}
            <div className="bg-cardbg border border-borderDark rounded-2xl p-6 shadow-md">
              <h3 className="font-display text-sm font-semibold mb-4 text-white">Process Tracker</h3>
              
              <div className="grid grid-cols-5 gap-4">
                {[
                  { name: '1. File Upload', status: activeRun.status === 'uploading' ? 'active' : 'completed' },
                  { name: '2. Ingest & Parse', status: activeRun.status === 'uploading' ? 'pending' : (activeRun.status === 'analyzing' ? 'active' : 'completed') },
                  { name: '3. Technical Compare', status: ['uploading', 'analyzing'].includes(activeRun.status) ? 'pending' : (activeRun.status === 'awaiting_approval' ? 'active' : 'completed') },
                  { name: '4. Decision Gate', status: ['approved', 'rejected', 'failed'].includes(activeRun.status) ? 'completed' : (activeRun.status === 'awaiting_approval' ? 'active' : 'pending') },
                  { name: '5. Document Export', status: activeRun.status === 'approved' ? 'completed' : 'pending' }
                ].map((st, i) => (
                  <div key={i} className={`p-4 rounded-xl border flex flex-col gap-1 transition ${
                    st.status === 'completed' 
                      ? 'bg-emerald-950/10 border-emerald-500/20 text-emerald-400' 
                      : (st.status === 'active' 
                        ? 'bg-accentGold/10 border-accentGold/40 text-accentGold status-pulse-anim' 
                        : 'bg-secondary border-borderDark text-gray-500')
                  }`}>
                    <span className="text-[10px] uppercase font-bold tracking-wider opacity-60">{st.status}</span>
                    <span className="text-xs font-semibold">{st.name}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Stage: Loading/Analyzing Spinner */}
            {activeRun.status === 'analyzing' && (
              <div className="flex flex-col items-center justify-center p-16 bg-cardbg border border-borderDark rounded-2xl text-center">
                <RefreshCw className="animate-spin text-accentGold w-12 h-12 mb-4" />
                <h3 className="text-white font-semibold text-sm">SuperDocs Agent Engine is comparing specifications...</h3>
                <p className="text-xs text-gray-500 mt-2 max-w-sm">Comparing requirements line-by-line against cut-sheet specs. Please wait, this may take up to 30-60 seconds.</p>
              </div>
            )}

            {/* Stage: Review Dashboard (Awaiting Approval / Completed) */}
            {['awaiting_approval', 'approved', 'rejected'].includes(activeRun.status) && (
              <>
                {/* Comparison Report Table */}
                {activeRun.comparison_report && (
                  <div className="bg-cardbg border border-borderDark rounded-2xl p-6 shadow-md">
                    <h3 className="font-display text-sm font-semibold mb-4 text-white">Line-By-Line Technical Comparison</h3>
                    <div 
                      className="markdown-body text-sm text-gray-300"
                      dangerouslySetInnerHTML={{ __html: formatMarkdown(activeRun.comparison_report) }}
                    />
                  </div>
                )}

                {/* Letter Draft & Actions */}
                <div className="grid grid-cols-2 gap-8">
                  {/* Response Letter Draft */}
                  {activeRun.response_letter && (
                    <div className="bg-cardbg border border-borderDark rounded-2xl p-6 shadow-md flex flex-col">
                      <h3 className="font-display text-sm font-semibold mb-4 text-white">Architect's Draft Response</h3>
                      <div className="flex-1 bg-secondary border border-borderDark rounded-xl p-5 font-serif text-xs leading-relaxed text-gray-400 max-h-[350px] overflow-y-auto whitespace-pre-line">
                        {activeRun.response_letter}
                      </div>
                    </div>
                  )}

                  {/* Decision Box */}
                  <div className="bg-cardbg border border-borderDark rounded-2xl p-6 shadow-md flex flex-col justify-center gap-6">
                    <h3 className="font-display text-sm font-semibold text-white">Audit Decision Gate</h3>
                    
                    {activeRun.status === 'awaiting_approval' ? (
                      <div className="flex flex-col gap-4">
                        <div className="flex items-center gap-3 bg-secondary border border-borderDark rounded-xl p-4 text-xs text-gray-400">
                          <AlertTriangle className="text-accentPurple w-5 h-5 shrink-0" />
                          <span>Review the technical comparison table. If requirements are met and you accept the substitution, click <b>Approve & Apply Edits</b> to update files.</span>
                        </div>
                        <div className="flex gap-4">
                          <button
                            onClick={handleApprove}
                            disabled={isCommitting}
                            className="flex-1 py-3 bg-emerald-600 hover:brightness-110 text-white rounded-lg text-sm font-semibold cursor-pointer transition disabled:opacity-50"
                          >
                            {isCommitting ? 'Applying Edits...' : 'Approve & Apply Edits'}
                          </button>
                          <button
                            onClick={handleReject}
                            disabled={isCommitting}
                            className="flex-1 py-3 bg-rose-600 hover:brightness-110 text-white rounded-lg text-sm font-semibold cursor-pointer transition disabled:opacity-50"
                          >
                            Reject & Discard
                          </button>
                        </div>
                      </div>
                    ) : (
                      <div className="flex flex-col gap-4 items-center text-center animate-scale-up">
                        {activeRun.status === 'approved' ? (
                          <>
                            <CheckCircle2 className="text-emerald-400 w-16 h-16 mb-2" />
                            <h4 className="text-white font-bold text-base">Substitution Request Accepted</h4>
                            <p className="text-xs text-gray-500 max-w-xs">The spec sheets and finish schedule have been updated in parallel in the active session.</p>
                            
                            {downloadUrls ? (
                              <div className="flex flex-col gap-3 w-full mt-4">
                                <a 
                                  href={downloadUrls.spec}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="w-full flex items-center justify-center gap-2 py-3 bg-emerald-600 hover:brightness-110 text-white rounded-lg text-xs font-semibold transition"
                                >
                                  <Download size={14} /> Download Updated Specification (.docx)
                                </a>
                                <a 
                                  href={downloadUrls.schedule}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="w-full flex items-center justify-center gap-2 py-3 bg-secondary hover:bg-borderDark border border-borderDark text-gray-300 rounded-lg text-xs font-semibold transition"
                                >
                                  <Download size={14} /> Download Updated Finish Schedule (.docx)
                                </a>
                              </div>
                            ) : (
                              <p className="text-xs text-gray-500 mt-2">Generating download packages...</p>
                            )}
                          </>
                        ) : (
                          <>
                            <X className="text-rose-400 w-16 h-16 border border-rose-500/20 bg-rose-950/20 rounded-full p-2 mb-2" />
                            <h4 className="text-white font-bold text-base">Substitution Request Rejected</h4>
                            <p className="text-xs text-gray-400 max-w-xs">Staged changes discarded. The Specification Section and Finish Schedule remain unchanged.</p>
                          </>
                        )}
                      </div>
                    )}
                  </div>
                </div>

                {/* Staged Document Diffs */}
                {activeRun.pending_changes && activeRun.pending_changes.length > 0 && (
                  <div className="bg-cardbg border border-borderDark rounded-2xl p-6 shadow-md">
                    <h3 className="font-display text-sm font-semibold mb-4 text-white">Staged Document Changes</h3>
                    <div className="flex flex-col gap-4">
                      {activeRun.pending_changes.map((ch, i) => (
                        <div key={i} className="bg-secondary border border-borderDark rounded-xl p-4 flex flex-col gap-2">
                          <div className="flex justify-between items-center">
                            <span className="text-xs font-semibold text-accentPurple flex items-center gap-2">
                              <FileText size={14} /> Document slot: {ch.document_id || 'Primary Spec'}
                            </span>
                            <span className="text-[10px] font-mono text-gray-500">Chunk: {ch.chunk_id}</span>
                          </div>
                          
                          <div className="grid grid-cols-2 gap-4 mt-2">
                            {/* Original */}
                            <div className="bg-cardbg/50 border border-borderDark p-3 rounded-lg flex flex-col">
                              <span className="text-[9px] uppercase font-bold tracking-wider text-gray-500 mb-1">Original Text</span>
                              <div 
                                className="text-xs text-gray-500 line-through leading-relaxed whitespace-pre-wrap font-sans"
                                dangerouslySetInnerHTML={{ __html: ch.original_html || ch.original || ch.old_html || ch.old }}
                              />
                            </div>
                            {/* Proposed / Changed */}
                            <div className="bg-emerald-950/10 border border-emerald-500/10 p-3 rounded-lg flex flex-col">
                              <span className="text-[9px] uppercase font-bold tracking-wider text-emerald-500 mb-1">Staged Change</span>
                              <div 
                                className="text-xs text-emerald-400 font-semibold leading-relaxed whitespace-pre-wrap font-sans"
                                dangerouslySetInnerHTML={{ __html: ch.proposed_html || ch.proposed || ch.new_html || ch.new }}
                              />
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        )}
      </main>
    </div>
  );
}

// Simple markdown conversion helper (handles headers, tables, lists, bold)
function formatMarkdown(markdown) {
  if (!markdown) return "";
  let html = markdown;
  
  html = html.replace(/^# (.*?)$/gm, '<h1>$1</h1>');
  html = html.replace(/^## (.*?)$/gm, '<h2>$1</h2>');
  html = html.replace(/^### (.*?)$/gm, '<h3>$1</h3>');
  
  html = html.replace(/\|(.+?)\|/g, (match) => {
    if (match.includes('---')) return '';
    const cols = match.split('|').filter(c => c.trim()).map(c => `<td>${c.trim()}</td>`).join('');
    return `<tr>${cols}</tr>`;
  });
  html = html.replace(/(<tr>.*?<\/tr>\s*)+/g, '<table>$&</table>');
  
  html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
  
  html = html.replace(/^\- (.*?)$/gm, '<li>$1</li>');
  html = html.replace(/(<li>.*?<\/li>\s*)+/g, '<ul>$&</ul>');

  html = html.replace(/\n/g, '<br/>');
  
  return html;
}
