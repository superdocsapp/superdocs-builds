export type StageStatus = "ok" | "degraded" | "skipped" | "failed";

export type StageRecord = {
  stage: string;
  status: StageStatus;
  milliseconds: number;
  detail?: string;
};

export type Clock = () => number;

/**
 * Records how long each pipeline stage took and how it ended.
 *
 * Every stage is written down, including the ones that degraded, so a run can
 * report where the time went and which step stopped being able to do its job.
 */
export class StageRecorder {
  private readonly records: StageRecord[] = [];

  constructor(private readonly now: Clock = () => Date.now()) {}

  async run<T>(
    stage: string,
    work: () => Promise<T> | T
  ): Promise<{ ok: true; value: T } | { ok: false; error: unknown }> {
    const started = this.now();

    try {
      const value = await work();
      this.records.push({
        stage,
        status: "ok",
        milliseconds: this.now() - started
      });
      return { ok: true, value };
    } catch (error) {
      this.records.push({
        stage,
        status: "failed",
        milliseconds: this.now() - started,
        detail: error instanceof Error ? error.message : "unknown error"
      });
      return { ok: false, error };
    }
  }

  note(stage: string, status: StageStatus, detail?: string): void {
    this.records.push({ stage, status, milliseconds: 0, detail });
  }

  /** Rewrites the last record for a stage, used when a stage succeeded but degraded. */
  markDegraded(stage: string, detail: string): void {
    const record = [...this.records]
      .reverse()
      .find((candidate) => candidate.stage === stage);

    if (record) {
      record.status = "degraded";
      record.detail = detail;
    }
  }

  all(): StageRecord[] {
    return [...this.records];
  }

  totalMilliseconds(): number {
    return this.records.reduce(
      (total, record) => total + record.milliseconds,
      0
    );
  }
}
