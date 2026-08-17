# Submitting a project

Read [CURATION.md](CURATION.md) first. It's short, and it tells you whether your
project qualifies before you spend time on the submission.

There are two ways in. Both end up in the same place: a reviewed entry in
`gallery/manifest.json`.

## Option 1 — open an issue

Use the **Submit a build** issue template. Its fields are the same three checks a
reviewer applies, so filling it in honestly is the whole submission. A reviewer
copies accepted entries into the manifest.

Choose this if you'd rather not edit JSON.

## Option 2 — send a pull request

Add one object to the `entries` array in `gallery/manifest.json`:

```json
{
  "slug": "your-project",
  "name": "Your project",
  "summary": "One sentence on what it is.",
  "link": "https://…",
  "superdocs_surfaces": ["Which feature you used, and what it changed"],
  "evidence": {
    "what": "What a reviewer will find at this link.",
    "url": "https://…"
  },
  "submitted_by": "you",
  "reviewed_on": "",
  "decision": "",
  "reviewer_note": ""
}
```

Then run:

```bash
python3 lint_manifest.py
python3 make_gallery.py
```

Commit both the manifest and the regenerated `index.html`. One project per pull
request.

Leave `reviewed_on`, `decision` and `reviewer_note` empty. Those belong to
whoever reviews it, and the lint fails if a submission fills in its own verdict.

## What happens next

1. A reviewer opens both your links.
2. They apply the three checks from CURATION.md, in order, stopping at the first
   failure.
3. The decision goes into the manifest — listed or declined — with a short
   reason, and is merged either way.
4. Expect an answer within seven days. Past that it's declined as R8, which means
   "send it again when the evidence is public", not "no".

## If your entry is declined

You'll get a code (R1–R8) and a sentence, recorded next to your entry in public.
Fix the reason and submit again; there's no limit on resubmissions. If you think
the reviewer got it wrong, say so on the same thread.

## What the automated checks do

Every pull request runs `.github/workflows/curation.yml`, which fails if:

- an entry has no evidence link, no review date, or no stated reason
- a rejection cites a code that isn't published above
- `index.html` doesn't match what the manifest generates, so entries can't be
  added by editing the page and skipping review
- the badge would break under GitHub's image proxy
- the gallery page loads anything from the network

None of these judge your project. A person does that, and no script can do it for
them.
