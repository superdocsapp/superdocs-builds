type IconName =
  | "review"
  | "documents"
  | "upload"
  | "download"
  | "eye"
  | "trash"
  | "check"
  | "close"
  | "refresh"
  | "chevron-down"
  | "chevron-up"
  | "chevron-right"
  | "compare"
  | "logs"
  | "brand"
  | "search"
  | "plus";

const STROKE = {
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.6,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
};

export function Icon({ name, size = 18 }: { name: IconName; size?: number }) {
  switch (name) {
    case "review":
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" {...STROKE}>
          <circle cx="12" cy="12" r="8.5" />
          <polyline points="8.5,12.3 11,14.8 15.5,9.5" />
        </svg>
      );
    case "documents":
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" {...STROKE}>
          <path d="M6 3.5h8l4 4V20a.5.5 0 0 1-.5.5h-11A.5.5 0 0 1 6 20z" />
          <path d="M14 3.5V8h4" />
          <line x1="9" y1="12.5" x2="15" y2="12.5" />
          <line x1="9" y1="16" x2="15" y2="16" />
        </svg>
      );
    case "upload":
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" {...STROKE}>
          <path d="M12 15.5V4.5" />
          <polyline points="7.5,9 12,4.5 16.5,9" />
          <path d="M4.5 15.5V19a1 1 0 0 0 1 1h13a1 1 0 0 0 1-1v-3.5" />
        </svg>
      );
    case "download":
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" {...STROKE}>
          <path d="M12 4.5v11" />
          <polyline points="7.5,11 12,15.5 16.5,11" />
          <path d="M4.5 15.5V19a1 1 0 0 0 1 1h13a1 1 0 0 0 1-1v-3.5" />
        </svg>
      );
    case "eye":
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" {...STROKE}>
          <path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Z" />
          <circle cx="12" cy="12" r="3" />
        </svg>
      );
    case "search":
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" {...STROKE}>
          <circle cx="10.5" cy="10.5" r="6" />
          <line x1="15" y1="15" x2="20" y2="20" />
        </svg>
      );
    case "trash":
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" {...STROKE}>
          <line x1="5" y1="7" x2="19" y2="7" />
          <path d="M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2" />
          <path d="M7 7l1 13a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1l1-13" />
          <line x1="10" y1="11" x2="10" y2="17" />
          <line x1="14" y1="11" x2="14" y2="17" />
        </svg>
      );
    case "check":
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" {...STROKE}>
          <polyline points="5,12.5 10,17.5 19,7" />
        </svg>
      );
    case "close":
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" {...STROKE}>
          <line x1="6" y1="6" x2="18" y2="18" />
          <line x1="18" y1="6" x2="6" y2="18" />
        </svg>
      );
    case "refresh":
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" {...STROKE}>
          <path d="M4.5 12a7.5 7.5 0 0 1 12.6-5.5L19.5 8" />
          <polyline points="19.5,3.5 19.5,8 15,8" />
          <path d="M19.5 12a7.5 7.5 0 0 1-12.6 5.5L4.5 16" />
          <polyline points="4.5,20.5 4.5,16 9,16" />
        </svg>
      );
    case "chevron-down":
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" {...STROKE}>
          <polyline points="6,9.5 12,15.5 18,9.5" />
        </svg>
      );
    case "chevron-up":
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" {...STROKE}>
          <polyline points="6,14.5 12,8.5 18,14.5" />
        </svg>
      );
    case "chevron-right":
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" {...STROKE}>
          <polyline points="9.5,6 15.5,12 9.5,18" />
        </svg>
      );
    case "brand":
      // A document whose lines diverge, with the drifted line flagged —
      // documentation that no longer matches reality.
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" {...STROKE}>
          <path d="M5 3.2h8.5l4.3 4.3V19a1.8 1.8 0 0 1-1.8 1.8H5A1.8 1.8 0 0 1 3.2 19V5A1.8 1.8 0 0 1 5 3.2Z" />
          <path d="M13.5 3.2v4.6h4.3" />
          <line x1="6.6" y1="11.4" x2="12.4" y2="11.4" />
          <line x1="6.6" y1="14.4" x2="10.4" y2="14.4" />
          <path d="M13.4 17.6c1.6 0 2.2-2.6 3.9-2.6" />
          <circle cx="18.4" cy="15" r="1.5" fill="currentColor" stroke="none" />
        </svg>
      );
    case "logs":
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" {...STROKE}>
          <line x1="4" y1="6" x2="20" y2="6" />
          <line x1="4" y1="12" x2="16" y2="12" />
          <line x1="4" y1="18" x2="18" y2="18" />
        </svg>
      );
    case "compare":
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" {...STROKE}>
          <rect x="3" y="4.5" width="8" height="15" rx="1.4" />
          <rect x="13" y="4.5" width="8" height="15" rx="1.4" />
        </svg>
      );
    case "plus":
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" {...STROKE}>
          <line x1="12" y1="5" x2="12" y2="19" />
          <line x1="5" y1="12" x2="19" y2="12" />
        </svg>
      );
    default:
      return null;
  }
}