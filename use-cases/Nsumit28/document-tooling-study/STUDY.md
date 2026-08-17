# What people are stuck on when software has to touch a Word document

Sumit Negi · 17 August 2026

I spent a day pulling the fifteen most-read pages on document tooling and
reading them properly. This is what I found, and every page is linked below so
you can check any of it yourself.

## Why I looked

I kept running into the same thing from two directions. Every document tool
claims it handles Word files, and every developer I read seems to be fighting
one. I wanted to know which specific problems people actually search for, where
they end up when they do, and whether those problems are settled or still being
argued about in 2026.

So rather than guess, I went and counted.

## How I picked these fifteen

I wrote down fifteen problems first — things that go wrong when a program or an
AI has to work on a document a person will open afterwards. Tracked changes,
comments, styles surviving an edit, docx to markdown and back, templates,
diffing two files, tables trapped in PDFs, OOXML that Word refuses to open.

Then I queried Stack Overflow, GitHub and Hacker News through their public APIs
and took their own engagement counters — votes, views, reactions, comments,
points. That gave me 129 candidate pages.

Ranking those purely by engagement doesn't work, and it's worth saying why. The
highest-voted result in my pool was a question about text boxes in markdown, and
GitHub's top hits included a release changelog and someone migrating a project to
pnpm. Popular isn't the same as relevant. So I filtered for genuine subject
matter first, then ranked by reach inside each platform, then took the top
fifteen while keeping at least three platforms and no more than four pages on any
single problem.

The full candidate pool, the rule and the measurements are all in this
repository.

## The fifteen pages

| # | Page | Where | Engagement | Last active |
|---|---|---|---|---|
| 1 | [How can doc/docx files be converted to markdown or structured text?](https://stackoverflow.com/questions/16383237/how-can-doc-docx-files-be-converted-to-markdown-or-structured-text) | Stack Overflow | 155 votes · 180,033 views | 2024 |
| 2 | [How to extract a table as text from the PDF](https://stackoverflow.com/questions/47533875/how-to-extract-a-table-as-text-from-the-pdf) | Stack Overflow | 58 votes · 159,685 views | 2023 |
| 3 | [Extract / Identify Tables from PDF python](https://stackoverflow.com/questions/28532770/extract-identify-tables-from-pdf-python) | Stack Overflow | 54 votes · 126,686 views | 2024 |
| 4 | [Markdown to docx, including complex template](https://stackoverflow.com/questions/14249811/markdown-to-docx-including-complex-template) | Stack Overflow | 91 votes · 78,169 views | 2024 |
| 5 | [Python docx Replace string in paragraph while keeping style](https://stackoverflow.com/questions/34779724/python-docx-replace-string-in-paragraph-while-keeping-style) | Stack Overflow | 25 votes · 68,687 views | 2024 |
| 6 | [Add styling rules in pandoc tables for odt/docx output](https://stackoverflow.com/questions/17858598/add-styling-rules-in-pandoc-tables-for-odt-docx-output-table-borders) | Stack Overflow | 36 votes · 24,806 views | 2026 |
| 7 | [Inserting a comment in docx file using python 3](https://stackoverflow.com/questions/53892070/inserting-a-comment-in-docx-file-using-python-3) | Stack Overflow | 4 votes · 8,161 views | 2025 |
| 8 | [Diff 2 Open XML Word Documents](https://stackoverflow.com/questions/4224649/diff-2-open-xml-word-documents) | Stack Overflow | 8 votes · 6,057 views | 2026 |
| 9 | [feat(docx-io): add tracked changes and comments import/export](https://github.com/cicero-im/plate/pull/66) | GitHub | 37 comments | 2026 |
| 10 | [WIP: DOCX import/export functionality](https://github.com/cicero-im/plate/pull/131) | GitHub | 25 comments | 2026 |
| 11 | [Use HTML Tables Instead of Markdown Syntax for Better Table Handling](https://github.com/microsoft/markitdown/issues/1211) | GitHub | 11 reactions | 2026 |
| 12 | [Suggestion: Word Add-In and DOCX Editing Feature](https://github.com/LegalQuants/lq-ai/pull/315) | GitHub | open PR | 2026 |
| 13 | [Tabula — extract tables from PDF](https://github.com/tabulapdf/tabula-java) | Hacker News → GitHub | 148 points · 2,037 stars | 2021 |
| 14 | [Nutrient DWS MCP server](https://github.com/PSPDFKit/nutrient-dws-mcp-server) | Hacker News → GitHub | 8 points · 68 stars | 2025 |
| 15 | [TinyDOCX](https://github.com/Lulzx/tinydocx) | Hacker News → GitHub | 6 points · 11 stars | 2025 |

The eight Stack Overflow questions have **652,284 views between them**. Whatever
else is true, this is not a niche complaint.

## Four things they have in common

**The pages are short and the threads are long.** The Stack Overflow questions
run from 35 to 181 words. Nobody is writing an essay; they paste the error, show
eight lines of code, and ask. The length is in the answers and the comments
underneath.

**Eleven of the fifteen carry code.** Not a screenshot, not a description —
actual code you can copy. On the three project pages, the README is mostly code
too.

**Almost none of the titles are questions.** Only two of fifteen start with how,
what or why. The rest are symptoms and statements: "Diff 2 Open XML Word
Documents", "docx styles lost after programmatic edit". People title by the thing
that is broken.

**Everything old is still being read.** Question 8 was asked in 2010 and had
activity this year. Question 5 is from 2016 and has 68,687 views. These are not
trending topics, they are permanent ones.

## The split that actually matters

Line the pages up by status and something obvious appears.

**All eight Stack Overflow questions are answered.** Every one. They are about
converting between formats and pulling tables out of PDFs, they were asked
between 2010 and 2018, and people are still reading them.

**All four GitHub items are open.** Not one is closed. Every one is from 2026,
and every one is about editing inside a document rather than converting it:
importing and exporting tracked changes and comments, getting docx in and out of
an editor intact, keeping tables through a format change, putting AI editing
inside Word itself.

That's the finding I didn't expect. **Getting a document out of Word is a solved
problem people still look up. Changing a document while it's still a document is
being figured out right now, in public, this year.** The single most-discussed
page in my whole set — 37 comments — is a pull request about tracked changes and
comments surviving import and export.

If you're building in this space, the first group is table stakes and the second
group is where the actual work is.

## What I'd do with this if I were writing for these people

Write short. Lead with the symptom, not a question. Put working code near the
top. Don't chase what's trending, because the pages people read are ten years old
and still going. And if you want to be useful rather than another conversion
tutorial, write about the second group — tracked changes, comments, styles
surviving an edit — because that is what is unsettled.

## What this doesn't tell you

It's one snapshot, taken on 16 August 2026. Do it in six months and the GitHub
half will have moved, because open pull requests don't stay open.

The engagement numbers aren't comparable across platforms. 155 votes on Stack
Overflow and 148 points on Hacker News are different currencies, and I've kept
them in separate columns rather than adding them up into a score that would mean
nothing.

The word counts are the question or issue body, not the whole page. A Stack
Overflow question of 43 words might sit above four long answers. I measured what
the person wrote, not what they got back.

And the relevance filter was my judgement. I've said what the rule was and left
the whole 129-page pool in the repository, so if you think I dropped something I
shouldn't have, you can see exactly what I dropped.

---

*I built this while applying for a role at SuperDocs, which makes AI document
editing software. The problems above are ones I went looking for on their
account, and I've tried to report what I found rather than what would be
convenient.*
