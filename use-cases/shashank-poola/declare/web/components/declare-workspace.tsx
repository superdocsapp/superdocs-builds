"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Check, ChevronDown, Download, FileUp, LoaderCircle, Upload, X } from "lucide-react";
import {
  analyzeDeclaration,
  applyStatements,
  createStatements,
  decideSuperdocsChanges,
  exportManuscript,
  getSuperdocsJob,
  uploadManuscript,
  type Analysis,
  type Author,
  type DeclareFacts,
} from "@/lib/declare-api";
import { ProjectNotes } from "./declare/project-notes";
import { WorkspaceProgress } from "./declare/workspace-progress";

const creditRoles = [
  ["conceptualization", "Conceptualization"], ["data_curation", "Data curation"], ["formal_analysis", "Formal analysis"],
  ["funding_acquisition", "Funding acquisition"], ["investigation", "Investigation"], ["methodology", "Methodology"],
  ["project_administration", "Project administration"], ["resources", "Resources"], ["software", "Software"],
  ["supervision", "Supervision"], ["validation", "Validation"], ["visualization", "Visualization"],
  ["writing_original_draft", "Writing – original draft"], ["writing_review_editing", "Writing – review & editing"],
] as const;

const toAuthors = (names: string): Author[] => names.split("\n").map((name) => name.trim()).filter(Boolean).map((name, index) => ({
  id: `${name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "") || "author"}-${index + 1}`,
  name,
}));

const toBase64 = (file: File) => new Promise<string>((resolve, reject) => {
  const reader = new FileReader();
  reader.onload = () => resolve(String(reader.result).split(",")[1] ?? "");
  reader.onerror = reject;
  reader.readAsDataURL(file);
});

const stripHtml = (value: unknown) => String(value ?? "").replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
const roleLabel = (roleId: string) => creditRoles.find(([id]) => id === roleId)?.[1] ?? roleId;

