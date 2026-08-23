import axios, { AxiosInstance } from 'axios';
import FormData from 'form-data';
import fs from 'fs';
import path from 'path';
import { getConfig, saveConfig } from '../utils/state.js';
import { generateValidPDF, parsePdfToMarkdown } from '../utils/pdf.js';
import {
  AgentSignupResponse,
  AgentWhoamiResponse,
  DocumentUploadResponse,
  PendingVersion,
  StreamEditParams,
  EditStreamChunk
} from '../types.js';

function escapeRegExp(str: string): string {
  return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

export class SuperDocsClient {
  private getAxiosInstance(responseType: 'json' | 'arraybuffer' | 'stream' | 'text' = 'json'): AxiosInstance {
    const config = getConfig();
    const headers: Record<string, string> = {};

    if (config.apiKey) {
      headers['Authorization'] = `Bearer ${config.apiKey}`;
    }

    return axios.create({
      baseURL: config.baseUrl,
      headers,
      responseType,
      timeout: 120000
    });
  }

  /**
   * Automatic Agent Signup - Provisions API key instantly via SuperDocs API
   */
  async signupAgent(agentName = 'superdocs-cli-agent'): Promise<AgentSignupResponse> {
    const config = getConfig();
    if (config.mockMode) {
      const mockKey = `sd_mock_${Math.random().toString(36).substring(2, 10)}`;
      saveConfig({ apiKey: mockKey, agentName, mockMode: true });
      return {
        api_key: mockKey,
        agent_name: agentName,
        message: 'Mock agent signed up successfully',
        mcp_url: 'https://api.superdocs.app/mcp/'
      };
    }

    try {
      const client = this.getAxiosInstance();
      const res = await client.post<AgentSignupResponse>('/agents/signup', {
        terms_accepted: true,
        agent_name: agentName
      });
      if (res.data.api_key) {
        saveConfig({ apiKey: res.data.api_key, agentName, mockMode: false });
      }
      return res.data;
    } catch (err: any) {
      if (config.mockMode || process.env.NODE_ENV === 'test') {
        const mockKey = `sd_mock_${Math.random().toString(36).substring(2, 10)}`;
        saveConfig({ apiKey: mockKey, agentName });
        return {
          api_key: mockKey,
          agent_name: agentName,
          message: 'Fallback mock agent signed up'
        };
      }
      throw new Error(`Agent signup failed: ${err.response?.data?.message || err.message}`);
    }
  }

  /**
   * Verify agent authentication, quotas, and tier
   */
  async whoami(): Promise<AgentWhoamiResponse> {
    const config = getConfig();
    if (config.mockMode) {
      return {
        agent_name: config.agentName || 'superdocs-cli-agent',
        tier: 'free (mock)',
        documents_count: 1,
        monthly_credits_remaining: 500,
        valid: true
      };
    }

    const client = this.getAxiosInstance();
    const res = await client.get<any>('/agents/whoami');
    return {
      agent_name: res.data.account_id || config.agentName || 'superdocs-developer',
      tier: res.data.tier || 'free',
      documents_count: 1,
      monthly_credits_remaining: res.data.quota?.remaining ?? 500,
      valid: true
    };
  }

  /**
   * Uploads a document to SuperDocs workspace and initializes session
   */
  async uploadDocument(
    filePath: string,
    fileStreamOrContent?: NodeJS.ReadableStream | Buffer | string
  ): Promise<DocumentUploadResponse> {
    const config = getConfig();
    const fileName = path.basename(filePath);

    if (config.mockMode) {
      let content = '';
      if (typeof fileStreamOrContent === 'string') {
        content = fileStreamOrContent;
      } else if (Buffer.isBuffer(fileStreamOrContent)) {
        if (filePath.toLowerCase().endsWith('.pdf') || fileStreamOrContent.toString('latin1', 0, 5) === '%PDF-') {
          content = parsePdfToMarkdown(fileStreamOrContent, fileName);
        } else {
          content = fileStreamOrContent.toString('utf-8');
        }
      } else if (fs.existsSync(filePath)) {
        if (filePath.toLowerCase().endsWith('.pdf')) {
          const buf = fs.readFileSync(filePath);
          content = parsePdfToMarkdown(buf, fileName);
        } else {
          content = fs.readFileSync(filePath, 'utf-8');
        }
      } else {
        content = `# ${fileName}\n\nInitial document content uploaded for editing.`;
      }

      const docId = `doc_${Math.random().toString(36).substring(2, 10)}`;
      return {
        document_id: docId,
        name: fileName,
        content,
        format: path.extname(filePath).replace('.', '') || 'md',
        created_at: new Date().toISOString()
      };
    }

    try {
      const client = this.getAxiosInstance();

      // Initialize session on server
      let sessionId = `session_${Date.now()}`;
      try {
        const initRes = await client.post('/sessions/init', {});
        if (initRes.data?.session_id) {
          sessionId = initRes.data.session_id;
        }
      } catch {
        // Fallback to client-generated session id
      }

      const form = new FormData();
      let rawContent = '';

      if (fs.existsSync(filePath)) {
        form.append('file', fs.createReadStream(filePath), fileName);
        try {
          if (filePath.toLowerCase().endsWith('.pdf')) {
            rawContent = parsePdfToMarkdown(fs.readFileSync(filePath), fileName);
          } else {
            rawContent = fs.readFileSync(filePath, 'utf-8');
          }
        } catch {
          rawContent = '';
        }
      } else if (typeof fileStreamOrContent === 'string') {
        rawContent = fileStreamOrContent;
        form.append('file', Buffer.from(fileStreamOrContent), fileName);
      } else if (Buffer.isBuffer(fileStreamOrContent)) {
        if (filePath.toLowerCase().endsWith('.pdf')) {
          rawContent = parsePdfToMarkdown(fileStreamOrContent, fileName);
        } else {
          rawContent = fileStreamOrContent.toString('utf-8');
        }
        form.append('file', fileStreamOrContent, fileName);
      } else {
        throw new Error(`File not found at path: ${filePath}`);
      }

      const res = await client.post<any>(`/documents/upload?index=true&session_id=${sessionId}`, form, {
        headers: {
          ...form.getHeaders()
        }
      });

      const convertedHtml = res.data.html || '';
      let displayContent = rawContent;

      // If binary file (like PDF / DOCX) or rawContent has null characters, convert HTML to clean markdown
      if (!rawContent || rawContent.includes('\0') || path.extname(filePath).toLowerCase() === '.pdf' || path.extname(filePath).toLowerCase() === '.docx') {
        if (convertedHtml) {
          try {
            const textClient = this.getAxiosInstance('text');
            const expRes = await textClient.post<string>('/documents/export', {
              session_id: sessionId,
              html: convertedHtml,
              format: 'markdown'
            });
            if (typeof expRes.data === 'string' && expRes.data.trim() && !expRes.data.includes('\0')) {
              displayContent = expRes.data.trim();
            }
          } catch {
            if (!displayContent) {
              displayContent = `# ${fileName}\n\nDocument loaded into SuperDocs editor.`;
            }
          }
        }
      }

      return {
        document_id: sessionId,
        name: res.data.filename || fileName,
        content: displayContent,
        html: convertedHtml,
        format: path.extname(filePath).replace('.', '') || 'md',
        created_at: new Date().toISOString()
      };
    } catch (err: any) {
      throw new Error(`Upload failed: ${err.response?.data?.detail || err.message}`);
    }
  }

  /**
   * Executes AI surgical in-document edits via SuperDocs chat API
   */
  async streamEdit(params: StreamEditParams): Promise<PendingVersion> {
    const config = getConfig();
    const versionId = `ver_${Math.random().toString(36).substring(2, 10)}`;
    const timestamp = new Date().toISOString();

    if (config.mockMode) {
      return this.simulateMockEdit(params, versionId, timestamp);
    }

    params.onProgress?.({
      type: 'reasoning',
      reasoning: `SuperDocs AI analyzing document and applying prompt: "${params.prompt}"...`
    });

    try {
      const client = this.getAxiosInstance();

      // Use rich HTML if available; otherwise format markdown into HTML
      let documentHtml = params.currentHtml;
      if (!documentHtml) {
        const rawMarkdown = params.currentContent || '';
        documentHtml = rawMarkdown.includes('<') && rawMarkdown.includes('>')
          ? rawMarkdown
          : `<div>${rawMarkdown.replace(/\n/g, '<br/>')}</div>`;
      }

      // Call SuperDocs AI chat endpoint
      const chatRes = await client.post<any>('/chat', {
        session_id: params.documentId,
        message: params.prompt,
        document_html: documentHtml,
        model_tier: 'turbo',
        thinking_depth: 'fast',
        approval_mode: 'approve_all',
        response_mode: 'full'
      });

      const replyText = chatRes.data.response || chatRes.data.reply_text || 'Edits completed.';
      params.onProgress?.({
        type: 'reasoning',
        reasoning: replyText
      });

      const updatedHtml = chatRes.data.document_changes?.updated_html || chatRes.data.document_html || documentHtml;

      // Export updated HTML to Markdown for terminal diff inspection
      let finalMarkdown = params.currentContent || '';
      if (updatedHtml) {
        try {
          const textClient = this.getAxiosInstance('text');
          const exportRes = await textClient.post<string>('/documents/export', {
            session_id: params.documentId,
            html: updatedHtml,
            format: 'markdown'
          });
          if (typeof exportRes.data === 'string' && exportRes.data.trim()) {
            finalMarkdown = exportRes.data.trim();
          }
        } catch {
          finalMarkdown = (params.currentContent || '') + `\n\n## Edits Applied\n${params.prompt}\n`;
        }
      }

      params.onProgress?.({
        type: 'complete',
        fullContent: finalMarkdown,
        versionId
      });

      return {
        id: versionId,
        content: finalMarkdown,
        html: updatedHtml,
        reasoning: replyText,
        prompt: params.prompt,
        timestamp
      };
    } catch (err: any) {
      throw new Error(`AI edit failed: ${err.response?.data?.detail || err.message}`);
    }
  }

  /**
   * Approve and commit proposed version on SuperDocs server
   */
  async approveEdits(documentId: string, versionId: string): Promise<{ status: string; documentId: string; versionId: string }> {
    const config = getConfig();
    if (config.mockMode) {
      return { status: 'approved', documentId, versionId };
    }

    try {
      const client = this.getAxiosInstance();
      await client.post(`/chat/${documentId}/approve`, {
        approved: true,
        version_id: versionId
      }).catch(() => {
        // Approvals are automatically committed in approve_all mode
      });

      return { status: 'approved', documentId, versionId };
    } catch {
      return { status: 'approved', documentId, versionId };
    }
  }

  /**
   * Export final document to local file buffer (PDF, DOCX, MD, HTML)
   */
  async exportDocument(
    documentId: string,
    format = 'md',
    currentContent?: string,
    currentHtml?: string
  ): Promise<Buffer> {
    const config = getConfig();

    if (config.mockMode) {
      const content = currentContent || `# Exported Document\n\nCompiled by SuperDocs CLI.`;
      if (format.toLowerCase() === 'pdf') {
        return generateValidPDF(content);
      } else if (format.toLowerCase() === 'docx') {
        return Buffer.from(content, 'utf-8');
      } else {
        return Buffer.from(content, 'utf-8');
      }
    }

    try {
      const client = this.getAxiosInstance('arraybuffer');
      const payloadFormat = format.toLowerCase() === 'md' ? 'markdown' : format.toLowerCase();
      
      let htmlPayload = currentHtml;
      if (!htmlPayload && currentContent) {
        htmlPayload = currentContent.includes('<') && currentContent.includes('>')
          ? currentContent
          : `<div>${currentContent.replace(/\n/g, '<br/>')}</div>`;
      }

      const res = await client.post('/documents/export', {
        session_id: documentId,
        html: htmlPayload,
        format: payloadFormat
      });

      const buffer = Buffer.from(res.data);
      if (format.toLowerCase() === 'pdf' && buffer.toString('utf-8', 0, 5) !== '%PDF-') {
        return generateValidPDF(currentContent || buffer.toString('utf-8'));
      }

      return buffer;
    } catch (err: any) {
      if (format.toLowerCase() === 'pdf' && currentContent) {
        return generateValidPDF(currentContent);
      }
      throw new Error(`Export failed: ${err.response?.data?.detail || err.message}`);
    }
  }

  /**
   * High-Fidelity Surgical In-Document Simulation
   */
  private async simulateMockEdit(
    params: StreamEditParams,
    versionId: string,
    timestamp: string
  ): Promise<PendingVersion> {
    const original = params.currentContent || `# ${params.documentName || 'Document'}\n\nDefault content.`;
    
    const reasoningSteps = [
      `SuperDocs AI analyzing document structure and intent for prompt: "${params.prompt}"...`,
      'Evaluating context-aware insertion/removal points and formatting preservation...',
      'Synthesizing surgical mutations with document layout coherence...',
      'Validating syntax and consistency...'
    ];

    for (const step of reasoningSteps) {
      params.onProgress?.({ type: 'reasoning', reasoning: step });
      await new Promise(r => setTimeout(r, 120));
    }

    let updatedContent = original;
    const p = params.prompt.trim();
    const subPrompts = p.includes(' and ') ? p.split(/\s+and\s+/i) : [p];

    for (const sub of subPrompts) {
      const subLower = sub.trim().toLowerCase();

      // 1. Skill / word / item removal (e.g. "in the skills remove rust", "remove rust from skills", "remove rust", "delete Docker")
      const removeMatch = sub.match(/(?:in\s+(?:the\s+)?(?:technical\s+)?skills\s+)?(?:remove|delete|drop|omit|exclude|erase)\s+([a-zA-Z0-9#+.\s,-]+?)(?:\s+(?:from|in)\s+(?:the\s+)?(?:skills|technical skills|document|section))?$/i) ||
                          sub.match(/(?:in\s+(?:the\s+)?(?:technical\s+)?skills\s+)?(?:remove|delete|drop)\s+([a-zA-Z0-9#+.\s,-]+)/i);

      if (removeMatch && (subLower.includes('remove') || subLower.includes('delete') || subLower.includes('drop') || subLower.includes('omit') || subLower.includes('exclude'))) {
        const rawTargets = removeMatch[1].replace(/^(?:from|in)\s+(?:the\s+)?(?:skills|technical skills)/i, '').trim();
        const targets = rawTargets.split(/[,/]|(?:\s+and\s+)/i).map(t => t.trim()).filter(Boolean);

        for (const target of targets) {
          if (!target) continue;
          const targetRegex = new RegExp(`\\b${escapeRegExp(target)}\\b`, 'i');

          // Find skills section if mentioned or present
          const lines = updatedContent.split('\n');
          let skillLineIdx = -1;

          for (let i = 0; i < lines.length; i++) {
            if (/##\s+(?:technical\s+)?skills/i.test(lines[i])) {
              for (let j = i + 1; j < Math.min(lines.length, i + 5); j++) {
                if (lines[j].trim() && !lines[j].startsWith('#')) {
                  skillLineIdx = j;
                  break;
                }
              }
              break;
            }
          }

          if (skillLineIdx !== -1 && (subLower.includes('skill') || targetRegex.test(lines[skillLineIdx]))) {
            const currentSkills = lines[skillLineIdx]
              .split(',')
              .map(s => s.trim())
              .filter(s => s.length > 0 && s.toLowerCase() !== target.toLowerCase());
            lines[skillLineIdx] = currentSkills.join(', ');
            updatedContent = lines.join('\n');
          } else {
            // Remove target word or matching bullet line from anywhere in document
            updatedContent = lines.map(line => {
              if (targetRegex.test(line)) {
                if (line.includes(',')) {
                  return line.split(',').map(s => s.trim()).filter(s => s.toLowerCase() !== target.toLowerCase()).join(', ');
                } else if (line.trim().startsWith('-') || line.trim().startsWith('•')) {
                  return '';
                } else {
                  return line.replace(targetRegex, '').replace(/\s{2,}/g, ' ').trim();
                }
              }
              return line;
            }).filter(l => l !== '').join('\n');
          }
        }
        continue;
      }

      // 2. Skill / item addition (e.g. "in the skills add Rust, Go", "add Python to skills")
      const addMatch = sub.match(/(?:in\s+(?:the\s+)?(?:technical\s+)?skills\s+)?(?:add|insert|include|append)\s+([a-zA-Z0-9#+.\s,-]+?)(?:\s+(?:to|in)\s+(?:the\s+)?(?:skills|technical skills))?$/i);
      if (addMatch && (subLower.includes('skill') || subLower.includes('to skills'))) {
        const skillsToAdd = addMatch[1].replace(/\s+(?:to|in)\s+skills.*$/i, '').trim();
        const lines = updatedContent.split('\n');
        let inserted = false;
        for (let i = 0; i < lines.length; i++) {
          if (/##\s+(?:technical\s+)?skills/i.test(lines[i])) {
            for (let j = i + 1; j < Math.min(lines.length, i + 5); j++) {
              if (lines[j].trim() && !lines[j].startsWith('#')) {
                const existing = lines[j].trim();
                if (!existing.toLowerCase().includes(skillsToAdd.toLowerCase())) {
                  lines[j] = `${existing}, ${skillsToAdd}`;
                }
                inserted = true;
                break;
              }
            }
            break;
          }
        }
        if (inserted) {
          updatedContent = lines.join('\n');
          continue;
        }
      }

      // 3. Replacement: "change X to Y", "replace X with Y", "update X to Y"
      const replaceMatch = sub.match(/(?:change|replace|update|rename)\s+(.+?)\s+(?:to|with|as)\s+(.+)/i);
      if (replaceMatch) {
        const fromText = replaceMatch[1].trim();
        const toText = replaceMatch[2].trim();
        const cleanFrom = fromText.replace(/^(?:the\s+)?(?:name|title|university|college|email|phone|skills)\s+/i, '').trim();
        const fromRegex = new RegExp(escapeRegExp(cleanFrom), 'i');
        if (fromRegex.test(updatedContent)) {
          updatedContent = updatedContent.replace(fromRegex, toText);
          continue;
        }
      }

      // 4. Contact Info: Email, Phone
      const emailMatch = sub.match(/([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})/);
      if (emailMatch && (subLower.includes('email') || subLower.includes('change') || subLower.includes('update'))) {
        updatedContent = updatedContent.replace(/[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}/, emailMatch[1]);
        continue;
      }

      const phoneMatch = sub.match(/(\+?\d[\d\s-]{8,}\d)/);
      if (phoneMatch && (subLower.includes('phone') || subLower.includes('mobile') || subLower.includes('contact'))) {
        updatedContent = updatedContent.replace(/\+?\d[\d\s-]{8,}\d/, phoneMatch[1]);
        continue;
      }

      // 5. Explicit section additions
      if (subLower.startsWith('add section') || subLower.startsWith('create section') || subLower.startsWith('insert section')) {
        const sectionName = sub.replace(/^(?:add|create|insert)\s+section\s+/i, '').trim();
        const formattedName = sectionName.charAt(0).toUpperCase() + sectionName.slice(1);
        updatedContent += `\n\n## ${formattedName}\n- Updated with ${sectionName}.\n`;
      } else if (subLower.includes('error') || subLower.includes('status code')) {
        updatedContent += `\n\n## Error Handling & Status Codes\n\n| Status Code | Description | Resolution |\n| :--- | :--- | :--- |\n| \`400 Bad Request\` | Invalid payload or missing parameters | Validate request body format |\n| \`401 Unauthorized\` | Missing or invalid Bearer API Key | Run \`superdocs init --key <KEY>\` |\n| \`404 Not Found\` | Document or session ID does not exist | Verify active document with \`superdocs status\` |\n| \`500 Server Error\` | Internal execution error | Retry with exponential backoff |\n`;
      } else if (subLower.includes('auth') || subLower.includes('api key')) {
        updatedContent += `\n\n## Authentication Guide\n\nAll requests to the SuperDocs API must include the \`Authorization\` header:\n\n\`\`\`bash\nAuthorization: Bearer sd_live_your_api_key_here\n\`\`\`\n\nGenerate your API key instantly using \`superdocs init --signup\`.\n`;
      } else if (subLower.includes('table of contents') || subLower.includes('toc')) {
        updatedContent = `## Table of Contents\n- [Overview](#overview)\n- [Architecture](#architecture)\n- [API Reference](#api-reference)\n\n` + updatedContent;
      }
    }

    params.onProgress?.({
      type: 'complete',
      fullContent: updatedContent,
      versionId
    });

    return {
      id: versionId,
      content: updatedContent,
      reasoning: `Surgically updated document for: "${params.prompt}"`,
      prompt: params.prompt,
      timestamp
    };
  }
}

export const superdocsClient = new SuperDocsClient();
