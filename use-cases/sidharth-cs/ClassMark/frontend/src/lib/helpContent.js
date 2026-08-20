// Help/About content as pure data — rendered by HelpPopover and verified
// by the node:test suite (no DOM needed). Wording is deliberately honest:
// no grading, plagiarism, fact-checking, or guarantee claims.

export const HELP_TITLE = 'How Classmark works'

export const HELP_INTRO =
  'Classmark brings AI-assisted document review into the Google Classroom ' +
  'assignment workflow. Your student’s submitted document is reviewed, you ' +
  'control which suggestions are accepted, and the reviewed file is returned ' +
  'to the same Classroom submission.'

export const HELP_SECTIONS = [
  {
    n: '1',
    title: 'SuperDocs review',
    body:
      'The submitted document is sent to SuperDocs for an automated review ' +
      'pass. Nothing is applied to the student’s document without your ' +
      'approval.',
  },
  {
    n: '2',
    title: 'You decide',
    body:
      'Each proposed change is shown as an Original → Suggested pair. ' +
      'Approve accepts a proposed edit for the reviewed document; Reject ' +
      'leaves that part of the student’s work unchanged. You can approve ' +
      'some suggestions and reject others — you stay in control.',
  },
  {
    n: '3',
    title: 'After approval',
    body:
      'Your decisions are sent back to SuperDocs, which generates the ' +
      'reviewed document. The reviewed DOCX is then exported. The original ' +
      'document is not silently replaced.',
  },
  {
    n: '4',
    title: 'Back to Classroom',
    body:
      'The reviewed document is uploaded to Google Drive, attached back to ' +
      'the SAME Classroom submission, and the submission is returned to the ' +
      'student. The workflow verifies that the reviewed file remains ' +
      'attached after return.',
  },
]

export const HELP_WORKFLOW = [
  'Classroom submission',
  'SuperDocs review',
  'Your approval',
  'Reviewed document',
  'Google Drive',
  'Same Classroom submission',
  'Returned to student',
]

export const HELP_EXAMPLES_TITLE = 'What can be reviewed?'

export const HELP_EXAMPLES = [
  'Grammar and spelling',
  'Punctuation and sentence structure',
  'Clarity, concision, and awkward wording',
  'Consistency and style according to your instruction',
  'Other document-editing criteria in the review instruction',
]

export const HELP_REVIEW_TYPES_TITLE = 'Review types'

export const HELP_REVIEW_TYPES = [
  'Proofreading — grammar, spelling, punctuation and usage',
  'Writing Quality — clarity, structure and flow',
  'Academic Writing — academic style and coherence',
  'Custom — your own review instructions, with the same teacher approval safeguards',
]

export const HELP_REVIEW_DEPTH_TITLE = 'Review depth'

export const HELP_REVIEW_DEPTH =
  'Quick is for straightforward writing tasks. Standard is a well-rounded choice for most student work. Thorough uses a deeper review configuration for more involved writing tasks.'

export const HELP_HONESTY =
  'AI suggestions are recommendations. Review them before approving.'
