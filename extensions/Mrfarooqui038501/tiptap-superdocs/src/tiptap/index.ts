import { Extension } from "@tiptap/core";

import {
  createSuperDocsPlugin,
  requestSuperDocsEdit,
  type SuperDocsClient,
} from "../core/index.js";

export interface SuperDocsTipTapOptions {
  client: SuperDocsClient;
  sessionId: string;
}

declare module "@tiptap/core" {
  interface Commands<ReturnType> {
    superdocs: {
      superdocsEdit: (
        instruction: string
      ) => ReturnType;
    };
  }
}

export const SuperDocsExtension =
  Extension.create<SuperDocsTipTapOptions>({
    name: "superdocs",

    addOptions() {
      return {
        client:
          undefined as unknown as SuperDocsClient,

        sessionId: "",
      };
    },

    addCommands() {
      return {
        superdocsEdit:
          (instruction: string) =>
          ({ editor }) => {
            void (async () => {
              try {
                const result =
                  await requestSuperDocsEdit(
                    editor.view,
                    {
                      client:
                        this.options.client,

                      sessionId:
                        this.options.sessionId,
                    },
                    instruction,
                    editor.getHTML()
                  );

                if (
                  result.updatedHtml &&
                  result.updatedHtml !==
                    editor.getHTML()
                ) {
                  editor.commands.setContent(
                    result.updatedHtml
                  );
                }
              } catch {
                // The shared core plugin already
                // records the error state.
              }
            })();

            return true;
          },
      };
    },

    addProseMirrorPlugins() {
      return [
        createSuperDocsPlugin({
          client: this.options.client,
          sessionId:
            this.options.sessionId,
        }),
      ];
    },
  });