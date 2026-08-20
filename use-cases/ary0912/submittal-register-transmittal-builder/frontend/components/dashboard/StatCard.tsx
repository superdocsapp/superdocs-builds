import { cn } from "@/lib/utils";

interface StatCardProps {
  label: string;
  value: number | string;
  variant?: "default" | "warning" | "danger" | "success";
  description?: string;
}

export function StatCard({ label, value, variant = "default", description }: StatCardProps) {
  return (
    <div
      className={cn(
        "rounded-lg border bg-white p-5",
        variant === "default" && "border-slate-200",
        variant === "warning" && "border-amber-200 bg-amber-50",
        variant === "danger" && "border-red-200 bg-red-50",
        variant === "success" && "border-green-200 bg-green-50",
      )}
    >
      <p className={cn(
        "text-xs font-medium uppercase tracking-wide",
        variant === "default" && "text-slate-500",
        variant === "warning" && "text-amber-700",
        variant === "danger" && "text-red-700",
        variant === "success" && "text-green-700",
      )}>
        {label}
      </p>
      <p className={cn(
        "mt-1.5 text-3xl font-semibold tabular-nums",
        variant === "default" && "text-slate-900",
        variant === "warning" && "text-amber-800",
        variant === "danger" && "text-red-800",
        variant === "success" && "text-green-800",
      )}>
        {value}
      </p>
      {description && (
        <p className="mt-1 text-xs text-slate-500">{description}</p>
      )}
    </div>
  );
}
