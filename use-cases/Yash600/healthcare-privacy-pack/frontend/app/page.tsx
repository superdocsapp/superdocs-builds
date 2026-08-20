"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api, WorkspaceOut, fileToBase64 } from "@/lib/api";
import { IconLayers, IconPlus, IconArrowRight, IconUpload, IconX, IconClipboard, IconTrash } from "./icons";
import { ProgressOverlay, useStagedProgress } from "./ProgressOverlay";

type ProcedureDraft = { id: string; title: string; file: File | null };
type PolicyGroupDraft = { id: string; title: string; file: File | null; procedures: ProcedureDraft[] };

let localIdCounter = 1;
const nextId = () => `d${localIdCounter++}`;

function MiniFilePicker({
  file, onChange, compact,
}: { file: File | null; onChange: (f: File | null) => void; compact?: boolean }) {
  const ref = useRef<HTMLInputElement>(null);
  return (
    <div>
      <button
        type="button"
        className="btn"
        style={{ width: compact ? undefined : "100%", justifyContent: "center", fontSize: 12.5, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}
        onClick={() => ref.current?.click()}
      >
        <IconUpload size={13} /> {file ? file.name : "Choose file"}
      </button>
      <input ref={ref} type="file" style={{ display: "none" }} onChange={(e) => onChange(e.target.files?.[0] || null)} />
    </div>
  );
}

const emptyGroup = (): PolicyGroupDraft => ({ id: nextId(), title: "", file: null, procedures: [] });

export default function HomePage() {
  const router = useRouter();
  const [workspaces, setWorkspaces] = useState<WorkspaceOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);

  const [orgName, setOrgName] = useState("");
  const [orgType, setOrgType] = useState("");
  const [packName, setPackName] = useState("");
  const [groups, setGroups] = useState<PolicyGroupDraft[]>([emptyGroup()]);
  const [creating, setCreating] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const progressUI = useStagedProgress();

  useEffect(() => {
    api
      .listWorkspaces()
      .then(setWorkspaces)
      .catch((e) => setError(String(e)));
  }, []);

  const updateGroup = (id: string, patch: Partial<PolicyGroupDraft>) =>
    setGroups((gs) => gs.map((g) => (g.id === id ? { ...g, ...patch } : g)));
  const removeGroup = (id: string) => setGroups((gs) => gs.filter((g) => g.id !== id));
  const addGroup = () => setGroups((gs) => [...gs, emptyGroup()]);

  const addProcedure = (groupId: string) =>
    setGroups((gs) => gs.map((g) => (g.id === groupId ? { ...g, procedures: [...g.procedures, { id: nextId(), title: "", file: null }] } : g)));
  const updateProcedure = (groupId: string, procId: string, patch: Partial<ProcedureDraft>) =>
    setGroups((gs) =>
      gs.map((g) =>
        g.id === groupId ? { ...g, procedures: g.procedures.map((p) => (p.id === procId ? { ...p, ...patch } : p)) } : g
      )
    );
  const removeProcedure = (groupId: string, procId: string) =>
    setGroups((gs) => gs.map((g) => (g.id === groupId ? { ...g, procedures: g.procedures.filter((p) => p.id !== procId) } : g)));

  const canSubmit =
    orgName.trim().length > 0 &&
    packName.trim().length > 0 &&
    groups.length > 0 &&
    groups.every((g) => g.title.trim() && g.file && g.procedures.every((p) => p.title.trim() && p.file));

  const create = async () => {
    if (!canSubmit) return;
    setCreating(true);
    setError(null);

    // Every stage below is one real awaited network call, in the exact
    // order the requests actually fire -- not a timer standing in for
    // progress. Each stage flips to "active" right before its request goes
    // out and to "done" only once that request has genuinely resolved, so
    // if e.g. the third procedure upload fails, the overlay shows exactly
    // that -- the first two really did finish, the rest never started.
    type Step =
      | { type: "workspace" }
      | { type: "policy"; group: PolicyGroupDraft }
      | { type: "procedure"; group: PolicyGroupDraft; proc: ProcedureDraft };

    const stageLabels: string[] = ["Creating workspace"];
    const steps: Step[] = [{ type: "workspace" }];
    for (const group of groups) {
      stageLabels.push(`Uploading policy — ${group.title}`);
      steps.push({ type: "policy", group });
      for (const proc of group.procedures) {
        stageLabels.push(`Uploading procedure — ${proc.title}`);
        steps.push({ type: "procedure", group, proc });
      }
    }

    progressUI.start("Creating compliance pack", stageLabels, "Each file uploads to SuperDocs and comes back parsed into sections before the next one starts.");

    const policyDocIdByGroup = new Map<string, string>();
    let ws: WorkspaceOut | null = null;

    try {
      for (let i = 0; i < steps.length; i++) {
        progressUI.setStageStatus(i, "active");
        const step = steps[i];

        if (step.type === "workspace") {
          ws = await api.createWorkspace({
            organizationName: orgName.trim(),
            organizationType: orgType.trim() || undefined,
            packName: packName.trim(),
          });
        } else if (step.type === "policy") {
          const fileBase64 = await fileToBase64(step.group.file as File);
          const uploaded = await api.uploadDocument(ws!.id, {
            filename: (step.group.file as File).name,
            fileBase64,
            docType: "policy",
            title: step.group.title.trim(),
          });
          policyDocIdByGroup.set(step.group.id, uploaded.document.id);
        } else {
          const policyDocId = policyDocIdByGroup.get(step.group.id)!;
          const procBase64 = await fileToBase64(step.proc.file as File);
          await api.uploadDocument(ws!.id, {
            filename: (step.proc.file as File).name,
            fileBase64: procBase64,
            docType: "procedure",
            title: step.proc.title.trim(),
            parentPolicyId: policyDocId,
          });
        }

        progressUI.setStageStatus(i, "done");
      }

      progressUI.finish();
      router.push(`/w/${ws!.id}`);
    } catch (e) {
      progressUI.fail(String(e));
      setError(String(e));
      setCreating(false);
    }
  };

  async function handleDeleteWorkspace(e: React.MouseEvent, ws: WorkspaceOut) {
    e.preventDefault();
    e.stopPropagation();
    if (
      !window.confirm(
        `Delete "${ws.pack_name}" (${ws.organization_name})? This permanently removes every policy, procedure, reference, proposed change, finding, and report in this workspace. This cannot be undone.`
      )
    ) {
      return;
    }
    setDeletingId(ws.id);
    setError(null);
    try {
      await api.deleteWorkspace(ws.id);
      setWorkspaces((prev) => (prev ? prev.filter((w) => w.id !== ws.id) : prev));
    } catch (e) {
      setError(String(e));
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <div>
      <div className="eyebrow">
        <IconLayers size={13} /> Healthcare Compliance
      </div>
      <h1>Compliance Packs</h1>
      <p className="lede">
        Every pack starts from a real upload -- no seed data, no hardcoded organization. Create a
        workspace, add your policies and their related procedures, and let the system discover and
        maintain the section-level references between them.
      </p>

      {error && <div className="error-banner">{error}</div>}

      <div className="card row between" style={{ marginBottom: 24 }}>
        <div className="muted">{workspaces ? `${workspaces.length} workspace(s)` : "Loading..."}</div>
        <button className="primary" onClick={() => setShowForm((v) => !v)}>
          <IconPlus size={14} /> New Compliance Pack
        </button>
      </div>

      {showForm && (
        <div className="card glass-strong" style={{ marginBottom: 24, maxWidth: 640 }}>
          <h3>New Compliance Pack</h3>
          <p className="muted" style={{ marginTop: -6, marginBottom: 18, fontSize: 12.5 }}>
            Fill in the workspace details, then add each policy and the procedures it governs.
            Everything uploads together when you create the pack.
          </p>

          <div className="row wrap" style={{ gap: 12, marginBottom: 20 }}>
            <div style={{ flex: "1 1 200px" }}>
              <label className="muted" style={{ display: "block", marginBottom: 4, fontSize: 12 }}>Organization</label>
              <input type="text" value={orgName} onChange={(e) => setOrgName(e.target.value)} placeholder="ABC Medical Center" disabled={creating} />
            </div>
            <div style={{ flex: "1 1 180px" }}>
              <label className="muted" style={{ display: "block", marginBottom: 4, fontSize: 12 }}>Organization type (optional)</label>
              <input type="text" value={orgType} onChange={(e) => setOrgType(e.target.value)} placeholder="hospital / clinic / lab" disabled={creating} />
            </div>
            <div style={{ flex: "1 1 200px" }}>
              <label className="muted" style={{ display: "block", marginBottom: 4, fontSize: 12 }}>Pack name</label>
              <input type="text" value={packName} onChange={(e) => setPackName(e.target.value)} placeholder="Healthcare Compliance Pack" disabled={creating} />
            </div>
          </div>

          <div className="section-head" style={{ margin: "0 0 var(--space-3)" }}>
            <div className="section-head-icon"><IconClipboard size={14} /></div>
            <h2>Policies &amp; Procedures</h2>
          </div>

          {groups.map((group, gi) => (
            <div key={group.id} className="group-card">
              <div className="group-card-head">
                <span className="badge policy">Policy {gi + 1}</span>
                {groups.length > 1 && (
                  <button type="button" className="icon-btn-remove" onClick={() => removeGroup(group.id)} disabled={creating} title="Remove this policy">
                    <IconX size={13} />
                  </button>
                )}
              </div>

              <label className="muted" style={{ display: "block", marginBottom: 4, fontSize: 12 }}>Policy name</label>
              <input
                type="text" value={group.title} onChange={(e) => updateGroup(group.id, { title: e.target.value })}
                placeholder="Patient Privacy Policy" disabled={creating} style={{ marginBottom: 10 }}
              />
              <MiniFilePicker file={group.file} onChange={(f) => updateGroup(group.id, { file: f })} />

              <div style={{ marginTop: 16 }}>
                <div className="muted" style={{ fontSize: 11.5, fontWeight: 700, letterSpacing: "0.06em", textTransform: "uppercase", marginBottom: 8 }}>
                  Related procedures
                </div>
                {group.procedures.map((proc) => (
                  <div key={proc.id} className="procedure-row">
                    <input
                      type="text" value={proc.title} onChange={(e) => updateProcedure(group.id, proc.id, { title: e.target.value })}
                      placeholder="Procedure name" disabled={creating}
                    />
                    <MiniFilePicker compact file={proc.file} onChange={(f) => updateProcedure(group.id, proc.id, { file: f })} />
                    <button type="button" className="icon-btn-remove" onClick={() => removeProcedure(group.id, proc.id)} disabled={creating} title="Remove this procedure">
                      <IconX size={12} />
                    </button>
                  </div>
                ))}
                <button type="button" className="btn dashed-btn" onClick={() => addProcedure(group.id)} disabled={creating}>
                  <IconPlus size={13} /> Add procedure
                </button>
              </div>
            </div>
          ))}

          <button type="button" className="btn dashed-btn" style={{ marginBottom: 20 }} onClick={addGroup} disabled={creating}>
            <IconPlus size={14} /> Add another policy
          </button>

          <button className="primary" onClick={create} disabled={creating || !canSubmit} style={{ width: "100%", justifyContent: "center" }}>
            {creating ? "Creating..." : "Create workspace"}
          </button>
        </div>
      )}

      {workspaces && workspaces.length === 0 && !showForm && (
        <div className="empty">No workspaces yet -- create one to get started.</div>
      )}

      <div className="col">
        {(workspaces || []).map((ws) => (
          <div key={ws.id} className="card hoverable row between" style={{ cursor: "pointer" }} onClick={() => router.push(`/w/${ws.id}`)}>
            <div>
              <div style={{ fontWeight: 700, fontSize: 14.5 }}>{ws.pack_name}</div>
              <div className="muted">{ws.organization_name}{ws.organization_type ? ` -- ${ws.organization_type}` : ""}</div>
            </div>
            <div className="row" style={{ gap: 12 }}>
              <span className={`badge ${ws.status === "ready" ? "synced" : ws.status === "needs_attention" ? "stale" : "procedure"}`}>{ws.status}</span>
              <button
                className="icon-btn-remove"
                onClick={(e) => handleDeleteWorkspace(e, ws)}
                disabled={deletingId === ws.id}
                title="Delete compliance pack"
              >
                <IconTrash size={14} />
              </button>
              <IconArrowRight size={16} />
            </div>
          </div>
        ))}
      </div>

      <ProgressOverlay
        visible={progressUI.visible}
        title={progressUI.title}
        labels={progressUI.labels}
        statuses={progressUI.statuses}
        detail={progressUI.detail}
        error={progressUI.error}
        onDismiss={() => {
          progressUI.close();
          setCreating(false);
        }}
      />
    </div>
  );
}
