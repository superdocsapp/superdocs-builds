import type { Tone } from "./Badge";

const TONE_VAR: Record<Tone, string> = {
  verified: "var(--color-verified)",
  warning: "var(--color-warning)",
  critical: "var(--color-critical)",
  neutral: "var(--color-neutral)",
  trust: "var(--color-trust)",
};

export function ProgressRing({
  value,
  size = 64,
  strokeWidth = 6,
  tone = "trust",
  label,
}: {
  value: number;
  size?: number;
  strokeWidth?: number;
  tone?: Tone;
  label?: string;
}) {
  const clamped = Math.max(0, Math.min(100, Math.round(value)));
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference * (1 - clamped / 100);
  const center = size / 2;

  return (
    <div
      className="relative inline-flex shrink-0 items-center justify-center"
      style={{ width: size, height: size }}
      role="img"
      aria-label={`${label ? `${label}: ` : ""}${clamped}%`}
    >
      <svg width={size} height={size} className="-rotate-90" aria-hidden="true">
        <circle cx={center} cy={center} r={radius} fill="none" stroke="var(--color-paper-100)" strokeWidth={strokeWidth} />
        <circle
          cx={center}
          cy={center}
          r={radius}
          fill="none"
          stroke={TONE_VAR[tone]}
          strokeWidth={strokeWidth}
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
          className="transition-[stroke-dashoffset] duration-500 ease-out motion-reduce:transition-none"
        />
      </svg>
      <span className="font-numeric absolute text-sm font-semibold text-text-primary">{clamped}%</span>
    </div>
  );
}
