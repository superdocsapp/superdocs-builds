# Demo vault

A four-note vault you can open in Obsidian to try the plugin. Everything in it is invented; Northwind Freight and Halberd Systems are not real companies.

```
demo-vault/
  Project Atlas.md          <- the designated living note, two owned regions
  Notes/
    Weekly status 2026-08-18.md
    Decisions.md
    Meeting - vendor call.md   <- contains a line that tries to give the agent orders
```

## Try it

1. Open `demo-vault` as a vault, or copy the folder into a vault you already have.
2. Install the plugin (see the main README), then in its settings set the designated note to `Project Atlas.md` and the source folder to `Notes`.
3. Run **Preview living-note update (no spend)** first. It makes no network call and shows you the exact text a real run would upload.
4. Run **Sync designated living note now**, approve one proposed change and reject another, and watch where the text lands.

`Project Atlas.md` ends with a paragraph that exists to be left alone. Compare it before and after: it should be identical byte for byte, and so should every other line outside the markers.
