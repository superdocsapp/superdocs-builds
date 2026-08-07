import { EXIT_CODES, type ExitCode } from '../core/exit-codes.js';
import type { HumanPresenter } from '../presentation/output.js';

export function reportUnimplemented(
  command: string,
  presenter: HumanPresenter,
): ExitCode {
  presenter.diagnostic(
    `sdx: ${command} is not implemented in the current stage; no document was changed.`,
  );
  return EXIT_CODES.invalidInput;
}

