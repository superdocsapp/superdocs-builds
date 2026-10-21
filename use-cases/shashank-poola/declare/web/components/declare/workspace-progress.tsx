import { Check } from "lucide-react";

type WorkspaceProgressProps = {
  activeStage: number;
  hasReview: boolean;
  hasStatements: boolean;
  hasJob: boolean;
  onStageChange: (stage: number) => void;
};

export const WorkspaceProgress = ({ activeStage, hasReview, hasStatements, hasJob, onStageChange }: WorkspaceProgressProps) => (
  <nav aria-label="Declare progress" className="py-1">
    <ol className="flex gap-1 overflow-x-auto text-sm sm:gap-4">
      {[[1, "Contributions", true], [2, "Review", hasReview], [3, "Statements", hasStatements], [4, "Manuscript", hasJob || hasStatements]].map(([stage, label, reachable]) => {
        const number = Number(stage);
        const completed = number < activeStage;
        const active = number === activeStage;
        return <li key={number} className="shrink-0"><button type="button" disabled={!reachable} onClick={() => onStageChange(number)} className={`flex items-center gap-2 rounded-full px-2.5 py-1.5 font-medium transition disabled:cursor-default ${active ? "bg-zinc-950 text-white" : completed ? "text-zinc-700 hover:bg-zinc-100 hover:text-zinc-950" : "text-zinc-400"}`}><span className={`flex size-5 items-center justify-center rounded-full border text-[11px] ${active ? "border-white/40 text-white" : completed ? "border-zinc-400 bg-zinc-100 text-zinc-700" : "border-zinc-300"}`}>{completed ? <Check className="size-3" /> : number}</span>{label}</button></li>;
      })}
    </ol>
  </nav>
);
