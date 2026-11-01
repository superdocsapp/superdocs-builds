import { redact } from '../evidence/redact.js';

export type LogLevel = 'debug' | 'info' | 'warn' | 'error';

const LEVEL_RANK: Record<LogLevel, number> = { debug: 0, info: 1, warn: 2, error: 3 };
const CONTENT_KEYS = ['document', 'content', 'beforeContent', 'afterContent', 'resultDocument', 'instructionText'];

export interface LogEvent {
  event: string;
  correlationId?: string;
  [key: string]: unknown;
}

export class Logger {
  constructor(
    private readonly level: LogLevel = 'info',
    private readonly logDocumentContent = false,
  ) {}

  debug(evt: LogEvent): void {
    this.emit('debug', evt);
  }
  info(evt: LogEvent): void {
    this.emit('info', evt);
  }
  warn(evt: LogEvent): void {
    this.emit('warn', evt);
  }
  error(evt: LogEvent): void {
    this.emit('error', evt);
  }

  private emit(level: LogLevel, evt: LogEvent): void {
    if (LEVEL_RANK[level] < LEVEL_RANK[this.level]) return;
    const scrubbed = this.logDocumentContent ? evt : omitDocumentContent(evt);
    const line = { level, ts: new Date().toISOString(), ...redact(scrubbed) };
    const text = JSON.stringify(line);
    if (level === 'error' || level === 'warn') console.error(text);
    else console.log(text);
  }
}

function omitDocumentContent(evt: LogEvent): LogEvent {
  const out: LogEvent = { ...evt };
  for (const key of CONTENT_KEYS) {
    if (key in out) out[key] = '[omitted — set AEGIS_LOG_DOCUMENT_CONTENT=true to include document text in logs]';
  }
  return out;
}
