import { Skeleton } from '@/shared/components/ui/skeleton'

export function KnowledgeCardSkeleton() {
  return (
    <div className="flex flex-col gap-3 rounded-lg border p-4">
      <div className="flex items-start justify-between gap-2">
        <Skeleton className="h-5 w-20 rounded-full" />
        <Skeleton className="h-3 w-16" />
      </div>
      <Skeleton className="h-4 w-3/4" />
      <Skeleton className="h-3 w-full" />
      <Skeleton className="h-3 w-5/6" />
      <div className="flex gap-2">
        <Skeleton className="h-5 w-14 rounded-full" />
        <Skeleton className="h-5 w-16 rounded-full" />
      </div>
    </div>
  )
}
