import type { SDDocument } from "../types/domain";
import { ironcladMsa } from "./documents/ironcladMsa";
import { brightpathDpa } from "./documents/brightpathDpa";
import { meridianVsq } from "./documents/meridianVsq";
import { remoteWorkPolicy } from "./documents/remoteWorkPolicy";
import { coastalBridgeLetter } from "./documents/coastalBridgeLetter";
import { heliosNda } from "./documents/heliosNda";

/**
 * The seed workspace. `ironcladMsa` is the flagship — deliberately messy and
 * mid-negotiation so every tab of the Document Reality view has something
 * real to show. The rest span the lifecycle: a clean approved reference
 * document, a rejected security questionnaire, a published policy, an
 * unsigned draft, and a fully clean NDA.
 */
export const SEED_DOCUMENTS: SDDocument[] = [ironcladMsa, brightpathDpa, meridianVsq, remoteWorkPolicy, coastalBridgeLetter, heliosNda];

export function findDocument(documents: SDDocument[], id: string | undefined): SDDocument | undefined {
  if (!id) return undefined;
  return documents.find((d) => d.id === id);
}