export const DeclareWorkspace = () => {
  const [authorNames, setAuthorNames] = useState("Shashank\nRahul\nPriya\nMei");
  const [contributions, setContributions] = useState("Shashank designed the study and built the software. Rahul collected and cleaned the data. Priya supervised the project. Mei helped with the research.");
  const [funding, setFunding] = useState("XYZ Foundation funded the study.");
  const [conflicts, setConflicts] = useState("No competing interests.");
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [facts, setFacts] = useState<DeclareFacts | null>(null);
  const [statements, setStatements] = useState<Awaited<ReturnType<typeof createStatements>> | null>(null);
  const sessionId = useRef<string | null>(null);
  const [uploaded, setUploaded] = useState(false);
  const [documentHtml, setDocumentHtml] = useState("");
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobDelayed, setJobDelayed] = useState(false);
  const [job, setJob] = useState<Record<string, unknown> | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [activeStage, setActiveStage] = useState(1);
  const [openRoleGroup, setOpenRoleGroup] = useState<string | null>(null);
  const authors = useMemo(() => toAuthors(authorNames), [authorNames]);
  const pendingChanges = useMemo(() => {
    const metadata = job?.metadata;
    if (typeof metadata !== "object" || metadata === null || !("pending_changes" in metadata)) return [];
    return Array.isArray(metadata.pending_changes) ? metadata.pending_changes.filter((item): item is Record<string, unknown> => typeof item === "object" && item !== null) : [];
  }, [job]);
  const reviewCount = facts?.contributions.filter((item) => item.status === "approved").length ?? 0;
  const clarityCount = facts?.contributions.filter((item) => item.status === "ambiguous").length ?? 0;
  const reviewGroups = useMemo(() => {
    if (!facts) return [];

    const groups = new Map<string, {
      key: string;
      authorIds: string[];
      evidence: string;
      roleIds: string[];
      status: "approved" | "ambiguous";
      indexes: number[];
    }>();

    facts.contributions.forEach((item, index) => {
      const key = [item.status, item.evidence, [...item.roleIds].sort().join(",")].join("|");
      const existing = groups.get(key);

      if (existing) {
        existing.authorIds.push(item.authorId);
        existing.indexes.push(index);
        return;
      }

      groups.set(key, {
        key,
        authorIds: [item.authorId],
        evidence: item.evidence,
        roleIds: item.roleIds,
        status: item.status,
        indexes: [index],
      });
    });

    return [...groups.values()];
  }, [facts]);
  const attentionGroups = reviewGroups.filter((group) => group.status === "ambiguous" || group.roleIds.length === 0);
  const readyGroups = reviewGroups.filter((group) => !attentionGroups.includes(group));
  const jobStatus = String(job?.status ?? "");
  const isJobWorking = ["queued", "pending", "processing", "in_progress"].includes(jobStatus);
  const isJobDelayed = jobDelayed && isJobWorking;

  const refreshJob = useCallback(async () => {
    if (!jobId) return;
    try {
      setJob(await getSuperdocsJob(jobId));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to refresh the manuscript status.");
    }
  }, [jobId]);

  useEffect(() => {
    if (!jobId || !isJobWorking) return;
    const timer = window.setInterval(() => void refreshJob(), 4000);
    return () => window.clearInterval(timer);
  }, [isJobWorking, jobId, refreshJob]); // Poll only while SuperDocs is preparing a proposal.

  useEffect(() => {
    if (!jobId || !isJobWorking) return;
    const timer = window.setTimeout(() => setJobDelayed(true), 90_000);
    return () => window.clearTimeout(timer);
  }, [isJobWorking, jobId]);

  const analyze = async () => {
    try {
      setBusy("analysis");
      setMessage(null);
      const nextAnalysis = await analyzeDeclaration({ authors, contributions, funding, conflicts });
      setAnalysis(nextAnalysis);
      setFacts({
        authors,
        contributions: nextAnalysis.contributions.map((item) => ({
          authorId: item.authorId,
          evidence: item.evidence,
          roleIds: item.roleIds,
          status: item.status === "proposed" ? "approved" : "ambiguous",
        })),
        funding: nextAnalysis.funding,
        conflicts: nextAnalysis.conflicts,
      });
      setStatements(null);
      setUploaded(false);
      setDocumentHtml("");
      sessionId.current = null;
      setJobId(null);
      setJob(null);
      setJobDelayed(false);
      setActiveStage(2);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Analysis failed.");
    } finally {
      setBusy(null);
    }
  };

  const updateGroupRoles = (indexes: number[], roleId: string) => {
    setFacts((current) => {
      if (!current) return current;

      const contributions = current.contributions.map((item, index) => {
        if (!indexes.includes(index)) return item;
        const roleIds = item.roleIds.includes(roleId)
          ? item.roleIds.filter((id) => id !== roleId)
          : [...item.roleIds, roleId];

        return { ...item, roleIds, status: roleIds.length ? "approved" as const : "ambiguous" as const };
      });

      return { ...current, contributions };
    });
    setStatements(null);
  };

  const keepGroupOpen = (indexes: number[]) => {
    setFacts((current) => current ? {
      ...current,
      contributions: current.contributions.map((item, index) => indexes.includes(index) ? { ...item, status: "ambiguous", roleIds: [] } : item),
    } : current);
    setStatements(null);
  };

  const generateStatements = async () => {
    if (!facts) return;
    try {
      setBusy("statements");
      setMessage(null);
      setStatements(await createStatements(facts));
      setActiveStage(3);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Please finish the review first.");
    } finally {
      setBusy(null);
    }
  };

  const upload = async (file: File) => {
    const currentSessionId = sessionId.current ?? `declare-${crypto.randomUUID()}`;
    sessionId.current = currentSessionId;
    try {
      setBusy("upload");
      setMessage(null);
      const result = await uploadManuscript({ sessionId: currentSessionId, filename: file.name, fileBase64: await toBase64(file) });
      setUploaded(true);
      setDocumentHtml(result.html ?? result.document_html ?? "");
      setMessage(`${file.name} is ready for a proposed edit.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Upload failed.");
    } finally {
      setBusy(null);
    }
  };

  const apply = async () => {
    const currentSessionId = sessionId.current;
    if (!facts || !statements || !uploaded || !currentSessionId) return;
    try {
      setBusy("apply");
      setMessage(null);
      const result = await applyStatements({ sessionId: currentSessionId, facts });
      setJobId(result.job_id);
      setJobDelayed(false);
      setJob(await getSuperdocsJob(result.job_id));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to propose manuscript changes.");
    } finally {
      setBusy(null);
    }
  };

  const decide = async (approved: boolean, changeId?: string) => {
    const currentSessionId = sessionId.current;
    if (!jobId || !currentSessionId) return;
    try {
      setBusy("approval");
      await decideSuperdocsChanges({ sessionId: currentSessionId, jobId, approved, changes: changeId ? [{ changeId, approved }] : pendingChanges.map((change) => ({ changeId: String(change.change_id), approved })) });
      await refreshJob();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to save that decision.");
    } finally {
      setBusy(null);
    }
  };

  const download = async () => {
    const currentSessionId = sessionId.current;
    if (!currentSessionId) return;
    try {
      setBusy("export");
      const blob = await exportManuscript(currentSessionId);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "declare-manuscript.docx";
      link.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Export failed.");
    } finally {
      setBusy(null);
    }
  };

  return <div className="mt-12 space-y-6">
    <WorkspaceProgress activeStage={activeStage} hasReview={Boolean(facts)} hasStatements={Boolean(statements)} hasJob={Boolean(jobId)} onStageChange={setActiveStage} />
    {activeStage === 1 && <ProjectNotes authorNames={authorNames} contributions={contributions} funding={funding} conflicts={conflicts} authorCount={authors.length} busy={busy} onAuthorNamesChange={setAuthorNames} onContributionsChange={setContributions} onFundingChange={setFunding} onConflictsChange={setConflicts} onAnalyze={() => void analyze()} />}

    {facts && activeStage === 2 && <section className="rounded-2xl border border-zinc-200 bg-white p-6 sm:p-8"><div className="flex flex-wrap items-start justify-between gap-4"><div><p className="text-xs font-semibold uppercase tracking-[0.16em] text-zinc-500">Review</p><h2 className="mt-2 text-xl font-semibold tracking-tight text-zinc-950">Review what Declare understood.</h2><p className="mt-2 text-sm text-zinc-700">{clarityCount ? `${clarityCount} needs attention · ` : ""}{reviewCount} ready</p></div><span className="rounded-full border border-zinc-200 px-3 py-1.5 text-xs text-zinc-600">Researcher review required</span></div>
      {attentionGroups.length > 0 && <div className="mt-6"><p className="mb-3 text-sm font-semibold text-amber-900">Needs attention</p><div className="space-y-3">{attentionGroups.map((group) => <article key={group.key} className="rounded-xl border border-amber-200 bg-amber-50/40 p-4"><div className="flex flex-wrap items-start justify-between gap-3"><div><p className="font-semibold text-zinc-950">{group.authorIds.map((authorId) => authors.find((author) => author.id === authorId)?.name ?? authorId).join(" · ")}</p><p className="mt-1 max-w-3xl text-sm leading-6 text-zinc-700">“{group.evidence}”</p></div><span className="rounded-full bg-amber-100 px-3 py-1 text-xs font-medium text-amber-800">Needs clarification</span></div><div className="mt-4 flex flex-wrap items-center gap-2"><span className="text-sm text-amber-900">No role assigned until this is clarified.</span><button onClick={() => setOpenRoleGroup(openRoleGroup === group.key ? null : group.key)} className="ml-auto inline-flex items-center gap-1 rounded-full border border-amber-300 bg-white px-3 py-1.5 text-xs font-medium text-zinc-800">Assign manually <ChevronDown className={`size-3 transition ${openRoleGroup === group.key ? "rotate-180" : ""}`} /></button></div>{openRoleGroup === group.key && <div className="mt-3 flex flex-wrap gap-2 border-t border-amber-200 pt-3">{creditRoles.map(([id, label]) => <button key={id} onClick={() => updateGroupRoles(group.indexes, id)} className="rounded-full border border-zinc-200 bg-white px-3 py-1.5 text-xs text-zinc-700 hover:border-zinc-400">{label}</button>)}</div>}</article>)}</div></div>}
      <div className="mt-6 overflow-hidden rounded-xl border border-zinc-200"><div className="border-b border-zinc-200 bg-zinc-50 px-4 py-3"><p className="text-sm font-semibold text-zinc-950">Ready to use</p><p className="mt-0.5 text-xs text-zinc-600">Shared evidence is grouped once, even when it applies to more than one author.</p></div>{readyGroups.map((group) => <article key={group.key} className="border-b border-zinc-200 px-4 py-4 last:border-b-0"><div className="flex flex-wrap items-start gap-x-5 gap-y-2"><p className="min-w-36 font-medium text-zinc-950">{group.authorIds.map((authorId) => authors.find((author) => author.id === authorId)?.name ?? authorId).join(" · ")}</p><p className="min-w-56 flex-1 text-sm leading-6 text-zinc-600">“{group.evidence}”</p><div className="flex flex-wrap items-center gap-2">{group.roleIds.map((roleId) => <span key={roleId} className="rounded-full bg-zinc-900 px-2.5 py-1 text-xs font-medium text-white">{roleLabel(roleId)}</span>)}<button onClick={() => setOpenRoleGroup(openRoleGroup === group.key ? null : group.key)} className="rounded-full px-2 py-1 text-xs font-medium text-zinc-600 hover:bg-zinc-100">Edit</button><button onClick={() => keepGroupOpen(group.indexes)} className="inline-flex items-center gap-1 rounded-full px-2 py-1 text-xs text-zinc-500 hover:bg-zinc-100"><X className="size-3" /> Keep open</button></div></div>{openRoleGroup === group.key && <div className="mt-3 flex flex-wrap gap-2 border-t border-zinc-200 pt-3">{creditRoles.map(([id, label]) => <button key={id} onClick={() => updateGroupRoles(group.indexes, id)} className={`rounded-full border px-3 py-1.5 text-xs transition ${group.roleIds.includes(id) ? "border-zinc-900 bg-zinc-900 text-white" : "border-zinc-200 bg-white text-zinc-600 hover:border-zinc-400"}`}>{label}</button>)}</div>}</article>)}</div>
      <div className="mt-5 grid gap-4 md:grid-cols-2"><div className="rounded-xl bg-[#f5f5f2] p-4"><p className="text-sm font-medium">Funding</p><div className="mt-3 flex gap-2"><select value={facts.funding.status} onChange={(event) => { setFacts((current) => current ? { ...current, funding: { ...current.funding, status: event.target.value as DeclareFacts["funding"]["status"] } } : current); setStatements(null); }} className="rounded-lg border border-zinc-200 bg-white px-2 py-1.5 text-xs"><option value="reported">Reported</option><option value="none">None</option><option value="unknown">Unknown</option></select><input value={facts.funding.funder ?? ""} onChange={(event) => { setFacts((current) => current ? { ...current, funding: { ...current.funding, funder: event.target.value } } : current); setStatements(null); }} placeholder="Funder name" className="min-w-0 flex-1 rounded-lg border border-zinc-200 bg-white px-2 py-1.5 text-xs outline-none focus:border-zinc-500" /></div><p className="mt-3 text-xs leading-5 text-zinc-600">Funding is an acknowledgement, not an automatic Funding acquisition role.</p></div><div className="rounded-xl bg-[#f5f5f2] p-4"><p className="text-sm font-medium">Competing interests</p><div className="mt-3 flex gap-2"><select value={facts.conflicts.status} onChange={(event) => { setFacts((current) => current ? { ...current, conflicts: { ...current.conflicts, status: event.target.value as DeclareFacts["conflicts"]["status"] } } : current); setStatements(null); }} className="rounded-lg border border-zinc-200 bg-white px-2 py-1.5 text-xs"><option value="none">None declared</option><option value="reported">Reported</option><option value="unknown">Unknown</option></select></div><p className="mt-3 text-xs leading-5 text-zinc-600">An empty source remains unknown; it is never silently treated as no conflict.</p></div></div>
      {analysis?.issues.length ? <p className="mt-5 rounded-xl bg-amber-50 px-4 py-3 text-sm text-amber-900">{analysis.issues.map((issue) => issue.message).join(" ")}</p> : null}
      <button onClick={generateStatements} disabled={busy !== null} className="mt-6 inline-flex items-center gap-2 rounded-full bg-zinc-900 px-5 py-2.5 text-sm font-medium text-white disabled:opacity-50">{busy === "statements" && <LoaderCircle className="size-4 animate-spin" />} Generate approved statements</button>
    </section>}

    {statements && (activeStage === 3 || activeStage === 4) && <section className="rounded-2xl border border-zinc-200 bg-white p-6 sm:p-8"><div className={activeStage === 3 ? "" : "hidden"}><div className="flex flex-wrap items-start justify-between gap-4"><div><p className="text-xs font-semibold uppercase tracking-[0.16em] text-zinc-500">Statements ready</p><h2 className="mt-2 text-xl font-semibold tracking-tight text-zinc-950">Generated from reviewed facts only.</h2></div><span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-100 px-3 py-1.5 text-xs font-semibold text-emerald-800"><Check className="size-3.5" /> Ready to hand off</span></div><pre className="mt-5 whitespace-pre-wrap rounded-xl border border-zinc-200 bg-[#fffefd] p-8 font-[family-name:var(--font-display)] text-base leading-7 text-zinc-900 shadow-sm">{`${statements.contributionStatement}\n\n${statements.fundingStatement}\n\n${statements.conflictStatement}`}</pre><div className="mt-6 flex justify-end"><button onClick={() => setActiveStage(4)} className="rounded-full bg-zinc-900 px-5 py-2.5 text-sm font-medium text-white">Apply to manuscript</button></div></div>
      <div className={activeStage === 4 ? "" : "hidden"}><p className="text-xs font-semibold uppercase tracking-[0.16em] text-zinc-500">Manuscript</p><h3 className="mt-2 text-lg font-semibold tracking-tight text-zinc-950">Apply statements to your manuscript.</h3><p className="mt-2 max-w-2xl text-sm leading-6 text-zinc-700">Your reviewed statements will be added as one complete block.</p><label className="mt-5 inline-flex cursor-pointer items-center gap-2 rounded-full border border-zinc-200 px-4 py-2 text-sm font-semibold transition hover:bg-zinc-50"><FileUp className="size-4" /> {busy === "upload" ? "Uploading…" : uploaded ? "Change file" : "Upload manuscript"}<input type="file" accept=".docx,.pdf,.txt,.rtf,.md,.html,.htm,.tex" className="hidden" onChange={(event) => { const file = event.target.files?.[0]; if (file) void upload(file); }} /></label>
        <div className="mt-4 flex flex-wrap gap-3"><button onClick={apply} disabled={busy !== null || !uploaded} className="rounded-full bg-zinc-900 px-5 py-2.5 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50">{busy === "apply" ? "Preparing…" : "Propose changes"}</button>{jobStatus === "completed" && <button onClick={download} disabled={busy !== null} className="inline-flex items-center gap-2 rounded-full bg-zinc-100 px-5 py-2.5 text-sm font-medium"><Download className="size-4" /> Export document</button>}</div>
      {uploaded && <div className="mt-6 rounded-xl border border-zinc-200 bg-[#f8f8f6] p-4"><div className="flex items-center justify-between gap-3"><div><p className="text-sm font-semibold text-zinc-950">Manuscript preview</p><p className="mt-1 text-xs text-zinc-600">The original document is shown here. Proposed edits appear below as an exact before-and-after review.</p></div><Upload className="size-4 text-zinc-400" /></div>{documentHtml ? <iframe title="Uploaded manuscript preview" sandbox="" srcDoc={documentHtml} className="mt-4 h-80 w-full rounded-lg border border-zinc-200 bg-white" /> : <div className="mt-4 rounded-lg border border-dashed border-zinc-300 bg-white p-5 text-sm text-zinc-500">The uploaded file is stored with SuperDocs. Its exact changed section will appear in the before-and-after proposal below.</div>}</div>}
      {job && <div className={`mt-5 rounded-xl p-4 text-sm ${isJobDelayed ? "bg-amber-50 text-amber-900" : "bg-zinc-50 text-zinc-700"}`}><p>SuperDocs: <span className="font-semibold text-zinc-950">{jobStatus || "processing"}</span>{isJobWorking ? " · applying your already reviewed declaration block as one document change." : jobStatus === "awaiting_approval" ? " · this is an older manual-review job; approve or reject the proposal below before exporting." : ""}</p>{isJobDelayed && <p className="mt-1 text-xs leading-5">This is taking longer than expected. Refresh the status; if it remains unchanged, retry the proposal. Your manuscript has not been edited.</p>}</div>}
      {pendingChanges.length > 0 && <div className="mt-4 space-y-3"><div className="flex flex-wrap items-center justify-between gap-3"><p className="text-sm font-medium">Review proposed changes</p>{pendingChanges.length > 1 && <button onClick={() => void decide(true)} disabled={busy !== null} className="rounded-full bg-zinc-900 px-3 py-1.5 text-xs font-medium text-white">Approve all proposed statements</button>}</div>{pendingChanges.map((change) => <article key={String(change.change_id)} className="rounded-xl border border-zinc-200 p-4 text-sm"><p className="font-medium">{String(change.ai_explanation ?? "Proposed manuscript change")}</p><div className="mt-3 grid gap-3 sm:grid-cols-2"><div className="rounded-lg bg-rose-50 p-3 text-zinc-600"><p className="mb-1 text-[11px] font-medium uppercase tracking-wide text-rose-700">Current</p>{stripHtml(change.old_html) || "New content"}</div><div className="rounded-lg bg-emerald-50 p-3 text-zinc-700"><p className="mb-1 text-[11px] font-medium uppercase tracking-wide text-emerald-700">Proposed</p>{stripHtml(change.new_html)}</div></div><div className="mt-3 flex gap-2"><button onClick={() => void decide(true, String(change.change_id))} disabled={busy !== null} className="rounded-full bg-zinc-900 px-3 py-1.5 text-xs font-medium text-white">Approve</button><button onClick={() => void decide(false, String(change.change_id))} disabled={busy !== null} className="rounded-full bg-zinc-100 px-3 py-1.5 text-xs font-medium">Reject</button></div></article>)}</div>}
      </div>
    </section>}
    {message && <p role="status" className="rounded-xl bg-zinc-100 px-4 py-3 text-sm text-zinc-700">{message}</p>}
  </div>;
};
