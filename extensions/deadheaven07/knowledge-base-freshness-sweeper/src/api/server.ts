import express from 'express';
import cors from 'cors';
import { KnowledgeBaseSweeper } from '../core/engine.js';
import { createRouter } from './routes.js';
import fs from 'fs';
import path from 'path';
import { Article, ChangeEvent } from '../core/types.js';

export function createServer(sweeperInstance?: KnowledgeBaseSweeper) {
  const app = express();
  app.use(cors());
  app.use(express.json({ limit: '10mb' }));

  let sweeper = sweeperInstance;
  if (!sweeper) {
    // Default: load fixtures if available
    try {
      const fixturesDir = path.resolve(process.cwd(), 'fixtures/corpus');
      if (fs.existsSync(path.join(fixturesDir, 'articles.json'))) {
        const articles: Article[] = JSON.parse(fs.readFileSync(path.join(fixturesDir, 'articles.json'), 'utf-8'));
        const changes: ChangeEvent[] = JSON.parse(fs.readFileSync(path.join(fixturesDir, 'changes.json'), 'utf-8'));
        sweeper = new KnowledgeBaseSweeper(articles, changes);
      } else {
        sweeper = new KnowledgeBaseSweeper();
      }
    } catch {
      sweeper = new KnowledgeBaseSweeper();
    }
  }

  app.use('/api', createRouter(sweeper));

  app.get('/health', (_req, res) => {
    res.json({ status: 'ok', service: 'knowledge-base-freshness-sweeper' });
  });

  return app;
}

// Start server if directly executed
if (process.argv[1] && process.argv[1].endsWith('server.ts')) {
  const app = createServer();
  const PORT = process.env.PORT || 3001;
  app.listen(PORT, () => {
    console.log(`Knowledge-base Freshness Sweeper API listening on http://localhost:${PORT}`);
  });
}
