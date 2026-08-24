/**
 * A small stand-in for the parts of the Obsidian API this plugin actually uses,
 * backed by a real folder on disk. It exists so the end-to-end test drives the
 * real plugin code against real files, with no Obsidian and no network.
 */
import { existsSync, mkdirSync, readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { dirname, join, relative, sep } from "node:path";

if (!(globalThis as Record<string, unknown>).window) (globalThis as Record<string, unknown>).window = globalThis;

export interface RequestUrlParam {
  url: string;
  method?: string;
  headers?: Record<string, string>;
  body?: string;
  throw?: boolean;
}

export interface RequestUrlResponse {
  status: number;
  text: string;
  json: unknown;
  arrayBuffer: ArrayBuffer;
}

export type RequestHandler = (request: RequestUrlParam) => Promise<Partial<RequestUrlResponse> & { status: number }>;

let handler: RequestHandler = async () => {
  throw new Error("the test made an unexpected network call");
};

export const requests: RequestUrlParam[] = [];

export function setRequestHandler(next: RequestHandler): void {
  handler = next;
  requests.length = 0;
}

export async function requestUrl(request: RequestUrlParam): Promise<RequestUrlResponse> {
  requests.push(request);
  const partial = await handler(request);
  const text = partial.text ?? (partial.json === undefined ? "" : JSON.stringify(partial.json));
  return {
    status: partial.status,
    text,
    get json() {
      return partial.json ?? JSON.parse(text);
    },
    arrayBuffer: partial.arrayBuffer ?? new TextEncoder().encode(text).buffer,
  };
}

export class TFile {
  constructor(readonly vaultRoot: string, readonly path: string) {}
  get name(): string {
    return this.path.split("/").pop() ?? this.path;
  }
  get basename(): string {
    return this.name.replace(/\.[^.]+$/, "");
  }
  get extension(): string {
    return this.name.includes(".") ? this.name.split(".").pop()! : "";
  }
  get absolute(): string {
    return join(this.vaultRoot, this.path);
  }
  get stat(): { mtime: number; ctime: number; size: number } {
    const info = statSync(this.absolute);
    return { mtime: info.mtimeMs, ctime: info.birthtimeMs, size: info.size };
  }
}

type VaultEvent = "modify" | "create" | "delete";

export class Vault {
  private readonly listeners = new Map<VaultEvent, Array<(file: TFile) => void>>();

  constructor(readonly root: string) {}

  on(event: VaultEvent, callback: (file: TFile) => void): { event: VaultEvent; callback: (file: TFile) => void } {
    const existing = this.listeners.get(event) ?? [];
    existing.push(callback);
    this.listeners.set(event, existing);
    return { event, callback };
  }

  /** Test helper: write a file the way a person editing in Obsidian would. */
  emitWrite(path: string, content: string): void {
    const file = new TFile(this.root, path);
    mkdirSync(dirname(file.absolute), { recursive: true });
    writeFileSync(file.absolute, content, "utf8");
    for (const callback of this.listeners.get("modify") ?? []) callback(file);
  }

  getMarkdownFiles(): TFile[] {
    const files: TFile[] = [];
    const walk = (directory: string): void => {
      for (const entry of readdirSync(directory, { withFileTypes: true })) {
        const full = join(directory, entry.name);
        if (entry.isDirectory()) walk(full);
        else if (entry.name.endsWith(".md")) files.push(new TFile(this.root, relative(this.root, full).split(sep).join("/")));
      }
    };
    walk(this.root);
    return files;
  }

  getFileByPath(path: string): TFile | null {
    const file = new TFile(this.root, path);
    return existsSync(file.absolute) ? file : null;
  }

  async read(file: TFile): Promise<string> {
    return readFileSync(file.absolute, "utf8");
  }

  async cachedRead(file: TFile): Promise<string> {
    return this.read(file);
  }

  async modify(file: TFile, data: string): Promise<void> {
    writeFileSync(file.absolute, data, "utf8");
  }

  async append(file: TFile, data: string): Promise<void> {
    writeFileSync(file.absolute, readFileSync(file.absolute, "utf8") + data, "utf8");
  }

  async process(file: TFile, fn: (data: string) => string): Promise<string> {
    const next = fn(readFileSync(file.absolute, "utf8"));
    writeFileSync(file.absolute, next, "utf8");
    return next;
  }
}

export class App {
  readonly workspace = { activeFile: null as TFile | null, getActiveFile: (): TFile | null => this.workspace.activeFile };
  constructor(readonly vault: Vault) {}
}

export const notices: string[] = [];

export class Notice {
  constructor(message: string) {
    notices.push(message);
  }
}

export class Plugin {
  private data: unknown = null;
  readonly intervals: Array<ReturnType<typeof setInterval>> = [];
  readonly commands: Array<{ id: string; name: string; callback: () => unknown }> = [];

  constructor(readonly app: App, readonly manifest: Record<string, unknown> = {}) {}

  addStatusBarItem(): { setText: (value: string) => void; setAttr: (name: string, value: string) => void; text: string } {
    const item = { text: "", setText(value: string) { item.text = value; }, setAttr() {} };
    return item as never;
  }
  addSettingTab(): void {}
  addCommand(command: { id: string; name: string; callback: () => unknown }): void {
    this.commands.push(command);
  }
  registerEvent(): void {}
  registerInterval(id: ReturnType<typeof setInterval>): number {
    this.intervals.push(id);
    if (typeof id === "object" && id && "unref" in id) (id as { unref: () => void }).unref();
    return 0 as never;
  }
  async loadData(): Promise<unknown> {
    return this.data;
  }
  async saveData(data: unknown): Promise<void> {
    this.data = data;
  }
}

export class Modal {
  constructor(readonly app: App) {}
  open(): void {}
  close(): void {}
}

export class PluginSettingTab {
  constructor(readonly app: App, readonly plugin: unknown) {}
}

export class Setting {
  constructor(readonly containerEl: unknown) {}
  setName(): this { return this; }
  setDesc(): this { return this; }
  setHeading(): this { return this; }
  addText(): this { return this; }
  addToggle(): this { return this; }
  addSlider(): this { return this; }
  addDropdown(): this { return this; }
}
