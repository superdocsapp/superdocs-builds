"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  api,
  Campaign,
  DocumentOut,
  CharacterOut,
  NPCOut,
  LocationOut,
  DocumentLinkOut,
  IllustrationOut,
  ValidationReport,
  ChangeEventOut,
  ChatMessageOut,
  AssistantDraft,
  DocType,
  LinkRelationshipType,
  IllustrationEntityType,
  DOC_TYPE_LABELS,
  DOC_TYPE_BADGE_CLASS,
  RELATIONSHIP_LABELS,
} from "@/lib/api";
import {
  IconBook,
  IconUsers,
  IconScroll,
  IconMap,
  IconLayers,
  IconEyeCheck,
  IconImage,
  IconDownload,
  IconCheckCircle,
  IconAlertTriangle,
  IconSparkle,
  IconPencil,
  IconTrash,
  IconSearch,
  IconUpload,
  IconClock,
} from "../../icons";

type Tab = "documents" | "characters" | "npcs" | "locations" | "links" | "illustrations" | "coherence" | "assistant";

const TABS: { id: Tab; label: string; Icon: any }[] = [
  { id: "documents", label: "Documents", Icon: IconBook },
  { id: "characters", label: "Characters", Icon: IconUsers },
  { id: "npcs", label: "NPCs", Icon: IconScroll },
  { id: "locations", label: "Locations", Icon: IconMap },
  { id: "links", label: "Links", Icon: IconLayers },
  { id: "illustrations", label: "Illustrations", Icon: IconImage },
  { id: "coherence", label: "Coherence", Icon: IconEyeCheck },
  { id: "assistant", label: "Assistant", Icon: IconSparkle },
];

