import { Skeleton } from '@/shared/components/ui/skeleton'

export function DocumentRowSkeleton() {
  return (
    <div className="flex items-center gap-4 border-b py-3 last:border-b-0">
      <Skeleton className="h-4 flex-1" />
      <Skeleton className="hidden h-4 w-24 sm:block" />
      <Skeleton className="hidden h-4 w-20 md:block" />
      <Skeleton className="hidden h-4 w-28 lg:block" />
      <Skeleton className="h-8 w-16 shrink-0" />
    </div>
  )
}
