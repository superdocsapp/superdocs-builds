import {
  Plugin,
  PluginKey,
  type EditorState,
  type Transaction,
} from "@tiptap/pm/state";

import type {
  SuperDocsChange,
  SuperDocsClient,
  SuperDocsPluginState,
  SuperDocsEditResult,
} from "./types.js";

export interface SuperDocsPluginOptions {
  client: SuperDocsClient;
  sessionId: string;
}

export const superDocsPluginKey =
  new PluginKey<SuperDocsPluginState>(
    "superdocs-plugin"
  );

const initialState: SuperDocsPluginState = {
  isProcessing: false,
  error: null,
  lastChanges: [],
};

export function createSuperDocsPlugin(
  options: SuperDocsPluginOptions
): Plugin<SuperDocsPluginState> {
  return new Plugin<SuperDocsPluginState>({
    key: superDocsPluginKey,

    state: {
      init() {
        return initialState;
      },

      apply(
        transaction: Transaction,
        value: SuperDocsPluginState
      ): SuperDocsPluginState {
        const meta = transaction.getMeta(
          superDocsPluginKey
        );

        if (!meta) {
          return value;
        }

        return {
          isProcessing:
            meta.isProcessing ??
            value.isProcessing,

          error:
            meta.error !== undefined
              ? meta.error
              : value.error,

          lastChanges:
            meta.lastChanges ??
            value.lastChanges,
        };
      },
    },
  });
}

export function getSuperDocsPluginState(
  state: EditorState
): SuperDocsPluginState {
  return (
    superDocsPluginKey.getState(state) ??
    initialState
  );
}

export function setSuperDocsProcessing(
  state: EditorState,
  processing: boolean
): Transaction {
  return state.tr.setMeta(
    superDocsPluginKey,
    {
      isProcessing: processing,
      error: null,
    }
  );
}

export function setSuperDocsSuccess(
  state: EditorState,
  changes: SuperDocsChange[]
): Transaction {
  return state.tr.setMeta(
    superDocsPluginKey,
    {
      isProcessing: false,
      error: null,
      lastChanges: changes,
    }
  );
}

export function setSuperDocsError(
  state: EditorState,
  error: string
): Transaction {
  return state.tr.setMeta(
    superDocsPluginKey,
    {
      isProcessing: false,
      error,
    }
  );
}

export async function requestSuperDocsEdit(
  view: {
    state: EditorState;
    dispatch: (transaction: Transaction) => void;
  },
  options: SuperDocsPluginOptions,
  instruction: string,
  documentHtml: string
): Promise<SuperDocsEditResult> {
  if (!documentHtml.trim()) {
    throw new Error(
      "Cannot send an empty document to SuperDocs."
    );
  }

  view.dispatch(
    setSuperDocsProcessing(
      view.state,
      true
    )
  );

  try {
    const result =
      await options.client.edit({
        sessionId: options.sessionId,
        documentHtml,
        instruction,
      });

    view.dispatch(
      setSuperDocsSuccess(
        view.state,
        result.changes
      )
    );

    return result;
  } catch (error) {
    const message =
      error instanceof Error
        ? error.message
        : "SuperDocs edit failed.";

    view.dispatch(
      setSuperDocsError(
        view.state,
        message
      )
    );

    throw error;
  }
}