import { describe, it, expect } from 'vitest';
import { extractSymbols, buildWorkspaceOutline } from '../src/services/outline';

describe('outline service', () => {
  it('extracts TypeScript functions, classes, interfaces, and types', () => {
    const tsCode = `
export interface UserConfig {
  apiKey: string;
  theme: 'dark' | 'light';
}

export type ThemeMode = 'dark' | 'light';

export class SuperDocsService {
  constructor() {}
}

export async function generateDocument(docType: string): Promise<void> {
  // implementation
}

export const fetchVersions = async (docId: string) => {
  // arrow func
};
`;

    const outline = extractSymbols('src/services/superdocs.ts', tsCode);
    expect(outline.symbols.length).toBe(5);
    expect(outline.symbols.map(s => s.kind)).toEqual(['interface', 'type', 'class', 'function', 'function']);
    expect(outline.summary).toContain('`src/services/superdocs.ts` (5 symbols)');
  });

  it('extracts Python classes, functions, and FastAPI routes', () => {
    const pyCode = `
class PacketBuilder:
  def build(self):
    pass

@app.get("/api/v1/packets")
async def get_packets():
  return []

def calculate_checksum(data: bytes) -> str:
  return "hash"
`;

    const outline = extractSymbols('backend/main.py', pyCode);
    expect(outline.symbols.length).toBe(5);
    expect(outline.symbols.map(s => s.kind)).toEqual(['class', 'function', 'route', 'function', 'function']);
    expect(outline.symbols.find(s => s.kind === 'route')?.name).toBe('GET /api/v1/packets');
  });

  it('builds workspace outline across multiple files', () => {
    const files = new Map<string, string>();
    files.set('src/index.ts', 'export function main() {}');
    files.set('src/types.ts', 'export interface State { active: boolean; }');

    const workspaceOutline = buildWorkspaceOutline(files);
    expect(workspaceOutline).toContain('`src/index.ts`');
    expect(workspaceOutline).toContain('`src/types.ts`');
    expect(workspaceOutline).toContain('**FUNCTION**: `function main()`');
    expect(workspaceOutline).toContain('**INTERFACE**: `export interface State`');
  });
});
