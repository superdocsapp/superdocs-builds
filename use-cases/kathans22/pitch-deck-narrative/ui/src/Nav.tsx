import { hrefFor, type Screen } from './screen'
import './Nav.css'

const LINKS: { id: Screen; label: string }[] = [
  { id: 'divergence', label: 'Divergence' },
  { id: 'verticals', label: 'Verticals' },
  { id: 'generate', label: 'Generate' },
  { id: 'narratives', label: 'Narratives' },
]

type Props = {
  current: Screen
}

export default function Nav({ current }: Props) {
  return (
    <nav className="nav" aria-label="Screens">
      {LINKS.map((l) => (
        <a
          key={l.id}
          href={hrefFor(l.id)}
          className={current === l.id ? 'nav-link is-current' : 'nav-link'}
          aria-current={current === l.id ? 'page' : undefined}
        >
          {l.label}
        </a>
      ))}
    </nav>
  )
}
