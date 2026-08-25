import React from 'react'
import type { DiffToken } from '@/features/reviews/buildDocumentDiff'

interface Props {
  tokens: DiffToken[]
}

export const DiffText: React.FC<Props> = ({ tokens }) => {
  if (!tokens || tokens.length === 0) return null

  return (
    <span className="text-sm leading-relaxed text-slate-800">
      {tokens.map((token, i) => {
        if (token.type === 'equal') {
          return <span key={i}>{token.text}{' '}</span>
        }
        if (token.type === 'delete') {
          return (
            <span
              key={i}
              className="inline bg-rose-100 text-rose-800 line-through decoration-rose-600 px-1 py-0.5 rounded font-medium mr-1"
            >
              {token.text}
            </span>
          )
        }
        if (token.type === 'insert') {
          return (
            <span
              key={i}
              className="inline bg-emerald-100 text-emerald-900 px-1 py-0.5 rounded font-medium mr-1"
            >
              {token.text}
            </span>
          )
        }
        if (token.type === 'modified') {
          return (
            <span
              key={i}
              className="inline bg-amber-100 text-amber-900 px-1 py-0.5 rounded font-medium mr-1"
            >
              {token.text}
            </span>
          )
        }
        return null
      })}
    </span>
  )
}
