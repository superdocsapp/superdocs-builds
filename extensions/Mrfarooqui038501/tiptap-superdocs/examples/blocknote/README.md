# SuperDocs BlockNote Example

This example shows how to register the shared SuperDocs plugin with BlockNote.

## Installation

```bash
npm install
```

## Usage

```ts
import {
  createSuperDocsBlockNoteExtension,
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

const superDocsExtension =
  createSuperDocsBlockNoteExtension({
    client,
    sessionId: "blocknote-example-session",
  });

// Register the extension with a BlockNote editor
// according to the BlockNote setup used by the host application.
console.log(superDocsExtension);
```

The BlockNote adapter reuses the same SuperDocs core plugin as the TipTap adapter.

This keeps the SuperDocs behaviour shared between editors instead of duplicating API and state-management logic.