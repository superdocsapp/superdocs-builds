import { Skeleton } from '@/shared/components/ui/skeleton'

export function ReviewSkeleton() {
  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <Skeleton className="h-6 w-48" />
        <Skeleton className="h-4 w-32" />
      </div>
      <div className="space-y-3">
        {Array.from({ length: 3 }).map((_, index) => (
          <div key={index} className="space-y-3 rounded-lg border p-4">
            <div className="flex items-center justify-between gap-3">
              <Skeleton className="h-5 w-24 rounded-full" />
              <Skeleton className="h-8 w-20" />
            </div>
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-3/4" />
          </div>
        ))}
      </div>
    </div>
  )
}
