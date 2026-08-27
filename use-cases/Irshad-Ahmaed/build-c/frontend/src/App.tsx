import React, { useState } from 'react';
import { Header } from './components/Header';
import { NotesDesk } from './components/NotesDesk';
import { GuidePreview } from './components/GuidePreview';
import { ChatRefineBar } from './components/ChatRefineBar';
import { PRESETS, StudyPreset } from './data/presets';

export const App: React.FC = () => {
  const defaultPreset = PRESETS[0];

  const [subject, setSubject] = useState(defaultPreset.subject);
  const [topic, setTopic] = useState(defaultPreset.topic);
  const [targetExam, setTargetExam] = useState(defaultPreset.targetExam);
  const [rawNotes, setRawNotes] = useState(defaultPreset.notes);
  const [depth, setDepth] = useState('detailed');

  const [sessionId, setSessionId] = useState<string | null>(null);
  const [guideMarkdown, setGuideMarkdown] = useState<string>('');
  const [isGenerating, setIsGenerating] = useState(false);
  const [isRefining, setIsRefining] = useState(false);
  const [isExporting, setIsExporting] = useState(false);
  const [pdfDataUrl, setPdfDataUrl] = useState<string | null>(null);
  const [pageCount, setPageCount] = useState(1);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const handleSelectPreset = (preset: StudyPreset) => {
    setSubject(preset.subject);
    setTopic(preset.topic);
    setTargetExam(preset.targetExam);
    setRawNotes(preset.notes);
  };

  const handleGenerate = async () => {
    setIsGenerating(true);
    setErrorMessage(null);
    setPdfDataUrl(null);
    try {
      const res = await fetch('http://localhost:8000/api/study-guide/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          subject,
          topic,
          target_exam: targetExam,
          raw_notes: rawNotes,
          depth,
        }),
      });

      if (!res.ok) {
        throw new Error(`Server returned HTTP ${res.status}`);
      }

      const data = await res.json();
      setSessionId(data.session_id);
      setGuideMarkdown(data.guide_markdown);
    } catch (e: any) {
      setErrorMessage(e.message || 'Failed to synthesize study guide.');
    } finally {
      setIsGenerating(false);
    }
  };

  const handleRefine = async (instruction: string) => {
    if (!guideMarkdown) return;
    setIsRefining(true);
    setErrorMessage(null);
    try {
      const res = await fetch('http://localhost:8000/api/study-guide/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId || 'default_session',
          current_markdown: guideMarkdown,
          instruction,
        }),
      });

      if (!res.ok) {
        throw new Error(`Server returned HTTP ${res.status}`);
      }

      const data = await res.json();
      setGuideMarkdown(data.updated_markdown);
    } catch (e: any) {
      setErrorMessage(e.message || 'Failed to apply refinement.');
    } finally {
      setIsRefining(false);
    }
  };

  const handleExportPdf = async () => {
    if (!guideMarkdown) return;
    setIsExporting(true);
    setErrorMessage(null);
    try {
      const res = await fetch('http://localhost:8000/api/study-guide/export', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          subject,
          topic,
          guide_markdown: guideMarkdown,
        }),
      });

      if (!res.ok) {
        throw new Error(`Server returned HTTP ${res.status}`);
      }

      const data = await res.json();
      setPdfDataUrl(data.download_url);
      setPageCount(data.page_count || 1);
    } catch (e: any) {
      setErrorMessage(e.message || 'Failed to export PDF.');
    } finally {
      setIsExporting(false);
    }
  };

  const handleQuickReviewerTest = async () => {
    handleSelectPreset(PRESETS[0]);
    setIsGenerating(true);
    setErrorMessage(null);
    setPdfDataUrl(null);
    try {
      const res = await fetch('http://localhost:8000/api/study-guide/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          subject: PRESETS[0].subject,
          topic: PRESETS[0].topic,
          target_exam: PRESETS[0].targetExam,
          raw_notes: PRESETS[0].notes,
          depth: 'detailed',
        }),
      });

      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setSessionId(data.session_id);
      setGuideMarkdown(data.guide_markdown);
    } catch (e: any) {
      setErrorMessage(e.message);
    } finally {
      setIsGenerating(false);
    }
  };

  return (
    <div className="app-container">
      <Header
        onQuickReviewerTest={handleQuickReviewerTest}
        isGenerating={isGenerating}
      />

      <main className="main-content">
        {errorMessage && (
          <div style={{
            background: 'var(--rose-bg)',
            border: '1px solid var(--rose-border)',
            color: 'var(--rose-text)',
            padding: '12px 16px',
            borderRadius: '10px',
            fontSize: '12px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between'
          }}>
            <span>⚠️ Error: {errorMessage}</span>
            <button
              onClick={() => setErrorMessage(null)}
              style={{ background: 'none', border: 'none', color: 'var(--rose-text)', cursor: 'pointer', fontWeight: '700' }}
            >
              ✕
            </button>
          </div>
        )}

        <div className="split-grid">
          <NotesDesk
            subject={subject}
            setSubject={setSubject}
            topic={topic}
            setTopic={setTopic}
            targetExam={targetExam}
            setTargetExam={setTargetExam}
            rawNotes={rawNotes}
            setRawNotes={setRawNotes}
            depth={depth}
            setDepth={setDepth}
            onGenerate={handleGenerate}
            isGenerating={isGenerating}
            onSelectPreset={handleSelectPreset}
          />

          <GuidePreview
            guideMarkdown={guideMarkdown}
            isGenerating={isGenerating}
            onExportPdf={handleExportPdf}
            isExporting={isExporting}
            pdfDataUrl={pdfDataUrl}
            pageCount={pageCount}
          />
        </div>

        <ChatRefineBar
          onRefine={handleRefine}
          isRefining={isRefining}
          disabled={!guideMarkdown || isGenerating}
        />
      </main>

      <footer className="footer-nav">
        SuperDocs Open Task List · Build C (Band S2) · Irshad Ahmad
      </footer>
    </div>
  );
};
export default App;
