import { describe, it, expect } from 'vitest';
import { buildProjectContext } from '../src/services/replit';

describe('Replit workspace adapter - pure functions', () => {
  
  describe('buildProjectContext', () => {
    it('builds context with file tree and contents', () => {
      const files = new Map([
        ['src/main.ts', 'export function main() {}'],
        ['package.json', '{"name": "test"}'],
      ]);

      const { context } = buildProjectContext(files, 'readme');
      
      expect(context).toContain('Project Context for README Generation');
      expect(context).toContain('Selected Files (2)');
      expect(context).toContain('src/main.ts');
      expect(context).toContain('package.json');
      expect(context).toContain('File: `src/main.ts`');
      expect(context).toContain('export function main() {}');
      expect(context).toContain('File: `package.json`');
      expect(context).toContain('{"name": "test"}');
    });

    it('handles different document types', () => {
      const files = new Map([['test.ts', 'content']]);
      
      expect(buildProjectContext(files, 'readme').context).toContain('README Generation');
      expect(buildProjectContext(files, 'spec').context).toContain('Specification Generation');
      expect(buildProjectContext(files, 'user-guide').context).toContain('User Guide Generation');
    });
  });
});