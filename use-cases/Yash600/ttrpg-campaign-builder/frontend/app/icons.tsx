// app/icons.tsx -- small hand-rolled line icons, no external icon library.
// Kept dependency-free on purpose, same as the healthcare build: this
// project's only runtime deps are next/react/react-dom (see package.json).

type IconProps = { size?: number; className?: string };

const base = (size: number) => ({
  width: size,
  height: size,
  viewBox: "0 0 24 24",
  fill: "none" as const,
  stroke: "currentColor",
  strokeWidth: 1.8,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
});

export function IconCrown({ size = 18, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M3 8l4 4 5-7 5 7 4-4-2 10H5L3 8z" />
      <path d="M5 18h14" />
    </svg>
  );
}

export function IconBook({ size = 18, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M4 4.5c2-1 5-1 8 0v15c-3-1-6-1-8 0v-15z" />
      <path d="M20 4.5c-2-1-5-1-8 0v15c3-1 6-1 8 0v-15z" />
    </svg>
  );
}

export function IconUsers({ size = 18, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <circle cx="9" cy="8" r="3.2" />
      <path d="M3.5 19c0-3.2 2.5-5.5 5.5-5.5s5.5 2.3 5.5 5.5" />
      <path d="M16 8.2c1.3.3 2.3 1.5 2.3 2.9 0 1.4-1 2.6-2.3 2.9" />
      <path d="M15.5 13.7c2 .5 3.6 2.4 3.6 5.3" />
    </svg>
  );
}

export function IconScroll({ size = 18, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M6 3.5h11a2 2 0 0 1 2 2V17a2 2 0 0 1-2 2H8" />
      <path d="M6 3.5A2 2 0 0 0 4 5.5v13a2 2 0 0 0 2 2h2" />
      <path d="M9 8h7" />
      <path d="M9 11.5h7" />
      <path d="M9 15h4" />
    </svg>
  );
}

export function IconWand({ size = 18, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M4 20L16 8" />
      <path d="M14 4l1 2 2 1-2 1-1 2-1-2-2-1 2-1 1-2z" />
      <path d="M19 12l.7 1.4 1.4.7-1.4.7-.7 1.4-.7-1.4-1.4-.7 1.4-.7.7-1.4z" />
    </svg>
  );
}

export function IconMap({ size = 18, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M9 4.5L4 6.5v13l5-2 6 2 5-2v-13l-5 2-6-2z" />
      <path d="M9 4.5v13" />
      <path d="M15 6.5v13" />
    </svg>
  );
}

export function IconPackage({ size = 18, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M12 3l8 4.5v9L12 21l-8-4.5v-9L12 3z" />
      <path d="M4.5 7.5L12 12l7.5-4.5" />
      <path d="M12 12v9" />
    </svg>
  );
}

export function IconPencil({ size = 18, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M12 20h9" />
      <path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z" />
    </svg>
  );
}

export function IconSparkle({ size = 18, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M12 3l1.8 4.6L18.5 9.4l-4.7 1.8L12 16l-1.8-4.8L5.5 9.4l4.7-1.8L12 3z" />
      <path d="M19 15l.9 2.3L22.2 18l-2.3.9L19 21.2l-.9-2.3L15.8 18l2.3-.7L19 15z" />
    </svg>
  );
}

export function IconLinkBroken({ size = 18, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M9 15l6-6" />
      <path d="M13 4l1.5-1.5a3.5 3.5 0 0 1 5 5L18 9" />
      <path d="M11 15l-1.5 1.5a3.5 3.5 0 0 1-5-5L6 10" />
      <path d="M15 5l1 1" strokeDasharray="2 2" />
      <path d="M18 15l1 1" strokeDasharray="2 2" />
    </svg>
  );
}

export function IconEyeCheck({ size = 18, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z" />
      <circle cx="12" cy="12" r="2.6" />
    </svg>
  );
}

export function IconDownload({ size = 18, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M12 3v12" />
      <path d="M7 10l5 5 5-5" />
      <path d="M4 19h16" />
    </svg>
  );
}

export function IconFileText({ size = 18, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M6 2.5h9l4 4v15H6V2.5z" />
      <path d="M15 2.5v4h4" />
      <path d="M9 12h6" />
      <path d="M9 15.5h6" />
      <path d="M9 8.5h3" />
    </svg>
  );
}

export function IconCheckCircle({ size = 18, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <circle cx="12" cy="12" r="9" />
      <path d="M8.3 12.3l2.4 2.4 5-5.2" />
    </svg>
  );
}

export function IconAlertTriangle({ size = 18, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M12 4.5l9 15.5H3l9-15.5z" />
      <path d="M12 10v4.2" />
      <circle cx="12" cy="17" r="0.15" fill="currentColor" stroke="none" />
    </svg>
  );
}

export function IconClock({ size = 18, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3.2 2" />
    </svg>
  );
}

export function IconArrowRight({ size = 18, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M4 12h16" />
      <path d="M14 6l6 6-6 6" />
    </svg>
  );
}

export function IconDatabase({ size = 18, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <ellipse cx="12" cy="5.5" rx="8" ry="3" />
      <path d="M4 5.5V12c0 1.7 3.6 3 8 3s8-1.3 8-3V5.5" />
      <path d="M4 12v6.5c0 1.7 3.6 3 8 3s8-1.3 8-3V12" />
    </svg>
  );
}

export function IconX({ size = 18, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M6 6l12 12" />
      <path d="M18 6L6 18" />
    </svg>
  );
}

export function IconLayers({ size = 18, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M12 3l9 5-9 5-9-5 9-5z" />
      <path d="M3 13l9 5 9-5" />
    </svg>
  );
}

export function IconImage({ size = 18, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <circle cx="8.5" cy="9.5" r="1.7" />
      <path d="M21 16l-5.5-5.5a1.5 1.5 0 0 0-2.1 0L4 19" />
    </svg>
  );
}

export function IconTrash({ size = 18, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M4 7h16" />
      <path d="M9 7V4.5h6V7" />
      <path d="M6 7l1 13a1.5 1.5 0 0 0 1.5 1.4h7a1.5 1.5 0 0 0 1.5-1.4L18 7" />
      <path d="M10 11v6" />
      <path d="M14 11v6" />
    </svg>
  );
}

export function IconSave({ size = 18, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M5 3.5h11L20 8v12.5H5V3.5z" />
      <path d="M8 3.5V9h8V3.5" />
      <path d="M8 14.5h8v6H8v-6z" />
    </svg>
  );
}

export function IconSearch({ size = 18, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <circle cx="10.5" cy="10.5" r="6.5" />
      <path d="M20 20l-5-5" />
    </svg>
  );
}

export function IconUpload({ size = 18, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M12 20V8" />
      <path d="M7 13l5-5 5 5" />
      <path d="M4 19h16" />
    </svg>
  );
}

// Used on the homepage's process-flow diagram to mark the steps that are an
// actual call to the SuperDocs API (document upload, chat_async edit,
// export) versus steps this app computes itself (linking, staleness).
export function IconCloud({ size = 18, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M7 18h10a4 4 0 0 0 .5-7.97A5.5 5.5 0 0 0 7.1 8.5 4 4 0 0 0 7 18z" />
    </svg>
  );
}
