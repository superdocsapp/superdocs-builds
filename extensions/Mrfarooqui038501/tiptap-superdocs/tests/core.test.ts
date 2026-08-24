import {
  describe,
  expect,
  it,
} from "vitest";

import {
  EditorState,
} from "@tiptap/pm/state";

import {
  Schema,
} from "@tiptap/pm/model";

import {
  createSuperDocsPlugin,
  getSuperDocsPluginState,
  setSuperDocsSuccess,
} from "../src/core/index.js";

describe(
  "SuperDocs ProseMirror core",
  () => {
    const schema =
      new Schema({
        nodes: {
          doc: {
            content: "paragraph+",
          },

          paragraph: {
            content: "inline*",

            toDOM() {
              return ["p", 0];
            },

            parseDOM: [
              {
                tag: "p",
              },
            ],
          },

          text: {
            group: "inline",
          },
        },
      });

    it(
      "starts with clean plugin state",
      () => {
        const plugin =
          createSuperDocsPlugin({
            client: {
              async edit() {
                return {
                  updatedHtml:
                    "<p>Hello</p>",
                  changes: [],
                };
              },
            },

            sessionId: "test-session",
          });

        const state =
          EditorState.create({
            schema,
            plugins: [plugin],
          });

        const pluginState =
          getSuperDocsPluginState(
            state
          );

        expect(
          pluginState.isProcessing
        ).toBe(false);

        expect(
          pluginState.error
        ).toBeNull();

        expect(
          pluginState.lastChanges
        ).toEqual([]);
      }
    );

    it(
      "stores returned changes",
      () => {
        const plugin =
          createSuperDocsPlugin({
            client: {
              async edit() {
                return {
                  updatedHtml:
                    "<p>Updated</p>",

                  changes: [
                    {
                      changeId: "change-1",
                      operation: "edit",
                      oldText: "Hello",
                      newText: "Updated",
                    },
                  ],
                };
              },
            },

            sessionId: "test-session",
          });

        let state =
          EditorState.create({
            schema,
            plugins: [plugin],
          });

        state = state.apply(
          setSuperDocsSuccess(
            state,
            [
              {
                changeId: "change-1",
                operation: "edit",
                oldText: "Hello",
                newText: "Updated",
              },
            ]
          )
        );

        const pluginState =
          getSuperDocsPluginState(
            state
          );

        expect(
          pluginState.lastChanges
        ).toHaveLength(1);

        expect(
          pluginState.lastChanges[0]
            ?.changeId
        ).toBe("change-1");
      }
    );
  }
);