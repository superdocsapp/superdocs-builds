import type { AegisDocument } from './document.js';
import type { BlockAlignment } from '../verification/normalize.js';
import type { CompiledIntent } from './instruction.js';

export interface VerificationContext {
  before: AegisDocument;
  after: AegisDocument;
  alignment: BlockAlignment[];
  intent: CompiledIntent;
}
