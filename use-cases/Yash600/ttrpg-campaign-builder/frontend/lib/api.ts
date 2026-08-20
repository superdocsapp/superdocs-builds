// lib/api.ts -- thin fetch wrapper around the FastAPI backend, v2.
// Every function here maps 1:1 to an endpoint in backend/main.py. v2 has no
// auto-ingestion: every Campaign starts empty, and every Document/
// Character/NPC/Location is created or imported by the user through these
// calls.

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8001";

export type DocType = "campaign_bible" | "character" | "session_log" | "npc" | "location" | "other";
export type VersionStatus = "draft" | "proposed" | "active" | "archived";
export type DocOrigin = "created" | "imported" | "generated";
export type LinkRelationshipType = "belongs_to_campaign" | "references" | "related_to" | "describes" | "appears_in";
export type LinkStatus = "synced" | "stale" | "pending_review";
export type IllustrationEntityType = "character" | "npc" | "location";
export type ChatRole = "user" | "assistant" | "system";

export interface Campaign {
  id: string;
  name: string;
  description: string;
  genre: string;
  setting: string;
  cover_image: string | null;
  created_at: string;
  updated_at: string;
  document_count?: number;
  character_count?: number;
  npc_count?: number;
  location_count?: number;
}

export interface DocumentVersionOut {
  id: string;
  document_id: string;
  version_number: number;
  status: VersionStatus;
  change_summary: string;
  created_by: string;
  pending_job_id: string | null;
  pending_change_id: string | null;
  created_at: string;
  content_html?: string;
  content_text?: string;
}

export interface DocumentOut {
  id: string;
  campaign_id: string;
  doc_type: DocType;
  title: string;
  description: string;
  origin: DocOrigin;
  superdocs_document_id: string;
  superdocs_session_id: string;
  active_version_id: string | null;
  created_at: string;
  updated_at: string;
  active_version?: DocumentVersionOut;
  active_version_number?: number | null;
  broken_references?: string[];
  entity_type?: IllustrationEntityType | null;
  entity_id?: string | null;
  entity_image_url?: string | null;
}

export interface DocumentLinkOut {
  id: string;
  source_document_id: string;
  target_document_id: string;
  relationship_type: LinkRelationshipType;
  note: string;
  synced_version_number: number;
  status: LinkStatus;
  created_at: string;
  last_checked_at: string;
}

export interface CharacterOut {
  id: string;
  campaign_id: string;
  document_id: string;
  name: string;
  race: string;
  char_class: string;
  level: number | null;
  image_url: string | null;
  created_at: string;
}

export interface NPCOut {
  id: string;
  campaign_id: string;
  document_id: string;
  name: string;
  role: string;
  related_location_id: string | null;
  image_url: string | null;
  created_at: string;
}

export interface LocationOut {
  id: string;
  campaign_id: string;
  document_id: string;
  name: string;
  image_url: string | null;
  created_at: string;
}

export interface IllustrationOut {
  id: string;
  campaign_id: string;
  entity_type: IllustrationEntityType;
  entity_id: string;
  prompt: string;
  provider?: string;
  superdocs_image_url: string;
  local_image_url?: string | null;
  embedded_in_document_id: string | null;
  embedded: boolean;
  created_at: string;
}

export interface ChatMessageOut {
  id: string;
  chat_session_id: string;
  role: ChatRole;
  content: string;
  result_document_id: string | null;
  result_version_id: string | null;
  created_at: string;
}

export interface ChangeEventOut {
  id: string;
  event_type: string;
  timestamp: string;
  campaign_id: string | null;
  document_id: string | null;
  link_id: string | null;
  actor: string;
  description: string;
  approved: boolean | null;
}

export interface AssistantDraft {
  content_html: string;
  suggested_title: string;
  suggested_doc_type: DocType | "other";
  chat_message: ChatMessageOut;
}

export interface ChatEditResult {
  status: "awaiting_approval" | "completed";
  version?: DocumentVersionOut;
  pending_change_count?: number;
  message?: string;
  chat_message: ChatMessageOut;
}

export interface ValidateLinkReport {
  link_id: string;
  source_document_id: string;
  target_document_id: string;
  relationship_type: LinkRelationshipType;
  synced_version_number: number;
  current_version_number: number | null;
  stale: boolean;
}

export interface ChecklistItem {
  ok: boolean;
  label: string;
  detail: string;
}

export interface BrokenReference {
  document_id: string;
  document_title: string;
  ref_title: string;
}

export interface DuplicateTitle {
  doc_type: DocType;
  title: string;
  count: number;
}

export interface UncoveredIllustration {
  entity_type: IllustrationEntityType;
  name: string;
}

