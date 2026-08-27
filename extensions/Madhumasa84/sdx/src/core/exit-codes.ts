export const EXIT_CODES = {
  success: 0,
  unchanged: 2,
  awaitingApproval: 3,
  rejected: 4,
  invalidInput: 10,
  authenticationFailure: 20,
  rateLimitFailure: 21,
  apiFailure: 22,
  uploadReadFailure: 23,
  exportWriteFailure: 24,
  schemaMismatch: 25,
  interrupted: 130,
} as const;

export type ExitCode = (typeof EXIT_CODES)[keyof typeof EXIT_CODES];

