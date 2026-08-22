# Google Docs Accessibility Preflight

Built by Anjani Devabattina for the SuperDocs engineering task.

## What it does

This project is a Google Docs add-on that performs an accessibility
preflight check before document export.

It scans the document for common accessibility issues, including:

- Heading structure
- Possible headings formatted as normal text
- Tables
- Images
- Document structure

The results are displayed in a sidebar so the user can review
potential accessibility issues without leaving Google Docs.

## How to run

1. Open the test Google Doc.
2. Open the Google Apps Script project connected to the document.
3. Make sure `Code.gs` and `Sidebar.html` are added to the project.
4. Save the Apps Script project.
5. Reload the Google Doc.
6. Open the `SuperDocs Preflight` menu.
7. Select `Run Accessibility Check`.
8. Review the accessibility findings in the sidebar.

The prototype is built using Google Apps Script and the Google Docs API.

## SuperDocs features used

- Google Docs integration
- Document analysis
- Accessibility preflight
- Sidebar-based review workflow
- Export testing

## Testing

I tested the add-on using a Google Doc containing:

- Proper headings
- Normal text that can appear visually similar to a heading
- Student information
- A table
- An image
- Document structure/content that can be reviewed for accessibility

I also tested the document export workflow and reviewed the resulting PDF.

## Known limitations

This is a prototype and some checks are heuristic.

- Possible-heading detection can produce false positives because
  visually bold text is not always intended to be a heading.
- The image check identifies images that need accessibility review,
  but it does not determine whether alternative text is meaningful.
- The current implementation does not provide complete automated
  PDF/UA validation.
- Reading order, colour-only meaning, and other advanced accessibility
  checks would require additional implementation.
- The current prototype focuses primarily on identifying and reporting
  accessibility issues rather than automatically fixing every issue.

## Demo

A short demonstration video and screenshots show the add-on running
on a test Google Doc.

## Author

Anjani Devabattina
