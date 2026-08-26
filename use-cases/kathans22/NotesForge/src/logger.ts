import { writeFile } from "node:fs/promises";

export interface LogEntry {
  timestamp: string;
  type: string;
  message?: string;
  data?: Record<string, unknown>;
}

export class Logger {
  private events: LogEntry[] = [];

  step(name: string): void {
    console.log(`\n[STEP] ${name}`);
  }

  info(msg: string): void {
    console.log(`[INFO] ${msg}`);
  }

  warn(msg: string): void {
    console.warn(`[WARN] ${msg}`);
  }

  error(msg: string): void {
    console.error(`[ERROR] ${msg}`);
  }

  success(msg: string): void {
    console.log(`[OK] ${msg}`);
  }

  record(entry: { type: string; message?: string; data?: Record<string, unknown> }): void {
    this.events.push({ timestamp: new Date().toISOString(), ...entry });
  }

  async flush(path = "run-log.json"): Promise<void> {
    await writeFile(path, JSON.stringify(this.events, null, 2), "utf8");
  }
}
