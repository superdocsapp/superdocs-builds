export class ChangelogError extends Error {
  constructor(message, code = 'INVALID_INPUT', exitCode = 10) {
    super(message);
    this.name = 'ChangelogError';
    this.code = code;
    this.exitCode = exitCode;
  }
}

export class InjectedFailure extends ChangelogError {
  constructor(checkpoint) {
    super(`deterministic interruption after ${checkpoint}`, 'INJECTED_INTERRUPTION', 12);
    this.checkpoint = checkpoint;
  }
}
