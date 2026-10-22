import { Router, Request, Response } from 'express';
import { KnowledgeBaseSweeper } from '../core/engine.js';
import { Article, ChangeEvent, GroundTruthEntry } from '../core/types.js';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

export function createRouter(sweeper: KnowledgeBaseSweeper): Router {
  const router = Router();

  // Change Feed
  router.post('/changes', (req: Request, res: Response) => {
    const changes: ChangeEvent[] = Array.isArray(req.body) ? req.body : [req.body];
    sweeper.addChanges(changes);
    res.status(201).json({ success: true, count: changes.length });
  });

  router.get('/changes', (_req: Request, res: Response) => {
    res.json(sweeper.getChanges());
  });

  // Articles
  router.post('/articles', (req: Request, res: Response) => {
    const articles: Article[] = Array.isArray(req.body) ? req.body : [req.body];
    sweeper.addArticles(articles);
    res.status(201).json({ success: true, count: articles.length });
  });

  router.get('/articles', (_req: Request, res: Response) => {
    res.json(sweeper.getArticles());
  });

  router.get('/articles/:id', (req: Request, res: Response) => {
    const id = Array.isArray(req.params.id) ? req.params.id[0] : req.params.id;
    const article = sweeper.getArticle(id);
    if (!article) {
      return res.status(404).json({ error: 'Article not found' });
    }
    res.json(article);
  });

  // Freshness Sweep
  router.post('/sweep', (req: Request, res: Response) => {
    try {
      const options = req.body || {};
      const result = sweeper.sweep(options);
      res.json(result);
    } catch (err: any) {
      res.status(400).json({ error: err.message });
    }
  });

  // Assessments
  router.get('/assessments', (_req: Request, res: Response) => {
    res.json(sweeper.getAssessments());
  });

  // Edit Proposals
  router.get('/proposals', (_req: Request, res: Response) => {
    res.json(sweeper.getProposals());
  });

  router.post('/proposals/:id/approve', (req: Request, res: Response) => {
    const id = Array.isArray(req.params.id) ? req.params.id[0] : req.params.id;
    const { reviewer, notes } = req.body || {};
    const result = sweeper.approveProposal(id, reviewer, notes);
    if (!result.success) {
      return res.status(404).json({ error: 'Proposal not found' });
    }
    res.json(result);
  });

  router.post('/proposals/:id/reject', (req: Request, res: Response) => {
    const id = Array.isArray(req.params.id) ? req.params.id[0] : req.params.id;
    const { reviewer, notes } = req.body || {};
    const result = sweeper.rejectProposal(id, reviewer, notes);
    if (!result.success) {
      return res.status(404).json({ error: 'Proposal not found' });
    }
    res.json(result);
  });

  // Screenshot assessments
  router.get('/screenshots', (_req: Request, res: Response) => {
    res.json(sweeper.getScreenshotAssessments());
  });

  // Metrics
  router.get('/metrics', (_req: Request, res: Response) => {
    res.json(sweeper.getMetrics());
  });

  // Seeded Benchmark Evaluation
  router.post('/evaluate', (_req: Request, res: Response) => {
    try {
      const fixturesDir = path.resolve(__dirname, '../../fixtures/corpus');
      const articles: Article[] = JSON.parse(fs.readFileSync(path.join(fixturesDir, 'articles.json'), 'utf-8'));
      const changes: ChangeEvent[] = JSON.parse(fs.readFileSync(path.join(fixturesDir, 'changes.json'), 'utf-8'));
      const groundTruth: GroundTruthEntry[] = JSON.parse(fs.readFileSync(path.join(fixturesDir, 'ground-truth.json'), 'utf-8'));

      const evalSweeper = new KnowledgeBaseSweeper(articles, changes);
      evalSweeper.sweep();
      const metrics = evalSweeper.getMetrics(groundTruth);

      res.json({
        success: true,
        corpus_size: articles.length,
        changes_count: changes.length,
        metrics
      });
    } catch (err: any) {
      res.status(500).json({ error: err.message });
    }
  });

  return router;
}
