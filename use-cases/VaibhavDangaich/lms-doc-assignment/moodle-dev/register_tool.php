<?php
/**
 * Registers this LTI 1.3 tool in the local test Moodle, correctly on the first try -
 * everything below was learned the hard way (see README's "what this cost to get right")
 * and is folded in here so nobody has to rediscover it.
 *
 * Run inside the moodle container:
 *   docker compose -f moodle-dev/docker-compose.yml exec moodle php /path/to/register_tool.php
 * (copy this file into the container first, e.g. via `docker cp`)
 */
define('CLI_SCRIPT', true);
require('/bitnami/moodle/config.php');
require_once($CFG->dirroot . '/mod/lti/locallib.php');

// Two different hostnames are needed because two different callers resolve "the tool":
//  - a real browser (or, headless, this script's sibling driver) needs a URL IT can reach -
//    localhost, since that's where the tool actually listens on the host machine.
//  - Moodle's own PHP backend, running INSIDE this container, needs a URL that resolves
//    from inside a container - host.docker.internal - for the one call that's genuinely
//    server-to-server: fetching the tool's JWKS to verify a signature.
// Splitting these was the single biggest source of "State not found" / "Invalid request"
// errors while getting this working: every browser-facing URL must agree on one hostname.
$browser_facing_base = 'http://localhost:9001';
$server_to_server_base = 'http://host.docker.internal:9001';

$type = new stdClass();
$type->state = LTI_TOOL_STATE_CONFIGURED;

$config = new stdClass();
$config->lti_typename = 'SuperDocs Document Review';
$config->lti_toolurl = "$browser_facing_base/launch/";
$config->lti_description = 'Launches a SuperDocs track-changes review for an assigned document.';
$config->lti_ltiversion = LTI_VERSION_1P3;
$config->lti_keytype = LTI_JWK_KEYSET;
$config->lti_publickeyset = "$server_to_server_base/jwks/";
$config->lti_initiatelogin = "$browser_facing_base/login/";
// Both are registered: the deep-link CONTENT ITEM's own resource URL (built by Flask's
// url_for(_external=True), which reflects whatever Host header reached the tool - in
// practice this driver's own requests, i.e. localhost) must exactly string-match one of
// these, or Moodle's auth.php refuses the launch with a bare "Invalid request".
$config->lti_redirectionuris = "$browser_facing_base/launch/\n$server_to_server_base/launch/";
$config->lti_contentitem = 1;
$config->lti_toolurl_ContentItemSelectionRequest = "$browser_facing_base/launch/";
$config->lti_coursevisible = LTI_COURSEVISIBLE_ACTIVITYCHOOSER;
$config->lti_sendname = LTI_SETTING_ALWAYS;
$config->lti_sendemailaddr = LTI_SETTING_ALWAYS;
$config->lti_acceptgrades = LTI_SETTING_ALWAYS;
$config->lti_forcessl = 0;
// Without this, Moodle launches the tool in legacy LTI 1.1 "basic outcomes" mode instead
// of LTI Advantage - the id_token simply never carries an AGS claim, and there is no
// error message pointing at this setting anywhere. Found by decoding a launch JWT and
// noticing lti-ags/claim/endpoint was silently absent.
$config->ltiservice_gradesynchronization = 2; // gradebookservices::GRADEBOOKSERVICES_FULL

// Moodle's outbound-request firewall (Site admin > Security > HTTP security) blocks any
// port outside {80, 443} by default - an SSRF protection that also, incidentally, blocks
// this tool's port 9001 from ever being reached for the JWKS fetch or the AGS token/score
// calls, failing with "$jwks must be of type array, null given" (JWKS) or a bare curl
// failure (AGS) that names neither the real cause nor 9001. Local test instance only -
// never disable this on a real deployment.
set_config('curlsecurityallowedport', "80\n443\n9001");

// The same firewall also blocks-by-default any destination IP in common private-network
// ranges (192.168.0.0/16 among them) - and Docker Desktop's host.docker.internal resolves
// to a gateway IP inside exactly that range (192.168.65.x on this machine; it can differ
// per install and can change after a Docker VM rebuild). With the port now allowed, the
// symptom moves from a PHP type error to a silent `download_file_content()` returning
// false - no exception, no log line naming the host as the reason. Local test instance
// only - never disable this on a real deployment.
set_config('curlsecurityblockedhosts', '');

$id = lti_add_type($type, $config);
$saved = $DB->get_record('lti_types', ['id' => $id]);
echo "tool_id={$id}\n";
echo "clientid={$saved->clientid}\n";
echo "wwwroot={$CFG->wwwroot}\n";
echo "\nNext: put clientid + wwwroot (as the issuer) + deployment_ids=[\"1\"] into configs/tool.json.\n";
