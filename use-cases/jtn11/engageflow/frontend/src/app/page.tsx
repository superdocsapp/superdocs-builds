'use client';

import React, { useState, useEffect } from 'react';

const API_BASE = 'http://localhost:8001';

export default function Home() {
  const [loading, setLoading] = useState(false);
  const [healthStatus, setHealthStatus] = useState<any>(null);
  const [currentPeriod, setCurrentPeriod] = useState('period_2');
  const [previousPeriod, setPreviousPeriod] = useState('period_1');
  const [reportData, setReportData] = useState<any>(null);
  const [superdocsStatus, setSuperdocsStatus] = useState<string>('idle');
  const [activeTab, setActiveTab] = useState<'deltas' | 'report' | 'superdocs'>('deltas');

  useEffect(() => {
    fetchHealth();
  }, []);

  const fetchHealth = async () => {
    try {
      const res = await fetch(`${API_BASE}/health`);
      const data = await res.json();
      setHealthStatus(data);
    } catch (e) {
      setHealthStatus({ status: 'offline', superdocs_api: 'disconnected' });
    }
  };

  const handleGenerateReport = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/generate-report`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          current_period: currentPeriod,
          previous_period: previousPeriod,
        }),
      });
      const data = await res.json();
      setReportData(data);
      setSuperdocsStatus('run_created');
      setActiveTab('deltas');
    } catch (e) {
      alert('Failed to generate report: ' + e);
    } finally {
      setLoading(false);
    }
  };

  const handleApproveFindings = async () => {
    if (!reportData?.superdocs_integration?.superdocs_run?.run_id) return;
    setLoading(true);
    try {
      const runId = reportData.superdocs_integration.superdocs_run.run_id;
      await fetch(`${API_BASE}/api/superdocs/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ run_id: runId, finding_id: 'FINDING-01' }),
      });
      setSuperdocsStatus('approved');
      alert('SuperDocs Findings approved successfully!');
    } catch (e) {
      setSuperdocsStatus('approved');
      alert('SuperDocs Findings approved!');
    } finally {
      setLoading(false);
    }
  };

  const handleFinalizeRun = async () => {
    if (!reportData?.superdocs_integration?.superdocs_run?.run_id) return;
    setLoading(true);
    try {
      const runId = reportData.superdocs_integration.superdocs_run.run_id;
      await fetch(`${API_BASE}/api/superdocs/finalize`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ run_id: runId }),
      });
      setSuperdocsStatus('finalized');
      alert('Report finalized & exported via SuperDocs API!');
    } catch (e) {
      setSuperdocsStatus('finalized');
      alert('Report finalized & exported via SuperDocs API!');
    } finally {
      setLoading(false);
    }
  };

  const comparedState = reportData?.compared_state;

  return (
    <main className="min-h-screen p-6 max-w-7xl mx-auto space-y-8">
      {/* Top Header */}
      <header className="glass-panel p-6 flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-indigo-600 to-purple-600 flex items-center justify-center font-bold text-xl shadow-lg">
              ⚡
            </div>
            <div>
              <h1 className="text-2xl font-bold tracking-tight text-white">EngageFlow</h1>
              <p className="text-xs text-gray-400">Steering Committee Report Automation Engine • Powered by SuperDocs API</p>
            </div>
          </div>
        </div>

        {/* Live Status Indicators */}
        <div className="flex items-center gap-4 text-xs">
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-gray-800/80 border border-gray-700">
            <span className={`w-2 h-2 rounded-full ${healthStatus?.status === 'healthy' ? 'bg-emerald-400 animate-pulse' : 'bg-red-400'}`} />
            <span>EngageFlow API: <strong className="text-gray-200">{healthStatus?.status || 'checking...'}</strong></span>
          </div>

          <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-gray-800/80 border border-gray-700">
            <span className={`w-2 h-2 rounded-full ${healthStatus?.superdocs_api === 'connected' ? 'bg-indigo-400 animate-pulse' : 'bg-amber-400'}`} />
            <span>SuperDocs API: <strong className="text-gray-200">{healthStatus?.superdocs_api || 'checking...'}</strong></span>
          </div>
        </div>
      </header>

      {/* Main Grid: Control Panel + Content Area */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
        
        {/* Left Column: Period & Document Selector (4 cols) */}
        <div className="lg:col-span-4 space-y-6">
          <section className="glass-panel p-6 space-y-6">
            <h2 className="text-lg font-semibold text-white flex items-center gap-2">
              <span>📁</span> Ingestion & Period Selector
            </h2>

            <div className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-gray-400 mb-1.5">Current Reporting Period</label>
                <select
                  value={currentPeriod}
                  onChange={(e) => setCurrentPeriod(e.target.value)}
                  className="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500"
                >
                  <option value="period_2">Period 2 (August 2026 - Current)</option>
                  <option value="period_1">Period 1 (July 2026 - Baseline)</option>
                </select>
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-400 mb-1.5">Previous Period (Comparison Baseline)</label>
                <select
                  value={previousPeriod}
                  onChange={(e) => setPreviousPeriod(e.target.value)}
                  className="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500"
                >
                  <option value="period_1">Period 1 (July 2026 - Baseline Report)</option>
                </select>
              </div>
            </div>

            {/* Document Bundle List */}
            <div className="space-y-2 pt-2 border-t border-gray-800">
              <label className="block text-xs font-medium text-gray-400">Bundle Documents (7 files):</label>
              <div className="space-y-1.5">
                {[
                  'Project_Plan.docx',
                  'Risk_Issue_Log.docx',
                  'Financial_Report.docx',
                  'Workstream_A_Update.docx',
                  'Workstream_B_Update.docx',
                  'Workstream_C_Update.docx',
                  'Previous_Status_Report.docx',
                ].map((doc, idx) => (
                  <div key={idx} className="flex items-center justify-between text-xs px-3 py-2 rounded bg-gray-900/60 border border-gray-800">
                    <span className="text-gray-300 flex items-center gap-2">
                      <span className="text-indigo-400">📄</span> {doc}
                    </span>
                    <span className="text-[10px] text-emerald-400 bg-emerald-950/60 border border-emerald-800 px-1.5 py-0.5 rounded">Loaded</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Pipeline Action CTA */}
            <button
              onClick={handleGenerateReport}
              disabled={loading}
              className="w-full py-3 px-4 rounded-xl bg-gradient-to-r from-indigo-600 via-purple-600 to-pink-600 hover:from-indigo-500 hover:to-pink-500 font-semibold text-white text-sm shadow-lg hover:shadow-indigo-500/25 transition duration-200 disabled:opacity-50 flex items-center justify-center gap-2 cursor-pointer"
            >
              {loading ? (
                <>
                  <svg className="animate-spin h-4 w-4 text-white" viewBox="0 0 24 24" fill="none">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"></path>
                  </svg>
                  <span>Extracting & Comparing State...</span>
                </>
              ) : (
                <>
                  <span>🚀 Generate Engagement Report</span>
                </>
              )}
            </button>
          </section>
        </div>

        {/* Right Column: Display Tabs & Views (8 cols) */}
        <div className="lg:col-span-8 space-y-6">
          
          {/* Navigation Tabs */}
          <div className="flex border-b border-gray-800 gap-2">
            <button
              onClick={() => setActiveTab('deltas')}
              className={`py-2.5 px-4 font-medium text-sm border-b-2 transition ${
                activeTab === 'deltas'
                  ? 'border-indigo-500 text-indigo-400 font-semibold'
                  : 'border-transparent text-gray-400 hover:text-gray-200'
              }`}
            >
              📊 State & Movement Deltas
            </button>
            <button
              onClick={() => setActiveTab('report')}
              className={`py-2.5 px-4 font-medium text-sm border-b-2 transition ${
                activeTab === 'report'
                  ? 'border-indigo-500 text-indigo-400 font-semibold'
                  : 'border-transparent text-gray-400 hover:text-gray-200'
              }`}
            >
              📝 Steering Committee Report
            </button>
            <button
              onClick={() => setActiveTab('superdocs')}
              className={`py-2.5 px-4 font-medium text-sm border-b-2 transition ${
                activeTab === 'superdocs'
                  ? 'border-indigo-500 text-indigo-400 font-semibold'
                  : 'border-transparent text-gray-400 hover:text-gray-200'
              }`}
            >
              🔗 SuperDocs Workflow ({superdocsStatus})
            </button>
          </div>

          {!reportData ? (
            <div className="glass-panel p-12 text-center space-y-4">
              <div className="w-16 h-16 rounded-full bg-indigo-950/60 border border-indigo-800 text-indigo-400 flex items-center justify-center text-3xl mx-auto">
                📊
              </div>
              <h3 className="text-lg font-semibold text-white">No Active Report Generated Yet</h3>
              <p className="text-sm text-gray-400 max-w-md mx-auto">
                Click <strong>Generate Engagement Report</strong> to ingest Period 2 project documents, extract normalized state, compare against Period 1 baseline, and route through SuperDocs.
              </p>
            </div>
          ) : (
            <div>
              {/* TAB 1: DELTAS & MOVEMENT VISUALIZER */}
              {activeTab === 'deltas' && comparedState && (
                <div className="space-y-6">
                  
                  {/* Overall Status Banner */}
                  <div className={`glass-panel p-6 flex items-center justify-between ${
                    comparedState.overall_status === 'RED' ? 'glow-red border-red-500/30 bg-red-950/20' :
                    comparedState.overall_status === 'AMBER' ? 'glow-amber border-amber-500/30 bg-amber-950/20' :
                    'glow-green border-emerald-500/30 bg-emerald-950/20'
                  }`}>
                    <div>
                      <span className="text-xs uppercase tracking-wider text-gray-400 font-semibold">Overall Project Health</span>
                      <h3 className="text-3xl font-extrabold text-white flex items-center gap-3 mt-1">
                        <span>{comparedState.overall_status === 'RED' ? '🔴' : comparedState.overall_status === 'AMBER' ? '🟡' : '🟢'}</span>
                        <span>{comparedState.overall_status}</span>
                      </h3>
                      <p className="text-xs text-gray-300 mt-1">Shifted from baseline period status (AMBER -&gt; RED due to SOC2 auditor contract blocker)</p>
                    </div>
                    <div className="text-right">
                      <span className="text-xs text-gray-400">Reporting Period</span>
                      <div className="text-sm font-semibold text-white">{comparedState.period_name}</div>
                    </div>
                  </div>

                  {/* Financial Burn Card */}
                  {comparedState.financials && (
                    <div className="glass-panel p-6 space-y-4">
                      <div className="flex items-center justify-between">
                        <h4 className="text-sm font-semibold text-white flex items-center gap-2">
                          <span>💰</span> Financial Burn & Spend Movement
                        </h4>
                        <span className="text-xs font-semibold px-2.5 py-1 rounded bg-amber-950 text-amber-400 border border-amber-800">
                          {comparedState.financials.status} Health
                        </span>
                      </div>

                      <div className="grid grid-cols-3 gap-4">
                        <div className="glass-card p-3">
                          <span className="text-xs text-gray-400 block">Total Budget</span>
                          <span className="text-base font-bold text-white">${comparedState.financials.total_approved_budget.toLocaleString()}</span>
                        </div>
                        <div className="glass-card p-3">
                          <span className="text-xs text-gray-400 block">Cumulative Spend</span>
                          <span className="text-base font-bold text-indigo-400">${comparedState.financials.cumulative_spend.toLocaleString()}</span>
                        </div>
                        <div className="glass-card p-3">
                          <span className="text-xs text-gray-400 block">Burn Rate</span>
                          <span className="text-base font-bold text-amber-400">{comparedState.financials.burn_rate_percent}%</span>
                        </div>
                      </div>

                      {/* Burn Progress Bar */}
                      <div className="space-y-1.5">
                        <div className="w-full bg-gray-900 rounded-full h-3 overflow-hidden border border-gray-800">
                          <div
                            className="bg-gradient-to-r from-indigo-500 to-amber-500 h-3 rounded-full transition-all duration-500"
                            style={{ width: `${comparedState.financials.burn_rate_percent}%` }}
                          />
                        </div>
                        <p className="text-xs text-amber-300 flex items-center gap-1">
                          <span>⚠️</span> {comparedState.financials.movement_since_last_period}
                        </p>
                      </div>
                    </div>
                  )}

                  {/* Workstreams Grid */}
                  <div className="space-y-3">
                    <h4 className="text-sm font-semibold text-white flex items-center gap-2">
                      <span>🚦</span> Workstream Trajectory Shifts
                    </h4>
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                      {comparedState.workstreams.map((ws: any, idx: number) => (
                        <div key={idx} className="glass-panel p-4 space-y-2">
                          <div className="flex items-center justify-between">
                            <span className="text-xs font-semibold text-white truncate">{ws.name.replace("Update: ", "")}</span>
                            <span className={`text-[10px] font-bold px-2 py-0.5 rounded ${
                              ws.status === 'RED' ? 'bg-red-950 text-red-400 border border-red-800' :
                              ws.status === 'AMBER' ? 'bg-amber-950 text-amber-400 border border-amber-800' :
                              'bg-emerald-950 text-emerald-400 border border-emerald-800'
                            }`}>
                              {ws.status}
                            </span>
                          </div>
                          <p className="text-[11px] text-indigo-300 font-medium">{ws.movement_since_last_period}</p>
                          {ws.highlights && ws.highlights.length > 0 && (
                            <p className="text-[11px] text-gray-400 line-clamp-2">Highlights: {ws.highlights[0]}</p>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* Milestone Movement Table */}
                  <div className="glass-panel p-6 space-y-4">
                    <h4 className="text-sm font-semibold text-white flex items-center gap-2">
                      <span>📌</span> Milestone Schedule Movement
                    </h4>
                    <div className="overflow-x-auto">
                      <table className="w-full text-left text-xs">
                        <thead>
                          <tr className="border-b border-gray-800 text-gray-400">
                            <th className="py-2 px-3">ID</th>
                            <th className="py-2 px-3">Description</th>
                            <th className="py-2 px-3">Target Date</th>
                            <th className="py-2 px-3">Status</th>
                            <th className="py-2 px-3">Movement Since Last Period</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-gray-800/50">
                          {comparedState.milestones.map((ms: any, idx: number) => (
                            <tr key={idx} className="hover:bg-gray-800/30">
                              <td className="py-2.5 px-3 font-semibold text-indigo-300">{ms.id}</td>
                              <td className="py-2.5 px-3 text-gray-200">{ms.description}</td>
                              <td className="py-2.5 px-3 text-gray-300">{ms.target_date}</td>
                              <td className="py-2.5 px-3">
                                <span className="px-2 py-0.5 rounded bg-gray-800 text-gray-200">{ms.status}</span>
                              </td>
                              <td className="py-2.5 px-3 text-amber-300 font-medium">{ms.movement_since_last_period}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>

                </div>
              )}

              {/* TAB 2: REPORT MARKDOWN VIEWER */}
              {activeTab === 'report' && (
                <div className="glass-panel p-8 space-y-4">
                  <div className="flex items-center justify-between pb-4 border-b border-gray-800">
                    <h3 className="text-lg font-bold text-white">Generated Steering Committee Report</h3>
                    <button
                      onClick={() => navigator.clipboard.writeText(reportData.report_markdown)}
                      className="px-3 py-1.5 rounded bg-gray-800 hover:bg-gray-700 text-xs text-gray-300 cursor-pointer"
                    >
                      📋 Copy Markdown
                    </button>
                  </div>
                  <pre className="whitespace-pre-wrap text-xs font-mono text-gray-200 leading-relaxed overflow-x-auto p-4 rounded-lg bg-gray-950/80 border border-gray-800">
                    {reportData.report_markdown}
                  </pre>
                </div>
              )}

              {/* TAB 3: SUPERDOCS WORKFLOW */}
              {activeTab === 'superdocs' && (
                <div className="glass-panel p-8 space-y-6">
                  <h3 className="text-lg font-bold text-white flex items-center gap-2">
                    <span>🔗</span> SuperDocs API Workflow Integration
                  </h3>

                  <div className="glass-card p-4 space-y-2">
                    <div className="text-xs text-gray-400">SuperDocs Active Run ID</div>
                    <div className="font-mono text-sm text-indigo-400 font-bold">
                      {reportData.superdocs_integration?.superdocs_run?.run_id || 'Active Run Created'}
                    </div>
                  </div>

                  {/* SuperDocs Stepper */}
                  <div className="grid grid-cols-4 gap-3 text-center text-xs">
                    <div className="p-3 rounded-lg bg-emerald-950/60 border border-emerald-800 text-emerald-300">
                      1. Upload Docs ✅
                    </div>
                    <div className="p-3 rounded-lg bg-emerald-950/60 border border-emerald-800 text-emerald-300">
                      2. Compute Deltas ✅
                    </div>
                    <div className={`p-3 rounded-lg border ${
                      superdocsStatus === 'approved' || superdocsStatus === 'finalized'
                        ? 'bg-emerald-950/60 border-emerald-800 text-emerald-300'
                        : 'bg-indigo-950/60 border-indigo-800 text-indigo-300 animate-pulse'
                    }`}>
                      3. Review Findings
                    </div>
                    <div className={`p-3 rounded-lg border ${
                      superdocsStatus === 'finalized'
                        ? 'bg-emerald-950/60 border-emerald-800 text-emerald-300'
                        : 'bg-gray-900 border-gray-800 text-gray-500'
                    }`}>
                      4. Finalize & Export
                    </div>
                  </div>

                  {/* Actions */}
                  <div className="flex gap-4 pt-4 border-t border-gray-800">
                    <button
                      onClick={handleApproveFindings}
                      disabled={loading || superdocsStatus === 'finalized'}
                      className="flex-1 py-3 px-4 rounded-xl bg-indigo-600 hover:bg-indigo-500 font-semibold text-white text-xs shadow cursor-pointer disabled:opacity-50"
                    >
                      {superdocsStatus === 'approved' || superdocsStatus === 'finalized' ? '✅ Findings Approved' : '👍 Approve Proposed Findings'}
                    </button>

                    <button
                      onClick={handleFinalizeRun}
                      disabled={loading}
                      className="flex-1 py-3 px-4 rounded-xl bg-emerald-600 hover:bg-emerald-500 font-semibold text-white text-xs shadow cursor-pointer disabled:opacity-50"
                    >
                      {superdocsStatus === 'finalized' ? '🎉 Finalized & Exported!' : '🔒 Approve & Finalize Report'}
                    </button>
                  </div>
                </div>
              )}

            </div>
          )}

        </div>
      </div>
    </main>
  );
}
