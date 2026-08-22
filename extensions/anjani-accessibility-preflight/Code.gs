function onOpen() {
  DocumentApp.getUi()
    .createMenu('SuperDocs Preflight')
    .addItem('Run Accessibility Check', 'showSidebar')
    .addToUi();
}


function showSidebar() {
  const html = HtmlService
    .createHtmlOutputFromFile('Sidebar')
    .setTitle('Accessibility Preflight');

  DocumentApp.getUi().showSidebar(html);
}


/**
 * Main accessibility scan
 */
function getAccessibilityReport() {

  const doc = DocumentApp.getActiveDocument();
  const body = doc.getBody();

  const report = {
    title: doc.getName(),

    issues: [],

    counts: {
      headings: 0,
      images: 0,
      tables: 0,
      emptyParagraphs: 0
    }
  };


  const paragraphs = body.getParagraphs();

  let previousWasNormal = false;


  // ---------------------------------------
  // CHECK PARAGRAPHS
  // ---------------------------------------

  paragraphs.forEach(function(paragraph, index) {

    const text = paragraph.getText().trim();

    const heading = paragraph.getHeading();


    // Empty paragraph
    if (text === '') {

      report.counts.emptyParagraphs++;

      return;
    }


    // Real heading
    if (heading !== DocumentApp.ParagraphHeading.NORMAL) {

      report.counts.headings++;

      previousWasNormal = false;

      return;
    }


    // Possible heading
    //
    // We treat short standalone text as a possible
    // heading when it does not look like a sentence.

    if (
      text.length > 0 &&
      text.length <= 60 &&
      !/[.!?]$/.test(text)
    ) {

      report.issues.push({
        type: 'heading',
        severity: 'warning',
        message:
          'Possible heading is formatted as normal text instead of a real heading.',
        text: text.substring(0, 80)
      });
    }

    previousWasNormal = true;

  });


  // ---------------------------------------
  // CHECK TABLES
  // ---------------------------------------

  const numChildren = body.getNumChildren();

  for (let i = 0; i < numChildren; i++) {

    const element = body.getChild(i);

    if (
      element.getType() ===
      DocumentApp.ElementType.TABLE
    ) {

      const table = element.asTable();

      report.counts.tables++;


      if (table.getNumRows() > 0) {

        const firstRow = table.getRow(0);

        report.issues.push({

          type: 'table',

          severity: 'warning',

          message:
            'Table detected. Verify that the first row is a header row.',

          text:
            firstRow.getText().substring(0, 100)

        });
      }
    }
  }


  // ---------------------------------------
  // CHECK IMAGES
  // ---------------------------------------

  scanForImages(body, report);


  // ---------------------------------------
  // EMPTY PARAGRAPHS
  // ---------------------------------------

  if (report.counts.emptyParagraphs > 0) {

    report.issues.push({

      type: 'structure',

      severity: 'warning',

      message:
        'The document contains ' +
        report.counts.emptyParagraphs +
        ' empty paragraphs. Excessive empty paragraphs can make navigation harder.',

      text: 'Empty paragraphs detected.'
    });
  }


  // ---------------------------------------
  // IF REAL HEADINGS DON'T EXIST
  // ---------------------------------------

  if (report.counts.headings === 0) {

    report.issues.push({

      type: 'heading',

      severity: 'warning',

      message:
        'No heading structure was detected. Consider using Heading 1, Heading 2, etc. for document structure.',

      text: 'Document'
    });
  }


  return report;
}


/**
 * Recursively find images
 */
function scanForImages(element, report) {

  const type = element.getType();


  if (
    type === DocumentApp.ElementType.INLINE_IMAGE
  ) {

    report.counts.images++;

    report.issues.push({

      type: 'image',

      severity: 'warning',

      message:
        'Image detected. Verify that it has meaningful alternative text.',

      text:
        'Image found in document.'
    });

  }


  if (
    element.getNumChildren &&
    element.getNumChildren() > 0
  ) {

    for (
      let i = 0;
      i < element.getNumChildren();
      i++
    ) {

      scanForImages(
        element.getChild(i),
        report
      );

    }
  }
}


/**
 * Fix likely headings.
 *
 * This is intentionally conservative:
 * only short standalone paragraphs are changed.
 */
function fixHeadings() {

  const doc = DocumentApp.getActiveDocument();

  const body = doc.getBody();

  const paragraphs = body.getParagraphs();

  let fixed = 0;


  paragraphs.forEach(function(paragraph, index) {

    const text = paragraph.getText().trim();

    if (!text) {
      return;
    }


    // Never modify existing headings
    if (
      paragraph.getHeading() !==
      DocumentApp.ParagraphHeading.NORMAL
    ) {

      return;
    }


    // First non-empty paragraph becomes title
    if (fixed === 0 && index === 0) {

      paragraph.setHeading(
        DocumentApp.ParagraphHeading.TITLE
      );

      fixed++;

      return;
    }


    // Short standalone lines are treated as section headings
    if (
      text.length <= 60 &&
      !/[.!?]$/.test(text)
    ) {

      paragraph.setHeading(
        DocumentApp.ParagraphHeading.HEADING1
      );

      fixed++;
    }

  });


  return fixed;
}
