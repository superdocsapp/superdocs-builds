import fs from 'fs';
import path from 'path';
import { BatchRunCheckpoint, ClientBatchRecord, StageLog } from '../types';

const DATA_DIR = path.join(process.cwd(), 'data');
const DB_FILE = path.join(DATA_DIR, 'db.json');

export interface AuditTrailEntry {
  id: string;
  timestamp: string;
  actor: string;
  action: string;
  clientRecordId?: string;
  documentId?: string;
  version?: number;
  details: string;
}

export interface PersistentDataStore {
  checkpoint: BatchRunCheckpoint | null;
  auditLogs: AuditTrailEntry[];
  exportedFiles: {
    id: string;
    clientRecordId: string;
    exportType: string;
    exportedAt: string;
    exportedBy: string;
    content: string;
  }[];
}

class PersistenceService {
  private data: PersistentDataStore = {
    checkpoint: null,
    auditLogs: [],
    exportedFiles: []
  };

  constructor() {
    this.ensureDirectory();
    this.loadFromDisk();
  }

  private ensureDirectory() {
    try {
      if (!fs.existsSync(DATA_DIR)) {
        fs.mkdirSync(DATA_DIR, { recursive: true });
      }
    } catch (err) {
      console.warn('Persistence directory creation warning:', err);
    }
  }

  public loadFromDisk(): PersistentDataStore {
    try {
      if (fs.existsSync(DB_FILE)) {
        const raw = fs.readFileSync(DB_FILE, 'utf-8');
        this.data = JSON.parse(raw);
      }
    } catch (err) {
      console.error('Failed to load persistence store from disk:', err);
    }
    return this.data;
  }

  public saveToDisk(): boolean {
    try {
      this.ensureDirectory();
      fs.writeFileSync(DB_FILE, JSON.stringify(this.data, null, 2), 'utf-8');
      return true;
    } catch (err) {
      console.error('Failed to save persistence store to disk:', err);
      return false;
    }
  }

  public getCheckpoint(): BatchRunCheckpoint | null {
    return this.data.checkpoint;
  }

  public saveCheckpoint(checkpoint: BatchRunCheckpoint): void {
    this.data.checkpoint = checkpoint;
    this.saveToDisk();
  }

  public addAuditEntry(entry: Omit<AuditTrailEntry, 'id' | 'timestamp'>): AuditTrailEntry {
    const fullEntry: AuditTrailEntry = {
      id: `audit-${Date.now()}-${Math.random().toString(36).substring(2, 7)}`,
      timestamp: new Date().toISOString(),
      ...entry
    };
    this.data.auditLogs.unshift(fullEntry);
    this.saveToDisk();
    return fullEntry;
  }

  public getAuditTrail(): AuditTrailEntry[] {
    return this.data.auditLogs;
  }

  public recordExport(clientRecordId: string, exportType: string, exportedBy: string, content: string) {
    const record = {
      id: `export-${Date.now()}`,
      clientRecordId,
      exportType,
      exportedAt: new Date().toISOString(),
      exportedBy,
      content
    };
    this.data.exportedFiles.push(record);
    this.addAuditEntry({
      actor: exportedBy,
      action: 'EXPORT_DOCUMENT',
      clientRecordId,
      details: `Exported ${exportType} for client record ${clientRecordId}`
    });
    this.saveToDisk();
    return record;
  }

  public getExportHistory() {
    return this.data.exportedFiles;
  }
}

export const persistenceService = new PersistenceService();
