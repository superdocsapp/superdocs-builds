import { createExtension } from "@blocknote/core";

import {
  createSuperDocsPlugin,
  type SuperDocsPluginOptions,
} from "../core/index.js";

/**
 * Creates the SuperDocs extension for BlockNote.
 *
 * The actual SuperDocs state management and API interaction remain in
 * the shared core plugin. BlockNote only provides the extension wrapper
 * needed to register that ProseMirror plugin with a BlockNote editor.
 */
export function createSuperDocsBlockNoteExtension(
  options: SuperDocsPluginOptions
) {
  return createExtension({
    key: "superdocs",

    plugins: [
      createSuperDocsPlugin(options),
    ],
  });
}