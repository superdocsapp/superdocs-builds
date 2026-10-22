/**
 * Symbol Outline Harvester
 * Extracts high-level structural declarations (functions, classes, interfaces,
 * API routes, types) from source code to enable compact, high-density context
 * generation for large codebases.
 */

export interface SymbolDeclaration {
  kind: 'function' | 'class' | 'interface' | 'type' | 'route' | 'export';
  name: string;
  signature: string;
  line: number;
}

export interface FileOutline {
  path: string;
  symbols: SymbolDeclaration[];
  summary: string;
}

/**
 * Extracts symbols from TypeScript, JavaScript, Python, Go, and Rust files.
 */
export function extractSymbols(path: string, content: string): FileOutline {
  const lines = content.split('\n');
  const symbols: SymbolDeclaration[] = [];
  const ext = path.split('.').pop()?.toLowerCase() || '';

  lines.forEach((line, index) => {
    const trimmed = line.trim();
    const lineNum = index + 1;

    // TypeScript / JavaScript
    if (['ts', 'tsx', 'js', 'jsx', 'mjs', 'cjs'].includes(ext)) {
      // Exported functions
      const funcMatch = trimmed.match(/^export\s+(?:async\s+)?function\s+([a-zA-Z0-9_$]+)\s*(\([^)]*\))/);
      if (funcMatch) {
        symbols.push({
          kind: 'function',
          name: funcMatch[1],
          signature: `function ${funcMatch[1]}${funcMatch[2]}`,
          line: lineNum,
        });
        return;
      }

      // Exported arrow functions / const handlers
      const constMatch = trimmed.match(/^export\s+const\s+([a-zA-Z0-9_$]+)\s*=\s*(?:async\s*)?\(([^)]*)\)\s*(?:=>|:)/);
      if (constMatch) {
        symbols.push({
          kind: 'function',
          name: constMatch[1],
          signature: `const ${constMatch[1]} = (${constMatch[2]})`,
          line: lineNum,
        });
        return;
      }

      // Classes & Interfaces
      const classMatch = trimmed.match(/^export\s+(?:abstract\s+)?class\s+([a-zA-Z0-9_$]+)(?:\s+extends\s+[a-zA-Z0-9_$]+)?(?:\s+implements\s+[^{]+)?/);
      if (classMatch) {
        symbols.push({
          kind: 'class',
          name: classMatch[1],
          signature: classMatch[0],
          line: lineNum,
        });
        return;
      }

      const ifaceMatch = trimmed.match(/^export\s+interface\s+([a-zA-Z0-9_$]+)(?:\s+extends\s+[^{]+)?/);
      if (ifaceMatch) {
        symbols.push({
          kind: 'interface',
          name: ifaceMatch[1],
          signature: ifaceMatch[0],
          line: lineNum,
        });
        return;
      }

      const typeMatch = trimmed.match(/^export\s+type\s+([a-zA-Z0-9_$]+)\s*=/);
      if (typeMatch) {
        symbols.push({
          kind: 'type',
          name: typeMatch[1],
          signature: `type ${typeMatch[1]}`,
          line: lineNum,
        });
        return;
      }

      // Express / API routes: app.get('/api/foo', ...) or router.post(...)
      const routeMatch = trimmed.match(/^(?:app|router)\.(get|post|put|delete|patch)\s*\(\s*['"`]([^'"`]+)['"`]/i);
      if (routeMatch) {
        symbols.push({
          kind: 'route',
          name: `${routeMatch[1].toUpperCase()} ${routeMatch[2]}`,
          signature: `${routeMatch[1].toUpperCase()} ${routeMatch[2]}`,
          line: lineNum,
        });
        return;
      }
    }

    // Python
    if (ext === 'py') {
      const pyClassMatch = trimmed.match(/^class\s+([a-zA-Z0-9_]+)(?:\([^)]*\))?:/);
      if (pyClassMatch) {
        symbols.push({
          kind: 'class',
          name: pyClassMatch[1],
          signature: `class ${pyClassMatch[1]}`,
          line: lineNum,
        });
        return;
      }

      const pyFuncMatch = trimmed.match(/^(?:async\s+)?def\s+([a-zA-Z0-9_]+)\s*(\([^)]*\))/);
      if (pyFuncMatch && !pyFuncMatch[1].startsWith('__')) {
        symbols.push({
          kind: 'function',
          name: pyFuncMatch[1],
          signature: `def ${pyFuncMatch[1]}${pyFuncMatch[2]}`,
          line: lineNum,
        });
        return;
      }

      // FastAPI / Flask route decorators: @app.get("/path")
      const pyRouteMatch = trimmed.match(/^@(app|router)\.(get|post|put|delete|patch)\s*\(\s*["']([^"']+)["']/i);
      if (pyRouteMatch) {
        symbols.push({
          kind: 'route',
          name: `${pyRouteMatch[2].toUpperCase()} ${pyRouteMatch[3]}`,
          signature: `${pyRouteMatch[2].toUpperCase()} ${pyRouteMatch[3]}`,
          line: lineNum,
        });
        return;
      }
    }
  });

  const summary = symbols.length > 0
    ? `### \`${path}\` (${symbols.length} symbols)\n` + symbols.map(s => `- **${s.kind.toUpperCase()}**: \`${s.signature}\` (line ${s.line})`).join('\n')
    : `### \`${path}\` (No public symbols extracted)`;

  return {
    path,
    symbols,
    summary,
  };
}

/**
 * Builds a compressed symbol outline dictionary for a batch of workspace files.
 */
export function buildWorkspaceOutline(files: Map<string, string>): string {
  const outlines: string[] = [];
  for (const [path, content] of files.entries()) {
    const outline = extractSymbols(path, content);
    if (outline.symbols.length > 0) {
      outlines.push(outline.summary);
    }
  }
  return outlines.join('\n\n');
}
