import { describe, it, expect } from 'vitest';
import { createGenerationContext, buildSuperDocsInstruction } from '../src/services/context';

describe('context builder', () => {
  const mockFiles = new Map([
    ['src/main.ts', 'export function main() { console.log("hello"); }'],
    ['package.json', '{"name": "test", "version": "1.0.0"}'],
    ['README.md', '# Test Project\n\nA simple test project.'],
  ]);

  describe('createGenerationContext', () => {
    it('creates context with correct document type', () => {
      const context = createGenerationContext('readme', 'Custom instruction', mockFiles);
      
      expect(context.documentType).toBe('readme');
      expect(context.instruction).toBe('Custom instruction');
      // JavaScript default sort is case-sensitive: uppercase before lowercase
      expect([...context.selectedPaths].sort()).toEqual(['README.md', 'package.json', 'src/main.ts']);
    });

    it('uses default instruction when empty', () => {
      const context = createGenerationContext('spec', '', mockFiles);
      
      expect(context.instruction).toContain('technical specification');
      expect(context.instruction).toContain('architecture');
    });

    it('uses different defaults for each document type', () => {
      const readmeContext = createGenerationContext('readme', '', mockFiles);
      const specContext = createGenerationContext('spec', '', mockFiles);
      const guideContext = createGenerationContext('user-guide', '', mockFiles);
      
      expect(readmeContext.instruction).toContain('README');
      expect(specContext.instruction).toContain('technical specification');
      expect(guideContext.instruction).toContain('user-facing guide');
    });
  });

  describe('buildSuperDocsInstruction', () => {
    it('includes document type in instruction', () => {
      const context = createGenerationContext('readme', 'Test', mockFiles);
      const instruction = buildSuperDocsInstruction(context);
      
      expect(instruction).toContain('Test');
      expect(instruction).toContain('README.md');
      expect(instruction).toContain('src/main.ts');
      expect(instruction).toContain('package.json');
      expect(instruction).toContain('README.md');
    });

    it('includes file contents with separators', () => {
      const context = createGenerationContext('readme', 'Test', mockFiles);
      const instruction = buildSuperDocsInstruction(context);
      
      expect(instruction).toContain('File: `src/main.ts`');
      expect(instruction).toContain('export function main()');
      expect(instruction).toContain('File: `package.json`');
      expect(instruction).toContain('"name": "test"');
    });

    it('handles all document types', () => {
      const readmeContext = createGenerationContext('readme', 'Test', mockFiles);
      const specContext = createGenerationContext('spec', 'Test', mockFiles);
      const guideContext = createGenerationContext('user-guide', 'Test', mockFiles);
      
      expect(buildSuperDocsInstruction(readmeContext)).toContain('README.md');
      expect(buildSuperDocsInstruction(specContext)).toContain('SPEC.md');
      expect(buildSuperDocsInstruction(guideContext)).toContain('USER_GUIDE.md');
    });
  });
});