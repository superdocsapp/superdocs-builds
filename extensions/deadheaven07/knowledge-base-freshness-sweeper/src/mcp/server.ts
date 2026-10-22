import { KnowledgeBaseDatabase } from '../core/db.js';
import { FreshnessSweeperAgentGraph } from '../core/agent-graph.js';
import { Article, ChangeEvent, ReviewDecision } from '../core/types.js';

export interface MCPToolDefinition {
  name: string;
  description: string;
  inputSchema: Record<string, any>;
}

export interface MCPCallToolRequest {
  name: string;
  arguments: Record<string, any>;
}

export interface MCPCallToolResponse {
  content: Array<{ type: 'text'; text: string }>;
  isError?: boolean;
}

/**
 * SuperDocs Model Context Protocol (MCP) Server
 * Exposes knowledge-base freshness sweeper tools and HITL review gates to external AI agents.
 */
export class SuperDocsMCPServer {
  private db: KnowledgeBaseDatabase;
  private agentGraph: FreshnessSweeperAgentGraph;

  constructor(db?: KnowledgeBaseDatabase) {
    this.db = db || new KnowledgeBaseDatabase(':memory:');
    this.agentGraph = new FreshnessSweeperAgentGraph(this.db);
  }

  public getTools(): MCPToolDefinition[] {
    return [
      {
        name: 'sweep_knowledge_base',
        description: 'Runs a freshness sweep across knowledge-base articles using provided product change events.',
        inputSchema: {
          type: 'object',
          properties: {
            thread_id: { type: 'string', description: 'Unique execution thread ID' },
            articles: { type: 'array', description: 'List of articles to evaluate' },
            changes: { type: 'array', description: 'List of product change events' }
          },
          required: ['thread_id', 'articles', 'changes']
        }
      },
      {
        name: 'list_pending_proposals',
        description: 'Lists all pending surgical edit proposals awaiting human review.',
        inputSchema: {
          type: 'object',
          properties: {
            thread_id: { type: 'string', description: 'Optional thread ID filter' }
          }
        }
      },
      {
        name: 'submit_review_decision',
        description: 'Submits human approval or rejection for a pending proposal and advances the agent graph.',
        inputSchema: {
          type: 'object',
          properties: {
            thread_id: { type: 'string', description: 'Workflow thread ID' },
            proposal_id: { type: 'string', description: 'Proposal ID' },
            decision: { type: 'string', enum: ['APPROVED', 'REJECTED'] },
            reviewer: { type: 'string', description: 'Reviewer name or agent ID' },
            notes: { type: 'string', description: 'Optional review commentary' }
          },
          required: ['thread_id', 'proposal_id', 'decision', 'reviewer']
        }
      },
      {
        name: 'get_portfolio_freshness',
        description: 'Retrieves current portfolio freshness metrics, coverage, and honest could-not-assess disclosures.',
        inputSchema: {
          type: 'object',
          properties: {
            thread_id: { type: 'string', description: 'Workflow thread ID' }
          },
          required: ['thread_id']
        }
      }
    ];
  }

  public async callTool(request: MCPCallToolRequest): Promise<MCPCallToolResponse> {
    try {
      switch (request.name) {
        case 'sweep_knowledge_base': {
          const { thread_id, articles, changes } = request.arguments as {
            thread_id: string;
            articles: Article[];
            changes: ChangeEvent[];
          };
          const state = await this.agentGraph.start(thread_id, articles, changes);
          return {
            content: [{
              type: 'text',
              text: JSON.stringify({
                thread_id: state.thread_id,
                status: state.status,
                current_node: state.current_node,
                proposals_count: state.proposals.length,
                screenshot_assessments_count: state.screenshot_assessments.length,
                logs: state.logs
              }, null, 2)
            }]
          };
        }

        case 'list_pending_proposals': {
          const proposals = this.db.getProposals('PENDING');
          return {
            content: [{
              type: 'text',
              text: JSON.stringify(proposals, null, 2)
            }]
          };
        }

        case 'submit_review_decision': {
          const { thread_id, proposal_id, decision, reviewer, notes } = request.arguments;
          const reviewDecision: ReviewDecision = {
            proposal_id,
            decision,
            reviewer,
            notes,
            timestamp: new Date().toISOString()
          };

          const state = await this.agentGraph.resume(thread_id, [reviewDecision]);
          return {
            content: [{
              type: 'text',
              text: JSON.stringify({
                thread_id: state.thread_id,
                status: state.status,
                current_node: state.current_node,
                applied_articles_count: state.applied_articles.length,
                metrics: state.metrics
              }, null, 2)
            }]
          };
        }

        case 'get_portfolio_freshness': {
          const { thread_id } = request.arguments;
          const state = this.agentGraph.getStatus(thread_id);
          if (!state) {
            return {
              isError: true,
              content: [{ type: 'text', text: `Thread ${thread_id} not found.` }]
            };
          }
          return {
            content: [{
              type: 'text',
              text: JSON.stringify(state.metrics || {}, null, 2)
            }]
          };
        }

        default:
          return {
            isError: true,
            content: [{ type: 'text', text: `Unknown MCP tool: ${request.name}` }]
          };
      }
    } catch (err: any) {
      return {
        isError: true,
        content: [{ type: 'text', text: `MCP Execution Error: ${err.message}` }]
      };
    }
  }
}
