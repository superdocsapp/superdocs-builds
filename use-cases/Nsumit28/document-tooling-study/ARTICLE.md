# Tracked changes disappear when a document round-trips through markdown

You export a .docx, run it through markdown or HTML, edit it, convert it back.
Word opens the result and every revision mark is gone. Not rejected — gone. The
edits are sitting there as ordinary text, as if someone had accepted them all
and never said so.

Here is what Word had before the trip:

```xml
<w:p>
  <w:ins w:id="41" w:author="Priya" w:date="2026-08-14T09:12:00Z">
    <w:r><w:t>net thirty days</w:t></w:r>
  </w:ins>
  <w:del w:id="42" w:author="Priya" w:date="2026-08-14T09:12:00Z">
    <w:r><w:delText>net sixty days</w:delText></w:r>
  </w:del>
</w:p>
```

Two things there have no equivalent in markdown. The `w:ins` and `w:del`
elements, which are what makes a change a *tracked* change rather than a fact.
And `w:delText`, which is where deleted text lives — a deleted run does not use
`w:t` at all. Convert that paragraph to markdown and you get one line of prose.
Convert it back and you get one run of plain text. The wrappers are not corrupted
in transit; there is simply nowhere to put them.

Comments go the same way and are easier to miss. A comment isn't stored in the
paragraph — it lives in `word/comments.xml`, and the body only holds anchors
pointing at it:

```xml
<w:commentRangeStart w:id="7"/>
<w:r><w:t>indemnity</w:t></w:r>
<w:commentRangeEnd w:id="7"/>
<w:r><w:commentReference w:id="7"/></w:r>
```

Drop the anchors and `comments.xml` is still in the file, still valid, and
attached to nothing. The document opens cleanly and the review thread is gone.

## How to tell whether your pipeline does this

Take a document with one tracked insertion and one comment. Send it through your
pipeline. Then unzip the result and look:

```bash
unzip -o out.docx -d out/
grep -c "w:ins\|w:del" out/word/document.xml
grep -c "commentReference" out/word/document.xml
```

Zero on either line means the pipeline flattened your review history. Do this
before it runs on anything that matters, because the failure is silent: the file
opens, the text is right, and nothing warns you.

One caveat on the test itself: a document that had no tracked changes to begin
with will also report zero, so use a file you know has them.

## What to do instead

If the changes matter, don't round-trip through a format that can't hold them.
Edit the OOXML in place, or use a tool that reads and writes the document as a
document. If you must convert, convert a copy and treat the result as a new
draft rather than the same document with edits applied — because that is what it
is.

This is also the part of document tooling that is least settled. Converting
files between formats has been answered for a decade. Keeping tracked changes
and comments alive through an edit is being worked out in open pull requests
right now, which is why it is worth checking rather than assuming.

*Written 17 August 2026 by Sumit Negi, while applying for a role at SuperDocs.
The XML above is from a test document I made; the author name is invented.*
