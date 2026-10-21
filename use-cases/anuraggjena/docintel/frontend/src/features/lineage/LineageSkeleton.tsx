import { Skeleton } from '@/shared/components/ui/skeleton'

export function LineageSkeleton() {
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <Skeleton className="h-4 w-40" />
        <Skeleton className="h-4 w-24" />
      </div>
      <div className="h-[600px] rounded-lg border p-6">
        <div className="flex flex-col items-center gap-8">
          <Skeleton className="h-20 w-56 rounded-lg" />
          <Skeleton className="h-4 w-px" />
          <div className="flex gap-8">
            <Skeleton className="h-20 w-56 rounded-lg" />
            <Skeleton className="h-20 w-56 rounded-lg" />
          </div>
          <Skeleton className="h-4 w-px" />
          <Skeleton className="h-20 w-56 rounded-lg" />
        </div>
      </div>
    </div>
  )
}
