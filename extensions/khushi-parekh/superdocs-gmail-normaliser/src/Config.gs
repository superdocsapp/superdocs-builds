/**
 * Config.gs
 * -----------------------------------------------------------------------
 * Keeps the SuperDocs API key OUT of source control.
 *
 * HOW TO SET IT: edit API_KEY_TO_SET below with your real key, select
 * "setup" in the function dropdown in the Apps Script editor, click
 * Run, then (optional but recommended) delete the key back out of the
 * line below so it isn't sitting in your source tree afterward - it
 * now lives safely in Script Properties on Google's servers instead.
 *
 * WHY NOT A PROMPT DIALOG (BUG FIXED, see PROGRESS.md): an earlier
 * version used Browser.inputBox() to prompt for the key interactively.
 * That threw, in a real run:
 *   "Specified permissions are not sufficient to call Browser.inputBox.
 *    Required permissions: (.../spreadsheets.currentonly || .../spreadsheets)"
 * Browser.inputBox() (and Ui.prompt(), which has the same restriction)
 * only work in a script BOUND to a Google Sheet/Doc/Form/Slide - this
 * project is a standalone Gmail/Drive add-on script, so neither is
 * available, no matter what scopes are granted. There is no dialog
 * substitute for a standalone script, so this uses the same
 * "edit-a-constant, then run once from the editor" pattern this project
 * already uses for setupPollingTrigger() and setupLabelWatcher().
 * -----------------------------------------------------------------------
 */

const API_KEY_TO_SET = "sk_da45c529f9a578d4df2add605138d885";

function setup() {
  if (!API_KEY_TO_SET || API_KEY_TO_SET.indexOf("PASTE_YOUR") !== -1) {
    console.log(
      "Edit API_KEY_TO_SET near the top of Config.gs with your real " +
        "SuperDocs API key (from use.superdocs.app -> Settings -> API), " +
        "then run setup() again.",
    );
    return;
  }
  PropertiesService.getScriptProperties().setProperty(
    "SUPERDOCS_API_KEY",
    API_KEY_TO_SET.trim(),
  );
  console.log("SuperDocs API key saved to Script Properties.");
}

function getApiKey() {
  const key =
    PropertiesService.getScriptProperties().getProperty("SUPERDOCS_API_KEY");
  if (!key) {
    throw new Error(
      "SuperDocs API key not set. Open this project in the Apps Script " +
        "editor, edit API_KEY_TO_SET in Config.gs, select the setup " +
        "function, and click Run.",
    );
  }
  return key;
}
