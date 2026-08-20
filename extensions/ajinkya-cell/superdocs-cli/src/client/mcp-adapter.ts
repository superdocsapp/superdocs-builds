import { superdocsClient } from './superdocs.js';
import { getSession, saveSession, getConfig, saveConfig, clearSession } from '../utils/state.js';
import { createDiff } from '../utils/diff.js';

export interface MCPToolDefinition {
  name: string;
  description: string;
  inputSchema: {
    type: 'object';
    properties: Record<string, unknown>;
    required?: string[];
  };
}

export const SUPERDOCS_MCP_TOOLS: MCPToolDefinition[] = [
  {
    name: 'superdocs_signup',
    description: 'Instantly register an AI agent or developer account on SuperDocs platform to obtain API credentials.',
    inputSchema: {
      type: 'object',
      properties: {
        agent_name: {
          type: 'string',
          description: 'Descriptive identifier for the AI agent or CLI client'
        }
      }
    }
  },
  {
    name: 'superdocs_upload',
    description: 'Upload a local document (.md, .txt, .pdf, .docx) to SuperDocs and set it as the active session.',
    inputSchema: {
      type: 'object',
      properties: {
        filePath: {
          type: 'string',
          description: 'Absolute or relative path to the local file to upload'
        },
        content: {
          type: 'string',
          description: 'Optional direct string content of the document'
        }
      },
      required: ['filePath']
    }
  },
  {
    name: 'superdocs_edit',
    description: 'Perform surgical, context-aware AI edits on the active document based on natural language instructions.',
    inputSchema: {
      type: 'object',
      properties: {
        prompt: {
          type: 'string',
          description: 'Instruction prompt specifying desired modifications'
        }
      },
      required: ['prompt']
    }
  },
  {
    name: 'superdocs_approve',
    description: 'Inspect the pending diff and commit or reject proposed AI edits.',
    inputSchema: {
      type: 'object',
      properties: {
        accept: {
          type: 'boolean',
          description: 'True to commit edits to the document, false to discard them'
        }
      },
      required: ['accept']
    }
  },
  {
    name: 'superdocs_export',
    description: 'Export the active SuperDocs document into target format (md, pdf, docx, html).',
    inputSchema: {
      type: 'object',
      properties: {
        format: {
          type: 'string',
          enum: ['pdf', 'docx', 'md', 'html', 'txt'],
          description: 'Desired export file format'
        },
        outputPath: {
          type: 'string',
          description: 'Target destination path on local disk'
        }
      },
      required: ['format', 'outputPath']
    }
  },
  {
    name: 'superdocs_get_status',
    description: 'Get the current active document ID, path, pending diff status, and configuration.',
    inputSchema: {
      type: 'object',
      properties: {}
    }
  }
];

export async function handleMCPCall(toolName: string, args: Record<string, any>): Promise<any> {
  switch (toolName) {
    case 'superdocs_signup': {
      const res = await superdocsClient.signupAgent(args.agent_name || 'superdocs-mcp-agent');
      return { success: true, ...res };
    }

    case 'superdocs_upload': {
      const res = await superdocsClient.uploadDocument(args.filePath, args.content);
      saveSession({
        activeDocumentId: res.document_id,
        documentName: res.name,
        originalPath: args.filePath,
        originalContent: res.content,
        currentContent: res.content,
        pendingVersion: undefined
      });
      return { success: true, document_id: res.document_id, name: res.name };
    }

    case 'superdocs_edit': {
      const session = getSession();
      if (!session.activeDocumentId) {
        throw new Error('No active document set. Call superdocs_upload first.');
      }

      const pending = await superdocsClient.streamEdit({
        documentId: session.activeDocumentId,
        prompt: args.prompt,
        currentContent: session.currentContent,
        documentName: session.documentName
      });

      const diffResult = createDiff(session.currentContent, pending.content, session.documentName);
      pending.additions = diffResult.additions;
      pending.deletions = diffResult.deletions;

      saveSession({ pendingVersion: pending });
      return {
        success: true,
        versionId: pending.id,
        additions: diffResult.additions,
        deletions: diffResult.deletions,
        diff: diffResult.markdownDiff
      };
    }

    case 'superdocs_approve': {
      const session = getSession();
      if (!session.pendingVersion) {
        throw new Error('No pending edit version to approve.');
      }

      if (args.accept) {
        if (session.activeDocumentId) {
          await superdocsClient.approveEdits(session.activeDocumentId, session.pendingVersion.id);
        }
        const updatedHistory = [
          ...session.history,
          {
            versionId: session.pendingVersion.id,
            prompt: session.pendingVersion.prompt,
            timestamp: session.pendingVersion.timestamp
          }
        ];
        saveSession({
          currentContent: session.pendingVersion.content,
          pendingVersion: undefined,
          history: updatedHistory
        });
        return { success: true, status: 'approved', content: session.pendingVersion.content };
      } else {
        saveSession({ pendingVersion: undefined });
        return { success: true, status: 'rejected' };
      }
    }

    case 'superdocs_export': {
      const session = getSession();
      const buffer = await superdocsClient.exportDocument(
        session.activeDocumentId || 'default',
        args.format,
        session.currentContent
      );
      return { success: true, size: buffer.length, format: args.format };
    }

    case 'superdocs_get_status': {
      const config = getConfig();
      const session = getSession();
      return {
        config: {
          baseUrl: config.baseUrl,
          mockMode: config.mockMode,
          hasApiKey: Boolean(config.apiKey)
        },
        session: {
          activeDocumentId: session.activeDocumentId,
          documentName: session.documentName,
          originalPath: session.originalPath,
          hasPendingEdit: Boolean(session.pendingVersion),
          historyCount: session.history.length
        }
      };
    }

    default:
      throw new Error(`Unknown SuperDocs MCP tool: ${toolName}`);
  }
}
