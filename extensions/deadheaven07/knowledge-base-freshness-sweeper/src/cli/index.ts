import fs from 'node:fs';
import path from 'node:path';
import readline from 'node:readline';
import { fileURLToPath } from 'node:url';
import { KnowledgeBaseSweeper } from '../core/engine.js';
import { Article, ChangeEvent, EditProposal } from '../core/types.js';
import { CorpusDriftSimulator } from '../core/drift-simulator.js';
import { loadGroundTruthFromYaml, loadExpectedYaml } from '../core/yaml-loader.js';
import { KnowledgeBaseDatabase } from '../core/db.js';
import { formatMetricsTable, formatControlArmComparisonTable, formatProposalDiff, colors } from './formatters.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

function loadFixtures() {
  const fixturesDir = path.resolve(__dirname, '../../fixtures/corpus');
  const articles: Article[] = JSON.parse(fs.readFileSync(path.join(fixturesDir, 'articles.json'), 'utf-8'));
  const changes: ChangeEvent[] = JSON.parse(fs.readFileSync(path.join(fixturesDir, 'changes.json'), 'utf-8'));
  const yamlPath = path.join(fixturesDir, 'expected.yaml');
  const groundTruth = loadGroundTruthFromYaml(yamlPath);
  const expectedStructure = loadExpectedYaml(yamlPath);

  return { articles, changes, groundTruth, expectedStructure };
}

function parseArgs() {
  const args = process.argv.slice(2);
  const command = args[0] || 'sweep';
  let sampleSize: number | undefined;
  let isInteractive = false;
  let exportPath: string | undefined;

  for (let i = 0; i < args.length; i++) {
    if (args[i] === '--sample' && args[i + 1]) {
      sampleSize = parseInt(args[i + 1], 10);
    }
    if (args[i] === '--interactive' || args[i] === '-i') {
      isInteractive = true;
    }
    if ((args[i] === '--export' || args[i] === '-e') && args[i + 1]) {
      exportPath = args[i + 1];
    }
  }

  return { command, sampleSize, isInteractive, exportPath };
}

async function promptReviewDecision(
  rl: readline.Interface,
  proposal: EditProposal,
  index: number,
  total: number
): Promise<'APPROVE' | 'REJECT' | 'SKIP' | 'QUIT'> {
  console.log(`\n${colors.bright}${colors.cyan}─── Proposal [${index + 1}/${total}]: Article ${proposal.article_id} (${proposal.change_id}) ───${colors.reset}`);
  console.log(formatProposalDiff(proposal));
  console.log(`  Confidence: ${colors.yellow}${proposal.confidence}${colors.reset} | Structural Preservation: ${colors.green}${(proposal.structural_preservation_ratio * 100).toFixed(1)}%${colors.reset}`);
  console.log(`  Verbatim Evidence: "${colors.dim}${proposal.evidence.map(e => e.sentence_text).join(' | ')}${colors.reset}"`);

  return new Promise(resolve => {
    rl.question(
      `\nDecision [${colors.green}a${colors.reset}=Approve, ${colors.red}r${colors.reset}=Reject, ${colors.yellow}s${colors.reset}=Skip, ${colors.dim}q${colors.reset}=Quit]: `,
      answer => {
        const key = answer.trim().toLowerCase();
        if (key === 'a' || key === 'approve') resolve('APPROVE');
        else if (key === 'r' || key === 'reject') resolve('REJECT');
        else if (key === 'q' || key === 'quit') resolve('QUIT');
        else resolve('SKIP');
      }
    );
  });
}

function exportAuditReport(
  exportPath: string,
  sweeper: KnowledgeBaseSweeper,
  proposals: EditProposal[],
  cnaCount: number
) {
  const resolved = path.resolve(process.cwd(), exportPath);
  const metrics = sweeper.getMetrics();
  const dir = path.dirname(resolved);
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });

  if (resolved.endsWith('.json')) {
    const jsonOutput = {
      timestamp: new Date().toISOString(),
      metrics,
      proposals_count: proposals.length,
      proposals,
      could_not_assess_count: cnaCount
    };
    fs.writeFileSync(resolved, JSON.stringify(jsonOutput, null, 2), 'utf-8');
  } else {
    let md = `# Knowledge-Base Freshness Sweeper — Audit Report\n\n`;
    md += `**Generated:** ${new Date().toISOString()}  \n`;
    md += `**Portfolio Freshness:** ${metrics.freshness_score}%  \n`;
    md += `**Assessment Coverage:** ${metrics.assessment_coverage}%  \n`;
    md += `**Scanned Articles:** ${metrics.total_articles} (${metrics.affected_articles} Stale, ${metrics.unchanged_articles} Healthy, ${metrics.could_not_assess} Could-Not-Assess)  \n\n`;
    md += `## Surgical Proposals (${proposals.length})\n\n`;
    for (const p of proposals) {
      md += `### Article ${p.article_id} — ${p.change_id}\n`;
      md += `- **Rationale:** ${p.rationale}\n`;
      md += `- **Status:** \`${p.status}\`\n`;
      md += `- **Structural Preservation:** ${(p.structural_preservation_ratio * 100).toFixed(1)}%\n\n`;
    }
    fs.writeFileSync(resolved, md, 'utf-8');
  }
  console.log(`\n${colors.green}✓ Exported audit report to: ${colors.bright}${resolved}${colors.reset}`);
}

