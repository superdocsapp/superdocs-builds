import {
  describe,
  expect,
  it,
} from "vitest";

import {
  Editor,
} from "@tiptap/core";

import StarterKit from
  "@tiptap/starter-kit";

import {
  SuperDocsExtension,
} from "../src/tiptap/index.js";

describe(
  "SuperDocs TipTap extension",
  () => {
    it(
      "registers the SuperDocs command",
      () => {
        const client = {
          async edit() {
            return {
              updatedHtml:
                "<p>Updated</p>",

              changes: [
                {
                  changeId: "change-1",
                  operation: "edit" as const,
                  oldText: "Hello",
                  newText: "Updated",
                },
              ],
            };
          },
        };

        const editor =
          new Editor({
            extensions: [
              StarterKit,

              SuperDocsExtension.configure({
                client,
                sessionId:
                  "test-session",
              }),
            ],

            content:
              "<p>Hello</p>",
          });

        expect(
          typeof editor.commands
            .superdocsEdit
        ).toBe("function");

        expect(
          editor.getHTML()
        ).toContain("Hello");

        editor.destroy();
      }
    );

    it(
      "applies updated HTML returned by SuperDocs",
      async () => {
        const client = {
          async edit() {
            return {
              updatedHtml:
                "<p>Updated</p>",

              changes: [
                {
                  changeId: "change-1",
                  operation: "edit" as const,
                  oldText: "Hello",
                  newText: "Updated",
                },
              ],
            };
          },
        };

        const editor =
          new Editor({
            extensions: [
              StarterKit,

              SuperDocsExtension.configure({
                client,
                sessionId:
                  "test-session",
              }),
            ],

            content:
              "<p>Hello</p>",
          });

        const result =
          editor.commands.superdocsEdit(
            "Improve the wording."
          );

        expect(result).toBe(true);

        await new Promise(
          (resolve) =>
            setTimeout(resolve, 0)
        );

        expect(
          editor.getHTML()
        ).toContain("Updated");

        expect(
          editor.getHTML()
        ).not.toContain("Hello");

        editor.destroy();
      }
    );
  }
);