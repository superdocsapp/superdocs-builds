import { HugeiconsIcon } from "@hugeicons/react";
import { AiBrain01Icon, BookOpen01Icon, MagicWand01Icon, Task01Icon, UserGroupIcon } from "@hugeicons/core-free-icons";
import { LoaderCircle } from "lucide-react";

type ProjectNotesProps = {
  authorNames: string;
  contributions: string;
  funding: string;
  conflicts: string;
  authorCount: number;
  busy: string | null;
  onAuthorNamesChange: (value: string) => void;
  onContributionsChange: (value: string) => void;
  onFundingChange: (value: string) => void;
  onConflictsChange: (value: string) => void;
  onAnalyze: () => void;
};

export const ProjectNotes = ({ authorNames, contributions, funding, conflicts, authorCount, busy, onAuthorNamesChange, onContributionsChange, onFundingChange, onConflictsChange, onAnalyze }: ProjectNotesProps) => (
  <section className="rounded-2xl border border-zinc-200 bg-white p-5 sm:p-6">
    <div className="flex flex-wrap items-start justify-between gap-4"><div><p className="text-xs font-semibold uppercase tracking-[0.16em] text-zinc-500">01 · Project context</p><h2 className="mt-2 text-xl font-semibold tracking-tight text-zinc-950">Start with the notes you already have.</h2><p className="mt-2 text-sm text-zinc-700">Declare will only map the authors listed here.</p></div><span className="rounded-full bg-[#edf4f0] px-3 py-1.5 text-xs font-semibold text-[#426657]">CRediT · 14 roles</span></div>
    <div className="mt-5 grid gap-4"><div className="grid gap-4 sm:grid-cols-[1.25fr_0.75fr]"><label className="text-sm font-medium"><span className="flex items-center gap-1.5"><HugeiconsIcon icon={UserGroupIcon} size={16} strokeWidth={1.8} /> Authors</span><span className="mt-1 block text-xs font-normal text-zinc-500">One author per line</span><textarea value={authorNames} onChange={(event) => onAuthorNamesChange(event.target.value)} className="mt-2 min-h-24 w-full rounded-xl border border-zinc-200 p-3 font-normal outline-none transition focus:border-zinc-600" /></label><div className="rounded-xl bg-[#f5f5f2] p-3.5"><p className="flex items-center gap-1.5 text-sm font-medium"><HugeiconsIcon icon={BookOpen01Icon} size={16} strokeWidth={1.8} /> Submission profile</p><p className="mt-2 text-sm leading-6 text-zinc-600">Standard CRediT contributor roles are selected for this project.</p></div></div>
      <label className="text-sm font-medium"><span className="flex items-center gap-1.5"><HugeiconsIcon icon={AiBrain01Icon} size={16} strokeWidth={1.8} /> Contribution notes</span><textarea value={contributions} onChange={(event) => onContributionsChange(event.target.value)} className="mt-2 min-h-32 w-full rounded-xl border border-zinc-200 p-3 font-normal outline-none transition focus:border-zinc-600" /></label>
      <div className="grid gap-4 sm:grid-cols-2"><label className="text-sm font-medium"><span className="flex items-center gap-1.5"><HugeiconsIcon icon={BookOpen01Icon} size={16} strokeWidth={1.8} /> Funding acknowledgement <span className="font-normal text-zinc-500">(optional)</span></span><textarea value={funding} onChange={(event) => onFundingChange(event.target.value)} className="mt-2 min-h-20 w-full rounded-xl border border-zinc-200 p-3 font-normal outline-none transition focus:border-zinc-600" /></label><label className="text-sm font-medium"><span className="flex items-center gap-1.5"><HugeiconsIcon icon={Task01Icon} size={16} strokeWidth={1.8} /> Competing interests <span className="font-normal text-zinc-500">(optional)</span></span><textarea value={conflicts} onChange={(event) => onConflictsChange(event.target.value)} className="mt-2 min-h-20 w-full rounded-xl border border-zinc-200 p-3 font-normal outline-none transition focus:border-zinc-600" /></label></div>
    </div>
    <button onClick={onAnalyze} disabled={busy !== null || !authorCount || !contributions.trim()} className="mt-5 inline-flex items-center gap-2 rounded-full bg-zinc-900 px-5 py-2.5 text-sm font-medium text-white transition hover:bg-zinc-700 disabled:cursor-not-allowed disabled:opacity-50">{busy === "analysis" ? <LoaderCircle className="size-4 animate-spin" /> : <HugeiconsIcon icon={MagicWand01Icon} size={17} strokeWidth={1.8} />} Analyze with CRediT</button>
  </section>
);
