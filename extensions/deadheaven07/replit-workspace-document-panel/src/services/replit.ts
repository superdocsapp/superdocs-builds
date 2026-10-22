import { readFile, writeFile, createDir } from '@replit/extensions';

export interface ReplitFile {
  path: string;
  content: string;
  isDirectory: boolean;
}

export interface FileTreeNode {
  name: string;
  path: string;
  isDirectory: boolean;
  children?: FileTreeNode[];
  selected?: boolean;
  ignored?: boolean;
  ignoreReason?: string;
}

const EXCLUDED_DIRS = new Set([
  '.git',
  'node_modules',
  'dist',
  'build',
  '.cache',
  '.vercel',
  '.netlify',
  'coverage',
  '.next',
  '.turbo',
  'vendor',
  'target',
  '__pycache__',
  '.pytest_cache',
  '.mypy_cache',
  '.ruff_cache',
  'venv',
  '.venv',
  'env',
  '.env',
]);

const EXCLUDED_FILES = new Set([
  'package-lock.json',
  'pnpm-lock.yaml',
  'yarn.lock',
  'Cargo.lock',
  'go.sum',
  'composer.lock',
  'poetry.lock',
  'requirements.txt',
  'Pipfile.lock',
  'yarn.lock',
]);

const EXCLUDED_EXTENSIONS = new Set([
  '.lock',
  '.log',
  '.map',
  '.min.js',
  '.min.css',
  '.woff',
  '.woff2',
  '.ttf',
  '.eot',
  '.png',
  '.jpg',
  '.jpeg',
  '.gif',
  '.ico',
  '.svg',
  '.pdf',
  '.zip',
  '.tar',
  '.gz',
  '.exe',
  '.dll',
  '.so',
  '.dylib',
  '.class',
  '.jar',
  '.pyc',
  '.pyo',
  '.pyd',
]);

const MAX_TOTAL_CONTEXT_SIZE = 500 * 1024; // 500KB total context limit

export interface ProjectContextResult {
  context: string;
  skippedFiles: Array<{ path: string; reason: string }>;
}

export function shouldIgnore(path: string): { ignored: boolean; reason?: string } {
  const parts = path.split('/');
  
  for (const part of parts) {
    if (EXCLUDED_DIRS.has(part)) {
      return { ignored: true, reason: `excluded directory: ${part}` };
    }
    if (part.startsWith('.env')) {
      return { ignored: true, reason: 'environment file' };
    }
  }

  const fileName = parts[parts.length - 1];
  if (EXCLUDED_FILES.has(fileName)) {
    return { ignored: true, reason: 'lock/dependency file' };
  }

  const ext = '.' + fileName.split('.').pop()?.toLowerCase();
  if (EXCLUDED_EXTENSIONS.has(ext)) {
    return { ignored: true, reason: `excluded extension: ${ext}` };
  }

  return { ignored: false };
}

export async function readProjectFile(path: string): Promise<string | null> {
  try {
    const result = await readFile(path, 'utf8');
    if ('error' in result) {
      console.warn(`Failed to read file ${path}: ${result.error}`);
      return null;
    }
    return result.content ?? null;
  } catch (error) {
    console.warn(`Error reading file ${path}:`, error);
    return null;
  }
}

export async function writeArtifactToWorkspace(
  destinationPath: string,
  content: Blob | string
): Promise<void> {
  const dirPath = destinationPath.split('/').slice(0, -1).join('/');
  
  if (dirPath) {
    try {
      await createDir(dirPath);
    } catch (error) {
      console.warn(`Directory may already exist: ${dirPath}`, error);
    }
  }

  const result = await writeFile(destinationPath, content);
  
  if ('error' in result) {
    throw new Error(`Failed to write file: ${result.error}`);
  }
}

export function buildProjectContext(
  selectedFiles: Map<string, string>,
  documentType: 'readme' | 'spec' | 'user-guide'
): ProjectContextResult {
  const typeLabels: Record<string, string> = {
    readme: 'README',
    spec: 'Technical Specification',
    'user-guide': 'User Guide',
  };

  const label = typeLabels[documentType] || 'Documentation';
  const paths = Array.from(selectedFiles.keys()).sort();
  
  let context = `# Project Context for ${label} Generation\n\n`;
  context += `## Selected Files (${paths.length})\n\n`;
  
  for (const path of paths) {
    context += `- \`${path}\`\n`;
  }
  
  context += '\n---\n\n';
  
  const skippedFiles: Array<{ path: string; reason: string }> = [];
  let currentSize = new TextEncoder().encode(context).length;
  
  for (const [path, content] of selectedFiles) {
    const fileSection = `## File: \`${path}\`\n\n\`\`\`\n${content}\n\`\`\`\n\n---\n\n`;
    const sectionSize = new TextEncoder().encode(fileSection).length;
    
    if (currentSize + sectionSize > MAX_TOTAL_CONTEXT_SIZE) {
      skippedFiles.push({ path, reason: `would exceed total context limit (${MAX_TOTAL_CONTEXT_SIZE / 1024}KB)` });
      continue;
    }
    
    context += fileSection;
    currentSize += sectionSize;
  }
  
  if (skippedFiles.length > 0) {
    context += `\n\n> **Warning**: ${skippedFiles.length} file(s) skipped due to context size limit:\n`;
    for (const skipped of skippedFiles) {
      context += `> - \`${skipped.path}\`: ${skipped.reason}\n`;
    }
  }
  
  return { context, skippedFiles };
}