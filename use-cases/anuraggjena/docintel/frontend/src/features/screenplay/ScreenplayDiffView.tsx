import React from 'react'
import type { DiffToken } from '@/core/api/screenplayApi'

interface Props {
  tokens: DiffToken[]
}

export const ScreenplayDiffView: React.FC<Props> = ({ tokens }) => {
  if (!tokens || tokens.length === 0) return null

  return (
    <span className="font-mono text-sm">
      {tokens.map((token, i) => {
        if (token.type === 'equal') {
          return <span key={i}>{token.text}</span>
        }
        if (token.type === 'delete') {
          return (
            <span key={i} className="bg-red-100 text-red-700 line-through">
              {token.text}
            </span>
          )
        }
        if (token.type === 'insert') {
          return (
            <span key={i} className="bg-green-100 text-green-700">
              {token.text}
            </span>
          )
        }
        return null
      })}
    </span>
  )
}
