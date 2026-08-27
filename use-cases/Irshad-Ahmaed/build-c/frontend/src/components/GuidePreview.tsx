import React, { useState } from 'react';
import katex from 'katex';

interface GuidePreviewProps {
  guideMarkdown: string;
  isGenerating: boolean;
  onExportPdf: () => void;
  isExporting: boolean;
  pdfDataUrl: string | null;
  pageCount: number;
}

export const GuidePreview: React.FC<GuidePreviewProps> = ({
  guideMarkdown,
  isGenerating,
  onExportPdf,
  isExporting,
  pdfDataUrl,
  pageCount,
}) => {
  const [activeTab, setActiveTab] = useState<'preview' | 'markdown'>('preview');
  const [copySuccess, setCopySuccess] = useState(false);

  const handleCopyMarkdown = () => {
    navigator.clipboard.writeText(guideMarkdown);
    setCopySuccess(true);
    setTimeout(() => setCopySuccess(false), 2000);
  };

  const formatMarkdownToHtml = (md: string) => {
    if (!md) return '<p style="color: var(--text-muted); font-style: italic;">No study guide generated yet. Select an academic preset or paste notes on the left to begin.</p>';
    
    let html = md;

    // 1. Render display math $$ ... $$
    html = html.replace(/\$\$\s*([\s\S]*?)\s*\$\$/g, (_, math) => {
      try {
        return `<div class="katex-display-box">${katex.renderToString(math.trim(), { displayMode: true, throwOnError: false })}</div>`;
      } catch (e) {
        return `$$${math}$$`;
      }
    });

    // 2. Render inline math $ ... $
    html = html.replace(/\$([^\$\n]+?)\$/g, (_, math) => {
      try {
        return katex.renderToString(math.trim(), { displayMode: false, throwOnError: false });
      } catch (e) {
        return `$${math}$`;
      }
    });

    // 3. Headings
    html = html.replace(/^# (.*$)/gim, '<h1 style="font-size: 18px; font-weight: 700; color: #fff; border-bottom: 2px solid var(--emerald-solid); padding-bottom: 6px; margin-bottom: 14px;">$1</h1>');
    html = html.replace(/^## (.*$)/gim, '<h2 style="font-size: 14px; font-weight: 600; color: var(--emerald-text); border-bottom: 1px solid var(--border-subtle); padding-bottom: 4px; margin-top: 18px; margin-bottom: 10px;">$1</h2>');
    html = html.replace(/^### (.*$)/gim, '<h3 style="font-size: 13px; font-weight: 500; color: var(--cyan-text); margin-top: 12px; margin-bottom: 6px;">$1</h3>');
    
    // 4. Horizontal rules
    html = html.replace(/^---$/gim, '<hr style="border: 0; border-top: 1px solid var(--border-subtle); margin: 16px 0;" />');
    
    // 5. Blockquotes
    html = html.replace(/^> (.*$)/gim, '<blockquote style="background: var(--emerald-bg); border-left: 3px solid var(--emerald-solid); padding: 8px 12px; border-radius: 0 6px 6px 0; color: var(--emerald-text); font-size: 12px; margin: 10px 0;">$1</blockquote>');
    
    // 6. Bold & Italics
    html = html.replace(/\*\*(.*?)\*\*/gim, '<strong style="color: #fff; font-weight: 600;">$1</strong>');
    html = html.replace(/\*(.*?)\*/gim, '<em style="color: var(--text-secondary);">$1</em>');
    
    // 7. List items
    html = html.replace(/^[*-] (.*$)/gim, '<li style="margin-left: 18px; margin-bottom: 4px; color: var(--text-secondary);">$1</li>');
    
    // 8. Render Markdown tables nicely
    const lines = html.split('\n');
    let inTable = false;
    let tableHtml = '';
    const outputLines: string[] = [];

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i].trim();
      if (line.startsWith('|') && line.endsWith('|')) {
        if (!inTable) {
          inTable = true;
          tableHtml = '<table class="table-rendered">';
        }
        if (line.includes('---')) {
          continue;
        }
        const cells = line.split('|').slice(1, -1);
        const isHeader = !tableHtml.includes('<tbody>') && !tableHtml.includes('<tr>');
        const tag = isHeader ? 'th' : 'td';
        tableHtml += '<tr>' + cells.map(c => `<${tag}>${c.trim()}</${tag}>`).join('') + '</tr>';
      } else {
        if (inTable) {
          inTable = false;
          tableHtml += '</table>';
          outputLines.push(tableHtml);
          tableHtml = '';
        }
        outputLines.push(line);
      }
    }
    if (inTable) {
      tableHtml += '</table>';
      outputLines.push(tableHtml);
    }

    html = outputLines.join('\n');
    html = html.replace(/\n\n/gim, '</p><p style="margin: 8px 0; color: var(--text-primary); font-size: 12.5px; line-height: 1.6;">');

    return `<div style="font-size: 12.5px; line-height: 1.6;">${html}</div>`;
  };

  return (
    <div className="card" style={{ flex: 1, minHeight: '520px' }}>
      {/* Header Toolbar */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: '1px solid var(--border-subtle)', paddingBottom: '10px', flexWrap: 'wrap', gap: '10px' }}>
        <div style={{ display: 'flex', gap: '6px' }}>
          <button
            onClick={() => setActiveTab('preview')}
            className={activeTab === 'preview' ? 'btn-cyan' : 'btn-secondary'}
          >
            👁️ Rendered Guide & Math
          </button>
          <button
            onClick={() => setActiveTab('markdown')}
            className={activeTab === 'markdown' ? 'btn-cyan' : 'btn-secondary'}
          >
            📋 Raw Markdown
          </button>
        </div>

        <div style={{ display: 'flex', gap: '8px' }}>
          <button
            onClick={handleCopyMarkdown}
            disabled={!guideMarkdown}
            className="btn-secondary"
          >
            {copySuccess ? '✅ Copied!' : '📋 Copy Markdown'}
          </button>

          <button
            onClick={onExportPdf}
            disabled={isExporting || !guideMarkdown}
            className="btn-primary"
            style={{ padding: '7px 14px', fontSize: '12px' }}
          >
            {isExporting ? (
              <>
                <span className="spinner" />
                <span>Generating Vector PDF...</span>
              </>
            ) : (
              <>
                <span>📥</span>
                <span>Export Printable PDF</span>
              </>
            )}
          </button>
        </div>
      </div>

      {/* PDF Ready Alert Box */}
      {pdfDataUrl && (
        <div style={{
          background: 'var(--emerald-bg)',
          border: '1px solid var(--emerald-border)',
          borderRadius: '10px',
          padding: '12px 16px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '12px'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <span style={{ fontSize: '20px' }}>📄</span>
            <div>
              <p style={{ fontSize: '12.5px', fontWeight: '600', color: 'var(--emerald-text)' }}>
                Printable Vector PDF Ready ({pageCount} {pageCount === 1 ? 'page' : 'pages'})
              </p>
              <p style={{ fontSize: '11px', color: 'var(--emerald-text)', opacity: 0.85 }}>
                Centered page numbering & running headers stamped via PyMuPDF.
              </p>
            </div>
          </div>
          <a
            href={pdfDataUrl}
            download="SuperDocs_Study_Guide.pdf"
            className="btn-primary"
            style={{ textDecoration: 'none', padding: '6px 12px', fontSize: '11.5px' }}
          >
            <span>📥 Download PDF</span>
          </a>
        </div>
      )}

      {/* Content Display Area */}
      <div style={{
        flex: 1,
        background: 'var(--bg-canvas)',
        border: '1px solid var(--border-subtle)',
        borderRadius: '10px',
        padding: '18px',
        overflowY: 'auto',
        maxHeight: '580px'
      }}>
        {activeTab === 'preview' ? (
          <div
            dangerouslySetInnerHTML={{ __html: formatMarkdownToHtml(guideMarkdown) }}
          />
        ) : (
          <pre style={{
            fontFamily: 'var(--font-mono)',
            fontSize: '11.5px',
            color: 'var(--text-secondary)',
            whiteSpace: 'pre-wrap',
            lineHeight: 1.6
          }}>
            {guideMarkdown || 'No content yet.'}
          </pre>
        )}
      </div>
    </div>
  );
};
