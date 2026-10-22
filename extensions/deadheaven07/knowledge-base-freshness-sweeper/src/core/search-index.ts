import { Article, ChangeEvent } from './types.js';

export interface SearchResult {
  article: Article;
  score: number;
  matchedKeywords: string[];
}

export class ArticleSearchIndex {
  private articles: Map<string, Article> = new Map();
  private index: Map<string, Set<string>> = new Map(); // keyword -> set of article IDs

  constructor(articles: Article[] = []) {
    this.rebuild(articles);
  }

  public rebuild(articles: Article[]): void {
    this.articles.clear();
    this.index.clear();

    for (const article of articles) {
      this.addArticle(article);
    }
  }

  public addArticle(article: Article): void {
    this.articles.set(article.id, article);
    const tokens = this.tokenizeArticle(article);

    for (const token of tokens) {
      if (!this.index.has(token)) {
        this.index.set(token, new Set());
      }
      this.index.get(token)!.add(article.id);
    }
  }

  public search(query: string, limit: number = 10): SearchResult[] {
    const queryTokens = this.tokenizeText(query);
    const scores = new Map<string, { score: number; matches: string[] }>();

    for (const token of queryTokens) {
      const matchingIds = this.index.get(token);
      if (matchingIds) {
        for (const id of matchingIds) {
          if (!scores.has(id)) {
            scores.set(id, { score: 0, matches: [] });
          }
          const entry = scores.get(id)!;
          entry.score += 1;
          entry.matches.push(token);
        }
      }
    }

    const results: SearchResult[] = [];
    for (const [id, data] of scores.entries()) {
      const article = this.articles.get(id);
      if (article) {
        // Boost for title matches
        const lowerTitle = article.title.toLowerCase();
        for (const token of queryTokens) {
          if (lowerTitle.includes(token)) {
            data.score += 2;
          }
        }
        results.push({
          article,
          score: data.score,
          matchedKeywords: data.matches
        });
      }
    }

    return results.sort((a, b) => b.score - a.score).slice(0, limit);
  }

  public findCandidatesForChange(change: ChangeEvent): Article[] {
    const terms = [
      change.title,
      change.before_state.entity_name || '',
      change.before_state.ui_label || '',
      change.before_state.path || '',
      String(change.before_state.value || '')
    ].filter(Boolean).join(' ');

    const results = this.search(terms, this.articles.size);
    // If specific search returns candidates, return those; otherwise return all articles to guarantee no recall loss
    return results.length > 0 ? results.map(r => r.article) : Array.from(this.articles.values());
  }

  private tokenizeArticle(article: Article): Set<string> {
    const text = `${article.title} ${article.content} ${article.metadata.tags?.join(' ') || ''} ${article.metadata.category || ''}`;
    return this.tokenizeText(text);
  }

  private tokenizeText(text: string): Set<string> {
    const words = text
      .toLowerCase()
      .replace(/[^a-z0-9\s]/g, ' ')
      .split(/\s+/)
      .filter(w => w.length > 2);
    return new Set(words);
  }
}
