import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import anime from 'animejs';
import { FileText, CheckCircle, XCircle, ChevronRight, Activity, Download, ArrowLeft } from 'lucide-react';
import ProseMirrorEditor from './components/ProseMirrorEditor';
import html2pdf from 'html2pdf.js';
import './index.css';

const API_BASE = 'http://localhost:8000/api';

function App() {
  const [documents, setDocuments] = useState([]);
  const [jobsList, setJobsList] = useState([]);
  const [job, setJob] = useState(null);
  const [loading, setLoading] = useState(false);
  const [decisions, setDecisions] = useState({});
  const [editingContent, setEditingContent] = useState('');
  const [exportUrl, setExportUrl] = useState(null);
  const [hasStarted, setHasStarted] = useState(false);
  const [isNavMovedLeft, setIsNavMovedLeft] = useState(false);
  const [commitTimestamp, setCommitTimestamp] = useState(Date.now());

  const handleStart = () => {
    setHasStarted(true);
    generatePackets();
    setTimeout(() => {
      setIsNavMovedLeft(true);
    }, 600);
  };

  const handleBack = () => {
    if (job) {
      setJob(null);
    } else {
      setIsNavMovedLeft(false);
      setTimeout(() => {
        setHasStarted(false);
        setDocuments([]);
        setJobsList([]);
      }, 600);
    }
  };

  const containerRef = useRef(null);
  const jobPanelRef = useRef(null);

  useEffect(() => {

    anime({
      targets: containerRef.current,
      opacity: [0, 1],
      translateY: [20, 0],
      duration: 800,
      easing: 'easeOutExpo'
    });
  }, []);

  useEffect(() => {
    if (job && jobPanelRef.current) {
      anime({
        targets: jobPanelRef.current,
        opacity: [0, 1],
        translateX: [20, 0],
        duration: 600,
        easing: 'easeOutQuart'
      });
    }
  }, [job?.job_id]); // Only trigger animation when the job changes, not on every poll update


  useEffect(() => {
    let interval;
    if (job && (job.status === 'starting' || job.status === 'in_progress' || job.status === 'invoked')) {
      interval = setInterval(() => {
        axios.get(`${API_BASE}/jobs/${job.job_id}`).then(res => {
          setJob(res.data);
        }).catch(err => console.error("Polling error:", err));
      }, 3000);
    }
    return () => clearInterval(interval);
  }, [job]);

  const generatePackets = async () => {
    setLoading(true);
    try {
      const res = await axios.post(`${API_BASE}/generate_enrollment`);
      setJobsList(res.data.jobs || []);
      anime({
        targets: '.doc-card',
        opacity: [0, 1],
        scale: [0.95, 1],
        delay: anime.stagger(100),
        duration: 500,
        easing: 'easeOutElastic(1, .8)'
      });
    } finally {
      setLoading(false);
    }
  };

  const fetchJob = async (jobId) => {
    setLoading(true);
    try {
      const res = await axios.get(`${API_BASE}/jobs/${jobId}`);
      setJob(res.data);
      setDecisions({});
      setExportUrl(null);
    } finally {
      setLoading(false);
    }
  };

  const toggleDecision = (changeId, status) => {
    setDecisions(prev => ({
      ...prev,
      [changeId]: prev[changeId] === status ? undefined : status
    }));
  };

  const approveEdit = async (jobId) => {
    const items = Object.entries(decisions).map(([item_id, status]) => ({ item_id, status }));


    anime({
      targets: '#submit-btn',
      scale: [0.95, 1.05, 1],
      duration: 400,
      easing: 'easeInOutQuad'
    });

    try {
      const res = await axios.post(`${API_BASE}/jobs/${jobId}/approve`, { items });


      const exportRes = await axios.post(`${API_BASE}/export/${job.document_id}`);
      setExportUrl(exportRes.data.download_url);


      let finalText = '';
      job.proposed_changes.forEach(change => {
        const isApproved = decisions[change.id] === 'approved';
        finalText += isApproved ? (change.proposed || '') : (change.original || '');
      });

      setEditingContent(finalText);
      setCommitTimestamp(Date.now());

      alert(`Job processed! ${res.data.approved_items_count} items approved.`);
    } catch (err) {
      console.error(err);
      alert('Failed to approve job.');
    }
  };

  const downloadPdf = (e) => {
    e.preventDefault();


    const element = document.querySelector('.ProseMirror').cloneNode(true);


    element.style.color = 'black';
    element.style.backgroundColor = 'white';
    element.style.padding = '2rem';


    element.querySelectorAll('h1, h2, h3').forEach(h => {
      h.style.color = 'black';
    });

    const opt = {
      margin: 1,
      filename: `${job?.job_id || 'document'}.pdf`,
      image: { type: 'jpeg', quality: 0.98 },
      html2canvas: { scale: 2 },
      jsPDF: { unit: 'in', format: 'letter', orientation: 'portrait' }
    };

    html2pdf().set(opt).from(element).save();
  };

  return (
    <div ref={containerRef} style={{ padding: '2rem', maxWidth: '1400px', margin: '0 auto' }}>

      <header style={{
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'center',
        marginBottom: hasStarted ? '3rem' : '0',
        height: hasStarted ? '10vh' : '80vh',
        transition: 'all 0.6s cubic-bezier(0.4, 0, 0.2, 1)'
      }}>
        <div style={{
          display: 'flex',
          width: '100%',
          alignItems: 'center',
        }}>
          {/* Left Spacer for centering */}
          <div style={{
            flexGrow: isNavMovedLeft ? 0 : 1,
            transition: 'flex-grow 0.6s cubic-bezier(0.4, 0, 0.2, 1)'
          }} />

          {/* Content Container */}
          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: isNavMovedLeft ? '1rem' : '0',
          }}>
            <button
              onClick={handleBack}
              style={{
                background: 'transparent',
                border: 'none',
                color: 'var(--text-secondary)',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                padding: '0.5rem',
                margin: 0,
                opacity: isNavMovedLeft ? 1 : 0,
                width: isNavMovedLeft ? '48px' : '0',
                overflow: 'hidden',
                pointerEvents: isNavMovedLeft ? 'auto' : 'none',
                transition: 'all 0.4s ease',
                transform: isNavMovedLeft ? 'translateX(0)' : 'translateX(-20px)'
              }}
              title="Go Back"
            >
              <ArrowLeft size={28} />
            </button>
            <div style={{ textAlign: isNavMovedLeft ? 'left' : 'center', transition: 'all 0.6s ease' }}>
              <h1 style={{
                fontSize: hasStarted ? '1.8rem' : '4rem',
                fontWeight: 700,
                letterSpacing: '-0.02em',
                margin: 0,
                background: 'linear-gradient(to right, #e2e8f0, #94a3b8)',
                WebkitBackgroundClip: 'text',
                WebkitTextFillColor: 'transparent',
                transition: 'all 0.6s ease'
              }}>
                SuperDocs Agent
              </h1>
              <p style={{
                color: 'var(--text-secondary)',
                fontSize: '1.2rem',
                opacity: hasStarted ? 0 : 1,
                height: hasStarted ? 0 : '30px',
                overflow: 'hidden',
                transition: 'all 0.4s ease',
                margin: hasStarted ? 0 : '0.5rem 0 0 0'
              }}>
              </p>
            </div>
          </div>

          {/* Right Spacer for centering */}
          <div style={{ flexGrow: 1 }} />
        </div>

        <div style={{
          display: 'flex',
          justifyContent: 'center',
          marginTop: hasStarted ? 0 : '0.5rem',
          opacity: hasStarted ? 0 : 1,
          pointerEvents: hasStarted ? 'none' : 'auto',
          height: hasStarted ? 0 : '60px',
          overflow: 'hidden',
          transition: 'all 0.4s ease'
        }}>
          <button
            className="btn btn-primary"
            onClick={handleStart}
            disabled={loading}
            style={{ fontSize: '1.2rem', padding: '1rem 2.5rem', borderRadius: '50px' }}
          >
            {loading ? <Activity size={20} className="spin" /> : <ChevronRight size={20} />}
            Generate HR Packets
          </button>
        </div>
      </header>

      <div style={{
        opacity: hasStarted ? 1 : 0,
        transform: hasStarted ? 'translateY(0)' : 'translateY(40px)',
        transition: 'all 0.8s cubic-bezier(0.4, 0, 0.2, 1)',
        pointerEvents: hasStarted ? 'auto' : 'none',
        display: 'grid',
        gridTemplateColumns: job ? '1fr 1fr' : '1fr',
        gap: '2rem'
      }}>

        {/* Left Column: Documents Dashboard */}
        <section>
          {jobsList.length > 0 && (
            <h2 style={{ marginBottom: '1.5rem', fontSize: '1.2rem', color: 'var(--text-secondary)' }}>
              Employee Enrollment Packets
            </h2>
          )}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            {jobsList.map(jobItem => (
              <div
                key={jobItem.job_id}
                className="doc-card glass-panel"
                style={{ padding: '1.5rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
                  <div style={{ padding: '10px', background: 'rgba(99, 102, 241, 0.1)', borderRadius: '10px', color: 'var(--accent-color)' }}>
                    <FileText size={24} />
                  </div>
                  <div>
                    <h3 style={{ margin: 0, fontSize: '1.1rem' }}>
                      {jobItem.employee_name ? `${jobItem.employee_name} - Packet` : 'Manager FAQ'}
                    </h3>
                    <span style={{ fontSize: '0.8rem', color: 'var(--success-color)', textTransform: 'uppercase', letterSpacing: '1px' }}>
                      {jobItem.type}
                    </span>
                  </div>
                </div>
                <button
                  className="btn"
                  style={{ backgroundColor: 'rgba(255,255,255,0.05)', border: '1px solid var(--glass-border)' }}
                  onClick={() => fetchJob(jobItem.job_id)}
                >
                  Review Packet
                </button>
              </div>
            ))}
          </div>
        </section>

        {/* Right Column: Item-by-Item Review Gate */}
        {job && (
          <section ref={jobPanelRef} className="glass-panel" style={{ padding: '2rem', display: 'flex', flexDirection: 'column', height: 'fit-content' }}>
            <div style={{ marginBottom: '2rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <h2 style={{ margin: 0, fontSize: '1.5rem', color: 'white' }}>Human Review Gate</h2>
              <span style={{ padding: '4px 12px', background: 'rgba(239, 169, 68, 0.2)', color: '#fbbf24', borderRadius: '20px', fontSize: '0.8rem', fontWeight: 600 }}>
                {job.status === 'pending' ? 'AWAITING DECISION' : job.status.toUpperCase().replace('_', ' ')}
              </span>
            </div>

            {job.status === 'pending' || job.status === 'approved' ? (
              <>
                <p style={{ color: 'var(--text-secondary)', marginBottom: '1.5rem', fontSize: '0.9rem' }}>
                  Review the agent's proposed changes for {job.document_id}. Rejecting one item will not discard the others.
                </p>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem', marginBottom: '2rem' }}>
                  {job.proposed_changes?.map((change) => {
                    const decision = decisions[change.id];

                    return (
                      <div key={change.id} style={{
                        padding: '1.2rem',
                        background: 'rgba(0,0,0,0.2)',
                        borderRadius: '12px',
                        border: '1px solid',
                        borderColor: decision === 'approved' ? 'var(--success-color)' : decision === 'rejected' ? 'var(--danger-color)' : 'transparent',
                        transition: 'border-color 0.3s'
                      }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.8rem' }}>
                          <strong style={{ color: 'var(--accent-color)' }}>{change.section}</strong>
                          <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>ID: {change.id}</span>
                        </div>

                        <div style={{ display: 'flex', gap: '1rem', marginBottom: '1rem' }}>
                          <div
                            style={{ flex: 1, padding: '0.8rem', background: 'rgba(239, 68, 68, 0.05)', borderRadius: '8px', color: 'var(--text-secondary)', overflowWrap: 'anywhere' }}
                            dangerouslySetInnerHTML={{ __html: change.original ? `<del>${change.original}</del>` : '' }}
                          />
                          <div
                            style={{ flex: 1, padding: '0.8rem', background: 'rgba(16, 185, 129, 0.05)', borderRadius: '8px', color: 'white', overflowWrap: 'anywhere' }}
                            dangerouslySetInnerHTML={{ __html: change.proposed || '' }}
                          />
                        </div>

                        <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'flex-end' }}>
                          <button
                            className={`btn ${decision === 'rejected' ? 'btn-danger' : ''}`}
                            style={{ opacity: decision === 'approved' ? 0.3 : 1 }}
                            onClick={() => toggleDecision(change.id, 'rejected')}
                          >
                            <XCircle size={16} /> Reject
                          </button>
                          <button
                            className={`btn ${decision === 'approved' ? 'btn-success' : ''}`}
                            style={{ opacity: decision === 'rejected' ? 0.3 : 1 }}
                            onClick={() => toggleDecision(change.id, 'approved')}
                          >
                            <CheckCircle size={16} /> Approve
                          </button>
                        </div>
                      </div>
                    )
                  })}
                </div>

                <button
                  id="submit-btn"
                  className="btn btn-primary"
                  style={{ padding: '1rem', fontSize: '1.1rem', width: '100%' }}
                  onClick={() => approveEdit(job.job_id)}
                >
                  Commit Selected Changes
                </button>

                {exportUrl && (
                  <div style={{ marginTop: '2rem', paddingTop: '2rem', borderTop: '1px solid var(--glass-border)' }}>
                    <button onClick={downloadPdf} className="btn btn-success" style={{ display: 'flex', width: '100%', marginBottom: '1.5rem', textDecoration: 'none' }}>
                      <Download size={18} /> Download Final PDF Deliverable
                    </button>

                    <h3 style={{ marginBottom: '1rem', color: 'var(--text-secondary)' }}>Review Editor</h3>
                    <ProseMirrorEditor key={commitTimestamp} initialHtml={editingContent} onChange={setEditingContent} />
                  </div>
                )}
              </>
            ) : (
              <div style={{ textAlign: 'center', padding: '3rem' }}>
                <Activity size={32} className="spin" style={{ color: 'var(--accent-color)', marginBottom: '1rem' }} />
                <h3 style={{ color: 'white', marginBottom: '0.5rem' }}>Analyzing Document...</h3>
                <p style={{ color: 'var(--text-secondary)' }}>SuperDocs AI is processing edits.</p>
                <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>This usually takes 30-60 seconds.</p>
              </div>
            )}
          </section>
        )}
      </div>

      {/* Global CSS for spinner */}
      <style>{`
        @keyframes spin { 100% { transform: rotate(360deg); } }
        .spin { animation: spin 1s linear infinite; }
      `}</style>
    </div>
  );
}

export default App;