export interface ValidationReport {
  campaign_id: string;
  document_count: number;
  documents_missing_active_version: string[];
  total_links: number;
  stale_links: number;
  synced_links: number;
  coherent: boolean;
  links: ValidateLinkReport[];
  broken_references: BrokenReference[];
  duplicate_titles: DuplicateTitle[];
  uncovered_illustrations: UncoveredIllustration[];
  checklist: ChecklistItem[];
  ready: boolean;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: init?.body instanceof FormData ? init?.headers : { "Content-Type": "application/json", ...(init?.headers || {}) },
    cache: "no-store",
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || JSON.stringify(body);
    } catch {
      // ignore
    }
    throw new Error(`${res.status} ${detail}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  // -- campaigns --------------------------------------------------------
  listCampaigns: () => request<Campaign[]>("/campaigns"),
  createCampaign: (body: { name: string; description?: string; genre?: string; setting?: string }) =>
    request<Campaign>("/campaigns", { method: "POST", body: JSON.stringify(body) }),
  getCampaign: (id: string) => request<Campaign>(`/campaigns/${id}`),
  listCampaignDocuments: (id: string, opts?: { q?: string; docType?: DocType | ""; sort?: "name" | "type" | "updated_at" }) => {
    const params = new URLSearchParams();
    if (opts?.q) params.set("q", opts.q);
    if (opts?.docType) params.set("doc_type", opts.docType);
    if (opts?.sort) params.set("sort", opts.sort);
    const qs = params.toString();
    return request<DocumentOut[]>(`/campaigns/${id}/documents${qs ? `?${qs}` : ""}`);
  },
  patchCampaign: (id: string, body: { name?: string; description?: string; genre?: string; setting?: string }) =>
    request<Campaign>(`/campaigns/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteCampaign: (id: string) =>
    request<{ status: string; campaign_id: string; campaign_name: string; deleted_documents: number }>(
      `/campaigns/${id}`,
      { method: "DELETE" }
    ),
  uploadCampaignCoverImage: (id: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<Campaign>(`/campaigns/${id}/cover-image`, { method: "POST", body: form });
  },
  listCharacters: (id: string) => request<CharacterOut[]>(`/campaigns/${id}/characters`),
  listNPCs: (id: string) => request<NPCOut[]>(`/campaigns/${id}/npcs`),
  listLocations: (id: string) => request<LocationOut[]>(`/campaigns/${id}/locations`),
  listCampaignLinks: (id: string) => request<DocumentLinkOut[]>(`/campaigns/${id}/links`),
  listCampaignEvents: (id: string) => request<ChangeEventOut[]>(`/campaigns/${id}/events`),
  listCampaignIllustrations: (id: string) => request<IllustrationOut[]>(`/campaigns/${id}/illustrations`),
  validateCampaign: (id: string) => request<ValidationReport>(`/campaigns/${id}/validate`),

  // -- documents ----------------------------------------------------------
  createDocument: (
    campaignId: string,
    body: { doc_type: DocType; title: string; description?: string; content_html?: string }
  ) => request<DocumentOut>(`/campaigns/${campaignId}/documents`, { method: "POST", body: JSON.stringify(body) }),
  importDocument: (campaignId: string, file: File, docType: DocType, title: string, description = "") => {
    const form = new FormData();
    form.append("doc_type", docType);
    form.append("title", title);
    form.append("description", description);
    form.append("file", file);
    return request<DocumentOut>(`/campaigns/${campaignId}/documents/import`, { method: "POST", body: form });
  },
  getDocument: (id: string) => request<DocumentOut>(`/documents/${id}`),
  listDocumentVersions: (id: string) => request<DocumentVersionOut[]>(`/documents/${id}/versions`),
  getDocumentVersion: (documentId: string, versionId: string) =>
    request<DocumentVersionOut>(`/documents/${documentId}/versions/${versionId}`),
  patchDocument: (id: string, body: { title?: string; description?: string; doc_type?: DocType }) =>
    request<DocumentOut>(`/documents/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteDocument: (id: string) => request<{ status: string }>(`/documents/${id}`, { method: "DELETE" }),
  saveDocument: (id: string, content_html: string, change_summary = "Manual edit") =>
    request<{ document: DocumentOut; broken_references: string[]; resolved_reference_count: number }>(
      `/documents/${id}/save`,
      { method: "POST", body: JSON.stringify({ content_html, change_summary }) }
    ),
  relinkDocumentReferences: (id: string) =>
    request<{ document: DocumentOut; changed: boolean; resolved_reference_count: number; broken_references: string[] }>(
      `/documents/${id}/relink-references`,
      { method: "POST" }
    ),
  relinkCampaignReferences: (campaignId: string) =>
    request<{ documents_scanned: number; documents_updated: number; total_resolved_references: number; total_broken_references: number }>(
      `/campaigns/${campaignId}/relink-references`,
      { method: "POST" }
    ),

  // -- chat / editing lifecycle -------------------------------------------
  chatEditDocument: (documentId: string, message: string) =>
    request<ChatEditResult>(`/documents/${documentId}/chat`, { method: "POST", body: JSON.stringify({ message }) }),
  listChatMessages: (documentId: string) => request<ChatMessageOut[]>(`/documents/${documentId}/chat/messages`),
  approveVersion: (documentId: string, versionId: string) =>
    request<{ document: DocumentOut; links_flagged_stale: number }>(
      `/documents/${documentId}/versions/${versionId}/approve`,
      { method: "POST" }
    ),
  rejectVersion: (documentId: string, versionId: string) =>
    request<{ status: string }>(`/documents/${documentId}/versions/${versionId}/reject`, { method: "POST" }),

  // -- characters / npcs / locations ---------------------------------------
  createCharacter: (
    campaignId: string,
    body: { name: string; race?: string; char_class?: string; level?: number; description?: string; content_html?: string }
  ) =>
    request<{ character: CharacterOut; document: DocumentOut }>(`/campaigns/${campaignId}/characters`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  createNPC: (
    campaignId: string,
    body: { name: string; role?: string; related_location_id?: string | null; description?: string; content_html?: string }
  ) =>
    request<{ npc: NPCOut; document: DocumentOut }>(`/campaigns/${campaignId}/npcs`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  createLocation: (campaignId: string, body: { name: string; description?: string; content_html?: string }) =>
    request<{ location: LocationOut; document: DocumentOut }>(`/campaigns/${campaignId}/locations`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  // -- links --------------------------------------------------------------
  createLink: (body: {
    source_document_id: string;
    target_document_id: string;
    relationship_type: LinkRelationshipType;
    note?: string;
  }) => request<DocumentLinkOut>("/links", { method: "POST", body: JSON.stringify(body) }),
  resyncLink: (linkId: string) => request<DocumentLinkOut>(`/links/${linkId}/resync`, { method: "POST" }),
  deleteLink: (linkId: string) => request<{ status: string }>(`/links/${linkId}`, { method: "DELETE" }),

  // -- illustrations --------------------------------------------------------
  generateIllustration: (body: {
    entity_type: IllustrationEntityType;
    entity_id: string;
    prompt: string;
    embed?: boolean;
    width?: number;
    height?: number;
  }) => request<IllustrationOut>("/illustrations", { method: "POST", body: JSON.stringify(body) }),
  uploadIllustration: (body: {
    entity_type: IllustrationEntityType;
    entity_id: string;
    prompt?: string;
    embed?: boolean;
    file: File;
  }) => {
    const form = new FormData();
    form.append("entity_type", body.entity_type);
    form.append("entity_id", body.entity_id);
    form.append("prompt", body.prompt || "");
    form.append("embed", body.embed === false ? "false" : "true");
    form.append("file", body.file);
    return request<IllustrationOut>("/illustrations/upload", { method: "POST", body: form });
  },

  // -- campaign assistant -----------------------------------------------
  campaignAssistant: (campaignId: string, message: string) =>
    request<AssistantDraft>(`/campaigns/${campaignId}/assistant`, { method: "POST", body: JSON.stringify({ message }) }),
  listAssistantMessages: (campaignId: string) => request<ChatMessageOut[]>(`/campaigns/${campaignId}/assistant/messages`),

  // -- export ---------------------------------------------------------------
  exportDocumentUrl: (documentId: string, format: string) => `${API_BASE}/documents/${documentId}/export?format=${format}`,
  exportCampaignUrl: (campaignId: string, format: string) => `${API_BASE}/campaigns/${campaignId}/export?format=${format}`,
};

export const DOC_TYPE_LABELS: Record<DocType, string> = {
  campaign_bible: "Campaign Bible",
  character: "Character Sheet",
  session_log: "Session Log",
  npc: "NPC",
  location: "Location",
  other: "Document",
};

export const DOC_TYPE_BADGE_CLASS: Record<DocType, string> = {
  campaign_bible: "bible",
  character: "character",
  session_log: "session_log",
  npc: "npc",
  location: "location",
  other: "entity",
};

export const STATUS_LABELS: Record<LinkStatus, string> = {
  synced: "Synced",
  stale: "Stale",
  pending_review: "Pending review",
};

export const RELATIONSHIP_LABELS: Record<LinkRelationshipType, string> = {
  belongs_to_campaign: "belongs to campaign",
  references: "references",
  related_to: "is related to",
  describes: "describes",
  appears_in: "appears in",
};
