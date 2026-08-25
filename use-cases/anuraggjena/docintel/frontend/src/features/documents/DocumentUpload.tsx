import React, { useState, useRef } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { documentApi, DocumentRole } from '@/core/api/documentApi'

interface DocumentUploadProps {
  workspaceId: string
}

const MAX_FILE_SIZE = 50 * 1024 * 1024 // 50MB

const ROLE_OPTIONS: Array<{ value: DocumentRole; label: string; accept: string; hint: string }> = [
  {
    value: 'product_spec',
    label: 'Product Specification',
    accept: '.pdf,.doc,.docx,.txt',
    hint: 'PDF, Word, or plain text specification sheets',
  },
  {
    value: 'ruling',
    label: 'Classification Ruling',
    accept: '.pdf,.doc,.docx,.txt',
    hint: 'Prior ruling or decision documents',
  },
  {
    value: 'product_image',
    label: 'Product Image',
    accept: '.jpg,.jpeg,.png,.gif,.webp,image/jpeg,image/png,image/gif,image/webp',
    hint: 'JPEG, PNG, GIF, or WebP product photos',
  },
  {
    value: 'other',
    label: 'Other Document',
    accept: '.pdf,.doc,.docx,.txt',
    hint: 'Supporting reference documents',
  },
]

export const DocumentUpload: React.FC<DocumentUploadProps> = ({ workspaceId }) => {
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [selectedRole, setSelectedRole] = useState<DocumentRole>('product_spec')
  const fileInputRef = useRef<HTMLInputElement>(null)
  const queryClient = useQueryClient()

  const roleConfig = ROLE_OPTIONS.find((option) => option.value === selectedRole) ?? ROLE_OPTIONS[0]

  const uploadMutation = useMutation({
    mutationFn: (file: File) => documentApi.upload(workspaceId, file, selectedRole),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents', workspaceId] })
      setSelectedFile(null)
      if (fileInputRef.current) {
        fileInputRef.current.value = ''
      }
    },
  })

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (file) {
      if (file.size > MAX_FILE_SIZE) {
        alert(`File size exceeds ${MAX_FILE_SIZE / 1024 / 1024}MB limit`)
        event.target.value = ''
        return
      }
      setSelectedFile(file)
    }
  }

  const handleUpload = () => {
    if (selectedFile) {
      uploadMutation.mutate(selectedFile)
    }
  }

  return (
    <div className="bg-white p-6 rounded-lg shadow">
      <h2 className="text-xl font-semibold mb-4">Upload Document</h2>

      <div className="space-y-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Document type</label>
          <select
            value={selectedRole}
            onChange={(e) => {
              setSelectedRole(e.target.value as DocumentRole)
              setSelectedFile(null)
              if (fileInputRef.current) {
                fileInputRef.current.value = ''
              }
            }}
            className="w-full border rounded px-3 py-2 text-sm"
            disabled={uploadMutation.isPending}
          >
            {ROLE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          <p className="text-xs text-gray-500 mt-1">{roleConfig.hint}</p>
        </div>

        <div>
          <input
            ref={fileInputRef}
            id="file-input"
            type="file"
            accept={roleConfig.accept}
            onChange={handleFileChange}
            className="block w-full text-sm text-gray-500
              file:mr-4 file:py-2 file:px-4
              file:rounded-md file:border-0
              file:text-sm file:font-semibold
              file:bg-blue-50 file:text-blue-700
              hover:file:bg-blue-100"
            disabled={uploadMutation.isPending}
          />
        </div>

        {selectedFile && (
          <div className="text-sm text-gray-600">
            Selected: {selectedFile.name} ({(selectedFile.size / 1024).toFixed(2)} KB)
          </div>
        )}

        <button
          onClick={handleUpload}
          disabled={!selectedFile || uploadMutation.isPending}
          className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
        >
          {uploadMutation.isPending ? 'Uploading...' : 'Upload'}
        </button>

        {uploadMutation.isError && (
          <div className="text-sm text-red-600">
            Upload failed. Check the file type and size, then try again.
          </div>
        )}

        {uploadMutation.isSuccess && (
          <div className="text-sm text-green-600">
            Document uploaded successfully.
          </div>
        )}
      </div>
    </div>
  )
}
