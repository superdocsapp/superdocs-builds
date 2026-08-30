// @ts-check
/**
 * Every mutation gets an immutable version. Undo/redo walk a linear
 * timeline; revertTo() can jump to any past version (including one that
 * isn't on the current undo/redo path) by creating a NEW commit with that
 * version's content — matching how `git revert` works: history is never
 * rewritten, a revert is itself an auditable, further-revertible commit.
 * That's what makes "revert a revert" well-defined rather than a special
 * case: it's just revertTo() called again, on a version that happens to
 * have kind: 'revert'.
 *
 * "Verify restored state" (the spec's words) is not a comment, it's
 * enforced code: every undo/redo/revert re-hashes the restored paragraphs
 * and throws if the recomputed fingerprint doesn't match what was recorded
 * at commit time, rather than assuming the stored object is still correct.
 */
import { randomUUID } from 'node:crypto';
import { fingerprintParagraphs } from '@prism/core';

/**
 * @typedef {{text: string, styleId: string|null, runs: Array<{text:string,bold:boolean,italic:boolean,underline:boolean}>}} Paragraph
 * @typedef {{versionId: string, parentVersionId: string|null, fingerprint: string, paragraphs: Paragraph[], label: string|null, kind: string, createdAt: string}} VersionRecord
 */

export class Vault {
  constructor() {
    /** @type {Map<string, VersionRecord>} versionId -> version record, every version ever created */
    this.versions = new Map();
    /** @type {string[]} linear undo/redo timeline (a subset/path through `versions`) */
    this.history = [];
    this.cursor = -1;
  }

  /**
   * @param {Paragraph[]} paragraphs
   * @param {{label?: string|null, kind?: string}} [opts]
   */
  commit(paragraphs, opts = {}) {
    const { label = null, kind = 'commit' } = opts;
    const parentVersionId = this.cursor >= 0 ? this.history[this.cursor] : null;
    const versionId = randomUUID();
    const fingerprint = fingerprintParagraphs(paragraphs);
    const version = { versionId, parentVersionId, fingerprint, paragraphs, label, kind, createdAt: new Date().toISOString() };
    this.versions.set(versionId, version);
    // A commit after an undo discards the redo-able future, same as any
    // standard undo/redo stack (e.g. a text editor) — never silently kept
    // around as a ghost branch.
    this.history = this.history.slice(0, this.cursor + 1);
    this.history.push(versionId);
    this.cursor = this.history.length - 1;
    return this._public(version);
  }

  current() {
    if (this.cursor < 0) return null;
    return this._public(this.versions.get(this.history[this.cursor]));
  }

  canUndo() {
    return this.cursor > 0;
  }

  canRedo() {
    return this.cursor < this.history.length - 1;
  }

  undo() {
    if (!this.canUndo()) throw new Error('Vault: nothing to undo.');
    this.cursor -= 1;
    return this._verifyCurrent();
  }

  redo() {
    if (!this.canRedo()) throw new Error('Vault: nothing to redo.');
    this.cursor += 1;
    return this._verifyCurrent();
  }

  /**
   * Jump to any past version by content, not by rewriting history — creates
   * a new commit. Works identically whether the target was a normal commit
   * or itself the product of an earlier revert (i.e. "revert a revert"
   * needs no special case).
   * @param {string} versionId
   */
  revertTo(versionId) {
    const target = this.versions.get(versionId);
    if (!target) throw new Error(`Vault: unknown versionId ${versionId}`);
    const reverted = this.commit(target.paragraphs, {
      label: `revert to ${versionId.slice(0, 8)}`,
      kind: 'revert',
    });
    if (reverted.fingerprint !== target.fingerprint) {
      // Should be unreachable (we pass target.paragraphs straight through),
      // but "verify restored state" means checking it, not assuming it.
      throw new Error('Vault: revert fingerprint mismatch — restoration could not be verified.');
    }
    return reverted;
  }

  _verifyCurrent() {
    const raw = this.versions.get(this.history[this.cursor]);
    const recomputed = fingerprintParagraphs(raw.paragraphs);
    if (recomputed !== raw.fingerprint) {
      throw new Error(`Vault: fingerprint mismatch on restore for version ${raw.versionId} — state may be corrupted.`);
    }
    return this._public(raw);
  }

  /** Full version graph — every version ever created, with parent pointers, for audit. Not just the current linear undo/redo path. */
  graph() {
    return [...this.versions.values()].map((v) => this._public(v));
  }

  /** @param {VersionRecord} v */
  _public(v) {
    const { versionId, parentVersionId, fingerprint, label, kind, createdAt, paragraphs } = v;
    return { versionId, parentVersionId, fingerprint, label, kind, createdAt, paragraphs };
  }
}
