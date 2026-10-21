import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { workspaceApi } from '@/core/api/client'
import { WorkspaceCard } from './WorkspaceCard'
import { CreateWorkspaceModal } from './CreateWorkspaceModal'
import type { WorkflowTypeValue } from './CreateWorkspaceForm'

interface WorkspaceListProps {
  onSelectWorkspace?: (workspaceId: string) => void
}

export function WorkspaceList({ onSelectWorkspace }: WorkspaceListProps = {}) {
  const [isModalOpen, setIsModalOpen] = useState(false)
  const queryClient = useQueryClient()

  const { data: workspaces, isLoading, error } = useQuery({
    queryKey: ['workspaces'],
    queryFn: () => workspaceApi.list()
  })

  const createMutation = useMutation({
    mutationFn: (data: { name: string; workflowType: WorkflowTypeValue }) =>
      workspaceApi.create({
        name: data.name,
        workflow_type: data.workflowType,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workspaces'] })
    }
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => workspaceApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workspaces'] })
    }
  })

  const handleCreate = (name: string, workflowType: WorkflowTypeValue) => {
    createMutation.mutate({ name, workflowType })
  }

  const handleDelete = (id: string) => {
    if (confirm('Are you sure you want to delete this workspace?')) {
      deleteMutation.mutate(id)
    }
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-gray-600">Loading workspaces...</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-red-600">Error loading workspaces: {(error as Error).message}</div>
      </div>
    )
  }

  return (
    <div className="max-w-7xl mx-auto">
      <div className="flex justify-between items-center mb-8">
        <h1 className="text-3xl font-bold text-gray-900">My Workspaces</h1>
        <button
          onClick={() => setIsModalOpen(true)}
          className="px-6 py-3 text-sm font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700"
        >
          Create Workspace
        </button>
      </div>

      {workspaces && workspaces.length === 0 ? (
        <div className="text-center py-12">
          <p className="text-gray-600 mb-4">No workspaces yet</p>
          <button
            onClick={() => setIsModalOpen(true)}
            className="text-blue-600 hover:text-blue-700 font-medium"
          >
            Create your first workspace
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {workspaces?.map((workspace) => (
            <WorkspaceCard
              key={workspace.id}
              workspace={workspace}
              onDelete={handleDelete}
              onOpen={onSelectWorkspace}
            />
          ))}
        </div>
      )}

      <CreateWorkspaceModal
        open={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        onCreate={handleCreate}
        isSubmitting={createMutation.isPending}
      />
    </div>
  )
}