export default function CampaignWorkspacePage() {
  const params = useParams();
  const router = useRouter();
  const campaignId = params.id as string;

  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [documents, setDocuments] = useState<DocumentOut[]>([]);
  const [characters, setCharacters] = useState<CharacterOut[]>([]);
  const [npcs, setNpcs] = useState<NPCOut[]>([]);
  const [locations, setLocations] = useState<LocationOut[]>([]);
  const [links, setLinks] = useState<DocumentLinkOut[]>([]);
  const [illustrations, setIllustrations] = useState<IllustrationOut[]>([]);
  const [validation, setValidation] = useState<ValidationReport | null>(null);
  const [events, setEvents] = useState<ChangeEventOut[]>([]);
  const [showActivity, setShowActivity] = useState(false);
  const [tab, setTab] = useState<Tab>("documents");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [editingCampaign, setEditingCampaign] = useState(false);
  const [ceName, setCeName] = useState("");
  const [ceGenre, setCeGenre] = useState("");
  const [ceSetting, setCeSetting] = useState("");
  const [ceDescription, setCeDescription] = useState("");
  const [ceCover, setCeCover] = useState<File | null>(null);
  const [ceBusy, setCeBusy] = useState(false);
  const [deletingCampaign, setDeletingCampaign] = useState(false);

  const refreshAll = useCallback(() => {
    if (!campaignId) return;
    api.getCampaign(campaignId).then(setCampaign).catch((e) => setError(String(e)));
    api.listCampaignDocuments(campaignId).then(setDocuments).catch(() => {});
    api.listCharacters(campaignId).then(setCharacters).catch(() => {});
    api.listNPCs(campaignId).then(setNpcs).catch(() => {});
    api.listLocations(campaignId).then(setLocations).catch(() => {});
    api.listCampaignLinks(campaignId).then(setLinks).catch(() => {});
    api.listCampaignIllustrations(campaignId).then(setIllustrations).catch(() => {});
    api.listCampaignEvents(campaignId).then(setEvents).catch(() => {});
    api.validateCampaign(campaignId).then(setValidation).catch(() => {});
  }, [campaignId]);

  useEffect(() => {
    refreshAll();
  }, [refreshAll]);

  const docById = useMemo(() => new Map(documents.map((d) => [d.id, d])), [documents]);

  function startEditCampaign() {
    if (!campaign) return;
    setCeName(campaign.name);
    setCeGenre(campaign.genre);
    setCeSetting(campaign.setting);
    setCeDescription(campaign.description);
    setCeCover(null);
    setEditingCampaign(true);
  }

  async function saveCampaignEdits(e: React.FormEvent) {
    e.preventDefault();
    setCeBusy(true);
    setError(null);
    try {
      await api.patchCampaign(campaignId, { name: ceName, genre: ceGenre, setting: ceSetting, description: ceDescription });
      if (ceCover) {
        await api.uploadCampaignCoverImage(campaignId, ceCover);
      }
      setEditingCampaign(false);
      refreshAll();
    } catch (e) {
      setError(String(e));
    } finally {
      setCeBusy(false);
    }
  }

  async function handleDeleteCampaign() {
    if (!campaign) return;
    if (
      !window.confirm(
        `Delete "${campaign.name}"? This permanently removes every document, character, NPC, location, and illustration in this campaign. This cannot be undone.`
      )
    ) {
      return;
    }
    setDeletingCampaign(true);
    setError(null);
    try {
      await api.deleteCampaign(campaignId);
      router.push("/");
    } catch (e) {
      setError(String(e));
      setDeletingCampaign(false);
    }
  }

  async function runValidate() {
    setBusy(true);
    try {
      setValidation(await api.validateCampaign(campaignId));
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  if (!campaign) {
    return <p>Loading campaign…</p>;
  }

  return (
    <>
      <section className="hero" style={{ padding: "28px 32px" }}>
        {campaign.cover_image && (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={campaign.cover_image} alt={campaign.name} style={{ width: "100%", maxHeight: 220, objectFit: "cover", borderRadius: 10, marginBottom: 16 }} />
        )}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
          <div>
            <div className="hero-eyebrow">CAMPAIGN</div>
            <h1>{campaign.name}</h1>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <button className="btn ghost" onClick={editingCampaign ? () => setEditingCampaign(false) : startEditCampaign}>
              {editingCampaign ? "Cancel" : "Edit details"}
            </button>
            <button className="btn ghost" onClick={handleDeleteCampaign} disabled={deletingCampaign} title="Delete campaign">
              <IconTrash size={14} /> {deletingCampaign ? "Deleting…" : "Delete campaign"}
            </button>
          </div>
        </div>

        {editingCampaign ? (
          <form className="card" onSubmit={saveCampaignEdits} style={{ display: "grid", gap: 10, marginTop: 10 }}>
            <label>
              Name
              <input value={ceName} onChange={(e) => setCeName(e.target.value)} required />
            </label>
            <label>
              Genre
              <input value={ceGenre} onChange={(e) => setCeGenre(e.target.value)} />
            </label>
            <label>
              Setting
              <input value={ceSetting} onChange={(e) => setCeSetting(e.target.value)} />
            </label>
            <label>
              Description
              <textarea value={ceDescription} onChange={(e) => setCeDescription(e.target.value)} rows={3} />
            </label>
            <label>
              Cover image (optional -- replaces current)
              <input type="file" accept="image/*" onChange={(e) => setCeCover(e.target.files?.[0] || null)} />
            </label>
            <button className="btn primary" type="submit" disabled={ceBusy}>
              {ceBusy ? "Saving…" : "Save campaign details"}
            </button>
          </form>
        ) : (
          <>
            {campaign.description && <p className="hero-lede">{campaign.description}</p>}
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 8 }}>
              {campaign.genre && <span className="badge bible">{campaign.genre}</span>}
              {campaign.setting && <span className="badge entity">{campaign.setting}</span>}
            </div>
          </>
        )}

        <div className="hero-stats">
          <div>
            <div className="hero-stat-value">{documents.length}</div>
            <div className="hero-stat-label">Documents</div>
          </div>
          <div>
            <div className="hero-stat-value">{characters.length + npcs.length}</div>
            <div className="hero-stat-label">People</div>
          </div>
          <div>
            <div className="hero-stat-value">{links.filter((l) => l.status === "stale").length}</div>
            <div className="hero-stat-label">Stale links</div>
          </div>
        </div>
      </section>

      {error && (
        <div className="card" style={{ borderColor: "var(--danger)", margin: "16px 0" }}>
          {error}
          <button className="btn ghost" onClick={() => setError(null)} style={{ marginLeft: 8 }}>
            dismiss
          </button>
        </div>
      )}

      <nav className="tabs" style={{ margin: "20px 0" }}>
        {TABS.map(({ id, label, Icon }) => (
          <a key={id} className={tab === id ? "active" : ""} onClick={() => setTab(id)} style={{ cursor: "pointer" }}>
            <Icon size={14} /> {label}
          </a>
        ))}
      </nav>

      <div style={{ display: "flex", justifyContent: "flex-end", alignItems: "center", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
        {validation && (
          <button
            className="btn ghost"
            onClick={() => setTab("coherence")}
            style={{ display: "flex", alignItems: "center", gap: 6, color: validation.ready ? "var(--success, #3fae6a)" : "var(--danger)" }}
            title="Open Coherence tab for the full readiness checklist"
          >
            {validation.ready ? <IconCheckCircle size={14} /> : <IconAlertTriangle size={14} />}
            {validation.ready
              ? "Export readiness: all checks passed"
              : `Export readiness: ${validation.checklist.filter((c) => !c.ok).length} issue(s)`}
          </button>
        )}
        <a className="btn ghost" href={api.exportCampaignUrl(campaignId, "docx")}>
          <IconDownload size={14} /> Export campaign (.zip)
        </a>
      </div>

      {tab === "documents" && (
        <DocumentsTab campaignId={campaignId} documents={documents} npcs={npcs} locations={locations} onChanged={refreshAll} />
      )}
      {tab === "characters" && (
        <CharactersTab campaignId={campaignId} characters={characters} onChanged={refreshAll} />
      )}
      {tab === "npcs" && <NPCsTab campaignId={campaignId} npcs={npcs} locations={locations} onChanged={refreshAll} />}
      {tab === "locations" && <LocationsTab campaignId={campaignId} locations={locations} onChanged={refreshAll} />}
      {tab === "links" && (
        <LinksTab links={links} documents={documents} docById={docById} onChanged={refreshAll} />
      )}
      {tab === "illustrations" && (
        <IllustrationsTab
          campaignId={campaignId}
          illustrations={illustrations}
          characters={characters}
          npcs={npcs}
          locations={locations}
          onChanged={refreshAll}
        />
      )}
      {tab === "coherence" && (
        <CoherenceTab campaignId={campaignId} validation={validation} onRun={runValidate} busy={busy} docById={docById} onChanged={refreshAll} />
      )}
      {tab === "assistant" && <AssistantTab campaignId={campaignId} onChanged={refreshAll} />}

      <div style={{ marginTop: 32 }}>
        <button className="btn ghost" onClick={() => setShowActivity((v) => !v)}>
          <IconClock size={14} /> {showActivity ? "Hide" : "Show"} recent activity
        </button>
        {showActivity && (
          <div style={{ display: "grid", gap: 6, marginTop: 10 }}>
            {events.length === 0 && <div className="card">No activity recorded yet.</div>}
            {events.slice(0, 30).map((ev) => (
              <div key={ev.id} className="card" style={{ display: "flex", gap: 10, alignItems: "center", padding: "8px 12px" }}>
                <span className="badge entity" style={{ textTransform: "none" }}>{ev.event_type.replace(/_/g, " ")}</span>
                <span style={{ fontSize: 13 }}>{ev.description}</span>
                <span style={{ marginLeft: "auto", color: "var(--text-muted)", fontSize: 12 }}>
                  {new Date(ev.timestamp).toLocaleString()}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </>
  );
}

// ---------------------------------------------------------------------- //
// Documents tab -- create blank + import, no auto-classification on import
// ---------------------------------------------------------------------- //

const DOC_GROUP_ORDER: DocType[] = ["campaign_bible", "character", "npc", "location", "session_log", "other"];
const DOC_GROUP_LABELS: Record<DocType, string> = {
  campaign_bible: "Campaign Bible",
  character: "Characters",
  npc: "NPCs",
  location: "Locations",
  session_log: "Sessions",
  other: "Other",
};
// Each document-type group gets its own hue (matching that type's badge
// color elsewhere in the app) so the section headers are distinguishable
// at a glance instead of all rendering as the same muted gray.
const DOC_GROUP_HEADING_COLOR: Record<DocType, string> = {
  campaign_bible: "var(--violet)",
  character: "var(--info)",
  npc: "var(--ok)",
  location: "var(--warn)",
  session_log: "var(--gold)",
  other: "var(--text-muted)",
};

function DocumentsTab({
  campaignId,
  documents,
  npcs,
  locations,
  onChanged,
}: {
  campaignId: string;
  documents: DocumentOut[];
  npcs: NPCOut[];
  locations: LocationOut[];
  onChanged: () => void;
}) {
  const [mode, setMode] = useState<"none" | "create" | "import" | "session">("none");
  const [docType, setDocType] = useState<DocType>("campaign_bible");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [contentHtml, setContentHtml] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // search / filter / sort
  const [query, setQuery] = useState("");
  const [filterType, setFilterType] = useState<DocType | "">("");
  const [sort, setSort] = useState<"name" | "type" | "updated_at">("name");

  // per-row edit state
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [editType, setEditType] = useState<DocType>("other");
  const [rowBusy, setRowBusy] = useState<string | null>(null);

  async function createBlank(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.createDocument(campaignId, { doc_type: docType, title, description, content_html: contentHtml });
      setMode("none");
      setTitle("");
      setDescription("");
      setContentHtml("");
      onChanged();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function importFile(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      await api.importDocument(campaignId, file, docType, title, description);
      setMode("none");
      setTitle("");
      setDescription("");
      setFile(null);
      onChanged();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  function startRename(d: DocumentOut) {
    setEditingId(d.id);
    setEditTitle(d.title);
    setEditType(d.doc_type);
  }

  async function saveRename(id: string) {
    setRowBusy(id);
    setError(null);
    try {
      await api.patchDocument(id, { title: editTitle.trim(), doc_type: editType });
      setEditingId(null);
      onChanged();
    } catch (e) {
      setError(String(e));
    } finally {
      setRowBusy(null);
    }
  }

  async function removeDoc(d: DocumentOut) {
    if (!window.confirm(`Delete "${d.title}"? This cannot be undone.`)) return;
    setRowBusy(d.id);
    setError(null);
    try {
      await api.deleteDocument(d.id);
      onChanged();
    } catch (e) {
      setError(String(e));
    } finally {
      setRowBusy(null);
    }
  }

  const filtered = documents
    .filter((d) => !filterType || d.doc_type === filterType)
    .filter((d) => {
      if (!query.trim()) return true;
      const q = query.trim().toLowerCase();
      return d.title.toLowerCase().includes(q) || (d.description || "").toLowerCase().includes(q);
    })
    .sort((a, b) => {
      if (sort === "type") return a.doc_type === b.doc_type ? a.title.localeCompare(b.title) : a.doc_type.localeCompare(b.doc_type);
      if (sort === "updated_at") return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime();
      return a.title.localeCompare(b.title);
    });

  const grouped = new Map<DocType, DocumentOut[]>();
  for (const d of filtered) {
    if (!grouped.has(d.doc_type)) grouped.set(d.doc_type, []);
    grouped.get(d.doc_type)!.push(d);
  }

  return (
    <div>
      <div style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
        <button className="btn primary" onClick={() => setMode(mode === "create" ? "none" : "create")}>
          New document
        </button>
        <button className="btn ghost" onClick={() => setMode(mode === "import" ? "none" : "import")}>
          Import file
        </button>
        <button className="btn ghost" onClick={() => setMode(mode === "session" ? "none" : "session")}>
          New session log
        </button>
      </div>

      {error && <div className="card" style={{ borderColor: "var(--danger)", marginBottom: 12 }}>{error}</div>}

      {mode === "create" && (
        <form className="card" onSubmit={createBlank} style={{ marginBottom: 16, display: "grid", gap: 10 }}>
          <label>
            Type
            <select value={docType} onChange={(e) => setDocType(e.target.value as DocType)}>
              {Object.entries(DOC_TYPE_LABELS).map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </select>
          </label>
          <label>
            Title
            <input value={title} onChange={(e) => setTitle(e.target.value)} required />
          </label>
          <label>
            Description
            <input value={description} onChange={(e) => setDescription(e.target.value)} />
          </label>
          <label>
            Starting content (optional HTML -- leave blank for a starter template; use [[Title]] to cross-link)
            <textarea value={contentHtml} onChange={(e) => setContentHtml(e.target.value)} rows={4} />
          </label>
          <button className="btn primary" type="submit" disabled={busy}>
            {busy ? "Creating…" : "Create document"}
          </button>
        </form>
      )}

      {mode === "import" && (
        <form className="card" onSubmit={importFile} style={{ marginBottom: 16, display: "grid", gap: 10 }}>
          <p style={{ margin: 0, color: "var(--text-muted)" }}>
            Files are never auto-classified -- tell us what this is.
          </p>
          <label>
            What is this?
            <select value={docType} onChange={(e) => setDocType(e.target.value as DocType)}>
              {Object.entries(DOC_TYPE_LABELS).map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </select>
          </label>
          <label>
            Title (optional -- defaults to filename)
            <input value={title} onChange={(e) => setTitle(e.target.value)} />
          </label>
          <label>
            File
            <input type="file" onChange={(e) => setFile(e.target.files?.[0] || null)} required />
          </label>
          <button className="btn primary" type="submit" disabled={busy || !file}>
            {busy ? "Importing…" : "Import"}
          </button>
        </form>
      )}

      {mode === "session" && (
        <SessionLogForm
          campaignId={campaignId}
          npcs={npcs}
          locations={locations}
          onDone={() => {
            setMode("none");
            onChanged();
          }}
          onError={setError}
        />
      )}

      <div className="card" style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center", marginBottom: 16 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6, flex: 1, minWidth: 180 }}>
          <IconSearch size={14} />
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search title or description…" style={{ border: "none", background: "transparent" }} />
        </div>
        <select value={filterType} onChange={(e) => setFilterType(e.target.value as DocType | "")}>
          <option value="">All types</option>
          {Object.entries(DOC_TYPE_LABELS).map(([v, l]) => (
            <option key={v} value={v}>
              {l}
            </option>
          ))}
        </select>
        <select value={sort} onChange={(e) => setSort(e.target.value as any)}>
          <option value="name">Sort: name</option>
          <option value="type">Sort: type</option>
          <option value="updated_at">Sort: recently updated</option>
        </select>
      </div>

      {documents.length === 0 && <div className="card">No documents yet -- create or import one above.</div>}
      {documents.length > 0 && filtered.length === 0 && <div className="card">No documents match your search/filter.</div>}

      {DOC_GROUP_ORDER.filter((t) => grouped.has(t)).map((t) => (
        <div key={t} style={{ marginBottom: 18 }}>
          <h4 style={{ margin: "0 0 8px", color: DOC_GROUP_HEADING_COLOR[t], letterSpacing: "0.03em", textTransform: "uppercase", fontSize: 13 }}>
            {DOC_GROUP_LABELS[t]}
          </h4>
          <div style={{ display: "grid", gap: 8 }}>
            {grouped.get(t)!.map((d) =>
              editingId === d.id ? (
                <div key={d.id} className="card" style={{ display: "grid", gap: 8 }}>
                  <input value={editTitle} onChange={(e) => setEditTitle(e.target.value)} />
                  <select value={editType} onChange={(e) => setEditType(e.target.value as DocType)}>
                    {Object.entries(DOC_TYPE_LABELS).map(([v, l]) => (
                      <option key={v} value={v}>
                        {l}
                      </option>
                    ))}
                  </select>
                  <div style={{ display: "flex", gap: 8 }}>
                    <button className="btn primary" onClick={() => saveRename(d.id)} disabled={rowBusy === d.id}>
                      Save
                    </button>
                    <button className="btn ghost" onClick={() => setEditingId(null)}>
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <div key={d.id} className="card hoverable entity-mini-row" style={{ display: "flex", alignItems: "center" }}>
                  <a href={`/documents/${d.id}`} style={{ textDecoration: "none", color: "inherit", display: "flex", alignItems: "center", flex: 1, minWidth: 0 }}>
                    <span className={`badge ${DOC_TYPE_BADGE_CLASS[d.doc_type]}`} style={{ flexShrink: 0 }}>{DOC_TYPE_LABELS[d.doc_type]}</span>
                    <strong style={{ marginLeft: 10, flex: 1, minWidth: 0 }} title={d.title}>{d.title}</strong>
                    <span style={{ marginLeft: 10, flexShrink: 0, color: "var(--text-muted)", fontSize: 13, paddingRight: 10 }}>
                      v{d.active_version_number ?? "—"} · {d.origin}
                    </span>
                  </a>
                  <button className="btn ghost" onClick={() => startRename(d)} title="Rename / change type" style={{ padding: "4px 8px" }}>
                    <IconPencil size={14} />
                  </button>
                  <button className="btn ghost" onClick={() => removeDoc(d)} disabled={rowBusy === d.id} title="Delete" style={{ padding: "4px 8px", color: "var(--danger)" }}>
                    <IconTrash size={14} />
                  </button>
                </div>
              )
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------- //
// Structured Session Log creation form
// ---------------------------------------------------------------------- //

function SessionLogForm({
  campaignId,
  npcs,
  locations,
  onDone,
  onError,
}: {
  campaignId: string;
  npcs: NPCOut[];
  locations: LocationOut[];
  onDone: () => void;
  onError: (msg: string) => void;
}) {
  const [sessionNumber, setSessionNumber] = useState("");
  const [date, setDate] = useState("");
  const [eventsText, setEventsText] = useState("");
  const [npcIds, setNpcIds] = useState<string[]>([]);
  const [locationIds, setLocationIds] = useState<string[]>([]);
  const [consequences, setConsequences] = useState("");
  const [nextHooks, setNextHooks] = useState("");
  const [busy, setBusy] = useState(false);

  function toggle(list: string[], id: string, set: (v: string[]) => void) {
    set(list.includes(id) ? list.filter((x) => x !== id) : [...list, id]);
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const title = `Session ${sessionNumber || "?"}${date ? ` — ${date}` : ""}`;
      const npcRefs = npcIds.map((id) => npcs.find((n) => n.id === id)?.name).filter(Boolean);
      const locRefs = locationIds.map((id) => locations.find((l) => l.id === id)?.name).filter(Boolean);
      const html = `
        <h1>${title}</h1>
        <h3>Events</h3><p>${eventsText.replace(/\n/g, "<br/>") || "—"}</p>
        <h3>NPCs involved</h3><p>${npcRefs.length ? npcRefs.map((n) => `[[${n}]]`).join(", ") : "—"}</p>
        <h3>Locations visited</h3><p>${locRefs.length ? locRefs.map((n) => `[[${n}]]`).join(", ") : "—"}</p>
        <h3>Consequences</h3><p>${consequences.replace(/\n/g, "<br/>") || "—"}</p>
        <h3>Next session hooks</h3><p>${nextHooks.replace(/\n/g, "<br/>") || "—"}</p>
      `.trim();

      const doc = await api.createDocument(campaignId, {
        doc_type: "session_log",
        title,
        description: `Session ${sessionNumber}`,
        content_html: html,
      });

      // [[Reference]] auto-linking already handles NPC/location cross-links
      // from the [[Name]] text above -- no separate createLink calls needed.
      void doc;
      onDone();
    } catch (e) {
      onError(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="card" onSubmit={submit} style={{ marginBottom: 16, display: "grid", gap: 10 }}>
      <div style={{ display: "grid", gridTemplateColumns: "140px 1fr", gap: 10 }}>
        <label>
          Session #
          <input value={sessionNumber} onChange={(e) => setSessionNumber(e.target.value)} type="number" />
        </label>
        <label>
          Date
          <input value={date} onChange={(e) => setDate(e.target.value)} type="date" />
        </label>
      </div>
      <label>
        Events
        <textarea value={eventsText} onChange={(e) => setEventsText(e.target.value)} rows={3} placeholder="What happened this session…" />
      </label>
      <div>
        <div style={{ marginBottom: 4 }}>NPCs involved</div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {npcs.length === 0 && <span style={{ color: "var(--text-muted)", fontSize: 13 }}>No NPCs created yet.</span>}
          {npcs.map((n) => (
            <label key={n.id} style={{ display: "flex", alignItems: "center", gap: 4, width: "auto" }}>
              <input type="checkbox" checked={npcIds.includes(n.id)} onChange={() => toggle(npcIds, n.id, setNpcIds)} style={{ width: "auto" }} />
              {n.name}
            </label>
          ))}
        </div>
      </div>
      <div>
        <div style={{ marginBottom: 4 }}>Locations visited</div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {locations.length === 0 && <span style={{ color: "var(--text-muted)", fontSize: 13 }}>No locations created yet.</span>}
          {locations.map((l) => (
            <label key={l.id} style={{ display: "flex", alignItems: "center", gap: 4, width: "auto" }}>
              <input type="checkbox" checked={locationIds.includes(l.id)} onChange={() => toggle(locationIds, l.id, setLocationIds)} style={{ width: "auto" }} />
              {l.name}
            </label>
          ))}
        </div>
      </div>
      <label>
        Consequences
        <textarea value={consequences} onChange={(e) => setConsequences(e.target.value)} rows={2} />
      </label>
      <label>
        Next-session hooks
        <textarea value={nextHooks} onChange={(e) => setNextHooks(e.target.value)} rows={2} />
      </label>
      <button className="btn primary" type="submit" disabled={busy}>
        {busy ? "Saving…" : "Create session log"}
      </button>
    </form>
  );
}

// ---------------------------------------------------------------------- //
// Characters / NPCs / Locations tabs
// ---------------------------------------------------------------------- //

function CharactersTab({ campaignId, characters, onChanged }: { campaignId: string; characters: CharacterOut[]; onChanged: () => void }) {
  const [show, setShow] = useState(false);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await api.createCharacter(campaignId, { name });
      setShow(false);
      setName("");
      onChanged();
      router.push(`/documents/${result.document.id}`);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <button className="btn primary" onClick={() => setShow((v) => !v)} style={{ marginBottom: 12 }}>
        New character
      </button>
      {error && <div className="card" style={{ borderColor: "var(--danger)", marginBottom: 12 }}>{error}</div>}
      {show && (
        <form className="card" onSubmit={submit} style={{ marginBottom: 16, display: "flex", gap: 10, alignItems: "flex-end" }}>
          <label style={{ flex: 1 }}>
            Character name
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Aric Stormborn" required autoFocus />
          </label>
          <button className="btn primary" type="submit" disabled={busy}>
            {busy ? "Creating…" : "Create & open sheet"}
          </button>
        </form>
      )}
      <p style={{ color: "var(--text-muted)", fontSize: 13, marginTop: -4, marginBottom: 12 }}>
        Just the name -- race, class, level, abilities, and backstory all live in the character sheet document itself,
        which opens right after you create it.
      </p>
      {characters.length === 0 && <div className="card">No characters yet.</div>}
      <div style={{ display: "grid", gap: 8 }}>
        {characters.map((c) => (
          <a key={c.id} href={`/documents/${c.document_id}`} className="card hoverable entity-mini-row" style={{ textDecoration: "none", color: "inherit" }}>
            <span className="badge character">Character</span>
            <strong style={{ marginLeft: 10 }}>{c.name}</strong>
            <span style={{ marginLeft: "auto", color: "var(--text-muted)", fontSize: 13 }}>
              {c.race} {c.char_class} {c.level ? `Lv.${c.level}` : ""}
            </span>
          </a>
        ))}
      </div>
    </div>
  );
}

function NPCsTab({
  campaignId,
  npcs,
  locations,
  onChanged,
}: {
  campaignId: string;
  npcs: NPCOut[];
  locations: LocationOut[];
  onChanged: () => void;
}) {
  const [show, setShow] = useState(false);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await api.createNPC(campaignId, { name });
      setShow(false);
      setName("");
      onChanged();
      router.push(`/documents/${result.document.id}`);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <button className="btn primary" onClick={() => setShow((v) => !v)} style={{ marginBottom: 12 }}>
        New NPC
      </button>
      {error && <div className="card" style={{ borderColor: "var(--danger)", marginBottom: 12 }}>{error}</div>}
      {show && (
        <form className="card" onSubmit={submit} style={{ marginBottom: 16, display: "flex", gap: 10, alignItems: "flex-end" }}>
          <label style={{ flex: 1 }}>
            NPC name
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Lord Kael Veyr" required autoFocus />
          </label>
          <button className="btn primary" type="submit" disabled={busy}>
            {busy ? "Creating…" : "Create & open sheet"}
          </button>
        </form>
      )}
      <p style={{ color: "var(--text-muted)", fontSize: 13, marginTop: -4, marginBottom: 12 }}>
        Just the name -- role, location, and everything else live in the dossier document itself (use [[Location Title]]
        to link a place), which opens right after you create it.
      </p>
      {npcs.length === 0 && <div className="card">No NPCs yet.</div>}
      <div style={{ display: "grid", gap: 8 }}>
        {npcs.map((n) => (
          <a key={n.id} href={`/documents/${n.document_id}`} className="card hoverable entity-mini-row" style={{ textDecoration: "none", color: "inherit" }}>
            <span className="badge npc">NPC</span>
            <strong style={{ marginLeft: 10 }}>{n.name}</strong>
            <span style={{ marginLeft: "auto", color: "var(--text-muted)", fontSize: 13 }}>{n.role}</span>
          </a>
        ))}
      </div>
    </div>
  );
}

function LocationsTab({ campaignId, locations, onChanged }: { campaignId: string; locations: LocationOut[]; onChanged: () => void }) {
  const [show, setShow] = useState(false);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await api.createLocation(campaignId, { name });
      setShow(false);
      setName("");
      onChanged();
      router.push(`/documents/${result.document.id}`);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <button className="btn primary" onClick={() => setShow((v) => !v)} style={{ marginBottom: 12 }}>
        New location
      </button>
      {error && <div className="card" style={{ borderColor: "var(--danger)", marginBottom: 12 }}>{error}</div>}
      {show && (
        <form className="card" onSubmit={submit} style={{ marginBottom: 16, display: "flex", gap: 10, alignItems: "flex-end" }}>
          <label style={{ flex: 1 }}>
            Location name
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Blackspire Keep" required autoFocus />
          </label>
          <button className="btn primary" type="submit" disabled={busy}>
            {busy ? "Creating…" : "Create & open dossier"}
          </button>
        </form>
      )}
      <p style={{ color: "var(--text-muted)", fontSize: 13, marginTop: -4, marginBottom: 12 }}>
        Just the name -- everything else lives in the location dossier document itself, which opens right after you
        create it.
      </p>
      {locations.length === 0 && <div className="card">No locations yet.</div>}
      <div style={{ display: "grid", gap: 8 }}>
        {locations.map((l) => (
          <a key={l.id} href={`/documents/${l.document_id}`} className="card hoverable entity-mini-row" style={{ textDecoration: "none", color: "inherit" }}>
            <span className="badge location">Location</span>
            <strong style={{ marginLeft: 10 }}>{l.name}</strong>
          </a>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------- //
// Links tab -- user-defined edges, staleness by version number
// ---------------------------------------------------------------------- //

function LinksTab({
  links,
  documents,
  docById,
  onChanged,
}: {
  links: DocumentLinkOut[];
  documents: DocumentOut[];
  docById: Map<string, DocumentOut>;
  onChanged: () => void;
}) {
  const [source, setSource] = useState("");
  const [target, setTarget] = useState("");
  const [relationship, setRelationship] = useState<LinkRelationshipType>("related_to");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!source || !target || source === target) return;
    setBusy(true);
    setError(null);
    try {
      await api.createLink({ source_document_id: source, target_document_id: target, relationship_type: relationship, note });
      setNote("");
      onChanged();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function resync(id: string) {
    setBusy(true);
    try {
      await api.resyncLink(id);
      onChanged();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  const bySource = useMemo(() => {
    const groups = new Map<string, DocumentLinkOut[]>();
    for (const l of links) {
      if (!groups.has(l.source_document_id)) groups.set(l.source_document_id, []);
      groups.get(l.source_document_id)!.push(l);
    }
    // Campaign Bible (and other doc-type-ordered sources) first, so the
    // tree reads top-down the way a GM thinks about the campaign.
    const order: DocType[] = ["campaign_bible", "character", "npc", "location", "session_log", "other"];
    return [...groups.entries()].sort((a, b) => {
      const ta = docById.get(a[0])?.doc_type;
      const tb = docById.get(b[0])?.doc_type;
      const ia = ta ? order.indexOf(ta) : 99;
      const ib = tb ? order.indexOf(tb) : 99;
      if (ia !== ib) return ia - ib;
      return (docById.get(a[0])?.title || "").localeCompare(docById.get(b[0])?.title || "");
    });
  }, [links, docById]);

  return (
    <div>
      <p style={{ color: "var(--text-muted)" }}>
        Links are drawn by you, not auto-discovered. Once drawn, a link is flagged stale the moment its target moves to
        a new version -- a plain version-number comparison, no AI judgment call.
      </p>

      {error && <div className="card" style={{ borderColor: "var(--danger)", marginBottom: 12 }}>{error}</div>}

      {bySource.length > 0 && (
        <div className="card" style={{ marginBottom: 16 }}>
          <h3 style={{ marginTop: 0, marginBottom: 10 }}>
            <IconLayers size={16} /> Campaign relationship tree
          </h3>
          <div style={{ display: "grid", gap: 14 }}>
            {bySource.map(([sourceId, group]) => {
              const source = docById.get(sourceId);
              return (
                <div key={sourceId}>
                  <a href={`/documents/${sourceId}`} style={{ fontWeight: 700, color: "inherit", textDecoration: "none" }}>
                    {source?.title || sourceId}
                  </a>
                  <div style={{ marginTop: 4, display: "grid", gap: 2 }}>
                    {group.map((l, i) => {
                      const target = docById.get(l.target_document_id);
                      const isLast = i === group.length - 1;
                      return (
                        <a
                          key={l.id}
                          href={`/documents/${l.target_document_id}`}
                          style={{
                            display: "flex", alignItems: "center", gap: 6, paddingLeft: 18,
                            fontSize: 13, color: "inherit", textDecoration: "none",
                          }}
                        >
                          <span style={{ color: "var(--text-muted)" }}>{isLast ? "└──" : "├──"}</span>
                          <span>{target?.title || l.target_document_id}</span>
                          {l.status === "stale" && <IconAlertTriangle size={12} />}
                          <span style={{ color: "var(--text-muted)", fontSize: 11 }}>({RELATIONSHIP_LABELS[l.relationship_type]})</span>
                        </a>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      <form className="card" onSubmit={submit} style={{ marginBottom: 16, display: "grid", gap: 10 }}>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          <label>
            Source document
            <select value={source} onChange={(e) => setSource(e.target.value)} required>
              <option value="">— select —</option>
              {documents.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.title}
                </option>
              ))}
            </select>
          </label>
          <label>
            Target document
            <select value={target} onChange={(e) => setTarget(e.target.value)} required>
              <option value="">— select —</option>
              {documents.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.title}
                </option>
              ))}
            </select>
          </label>
        </div>
        <label>
          Relationship
          <select value={relationship} onChange={(e) => setRelationship(e.target.value as LinkRelationshipType)}>
            {Object.entries(RELATIONSHIP_LABELS).map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </label>
        <label>
          Note (optional)
          <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="mentions the Fall of Eldoria" />
        </label>
        <button className="btn primary" type="submit" disabled={busy}>
          {busy ? "Linking…" : "Create link"}
        </button>
      </form>

      {links.length === 0 && <div className="card">No links yet.</div>}
      <div style={{ display: "grid", gap: 8 }}>
        {links.map((l) => {
          const src = docById.get(l.source_document_id);
          const tgt = docById.get(l.target_document_id);
          return (
            <div key={l.id} className="card" style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <span className={`badge ${l.status}`}>{l.status}</span>
              <span>
                <strong>{src?.title ?? l.source_document_id}</strong> {RELATIONSHIP_LABELS[l.relationship_type]}{" "}
                <strong>{tgt?.title ?? l.target_document_id}</strong>
              </span>
              {l.note && <span style={{ color: "var(--text-muted)" }}>— {l.note}</span>}
              {l.status === "stale" && (
                <button className="btn ghost" style={{ marginLeft: "auto" }} onClick={() => resync(l.id)} disabled={busy}>
                  Resync
                </button>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------- //
// Illustrations tab
// ---------------------------------------------------------------------- //

function IllustrationsTab({
  campaignId,
  illustrations,
  characters,
  npcs,
  locations,
  onChanged,
}: {
  campaignId: string;
  illustrations: IllustrationOut[];
  characters: CharacterOut[];
  npcs: NPCOut[];
  locations: LocationOut[];
  onChanged: () => void;
}) {
  const [source, setSource] = useState<"generate" | "upload">("generate");
  const [entityType, setEntityType] = useState<IllustrationEntityType>("character");
  const [entityId, setEntityId] = useState("");
  const [prompt, setPrompt] = useState("");
  const [embed, setEmbed] = useState(true);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const options = entityType === "character" ? characters : entityType === "npc" ? npcs : locations;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!entityId) return;
    if (source === "generate" && !prompt.trim()) return;
    if (source === "upload" && !uploadFile) return;
    setBusy(true);
    setError(null);
    try {
      if (source === "generate") {
        await api.generateIllustration({ entity_type: entityType, entity_id: entityId, prompt: prompt.trim(), embed });
      } else {
        await api.uploadIllustration({ entity_type: entityType, entity_id: entityId, prompt: prompt.trim(), embed, file: uploadFile! });
      }
      setPrompt("");
      setUploadFile(null);
      onChanged();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <p style={{ color: "var(--text-muted)" }}>
        Generate (free, keyless via Pollinations) or upload your own image. If "embed" is checked, the image is inserted
        directly into the entity's own document as a new active version.
      </p>
      <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
        <button className={`btn ${source === "generate" ? "primary" : "ghost"}`} onClick={() => setSource("generate")} type="button">
          <IconSparkle size={14} /> Generate
        </button>
        <button className={`btn ${source === "upload" ? "primary" : "ghost"}`} onClick={() => setSource("upload")} type="button">
          <IconUpload size={14} /> Upload
        </button>
      </div>
      {error && <div className="card" style={{ borderColor: "var(--danger)", marginBottom: 12 }}>{error}</div>}
      <form className="card" onSubmit={submit} style={{ marginBottom: 16, display: "grid", gap: 10 }}>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          <label>
            Entity type
            <select
              value={entityType}
              onChange={(e) => {
                setEntityType(e.target.value as IllustrationEntityType);
                setEntityId("");
              }}
            >
              <option value="character">Character</option>
              <option value="npc">NPC</option>
              <option value="location">Location</option>
            </select>
          </label>
          <label>
            Which one
            <select value={entityId} onChange={(e) => setEntityId(e.target.value)} required>
              <option value="">— select —</option>
              {options.map((o: any) => (
                <option key={o.id} value={o.id}>
                  {o.name}
                </option>
              ))}
            </select>
          </label>
        </div>

        {source === "generate" ? (
          <label>
            Prompt
            <textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} rows={2} placeholder="a brooding elven ranger, portrait, fantasy art" />
          </label>
        ) : (
          <>
            <label>
              Image file
              <input type="file" accept="image/*" onChange={(e) => setUploadFile(e.target.files?.[0] || null)} required />
            </label>
            <label>
              Caption (optional)
              <input value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="portrait commissioned from a friend" />
            </label>
          </>
        )}

        <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <input type="checkbox" checked={embed} onChange={(e) => setEmbed(e.target.checked)} style={{ width: "auto" }} />
          Embed into document
        </label>
        <button className="btn primary" type="submit" disabled={busy}>
          {busy ? (source === "generate" ? <><IconSparkle size={14} /> Generating…</> : "Uploading…") : source === "generate" ? "Generate illustration" : "Upload illustration"}
        </button>
      </form>

      {illustrations.length === 0 && <div className="card">No illustrations yet.</div>}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 12 }}>
        {illustrations.map((i) => (
          <IllustrationCard key={i.id} illustration={i} />
        ))}
      </div>
    </div>
  );
}

function IllustrationCard({ illustration: i }: { illustration: any }) {
  // Prefer the copy hosted by this app's own backend -- SuperDocs' returned
  // URL has been observed coming back with the underlying storage object's
  // ACL not actually public (anonymous fetch = AccessDenied), which is a
  // platform-side issue on SuperDocs' end. local_image_url is generated
  // from the same bytes and always reachable, so it's the primary preview;
  // fall back to the SuperDocs URL only if no local copy exists (e.g. an
  // illustration created before this fallback was added).
  const [failedLocal, setFailedLocal] = useState(false);
  const [failedRemote, setFailedRemote] = useState(false);

  const src = i.local_image_url && !failedLocal ? i.local_image_url : i.superdocs_image_url;
  const usingFallback = !(i.local_image_url && !failedLocal);
  const failed = usingFallback && failedRemote;

  return (
    <div className="card">
      {!src ? (
        <div
          style={{
            width: "100%", aspectRatio: "1", borderRadius: 8, marginBottom: 8, display: "flex",
            alignItems: "center", justifyContent: "center", background: "var(--panel-raised)",
            color: "var(--text-muted)", fontSize: 12, textAlign: "center", padding: 8,
          }}
        >
          No image URL was returned for this illustration.
        </div>
      ) : failed ? (
        <div
          style={{
            width: "100%", borderRadius: 8, marginBottom: 8, padding: 10,
            background: "var(--panel-raised)", fontSize: 12,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 6, color: "var(--danger)", fontWeight: 700, marginBottom: 6 }}>
            <IconAlertTriangle size={14} /> Image failed to load
          </div>
          <div style={{ color: "var(--text-muted)", wordBreak: "break-all", marginBottom: 6 }}>{src}</div>
          <a className="btn ghost" href={src} target="_blank" rel="noreferrer" style={{ padding: "2px 8px", fontSize: 12 }}>
            Open URL directly
          </a>
        </div>
      ) : (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={src}
          alt={i.prompt}
          style={{ width: "100%", borderRadius: 8, marginBottom: 8 }}
          onError={() => (usingFallback ? setFailedRemote(true) : setFailedLocal(true))}
        />
      )}
      <div style={{ fontSize: 13, color: "var(--text-muted)" }}>{i.prompt}</div>
      <div style={{ display: "flex", gap: 6, marginTop: 6, flexWrap: "wrap" }}>
        <span className={`badge ${i.embedded ? "synced" : "pending_review"}`}>{i.embedded ? "Embedded" : "Not embedded"}</span>
        {i.provider === "upload" && <span className="badge entity">Uploaded</span>}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------- //
// Coherence / validate tab
// ---------------------------------------------------------------------- //

function CoherenceTab({
  campaignId,
  validation,
  onRun,
  busy,
  docById,
  onChanged,
}: {
  campaignId: string;
  validation: ValidationReport | null;
  onRun: () => void;
  busy: boolean;
  docById: Map<string, DocumentOut>;
  onChanged: () => void;
}) {
  const [relinking, setRelinking] = useState(false);
  const [relinkNote, setRelinkNote] = useState<string | null>(null);

  async function relinkAll() {
    setRelinking(true);
    setRelinkNote(null);
    try {
      const result = await api.relinkCampaignReferences(campaignId);
      setRelinkNote(
        `Scanned ${result.documents_scanned} document(s), updated ${result.documents_updated}. ` +
          `${result.total_resolved_references} reference(s) resolved, ${result.total_broken_references} still unresolved.`
      );
      onChanged();
      onRun();
    } catch (e) {
      setRelinkNote(String(e));
    } finally {
      setRelinking(false);
    }
  }

  return (
    <div>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 16 }}>
        <button className="btn primary" onClick={onRun} disabled={busy}>
          {busy ? "Checking…" : "Run readiness check"}
        </button>
        <button className="btn ghost" onClick={relinkAll} disabled={relinking} title="Re-check every document's [[references]] against the campaign's current documents and re-save any that changed">
          {relinking ? "Re-linking all…" : "Re-link all references"}
        </button>
      </div>
      {relinkNote && (
        <div className="card" style={{ marginBottom: 16, fontSize: 13 }}>
          {relinkNote}
        </div>
      )}

      {validation && (
        <>
          <div className="card" style={{ borderColor: validation.ready ? "var(--ok)" : "var(--warn)", marginBottom: 16 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              {validation.ready ? <IconCheckCircle size={18} /> : <IconAlertTriangle size={18} />}
              <strong>{validation.ready ? "Campaign Readiness: ready to export" : "Campaign Readiness: needs attention"}</strong>
            </div>
            <p style={{ margin: "8px 0 0", color: "var(--text-muted)" }}>
              {validation.document_count} documents · {validation.synced_links} synced links · {validation.stale_links} stale links
            </p>
          </div>

          <div style={{ display: "grid", gap: 8, marginBottom: 20 }}>
            {validation.checklist.map((item, idx) => (
              <div key={idx} className={`readiness-item ${item.ok ? "ok" : "warn"}`}>
                <span className="readiness-icon">{item.ok ? <IconCheckCircle size={16} /> : <IconAlertTriangle size={16} />}</span>
                <div>
                  <div>
                    {item.ok ? "✓" : "⚠"} {item.label}
                  </div>
                  {item.detail && <div style={{ color: "var(--text-muted)", fontSize: 13, marginTop: 2 }}>{item.detail}</div>}
                </div>
              </div>
            ))}
          </div>

          {validation.links.length > 0 && (
            <>
              <h4 style={{ margin: "0 0 8px", color: "var(--text-muted)" }}>Links</h4>
              <div style={{ display: "grid", gap: 8 }}>
                {validation.links.map((l) => (
                  <div key={l.link_id} className="card" style={{ display: "flex", gap: 10, alignItems: "center" }}>
                    <span className={`badge ${l.stale ? "stale" : "synced"}`}>{l.stale ? "stale" : "synced"}</span>
                    <span>
                      <strong>{docById.get(l.source_document_id)?.title ?? l.source_document_id}</strong> →{" "}
                      <strong>{docById.get(l.target_document_id)?.title ?? l.target_document_id}</strong>
                    </span>
                    <span style={{ marginLeft: "auto", color: "var(--text-muted)", fontSize: 13 }}>
                      synced @ v{l.synced_version_number} · current v{l.current_version_number ?? "—"}
                    </span>
                  </div>
                ))}
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------- //
// Campaign Assistant -- free-text prompt -> drafted content, GM chooses
// whether/how to save it (insert into an open doc is out of scope for this
// pass; "save as a new document" is the primary path, matching "prove the
// app can grow a campaign, not only import one").
// ---------------------------------------------------------------------- //

const DOC_TYPES_FOR_SAVE: DocType[] = ["campaign_bible", "character", "npc", "location", "session_log", "other"];

function AssistantTab({ campaignId, onChanged }: { campaignId: string; onChanged: () => void }) {
  const [messages, setMessages] = useState<ChatMessageOut[]>([]);
  const [prompt, setPrompt] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState<AssistantDraft | null>(null);
  const [saveTitle, setSaveTitle] = useState("");
  const [saveType, setSaveType] = useState<DocType>("other");
  const [saving, setSaving] = useState(false);
  const [savedDocId, setSavedDocId] = useState<string | null>(null);

  useEffect(() => {
    api.listAssistantMessages(campaignId).then(setMessages).catch(() => {});
  }, [campaignId]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!prompt.trim()) return;
    setBusy(true);
    setError(null);
    setDraft(null);
    setSavedDocId(null);
    try {
      const result = await api.campaignAssistant(campaignId, prompt.trim());
      setPrompt("");
      if (result.content_html) {
        setDraft(result);
        setSaveTitle(result.suggested_title);
        setSaveType((result.suggested_doc_type as DocType) || "other");
      }
      const history = await api.listAssistantMessages(campaignId);
      setMessages(history);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function saveDraftAsDocument() {
    if (!draft || !saveTitle.trim()) return;
    setSaving(true);
    setError(null);
    try {
      const created = await api.createDocument(campaignId, { doc_type: saveType, title: saveTitle.trim(), content_html: draft.content_html });
      setSavedDocId(created.id);
      setDraft(null);
      onChanged();
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      <p style={{ color: "var(--text-muted)" }}>
        Ask the assistant to draft new campaign content -- an NPC, a location, a session summary. Nothing is saved to the
        campaign until you review the draft and save it below.
      </p>

      {error && <div className="card" style={{ borderColor: "var(--danger)", marginBottom: 12 }}>{error}</div>}

      <form className="card" onSubmit={submit} style={{ display: "flex", gap: 8, marginBottom: 16 }}>
        <input
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder='e.g. Create an NPC who serves Lord Kael, or "Summarize Session 3"'
          style={{ flex: 1 }}
          disabled={busy}
        />
        <button className="btn primary" type="submit" disabled={busy}>
          {busy ? <><IconSparkle size={14} /> Thinking…</> : "Ask"}
        </button>
      </form>

      {savedDocId && (
        <div className="card" style={{ marginBottom: 16, display: "flex", alignItems: "center", gap: 10 }}>
          <IconCheckCircle size={16} />
          <span>Saved to the campaign.</span>
          <a className="btn ghost" href={`/documents/${savedDocId}`} style={{ marginLeft: "auto" }}>
            Open document
          </a>
        </div>
      )}

      {draft && (
        <div className="card" style={{ marginBottom: 16 }}>
          <h3 style={{ marginTop: 0 }}>Draft</h3>
          <div className="card chunk-card is-entity" dangerouslySetInnerHTML={{ __html: draft.content_html }} />
          <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 10, marginTop: 12 }}>
            <label>
              Title
              <input value={saveTitle} onChange={(e) => setSaveTitle(e.target.value)} required />
            </label>
            <label>
              Type
              <select value={saveType} onChange={(e) => setSaveType(e.target.value as DocType)}>
                {DOC_TYPES_FOR_SAVE.map((t) => (
                  <option key={t} value={t}>
                    {DOC_TYPE_LABELS[t]}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
            <button className="btn approve" onClick={saveDraftAsDocument} disabled={saving || !saveTitle.trim()}>
              {saving ? "Saving…" : "Save as new document"}
            </button>
            <button className="btn ghost" onClick={() => setDraft(null)} disabled={saving}>
              Discard
            </button>
          </div>
        </div>
      )}

      {messages.length > 0 && (
        <div>
          <h3 style={{ marginBottom: 8 }}>Conversation</h3>
          <div style={{ display: "grid", gap: 8 }}>
            {messages.map((m) => (
              <div key={m.id} className="card" style={{ background: m.role === "user" ? "var(--panel-raised)" : undefined }}>
                <strong style={{ textTransform: "capitalize" }}>{m.role}</strong>
                <p style={{ margin: "4px 0 0" }}>{m.content}</p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
