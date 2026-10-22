import { useState, useCallback } from 'react';
import { FileHashMap, detectChangedFiles, computeFileHashesAsync } from '../utils/hash';
import { usePersistedFileHashes } from './useStatePersistence';

export interface FileHashState {
  currentHashes: FileHashMap;
  captureHashes: (files: Map<string, string>) => Promise<void>;
  updateCurrentHashes: (files: Map<string, string>) => Promise<void>;
  getChanges: () => { changed: string[]; added: string[]; removed: string[] };
  getBaselineHashes: () => FileHashMap;
}

export function useFileHashes(): FileHashState {
  const { fileHashes: persistedHashes, setFileHashes } = usePersistedFileHashes();
  const [currentHashes, setCurrentHashes] = useState<FileHashMap>({});

  const captureHashes = useCallback(async (files: Map<string, string>) => {
    const hashes = await computeFileHashesAsync(files);
    setCurrentHashes(hashes);
    await setFileHashes(hashes);
  }, [setFileHashes]);

  const updateCurrentHashes = useCallback(async (files: Map<string, string>) => {
    const hashes = await computeFileHashesAsync(files);
    setCurrentHashes(hashes);
  }, []);

  const getChanges = useCallback(() => {
    return detectChangedFiles(persistedHashes, currentHashes);
  }, [persistedHashes, currentHashes]);

  const getBaselineHashes = useCallback(() => {
    return { ...persistedHashes };
  }, [persistedHashes]);

  return {
    currentHashes,
    captureHashes,
    updateCurrentHashes,
    getChanges,
    getBaselineHashes,
  };
}