import { describe, it, expect } from 'vitest';
import { mergePersistedStates, PersistedState } from '../src/hooks/useStatePersistence';

// -------------------------------------------------------------------------
// Dual-layer persistence (localStorage + `.superdocs-state.json`)
//
// Scenario map:
//   - Browser tab refresh   : BOTH layers present -> most recent wins
//   - Container re-entry    : localStorage lost, workspace file present
//     (Replit reloads the  -> workspace state restored
//     workspace container)
//   - Browser data cleared  : localStorage lost, workspace file present
//     -> workspace state restored
//   - Corrupt payload       : loaders null-out invalid JSON -> other layer
//     (or default) wins
//
// The loaders (`loadFromWorkspace`/`loadFromLocalStorage`) return `null` for
// missing or invalid payloads, so passing `null` here faithfully simulates
// both "absent" and "corrupt" cases.
// -------------------------------------------------------------------------

function makeState(overrides: Partial<PersistedState>): PersistedState {
  return {
    selectedPaths: ['src/main.ts'],
    fileHashes: { 'src/main.ts': 'abc123' },
    sessionId: 'session-1',
    documentId: 'doc-1',
    documentType: 'readme',
    lastUpdated: 1000,
    version: 1,
    ...overrides,
  };
}

describe('mergePersistedStates (dual-layer persistence)', () => {
  it('browser refresh: both layers present, the more recent layer wins', () => {
    const local = makeState({ lastUpdated: 5000, selectedPaths: ['a.ts'] });
    const workspace = makeState({ lastUpdated: 3000, selectedPaths: ['b.ts'] });

    expect(mergePersistedStates(workspace, local)).toBe(local);

    const newerWorkspace = makeState({ lastUpdated: 6000, sessionId: 'session-2' });
    expect(mergePersistedStates(newerWorkspace, local)).toBe(newerWorkspace);
  });

  it('container re-entry: localStorage cleared but workspace file intact -> state fully restored (no data loss)', () => {
    const workspace = makeState({
      lastUpdated: 9000,
      sessionId: 'session-restored',
      documentId: 'doc-restored',
      originalInstruction: 'Keep my instruction',
    });

    const merged = mergePersistedStates(workspace, null);

    expect(merged.sessionId).toBe('session-restored');
    expect(merged.documentId).toBe('doc-restored');
    expect(merged.originalInstruction).toBe('Keep my instruction');
    expect(merged.selectedPaths).toEqual(['src/main.ts']);
    expect(merged.fileHashes).toEqual({ 'src/main.ts': 'abc123' });
  });

  it('browser data cleared: same as container re-entry - workspace layer restores the session', () => {
    const workspace = makeState({ lastUpdated: 9000 });
    const merged = mergePersistedStates(workspace, null);
    expect(merged.sessionId).toBe('session-1');
  });

  it('first run on a fresh machine: only localStorage exists -> local state wins', () => {
    const local = makeState({ lastUpdated: 100, sessionId: 'session-local' });
    expect(mergePersistedStates(null, local).sessionId).toBe('session-local');
  });

  it('corrupt payload on one layer (loader returns null) -> the healthy layer wins', () => {
    // Simulates JSON.parse() throwing in loadFromLocalStorage: the loader
    // catches it and returns null, so the workspace copy takes over.
    const workspace = makeState({ lastUpdated: 7000, sessionId: 'session-healthy' });
    expect(mergePersistedStates(workspace, null).sessionId).toBe('session-healthy');

    // And the reverse: corrupt workspace file, healthy localStorage.
    const local = makeState({ lastUpdated: 7000, sessionId: 'session-local-healthy' });
    expect(mergePersistedStates(null, local).sessionId).toBe('session-local-healthy');
  });

  it('both layers missing -> the default empty state is returned', () => {
    const merged = mergePersistedStates(null, null);
    expect(merged.selectedPaths).toEqual([]);
    expect(merged.fileHashes).toEqual({});
    expect(merged.sessionId).toBeUndefined();
  });

  it('merged state never drops session continuity fields', () => {
    const workspace = makeState({
      lastUpdated: 1000,
      sessionId: 's1',
      documentId: 'd1',
      jobId: 'j1',
      originalInstruction: 'orig',
      lastInstruction: 'last',
      codeDeltaHash: 'delta',
      lastDeltaComputed: 42,
    });

    const merged = mergePersistedStates(workspace, null);

    expect(merged).toEqual(expect.objectContaining({
      sessionId: 's1',
      documentId: 'd1',
      jobId: 'j1',
      originalInstruction: 'orig',
      lastInstruction: 'last',
      codeDeltaHash: 'delta',
      lastDeltaComputed: 42,
      lastUpdated: 1000,
      version: 1,
    }));
  });
});