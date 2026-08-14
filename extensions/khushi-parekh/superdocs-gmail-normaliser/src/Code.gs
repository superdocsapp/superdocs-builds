/**
 * Code.gs
 * -----------------------------------------------------------------------
 * SuperDocs Gmail Add-on: inbound attachment normaliser
 *
 * WHAT THIS DOES
 *   Open a Gmail message with an attachment -> the add-on offers to
 *   "Normalise" it -> the file is sent to SuperDocs, converted into the
 *   organisation's house template (headings mapped, tables restyled,
 *   logo placed, cover page added) -> the result is saved to a Drive
 *   folder AND sent back as a reply attachment on the same thread.
 *
 * ENTRY POINTS (wired in appsscript.json under addOns.gmail.contextualTriggers)
 *   buildAddOn(e)          - renders the card when a message is opened
 *   normaliseAttachment(e) - button handler; ONLY queues the job (fast)
 *
 * WHY THE CLICK HANDLER IS DELIBERATELY THIN
 *   A real run hit "Exceeded maximum execution time" when an earlier
 *   version did session-init + upload-document + upload-reference
 *   synchronously inside this click handler (confirmed - see
 *   PROGRESS.md). Add-on click handlers are killed by Google at
 *   roughly 30-45 seconds, well under the doc's own warning that
 *   SuperDocs operations on real documents "can take from thirty
 *   seconds to several minutes." So this handler does only two cheap,
 *   local, no-network things - check for a duplicate via content hash
 *   (Dedupe.gs), and register a job - then returns immediately. Every
 *   network call to SuperDocs happens inside AsyncJobs.gs's
 *   advanceNotStartedJob, running on the 1-minute polling trigger,
 *   which has a far longer execution budget.
 *
 * THE FOUR-CALL CONTRACT WITH SUPERDOCS (see SuperDocsClient.gs)
 *   upload -> chat (edit instruction) -> approve -> export
 * -----------------------------------------------------------------------
 */

// --- Configuration -------------------------------------------------------
// Never hardcode secrets here - the API key itself lives in Script
// Properties, set via setup() in Config.gs.

// Drive file ID of house-template.docx (upload it to Drive once, open it,
// copy the ID out of the URL: drive.google.com/file/d/<THIS_PART>/view).
// We upload it fresh as a reference attachment on every run rather than
// relying on SuperDocs's own "saved template" feature - see PROGRESS.md
// for why (the saved-template flow replaced the active document instead
// of just informing its style).
const HOUSE_TEMPLATE_DRIVE_FILE_ID = "16EIWFTzCFcSjhqVMtQMPQvG2069PbwBQ";
const DRIVE_FOLDER_ID = "1z7CxhGjWwBkGPL2I82TfKKTaCvj1QIGb";
// Formats we advertise support for (per task doc: "declare your accepted
// formats/domains in the README"). Keep this in sync with README.md.
const SUPPORTED_EXTENSIONS = [".doc", ".docx", ".odt", ".rtf", ".pdf"];

/**
 * Contextual trigger: runs whenever a Gmail message is opened.
 * Shows a "Normalise" button for every attachment found on the message,
 * plus a small stats line (see Stats.gs) so a coordinator can see the
 * add-on is actually doing work over time.
 */
function buildAddOn(e) {
  const messageId = e.gmail.messageId;
  GmailApp.setCurrentMessageAccessToken(e.gmail.accessToken);
  const message = GmailApp.getMessageById(messageId);
  const attachments = message.getAttachments({ includeInlineImages: false });

  const header = CardService.newCardHeader().setTitle("SuperDocs Normaliser");

  if (!attachments || attachments.length === 0) {
    return CardService.newCardBuilder()
      .setHeader(header)
      .addSection(
        CardService.newCardSection().addWidget(
          CardService.newTextParagraph().setText(
            "No attachment found on this message.",
          ),
        ),
      )
      .build();
  }

  const section = CardService.newCardSection().setHeader("Attachments found");

  // BUG FIXED (see PROGRESS.md): this used to offer a "Normalise"
  // button for EVERY attachment on ANY opened message, with no way to
  // tell a genuine inbound document apart from the add-on's own output
  // (finishJob's reply attaches the normalised file back onto this same
  // thread). Opening that reply and clicking its button re-ran the
  // whole pipeline on already-normalised output - confirmed by a real
  // run producing a "(normalised) (normalised) (normalised)"-stacked
  // filename. Fixed by simply not offering a button for attachments
  // that already look like SuperDocs output.
  let skippedAlreadyNormalised = 0;
  attachments.forEach(function (att, idx) {
    if (isAlreadyNormalisedFilename(att.getName())) {
      skippedAlreadyNormalised++;
      return;
    }
    const supported = isSupportedFormat(att.getName());
    const button = CardService.newTextButton()
      .setText((supported ? "Normalise: " : "Try anyway: ") + att.getName())
      .setOnClickAction(
        CardService.newAction()
          .setFunctionName("normaliseAttachment")
          .setParameters({
            messageId: messageId,
            attachmentIndex: String(idx),
          }),
      );
    section.addWidget(button);
  });

  if (skippedAlreadyNormalised > 0) {
    section.addWidget(
      CardService.newTextParagraph().setText(
        '<font color="#5f6368">(' +
          skippedAlreadyNormalised +
          " attachment(s) already look like SuperDocs output, so they " +
          "were not offered again.)</font>",
      ),
    );
  }

  section.addWidget(
    CardService.newTextParagraph().setText(
      "Declared formats: " +
        SUPPORTED_EXTENSIONS.join(", ") +
        " (legacy .doc, OpenDocument, RTF and scanned PDF are handled, not refused).",
    ),
  );

  addStatsFooter(section);

  return CardService.newCardBuilder()
    .setHeader(header)
    .addSection(section)
    .build();
}

