import type { ReactElement, SVGProps } from "react";
import type { NavIconName } from "../nav";

type IconProps = SVGProps<SVGSVGElement>;

function Svg(props: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      width="22"
      height="22"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...props}
    />
  );
}

export function IconOverview(props: IconProps) {
  return (
    <Svg {...props}>
      <rect x="3" y="3" width="7" height="7" rx="1.5" />
      <rect x="14" y="3" width="7" height="7" rx="1.5" />
      <rect x="3" y="14" width="7" height="7" rx="1.5" />
      <rect x="14" y="14" width="7" height="7" rx="1.5" />
    </Svg>
  );
}

export function IconSources(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M8 6h13M8 12h13M8 18h13" />
      <path d="M3 6h.01M3 12h.01M3 18h.01" />
    </Svg>
  );
}

export function IconArchitecture(props: IconProps) {
  return (
    <Svg {...props}>
      <circle cx="6" cy="7" r="2.2" />
      <circle cx="18" cy="7" r="2.2" />
      <circle cx="12" cy="17" r="2.2" />
      <path d="M8 8.2 10.4 15M16 8.2 13.6 15" />
    </Svg>
  );
}

export function IconExceptions(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M12 3 21 19H3L12 3z" />
      <path d="M12 9v5M12 16.5v.5" />
    </Svg>
  );
}

export function IconFramework(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M4 6h16v12H4z" />
      <path d="M4 10h16M10 6v12" />
    </Svg>
  );
}

export function IconProfiles(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M8 19a4 4 0 0 1 8 0" />
      <circle cx="12" cy="9" r="3" />
      <path d="M4 19a3.2 3.2 0 0 1 4.5-3M20 19a3.2 3.2 0 0 0-4.5-3" />
    </Svg>
  );
}

export function IconImpact(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M5 12h14M13 6l6 6-6 6" />
    </Svg>
  );
}

export function IconReview(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M5 12.5 9.5 17 19 7" />
    </Svg>
  );
}

export function IconExport(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M12 4v10M8 8l4-4 4 4" />
      <path d="M5 16v3h14v-3" />
    </Svg>
  );
}

export function IconMenu(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M4 7h16M4 12h16M4 17h16" />
    </Svg>
  );
}

export function IconClose(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M6 6l12 12M18 6 6 18" />
    </Svg>
  );
}

export function IconCollapse(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M15 6 9 12l6 6" />
    </Svg>
  );
}

export function IconExpand(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M9 6l6 6-6 6" />
    </Svg>
  );
}

export function IconDocs(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M7 4h8l4 4v12H7z" />
      <path d="M15 4v4h4M9 12h6M9 16h6" />
    </Svg>
  );
}

export function IconMark(props: IconProps) {
  return (
    <svg viewBox="0 0 32 32" width="36" height="36" aria-hidden="true" {...props} className="brand-mark">
      <rect width="32" height="32" rx="9" fill="currentColor" opacity="0.16" />
      <path
        d="M8 21.5V11.2L16 7l8 4.2v10.3L16 25.5 8 21.5z"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
      <path d="M16 7.2v18M8.2 11.3 16 15.2l7.8-3.9" fill="none" stroke="currentColor" strokeWidth="1.6" />
    </svg>
  );
}

const NAV_ICONS: Record<NavIconName, (props: IconProps) => ReactElement> = {
  overview: IconOverview,
  sources: IconSources,
  architecture: IconArchitecture,
  exceptions: IconExceptions,
  framework: IconFramework,
  profiles: IconProfiles,
  impact: IconImpact,
  review: IconReview,
  export: IconExport,
};

export function NavIcon({ name, ...props }: { name: NavIconName } & IconProps) {
  const Icon = NAV_ICONS[name];
  return <Icon {...props} />;
}
