<?php
/**
 * Headless-testing helper ONLY - not part of the shipped tool, not needed by a real
 * instructor in a real browser.
 *
 * In a real browser, Deep Linking's last step is cross-window JS messaging: the "Add
 * activity" page opens contentitem.php in a popup/iframe, and when the tool's deep-link
 * response lands back on contentitem_return.php, its JS calls
 * `parent.processContentItemReturnData(...)` on the ORIGINAL window, which then submits
 * Moodle's own "add activity" form. That handshake has no HTTP equivalent to curl - it's
 * how this whole tool was verified without browser automation available in this
 * environment (see README's "how this was actually verified").
 *
 * This script does, via Moodle's own supported add_moduleinfo() API, exactly what that
 * JS handshake would have driven a human to submit: takes the deep-link response JWT
 * (which DID travel over real HTTP, and IS verified for real against the tool's JWKS by
 * lti_convert_from_jwt()) and creates the course module from it.
 *
 * Usage: save a deep-link response JWT to /tmp/deeplink_jwt.txt, then run this inside the
 * moodle container.
 */
define('CLI_SCRIPT', true);
require('/bitnami/moodle/config.php');
require_once($CFG->dirroot . '/mod/lti/locallib.php');
require_once($CFG->dirroot . '/course/modlib.php');

global $DB, $USER;

$typeid = (int)($argv[1] ?? 1);
$courseid = (int)($argv[2] ?? 2);
$asuser = $argv[3] ?? 'admin';

$USER = $DB->get_record('user', ['username' => $asuser]);
\core\session\manager::set_user($USER);

$jwt = trim(file_get_contents('/tmp/deeplink_jwt.txt'));

// The real signature check: this fetches the TOOL's registered JWKS and verifies the
// deep-link response was actually signed by it, exactly as a browser-driven flow would.
$params = lti_convert_from_jwt($typeid, $jwt);
$config = lti_tool_configuration_from_content_item(
    $typeid, $params['lti_message_type'], $params['lti_version'], $params['oauth_consumer_key'], $params['content_items']
);

$course = get_course($courseid);
$moduleinfo = new stdClass();
$moduleinfo->modulename = 'lti';
$moduleinfo->module = $DB->get_field('modules', 'id', ['name' => 'lti']);
$moduleinfo->course = $courseid;
$moduleinfo->section = 0;
$moduleinfo->visible = 1;
$moduleinfo->visibleoncoursepage = 1;
$moduleinfo->groupmode = 0;
$moduleinfo->groupingid = 0;
$moduleinfo->cmidnumber = '';
$moduleinfo->availability = null;
$moduleinfo->completion = 0;
$moduleinfo->completionexpected = 0;
$moduleinfo->showdescription = 0;
foreach ($config as $key => $value) {
    $moduleinfo->$key = $value;
}
$moduleinfo->intro = $moduleinfo->introeditor['text'] ?? '';
$moduleinfo->introformat = $moduleinfo->introeditor['format'] ?? FORMAT_PLAIN;

$created = add_moduleinfo($moduleinfo, $course);
echo "cmid={$created->coursemodule}\n";
echo "lti_instance_id={$created->instance}\n";
