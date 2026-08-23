process.env.NODE_ENV = 'test';
import { test, describe, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import { createDiff, formatDiffStats } from '../src/utils/diff.js';
import { getConfig, saveConfig, resetConfig, getSession, saveSession, clearSession } from '../src/utils/state.js';
import { superdocsClient } from '../src/client/superdocs.js';
import { handleMCPCall, SUPERDOCS_MCP_TOOLS } from '../src/client/mcp-adapter.js';

describe('SuperDocs CLI Test Suite', () => {
  beforeEach(() => {
    resetConfig();
    clearSession();
    saveConfig({ mockMode: true });
  });

  describe('Diff Generator', () => {
    test('accurately calculates line additions and deletions', () => {
      const oldDoc = '# Title\n\nOriginal line 1\nOriginal line 2\n';
      const newDoc = '# Title\n\nOriginal line 1\nModified line 2\nAdded line 3\n';

      const diffResult = createDiff(oldDoc, newDoc, 'test.md');

      assert.equal(diffResult.hasChanges, true);
      assert.equal(diffResult.additions, 2);
      assert.equal(diffResult.deletions, 1);
      assert.match(diffResult.unifiedView, /\+ Modified line 2/);
      assert.match(diffResult.unifiedView, /\+ Added line 3/);
      assert.match(diffResult.unifiedView, /\- Original line 2/);
      assert.match(diffResult.markdownDiff, /```diff/);
    });

    test('handles identical documents gracefully', () => {
      const doc = '# Same Doc\n\nNo changes here.\n';
      const diffResult = createDiff(doc, doc, 'test.md');

      assert.equal(diffResult.hasChanges, false);
      assert.equal(diffResult.additions, 0);
      assert.equal(diffResult.deletions, 0);
      assert.match(formatDiffStats(diffResult), /No changes/);
    });
  });

  describe('Web Diff & Large PDF Threshold', () => {
    test('detects large documents exceeding word and line threshold', async () => {
      const { isTooLargeForTerminal, countWords } = await import('../src/utils/web-diff.js');
      const longText = Array.from({ length: 400 }, (_, i) => `word${i}`).join(' ');
      const shortText = 'Short document content';

      assert.equal(countWords(longText), 400);
      assert.equal(countWords(shortText), 3);

      const checkLarge = isTooLargeForTerminal(shortText, longText, 350, 50);
      assert.equal(checkLarge.tooLarge, true);
      assert.match(checkLarge.reason || '', /exceeds terminal limit/);

      const checkSmall = isTooLargeForTerminal('Hello', 'Hello world', 350, 50);
      assert.equal(checkSmall.tooLarge, false);
    });

    test('generates valid HTML diff report with styling and diff rows', async () => {
      const { generateHtmlDiffReport } = await import('../src/utils/web-diff.js');
      const oldDoc = '# Overview\n\nOld line content.';
      const newDoc = '# Overview\n\nNew line content.\nAdded line.';

      const html = generateHtmlDiffReport(oldDoc, newDoc, {
        documentName: 'large-report.pdf',
        prompt: 'Update line content'
      });

      assert.match(html, /<!DOCTYPE html>/);
      assert.match(html, /large-report\.pdf/);
      assert.match(html, /Update line content/);
      assert.match(html, /diff-table/);
      assert.match(html, /line-added/);
      assert.match(html, /line-deleted/);
    });
  });

  describe('Persistent State & Session', () => {
    test('persists and updates configuration correctly', () => {
      saveConfig({
        apiKey: 'sd_test_api_key_123',
        defaultExportFormat: 'pdf',
        mockMode: true
      });

      const config = getConfig();
      assert.equal(config.apiKey, 'sd_test_api_key_123');
      assert.equal(config.defaultExportFormat, 'pdf');
      assert.equal(config.mockMode, true);
    });

    test('persists active document session and history', () => {
      saveSession({
        activeDocumentId: 'doc_12345',
        documentName: 'api-guide.md',
        originalContent: '# API Guide',
        currentContent: '# API Guide\n\nUpdated content.',
        history: [
          {
            versionId: 'ver_001',
            prompt: 'Add intro',
            timestamp: new Date().toISOString()
          }
        ]
      });

      const session = getSession();
      assert.equal(session.activeDocumentId, 'doc_12345');
      assert.equal(session.documentName, 'api-guide.md');
      assert.equal(session.history.length, 1);
      assert.equal(session.history[0].prompt, 'Add intro');
    });
  });

  describe('SuperDocs Client Engine', () => {
    test('performs mock agent signup', async () => {
      const res = await superdocsClient.signupAgent('test-suite-agent');
      assert.ok(res.api_key.startsWith('sd_mock_'));
      assert.equal(res.agent_name, 'test-suite-agent');
    });

    test('uploads document and generates session payload', async () => {
      const uploadRes = await superdocsClient.uploadDocument(
        'sample.md',
        '# Sample Document\n\nTest content for SuperDocs.'
      );

      assert.ok(uploadRes.document_id.startsWith('doc_'));
      assert.equal(uploadRes.name, 'sample.md');
      assert.match(uploadRes.content, /Test content for SuperDocs/);
    });

    test('streams AI surgical edits with progress callbacks', async () => {
      const progressChunks: any[] = [];

      const pendingVersion = await superdocsClient.streamEdit({
        documentId: 'doc_mock_123',
        prompt: 'Add error handling section',
        currentContent: '# API Reference\n\nEndpoints list.',
        onProgress: (chunk) => progressChunks.push(chunk)
      });

      assert.ok(pendingVersion.id.startsWith('ver_'));
      assert.match(pendingVersion.content, /Error Handling/);
      assert.ok(progressChunks.length > 0);
      assert.ok(progressChunks.some(c => c.type === 'reasoning'));
      assert.ok(progressChunks.some(c => c.type === 'complete'));
    });

    test('surgically removes skills from list without appending dummy headers', async () => {
      const initialResume = '# Dev\n\n## TECHNICAL SKILLS\nJava, JavaScript, TypeScript, Rust, Docker\n';

      const pending = await superdocsClient.streamEdit({
        documentId: 'doc_mock_123',
        prompt: 'in the skills remove rust',
        currentContent: initialResume
      });

      assert.doesNotMatch(pending.content, /## In the skills remove rust/);
      assert.doesNotMatch(pending.content, /\bRust\b/);
      assert.match(pending.content, /Java, JavaScript, TypeScript, Docker/);
    });

    test('approves and commits proposed versions', async () => {
      const approval = await superdocsClient.approveEdits('doc_123', 'ver_456');
      assert.equal(approval.status, 'approved');
      assert.equal(approval.documentId, 'doc_123');
      assert.equal(approval.versionId, 'ver_456');
    });

    test('exports documents in target formats', async () => {
      const mdBuffer = await superdocsClient.exportDocument('doc_123', 'md', '# Hello World');
      assert.equal(mdBuffer.toString('utf-8'), '# Hello World');

      const pdfBuffer = await superdocsClient.exportDocument('doc_123', 'pdf', '# Hello World');
      assert.ok(pdfBuffer.toString('utf-8').startsWith('%PDF-1.4'));
    });
  });

  describe('MCP (Model Context Protocol) Adapter', () => {
    test('exposes all required MCP tools', () => {
      const toolNames = SUPERDOCS_MCP_TOOLS.map(t => t.name);
      assert.ok(toolNames.includes('superdocs_signup'));
      assert.ok(toolNames.includes('superdocs_upload'));
      assert.ok(toolNames.includes('superdocs_edit'));
      assert.ok(toolNames.includes('superdocs_approve'));
      assert.ok(toolNames.includes('superdocs_export'));
      assert.ok(toolNames.includes('superdocs_get_status'));
    });

    test('executes end-to-end workflow through MCP calls', async () => {
      // 1. Signup
      const signupRes = await handleMCPCall('superdocs_signup', { agent_name: 'mcp-test-bot' });
      assert.equal(signupRes.success, true);

      // 2. Upload
      const uploadRes = await handleMCPCall('superdocs_upload', {
        filePath: 'mcp-doc.md',
        content: '# MCP Document\n\nInitial lines.'
      });
      assert.equal(uploadRes.success, true);
      assert.ok(uploadRes.document_id);

      // 3. Edit
      const editRes = await handleMCPCall('superdocs_edit', {
        prompt: 'Add authentication section'
      });
      assert.equal(editRes.success, true);
      assert.ok(editRes.additions > 0);

      // 4. Approve
      const approveRes = await handleMCPCall('superdocs_approve', { accept: true });
      assert.equal(approveRes.success, true);
      assert.equal(approveRes.status, 'approved');
      assert.match(approveRes.content, /Authentication Guide/);

      // 5. Status
      const statusRes = await handleMCPCall('superdocs_get_status', {});
      assert.equal(statusRes.session.hasPendingEdit, false);
      assert.equal(statusRes.session.historyCount, 1);

      // 6. Export
      const exportRes = await handleMCPCall('superdocs_export', { format: 'md', outputPath: './test-out.md' });
      assert.equal(exportRes.success, true);
      assert.ok(exportRes.size > 0);
    });
  });
});
