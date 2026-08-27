import {
  OutputEnvelopeSchema,
  type OutputEnvelope,
} from '../core/output.js';

export interface TextSink {
  write(text: string): void;
}

export class HumanPresenter {
  public constructor(
    private readonly stdout: TextSink = process.stdout,
    private readonly stderr: TextSink = process.stderr,
  ) {}

  public result(message: string): void {
    this.stdout.write(`${message}\n`);
  }

  public diagnostic(message: string): void {
    this.stderr.write(`${message}\n`);
  }
}

export class JsonPresenter {
  private emitted = false;

  public constructor(private readonly stdout: TextSink = process.stdout) {}

  public result(candidate: OutputEnvelope): void {
    if (this.emitted) {
      throw new Error('JSON output has already been emitted');
    }

    const envelope = OutputEnvelopeSchema.parse(candidate);
    this.stdout.write(`${JSON.stringify(envelope)}\n`);
    this.emitted = true;
  }
}

