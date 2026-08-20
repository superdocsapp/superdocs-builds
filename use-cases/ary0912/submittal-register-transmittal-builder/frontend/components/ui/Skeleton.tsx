import { cn } from "@/lib/utils";

interface SkeletonProps {
  className?: string;
}

export function Skeleton({ className }: SkeletonProps) {
  return (
    <div
      aria-hidden
      className={cn("animate-pulse rounded bg-slate-200", className)}
    />
  );
}

export function SkeletonRow() {
  return (
    <div className="flex items-center gap-4 px-4 py-3">
      <Skeleton className="h-4 w-14" />
      <Skeleton className="h-4 w-48" />
      <Skeleton className="h-4 w-20" />
      <Skeleton className="h-4 w-32" />
      <Skeleton className="h-5 w-24 rounded-full" />
    </div>
  );
}

export function SkeletonCard() {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-5 space-y-3">
      <div className="flex items-center justify-between">
        <Skeleton className="h-5 w-32" />
        <Skeleton className="h-5 w-20 rounded-full" />
      </div>
      <Skeleton className="h-4 w-full" />
      <Skeleton className="h-4 w-3/4" />
      <Skeleton className="h-4 w-1/2" />
    </div>
  );
}

export function SkeletonStatCard() {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-5 space-y-2">
      <Skeleton className="h-4 w-24" />
      <Skeleton className="h-8 w-16" />
    </div>
  );
}
