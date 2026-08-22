# Google Docs Accessibility Preflight

Built by Anjani Devabattina for the SuperDocs engineering task.

## What it does

This project is a Google Docs add-on that performs an accessibility
preflight before document export.

It checks the document for common accessibility issues such as:

- Heading structure
- Possible headings formatted as normal text
- Tables
- Images
- Document structure

The results are shown in a sidebar so the user can review the
document before exporting it.

## How to run

1. Open the Google Doc.
2. Open the SuperDocs Preflight menu.
3. Select Run Accessibility Check.
4. Review the findings in the sidebar.
5. Review the suggested fixes.
6. Export the document.

The prototype uses Google Apps Script and the Google Docs APIs.

## SuperDocs features used

- Document editing
- Document analysis
- Accessibility preflight
- Review workflow
- Export testing

## Testing

I tested the add-on using a Google Doc containing headings,
student information, an image, a table and document structure
issues.

I also tested the exported PDF.

## Limitations

Some checks are heuristic and may produce false positives.
For example, normal text that looks like a heading can be flagged
for review.

The image check identifies images but does not judge whether the
alternative text is meaningful.

## Author

Anjani Devabattina
