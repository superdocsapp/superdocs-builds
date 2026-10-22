import { vi } from 'vitest';
import type { ReactNode } from 'react';

// Mock @replit/extensions for testing
vi.mock('@replit/extensions', () => ({
  readFile: vi.fn().mockResolvedValue({ content: 'file content', error: null }),
  writeFile: vi.fn().mockResolvedValue({ success: true, error: null }),
  readDir: vi.fn().mockResolvedValue({ 
    children: [
      { filename: 'src', type: 'DIRECTORY' },
      { filename: 'package.json', type: 'FILE' },
    ], 
    error: null 
  }),
  createDir: vi.fn().mockResolvedValue({ success: true, error: null }),
  deleteFile: vi.fn().mockResolvedValue({}),
  deleteDir: vi.fn().mockResolvedValue({}),
  move: vi.fn().mockResolvedValue({ success: true, error: null }),
  copyFile: vi.fn().mockResolvedValue({ success: true, error: null }),
  watchFile: vi.fn(),
  watchDir: vi.fn(),
  watchTextFile: vi.fn(),
  init: vi.fn().mockResolvedValue({ status: 'ready' }),
  extensionPort: {},
}));

// Mock @replit/extensions-react for testing
vi.mock('@replit/extensions-react', () => ({
  useReplit: () => ({
    status: 'ready' as const,
    error: null,
    filePath: null,
    replit: {
      fs: {
        readFile: vi.fn().mockResolvedValue({ content: 'file content', error: null }),
        writeFile: vi.fn().mockResolvedValue({ success: true, error: null }),
        readDir: vi.fn().mockResolvedValue({ 
          children: [
            { filename: 'src', type: 'DIRECTORY' },
            { filename: 'package.json', type: 'FILE' },
          ], 
          error: null 
        }),
        createDir: vi.fn().mockResolvedValue({ success: true, error: null }),
        deleteFile: vi.fn().mockResolvedValue({}),
        deleteDir: vi.fn().mockResolvedValue({}),
        move: vi.fn().mockResolvedValue({ success: true, error: null }),
        copyFile: vi.fn().mockResolvedValue({ success: true, error: null }),
      },
    },
  }),
  useReplitEffect: vi.fn(),
  useActiveFile: () => null,
  useTheme: () => null,
  useThemeValues: () => null,
  useIsExtension: () => true,
  useSetThemeCssVariables: () => null,
  useWatchTextFile: () => ({ status: 'watching' as const, content: '', watchError: null, writeChange: null }),
  HandshakeProvider: ({ children }: { children: ReactNode }) => children,
}));