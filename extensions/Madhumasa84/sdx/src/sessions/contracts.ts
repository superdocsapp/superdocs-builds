export interface SessionRecord {
  readonly id: string;
  readonly name: string;
  readonly documentId: string;
  readonly updatedAt: string;
}

export interface SessionStore {
  get(name: string): Promise<SessionRecord | undefined>;
  put(session: SessionRecord): Promise<void>;
}

