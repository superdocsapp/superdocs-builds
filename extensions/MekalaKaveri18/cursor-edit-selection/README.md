# SuperDocs: edit the current Cursor / VS Code selection

Built by **Mekala Kaveri** for the SuperDocs task.

**Kind:** original coding-tool integration. SuperDocs asked for Cursor/VS Code extras. This is not an editor clone: Cursor stays the editor; SuperDocs performs the targeted rewrite.

**Who:** engineers writing RFCs, design docs, and ADRs in the IDE (the same people already in Cursor).

## Install (sideload)

1. Copy this folder.
2. In Cursor/VS Code: **Extensions → Install from VSIX** after `npx @vscode/vsce package`, or symlink the folder into `~/.cursor/extensions` for local dev.
3. Set `superdocs.apiKey` in settings (never commit it).
4. Select a paragraph → Command Palette → **SuperDocs: Edit selection**.

The command replaces **only the selected range**. Surrounding file bytes are never sent as the thing to rewrite.

```bash
node test.js
```

Four-call contract in spirit: the selection is uploaded as HTML, chat edits it, auto-approve is the IDE default (you are already looking at the buffer), export is saving the file.

Credit: built for the SuperDocs task.
