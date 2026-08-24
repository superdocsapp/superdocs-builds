# SuperDocs TipTap Example

This example shows how to register the SuperDocs TipTap extension.

## Installation

```bash
npm install
```

## Usage

```ts
import { Editor } from "@tiptap/core";
import StarterKit from "@tiptap/starter-kit";

import {
  SuperDocsExtension,
  type SuperDocsClient,
} from "../../src/index.js";

const client: SuperDocsClient = {
  edit: async ({ sessionId, documentHtml, instruction }) => {
    console.log("SuperDocs edit requested:", {
      sessionId,
      instruction,
    });

    return {
      changes: [],
    };
  },
};

const editor = new Editor({
  extensions: [
    StarterKit,
    SuperDocsExtension.configure({
      client,
      sessionId: "example-session",
    }),
  ],

  content: `
    <h1>Client Progress Report</h1>
    <p>The client completed the first training block.</p>
  `,
});

// Trigger a SuperDocs edit.
editor.commands.superdocsEdit(
  "Improve the wording while keeping the facts unchanged."
);
```

The extension:

1. Registers the `superdocsEdit` command.
2. Sends the current editor HTML to the shared SuperDocs core.
3. Uses the configured session ID.
4. Keeps the SuperDocs plugin state in ProseMirror.