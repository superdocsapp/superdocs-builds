declare module '@replit/extensions' {
  export interface ReadFileResult {
    content?: string;
    error?: string;
  }

  export interface WriteFileResult {
    success?: boolean;
    error?: string;
  }

  export interface ReadDirResult {
    children?: Array<{ filename: string; type: 'FILE' | 'DIRECTORY' }>;
    error?: string;
  }

  export interface CreateDirResult {
    success?: boolean;
    error?: string;
  }

  export interface Fs {
    readFile(path: string, encoding?: string): Promise<ReadFileResult>;
    writeFile(path: string, content: string | Blob): Promise<WriteFileResult>;
    readDir(path: string): Promise<ReadDirResult>;
    createDir(path: string): Promise<CreateDirResult>;
    deleteFile(path: string): Promise<void>;
    deleteDir(path: string): Promise<void>;
    move(oldPath: string, newPath: string): Promise<WriteFileResult>;
    copyFile(oldPath: string, newPath: string): Promise<WriteFileResult>;
    watchFile(path: string, callback: (content: string) => void): void;
    watchDir(path: string, callback: (children: Array<{ filename: string; type: 'FILE' | 'DIRECTORY' }>) => void): void;
    watchTextFile(path: string): { status: 'watching'; content: string; watchError: null | Error; writeChange: (content: string) => void };
  }

  export interface Replit {
    fs: Fs;
  }

  export function readFile(path: string, encoding?: string): Promise<ReadFileResult>;
  export function writeFile(path: string, content: string | Blob): Promise<WriteFileResult>;
  export function readDir(path: string): Promise<ReadDirResult>;
  export function createDir(path: string): Promise<CreateDirResult>;
  export function deleteFile(path: string): Promise<void>;
  export function deleteDir(path: string): Promise<void>;
  export function move(oldPath: string, newPath: string): Promise<WriteFileResult>;
  export function copyFile(oldPath: string, newPath: string): Promise<WriteFileResult>;
  export function watchFile(path: string, callback: (content: string) => void): void;
  export function watchDir(path: string, callback: (children: Array<{ filename: string; type: 'FILE' | 'DIRECTORY' }>) => void): void;
  export function watchTextFile(path: string): { status: 'watching'; content: string; watchError: null | Error; writeChange: (content: string) => void };
  export function init(): Promise<{ status: 'ready' | 'error'; error?: string }>;
  export const extensionPort: any;
}

declare module '@replit/extensions-react' {
  import { Replit } from '@replit/extensions';

  export interface UseReplitResult {
    status: 'loading' | 'ready' | 'error';
    error: string | null;
    filePath: string | null;
    replit: Replit | null;
  }

  export function useReplit(): UseReplitResult;
  export function useReplitEffect(effect: (replit: Replit) => void | (() => void)): void;
  export function useActiveFile(): string | null;
  export function useTheme(): string | null;
  export function useThemeValues(): Record<string, string> | null;
  export function useIsExtension(): boolean;
  export function useSetThemeCssVariables(): void;
  export function useWatchTextFile(path: string): { status: 'watching'; content: string; watchError: null | Error; writeChange: (content: string) => void };

  export interface HandshakeProviderProps {
    children: React.ReactNode;
  }
  export function HandshakeProvider({ children }: HandshakeProviderProps): React.ReactElement;
}