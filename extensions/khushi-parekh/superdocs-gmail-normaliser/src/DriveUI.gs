/**
 * DriveUI.gs  (v3 - thin click handler, matches Code.gs's fix)
 * -----------------------------------------------------------------------
 * Extends the add-on into Drive itself, closing the assignment card's
 * "also surfaces in Drive" requirement.
 *
 * WHY A PASTED LINK INSTEAD OF onItemsSelectedTrigger: the first version
 * used Drive's onItemsSelectedTrigger, which needs the
 * drive.addons.metadata.readonly scope. In real testing that scope
 * consistently failed to authorize through a Test Deployment - Google's
 * Test Deployments are known to be unreliable about picking up newly
 * added, narrower OAuth scopes even after reinstalling, revoking
 * account access, and re-authorizing (all tried, all failed the same
 * way, logged in PROGRESS.md). Rather than block the Drive surface on
 * an infrastructure quirk outside this add-on's control, this version
 * asks the user to paste the Drive file's link or ID directly on the
 * add-on's homepage card instead of relying on Drive's "selected item"
 * event. This only needs the standard `drive` scope (already used
 * elsewhere in this project for saving output), which is confirmed
 * working.
 *
 * WHY THE CLICK HANDLER IS THIN: same reasoning as Code.gs - a real run
 * hit "Exceeded maximum execution time" when session-init and both
 * uploads ran synchronously in this handler. Fixed the same way: the
 * handler below only validates input and queues a job in state
 * 'not_started'; every SuperDocs network call happens later, inside
 * AsyncJobs.gs's advanceNotStartedJob, on the polling trigger.
 * -----------------------------------------------------------------------
 */

/**
 * Drive homepage trigger: shown whenever the add-on is opened in Drive.
 */
function buildDriveHomepage(e) {
  const section = CardService.newCardSection()
    .setHeader("Normalise a Drive file")
    .addWidget(
      CardService.newTextParagraph().setText(
        "Paste the link (or just the file ID) of a document in your Drive. " +
          "Declared formats: " +
          SUPPORTED_EXTENSIONS.join(", ") +
          ".",
      ),
    )
    .addWidget(
      CardService.newTextInput()
        .setFieldName("driveFileLink")
        .setTitle("Drive file link or ID")
        .setHint("e.g. https://drive.google.com/file/d/XXXXXXXX/view"),
    )
    .addWidget(
      CardService.newTextInput()
        .setFieldName("notifyEmail")
        .setTitle('Your email (for the "it\'s done" notification)')
        .setHint(
          "Session.getActiveUser() is unreliable under a Test " +
            "Deployment's OAuth scopes (see PROGRESS.md) - typing it in " +
            "directly sidesteps that entirely, the same way the file-link " +
            "input above sidesteps the selected-item scope issue.",
        ),
    )
    .addWidget(
      CardService.newTextButton()
        .setText("Normalise")
        .setOnClickAction(
          CardService.newAction().setFunctionName(
            "normaliseDriveFileFromInput",
          ),
        ),
    );

  addStatsFooter(section);

  return CardService.newCardBuilder()
    .setHeader(CardService.newCardHeader().setTitle("SuperDocs Normaliser"))
    .addSection(section)
    .build();
}

/**
 * Button handler: pull the file ID out of whatever the user pasted (a
 * full share link or a bare ID both work), then queue a job. Does NOT
 * call the SuperDocs API - that's the part that must stay off this
 * handler (see AsyncJobs.gs). The dedupe check below does read the
 * file's bytes locally to hash it (see Dedupe.gs's note on why
 * getMd5Checksum() isn't available here), which is a same-network
 * Drive-to-script read, not a SuperDocs call, so it doesn't reintroduce
 * the timeout risk this handler was fixed to avoid.
 */
function normaliseDriveFileFromInput(e) {
  const raw = (e.formInput && e.formInput.driveFileLink) || "";
  const fileId = extractDriveFileId(raw);
  const notifyEmail = ((e.formInput && e.formInput.notifyEmail) || "").trim();

  if (!fileId) {
    return CardService.newActionResponseBuilder()
      .setNotification(
        CardService.newNotification().setText(
          "Couldn't find a file ID in that - paste the full Drive share link or just the ID.",
        ),
      )
      .build();
  }
  if (!notifyEmail || notifyEmail.indexOf("@") === -1) {
    return CardService.newActionResponseBuilder()
      .setNotification(
        CardService.newNotification().setText(
          "Enter a valid email address to be notified at.",
        ),
      )
      .build();
  }

  try {
    const file = DriveApp.getFileById(fileId);
    const fileName = file.getName();

    // Dedupe check via Drive's own MD5 checksum - no bytes read, no
    // network call, safe inside the click handler's execution window.
    const hash = contentHashForDriveFile(file);
    const existing = findProcessedRecord(hash);
    if (existing) {
      recordStat("deduped");
      return CardService.newActionResponseBuilder()
        .setNotification(
          CardService.newNotification().setText(
            "Already normalised earlier (" +
              existing.filename +
              "). " +
              "Drive copy: " +
              existing.driveUrl,
          ),
        )
        .build();
    }

    trackPendingJob({
      state: "not_started",
      driveFileId: fileId,
      notifyEmail: notifyEmail,
      originalFilename: fileName,
      contentHash: hash,
    });

    return CardService.newActionResponseBuilder()
      .setNotification(
        CardService.newNotification().setText(
          'Queued "' +
            fileName +
            '" - you will get an email at ' +
            notifyEmail +
            " when it is done.",
        ),
      )
      .build();
  } catch (err) {
    console.error("normaliseDriveFileFromInput failed: " + err);
    return CardService.newActionResponseBuilder()
      .setNotification(
        CardService.newNotification().setText("Failed: " + err.message),
      )
      .build();
  }
}

/**
 * Accepts a bare Drive file ID, or a full share link in any of Drive's
 * common URL shapes, and returns just the ID.
 */
function extractDriveFileId(input) {
  const trimmed = String(input || "").trim();
  if (!trimmed) return null;

  // https://drive.google.com/file/d/FILE_ID/view...
  var match = trimmed.match(/\/file\/d\/([a-zA-Z0-9_-]+)/);
  if (match) return match[1];

  // https://docs.google.com/document/d/FILE_ID/edit...
  match = trimmed.match(/\/document\/d\/([a-zA-Z0-9_-]+)/);
  if (match) return match[1];

  // ...?id=FILE_ID
  match = trimmed.match(/[?&]id=([a-zA-Z0-9_-]+)/);
  if (match) return match[1];

  // Looks like a bare ID already (Drive IDs are long alphanumeric/-/_ strings).
  if (/^[a-zA-Z0-9_-]{15,}$/.test(trimmed)) return trimmed;

  return null;
}
