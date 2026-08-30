import type { ComponentType } from "react";
import type { LucideProps } from "lucide-react";

export function MetricCard({ label, value, icon: Icon }: { label: string; value: string; icon: ComponentType<LucideProps> }) {
  return (
    <div className="rounded-md border border-line bg-paper-0 p-4">
      <div className="flex items-center gap-2 text-text-tertiary">
        <Icon className="h-4 w-4" aria-hidden="true" />
        <span className="text-xs font-medium uppercase tracking-wide">{label}</span>
      </div>
      <p className="font-numeric mt-2 text-2xl font-semibold text-text-primary">{value}</p>
    </div>
  );
}
