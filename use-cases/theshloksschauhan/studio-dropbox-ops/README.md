# Studio Dropbox ops (use case)

Named buyers and a studio workflow for SuperDocs sitting beside Dropbox, not replacing it. Built by **Shlok Chauhan**.

This is a use-case pack, not a second copy of the assigned watcher. The runnable build is a separate PR:

https://github.com/superdocsapp/superdocs-builds/pull/122

## What it does

A boutique studio already lives in Dropbox. A client drops a messy brief into a nominated inbox. SuperDocs proposes a studio-template document or a one-page companion brief. A principal reviews in a console. On approve, the export is filed beside the original as `{basename}.superdocs.{treatment}{ext}`. Reject leaves Dropbox unchanged. Touching our own output does not start a new job.

[USE_CASES.md](USE_CASES.md) lists nine buyer roles (companies named, nobody contacted) and three poor fits: e-sign replacement, hospital EHR as buyer one, and pitching SuperDocs as a DMS.

## SuperDocs features used

Upload, chat (edit instruction), human approve, export. The four-call loop is the product; Dropbox is the folder the studio already has.

## How to read this folder

No install. Open, in order:

1. [ONE_PAGE.md](ONE_PAGE.md) — what the loop is
2. [workflow-diagram.svg](workflow-diagram.svg) — drop → watch → SuperDocs → human gate → sibling file
3. [ARCHITECTURE.md](ARCHITECTURE.md) — states and safety rails
4. [USE_CASES.md](USE_CASES.md) — who would buy, where they listen, what would open a first conversation
5. [NOT_DOING.md](NOT_DOING.md) — cuts on the assigned build that this use case inherits

To run the demo that proves use case 1, follow the README in `extensions/theshloksschauhan/dropbox-folder-watcher` on PR 122.

## Status

Nobody on these lists has been emailed, called, or DMed. Companies and roles only.
