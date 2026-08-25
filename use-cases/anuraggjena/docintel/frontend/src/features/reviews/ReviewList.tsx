import React from 'react'
import { useQuery } from '@tanstack/react-query'
import { reviewApi } from '@/core/api/reviewApi'
import { formatDate } from '@/shared/utils/formatDate'

interface ReviewListProps {
  workspaceId: string
  onSelectReview: (reviewId: string) => void
}

export const ReviewList: React.FC<ReviewListProps> = ({ workspaceId, onSelectReview }) => {
  const { data: reviews, isLoading, error } = useQuery({
    queryKey: ['reviews', workspaceId],
    queryFn: () => reviewApi.listWorkspaceReviews(workspaceId),
  })

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'approved':
        return 'bg-green-100 text-green-800'
      case 'rejected':
        return 'bg-red-100 text-red-800'
      default:
        return 'bg-yellow-100 text-yellow-800'
    }
  }

  if (isLoading) {
    return <div className="text-center py-8">Loading reviews...</div>
  }

  if (error) {
    return <div className="text-center py-8 text-red-600">Error loading reviews</div>
  }

  return (
    <div className="bg-white p-6 rounded-lg shadow">
      <h2 className="text-xl font-semibold mb-4">Reviews</h2>

      {reviews && reviews.length === 0 ? (
        <p className="text-gray-500 text-center py-8">
          No reviews yet. Create a review after running a workflow.
        </p>
      ) : (
        <div className="space-y-3">
          {reviews?.map((review) => (
            <div
              key={review.id}
              onClick={() => onSelectReview(review.id)}
              className="border rounded-lg p-4 hover:border-blue-500 hover:shadow-md transition-all cursor-pointer"
            >
              <div className="flex items-start justify-between">
                <div className="flex-1">
                  <div className="flex items-center gap-2 mb-2">
                    <span className={`px-2 py-1 text-xs font-semibold rounded ${getStatusColor(review.status)}`}>
                      {review.status}
                    </span>
                  </div>
                  <p className="text-sm text-gray-600 mb-1">
                    Workflow Run: {review.workflow_run_id.substring(0, 8)}...
                  </p>
                  <p className="text-xs text-gray-400">{formatDate(review.created_at)}</p>
                </div>
                <button className="text-blue-600 hover:text-blue-700 text-sm font-medium">
                  View →
                </button>
              </div>

              {review.notes && (
                <p className="text-sm text-gray-600 mt-3 pt-3 border-t">
                  {review.notes}
                </p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
