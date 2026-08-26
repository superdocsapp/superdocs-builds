import { NavLink } from 'react-router-dom';

const LINKS = [
  { to: '/', label: 'Integrity', end: true },
  { to: '/countries', label: 'Countries' },
  { to: '/generate', label: 'Generate' },
  { to: '/packs', label: 'Packs' },
  { to: '/amend', label: 'Amend' },
];

export default function Nav() {
  return (
    <nav className="app-nav">
      <div className="app-nav-inner">
        {LINKS.map(({ to, label, end }) => (
          <NavLink key={to} to={to} end={end} className={({ isActive }) => (isActive ? 'active' : undefined)}>
            {label}
          </NavLink>
        ))}
      </div>
    </nav>
  );
}