/**
 * Button handler: does only the FAST, LOCAL part synchronously.
 *   1. Compute a content hash of the attachment and check Dedupe.gs -
 *      if this exact file was already normalised, skip straight to
 *      telling the user where the existing result is (no wasted
 *      SuperDocs operation).
 *   2. Otherwise, register a job in state 'not_started' for the
 *      background poller (see AsyncJobs.gs) to pick up on the next
 *      1-minute tick. The poller does: upload -> wait for reference ->
 *      async edit -> approve -> export -> Drive + reply.
 * No SuperDocs API call happens in this function - see file header for
 * why that matters.
 */
function normaliseAttachment(e) {
  const messageId = e.parameters.messageId;
  const attachmentIndex = parseInt(e.parameters.attachmentIndex, 10);

  GmailApp.setCurrentMessageAccessToken(e.gmail.accessToken);
  const message = GmailApp.getMessageById(messageId);
  const attachment = message.getAttachments({ includeInlineImages: false })[
    attachmentIndex
  ];

  try {
    // Same guard as buildAddOn's button list, kept here too in case a
    // stale/cached card still shows a button for an already-normalised
    // file - never re-run the pipeline on the add-on's own output.
    if (isAlreadyNormalisedFilename(attachment.getName())) {
      return CardService.newActionResponseBuilder()
        .setNotification(
          CardService.newNotification().setText(
            "This looks like an already-normalised SuperDocs output file - skipping to avoid reprocessing it.",
          ),
        )
        .build();
    }

    // Dedupe check: local hash + Script Properties lookup only, no
    // network call, so this stays well inside the click handler's
    // execution budget even for large attachments.
    const hash = contentHashForBlob(attachment.copyBlob());
    const existing = findProcessedRecord(hash);
    if (existing) {
      recordStat("deduped");
      return CardService.newActionResponseBuilder()
        .setNotification(
          CardService.newNotification().setText(
            "Already normalised earlier (" +
              existing.filename +
              "). Drive copy: " +
              existing.driveUrl,
          ),
        )
        .build();
    }

    trackPendingJob({
      state: "not_started",
      messageId: messageId,
      originalFilename: attachment.getName(),
      contentHash: hash,
    });

    return CardService.newActionResponseBuilder()
      .setNotification(
        CardService.newNotification().setText(
          "Started - normalising in the background. You will get a reply " +
            "on this thread in a minute or two.",
        ),
      )
      .build();
  } catch (err) {
    console.error("normaliseAttachment failed: " + err);
    return CardService.newActionResponseBuilder()
      .setNotification(
        CardService.newNotification().setText("Failed: " + err.message),
      )
      .build();
  }
}

// --- Small helpers ---------------------------------------------------------

function isSupportedFormat(filename) {
  const lower = filename.toLowerCase();
  return SUPPORTED_EXTENSIONS.some(function (ext) {
    return lower.endsWith(ext);
  });
}

function stripExtension(filename) {
  return filename.replace(/\.[^/.]+$/, "");
}

/**
 * True if a filename already carries the "(normalised)" marker
 * finishJob (AsyncJobs.gs) puts on every file this add-on produces.
 * Shared by Code.gs (button list + click handler) and LabelWatcher.gs
 * (thread scan) so the add-on's own output is never fed back into
 * itself - see the BUG FIXED note above buildAddOn's attachment loop.
 */
function isAlreadyNormalisedFilename(filename) {
  return /\(normalised\)/i.test(filename);
}

/**
 * Shared by both the Gmail card and the Drive homepage card - a small,
 * honest "here's what this add-on has actually done" line, sourced from
 * Stats.gs. Wrapped defensively: a stats read failure should never
 * break the main card.
 */
function addStatsFooter(section) {
  try {
    const stats = getStats();
    const total = Object.keys(stats).filter(function (k) {
      return k !== "_lastUpdated";
    }).length;
    if (total === 0) return;
    section.addWidget(
      CardService.newTextParagraph().setText(
        '<font color="#5f6368">Queued: ' +
          (stats.queued || 0) +
          " · Auto-queued: " +
          (stats.auto_queued || 0) +
          " · Completed: " +
          (stats.completed || 0) +
          " · Failed: " +
          (stats.failed || 0) +
          " · Deduped: " +
          (stats.deduped || 0) +
          "</font>",
      ),
    );
  } catch (err) {
    console.warn("addStatsFooter: skipped (non-fatal): " + err);
  }
}
