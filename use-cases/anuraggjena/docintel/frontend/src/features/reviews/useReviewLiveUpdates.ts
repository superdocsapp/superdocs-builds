import { useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'

export function useReviewLiveUpdates(reviewId: string, status?: string) {
  const queryClient = useQueryClient()
  const enabled = status === 'in_review'

  useEffect(() => {
    if (!enabled || !reviewId) return

    const interval = window.setInterval(() => {
      void queryClient.invalidateQueries({ queryKey: ['review', reviewId] })
      void queryClient.invalidateQueries({ queryKey: ['claims', reviewId] })
    }, 3000)

    return () => window.clearInterval(interval)
  }, [enabled, reviewId, queryClient])
}