export async function runCli() {
  const { command, sampleSize, isInteractive, exportPath } = parseArgs();
  const { articles, changes, groundTruth, expectedStructure } = loadFixtures();

  console.log(`\n${colors.bright}${colors.cyan}SuperDocs — Knowledge-base Freshness Sweeper v1.0.0${colors.reset}`);
  console.log(`${colors.dim}Loaded ${articles.length} articles, ${changes.length} product changes, and pre-registered expected.yaml (${expectedStructure.protocol}).${colors.reset}\n`);

  if (command === 'evaluate') {
    console.log(`${colors.bright}Running Single-Pass Seeded Baseline (${articles.length} articles)...${colors.reset}`);
    const sweeper = new KnowledgeBaseSweeper(articles, changes);
    const { screenshotAssessments } = sweeper.sweep({ provider: 'deterministic' });
    const metrics = sweeper.getMetrics(groundTruth);

    console.log(formatMetricsTable(metrics));

    const staleScreenshots = screenshotAssessments.filter(s => s.replacement_required);
    if (staleScreenshots.length > 0) {
      console.log(`${colors.yellow}⚠️  Detected ${staleScreenshots.length} stale screenshot(s) requiring replacement:${colors.reset}`);
      for (const ss of staleScreenshots) {
        console.log(`  - [Article ${ss.article_id}] Screenshot ${ss.screenshot_id}: ${ss.reason}`);
      }
    }

    console.log(`\n${colors.bright}Running Multi-Epoch Corpus Drift Simulation vs. Naive Control Arm Baseline...${colors.reset}`);
    const simulator = new CorpusDriftSimulator(articles, changes, groundTruth);
    const report = simulator.runSimulation(10);
    console.log(formatControlArmComparisonTable(report.sweeperStats, report.controlArmStats, report.iterations));
    return;
  }

  if (command === 'sweep') {
    const sweepCount = sampleSize ? Math.min(sampleSize, articles.length) : articles.length;
    console.log(`${colors.bright}Executing Freshness Sweep (${sampleSize ? `Small-Sample Mode: ${sweepCount} articles` : `Full Corpus: ${sweepCount} articles`})...${colors.reset}`);

    const db = new KnowledgeBaseDatabase(':memory:');
    for (const a of articles) db.saveArticle(a);

    const sweeper = new KnowledgeBaseSweeper(articles, changes);
    const { assessments, proposals, metrics } = sweeper.sweep({
      sample_size: sampleSize,
      provider: 'deterministic'
    });

    console.log(formatMetricsTable(metrics));

    if (proposals.length > 0) {
      console.log(`\n${colors.bright}Generated ${proposals.length} surgical edit proposal(s):${colors.reset}`);

      if (isInteractive) {
        const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
        let approvedCount = 0;
        let rejectedCount = 0;

        for (let i = 0; i < proposals.length; i++) {
          const prop = proposals[i];
          const decision = await promptReviewDecision(rl, prop, i, proposals.length);
          if (decision === 'QUIT') {
            console.log(`\n${colors.yellow}Review session exited.${colors.reset}`);
            break;
          }
          if (decision === 'APPROVE') {
            sweeper.approveProposal(prop.id, 'cli-reviewer', 'Approved via CLI wizard');
            approvedCount++;
            console.log(`  ${colors.green}✓ Approved and applied surgical patch.${colors.reset}`);
          } else if (decision === 'REJECT') {
            sweeper.rejectProposal(prop.id, 'cli-reviewer', 'Rejected via CLI wizard');
            rejectedCount++;
            console.log(`  ${colors.red}✗ Rejected proposal.${colors.reset}`);
          } else {
            console.log(`  ${colors.dim}⤳ Skipped proposal.${colors.reset}`);
          }
        }
        rl.close();

        const updatedMetrics = sweeper.getMetrics();
        console.log(`\n${colors.bright}Review Session Complete (${approvedCount} Approved, ${rejectedCount} Rejected)${colors.reset}`);
        console.log(`Updated Freshness Score: ${colors.green}${updatedMetrics.freshness_score}%${colors.reset}`);
      } else {
        for (const prop of proposals.slice(0, 2)) {
          console.log(formatProposalDiff(prop));
        }
        if (proposals.length > 2) {
          console.log(`${colors.dim}... and ${proposals.length - 2} more proposal(s) available in the review queue (run with --interactive to review).${colors.reset}`);
        }
      }
    }

    const cna = assessments.filter(a => a.status === 'COULD_NOT_ASSESS');
    if (cna.length > 0) {
      console.log(`\n${colors.yellow}📋 Honest Could-Not-Assess Disclosures (${cna.length} articles):${colors.reset}`);
      for (const item of cna) {
        console.log(`  - [${item.article_id}]: ${item.reason}`);
        if (item.could_not_assess_details) {
          console.log(`    ↳ Missing evidence: ${colors.dim}${item.could_not_assess_details.missing_evidence}${colors.reset}`);
        }
      }
    }

    if (exportPath) {
      exportAuditReport(exportPath, sweeper, proposals, cna.length);
    }
    return;
  }

  console.log(`Unknown command: ${command}. Use 'sweep' or 'evaluate'.`);
}

if (process.argv[1] && (process.argv[1].endsWith('index.ts') || process.argv[1].endsWith('index.js'))) {
  runCli();
}
