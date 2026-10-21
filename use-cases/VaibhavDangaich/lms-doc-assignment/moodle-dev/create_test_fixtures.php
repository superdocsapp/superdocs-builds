<?php
/**
 * Creates a course and an enrolled student, so there's something to launch into and
 * someone gradable to launch as. AGS specifically requires a gradable (Student-role) user -
 * launching as the site admin gets a bare 400 "Incorrect score received" from Moodle's own
 * AGS scores endpoint with no further explanation, because admins aren't gradable.
 *
 * Run inside the moodle container, same way as register_tool.php.
 */
define('CLI_SCRIPT', true);
require('/bitnami/moodle/config.php');
require_once($CFG->dirroot . '/user/lib.php');
require_once($CFG->libdir . '/enrollib.php');
require_once($CFG->dirroot . '/course/lib.php');

global $DB;

$course = $DB->get_record('course', ['shortname' => 'LTITEST']);
if (!$course) {
    $coursedata = new stdClass();
    $coursedata->fullname = 'LTI Test Course';
    $coursedata->shortname = 'LTITEST';
    $coursedata->category = 1;
    $coursedata->format = 'topics';
    $coursedata->numsections = 3;
    $coursedata->startdate = time();
    $coursedata->visible = 1;
    $course = create_course($coursedata);
}
echo "course_id={$course->id}\n";

$student = $DB->get_record('user', ['username' => 'student1']);
if (!$student) {
    $user = new stdClass();
    $user->username = 'student1';
    $user->password = 'Sup3rD0csTest!';
    $user->firstname = 'Sam';
    $user->lastname = 'Student';
    $user->email = 'student1@example.test';
    $user->confirmed = 1;
    $user->mnethostid = $CFG->mnet_localhost_id;
    $studentid = user_create_user($user, true, false);
} else {
    $studentid = $student->id;
}
echo "student_id={$studentid}\n";

$studentrole = $DB->get_record('role', ['shortname' => 'student']);
$enrolplugin = enrol_get_plugin('manual');
foreach (enrol_get_instances($course->id, true) as $inst) {
    if ($inst->enrol === 'manual') {
        $enrolplugin->enrol_user($inst, $studentid, $studentrole->id);
        break;
    }
}
echo "enrolled student1 in course {$course->id}\n";
