const controllers = new Set<AbortController>();
let interrupted = false;

export function installEarlyInterruptLatch(): () => void {
  const handler = (): void => {
    interrupted = true;
    for (const controller of controllers) controller.abort(new DOMException('Aborted', 'AbortError'));
  };
  process.on('SIGINT', handler);
  return () => process.removeListener('SIGINT', handler);
}

export function commandAbortController(): AbortController {
  const controller = new AbortController();
  controllers.add(controller);
  if (interrupted) controller.abort(new DOMException('Aborted', 'AbortError'));
  return controller;
}
