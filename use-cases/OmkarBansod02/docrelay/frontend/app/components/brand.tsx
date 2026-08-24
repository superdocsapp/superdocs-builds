import type { SVGProps } from "react";

import { cn } from "@/lib/utils";

/**
 * Product and provider marks.
 *
 * These are the only decorative glyphs in the product. The DocRelay mark is
 * drawn in the accent so brand, selection and verified state all read as the
 * same green; the provider marks keep Google's own colours so a document's
 * origin is never ambiguous.
 */

/** DocRelay's pine. Inherits `currentColor` so it can sit on any surface. */
export function DocRelayMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={cn("shrink-0", className)}
      fill="currentColor"
      aria-hidden="true"
      focusable="false"
    >
      <path d="M12 1.8 8.15 8.05h7.7L12 1.8Z" />
      <path d="M12 5.6 6.6 13.35h10.8L12 5.6Z" />
      <path d="M12 10 4.9 19.05h14.2L12 10Z" />
      <path d="M10.85 18.4h2.3V22.4h-2.3z" />
    </svg>
  );
}

/**
 * The DocRelay mark on its own plate — the sidebar brand, the assistant's
 * avatar in the conversation, and nothing else.
 */
export function DocRelayAvatar({
  className,
  tone = "solid",
}: {
  className?: string;
  tone?: "solid" | "soft";
}) {
  return (
    <span
      className={cn(
        "grid shrink-0 place-items-center rounded-[9px]",
        tone === "solid"
          ? "bg-primary text-primary-foreground"
          : "border border-primary-line bg-accent-soft text-primary",
        className,
      )}
      aria-hidden="true"
    >
      <DocRelayMark className="size-[58%]" />
    </span>
  );
}

/**
 * The person on the other side of the conversation. The soft tone marks a turn
 * replayed from saved history, so a reopened thread visibly recedes behind the
 * exchange that is actually live.
 */
export function UserAvatar({
  className,
  tone = "solid",
}: {
  className?: string;
  tone?: "solid" | "soft";
}) {
  return (
    <span
      className={cn(
        "grid shrink-0 place-items-center rounded-full border",
        "text-[10.5px] leading-none font-semibold tracking-[0.02em]",
        tone === "solid"
          ? "border-border bg-surface text-muted"
          : "border-transparent bg-surface-muted text-muted-soft",
        className,
      )}
      aria-hidden="true"
    >
      You
    </span>
  );
}

/** Google Docs file mark, used wherever the document's provider is named. */
export function GoogleDocsMark({ className, ...props }: SVGProps<SVGSVGElement>) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={cn("shrink-0", className)}
      aria-hidden="true"
      focusable="false"
      {...props}
    >
      <rect x="1.5" y="1.5" width="21" height="21" rx="5.5" fill="#1a73e8" />
      <path
        d="M13.15 5.5H8.6a1.6 1.6 0 0 0-1.6 1.6v9.8a1.6 1.6 0 0 0 1.6 1.6h6.8a1.6 1.6 0 0 0 1.6-1.6V9.05L13.15 5.5Z"
        fill="#fff"
      />
      <path d="M13.15 5.5 17 9.05h-3.85V5.5Z" fill="#a8c7fa" />
      <path
        d="M9.5 11.35h5v1H9.5v-1Zm0 2.3h5v1h-5v-1Z"
        fill="#1a73e8"
      />
    </svg>
  );
}

/** Google Drive mark, used only where Drive itself is the subject. */
export function GoogleDriveMark({ className, ...props }: SVGProps<SVGSVGElement>) {
  return (
    <svg
      viewBox="0 0 87.3 78"
      className={cn("shrink-0", className)}
      aria-hidden="true"
      focusable="false"
      {...props}
    >
      <path fill="#0066da" d="m6.6 66.85 3.85 6.65c.8 1.4 1.95 2.5 3.3 3.3l13.75-23.8H0c0 1.55.4 3.1 1.2 4.5z" />
      <path fill="#00ac47" d="M43.65 25 29.9 1.2c-1.35.8-2.5 1.9-3.3 3.3l-25.4 44C.41 49.88 0 51.44 0 53h27.5z" />
      <path fill="#ea4335" d="M73.55 76.8c1.35-.8 2.5-1.9 3.3-3.3l1.6-2.75 7.65-13.25c.8-1.4 1.2-2.95 1.2-4.5H59.797l5.852 11.5z" />
      <path fill="#00832d" d="M43.65 25 57.4 1.2C56.05.4 54.5 0 52.9 0H34.4c-1.6 0-3.15.45-4.5 1.2z" />
      <path fill="#2684fc" d="M59.8 53H27.5L13.75 76.8c1.35.8 2.9 1.2 4.5 1.2h50.8c1.6 0 3.15-.45 4.5-1.2z" />
      <path fill="#ffba00" d="m73.4 26.5-12.7-22c-.8-1.4-1.95-2.5-3.3-3.3L43.65 25l16.15 28h27.45c0-1.55-.4-3.1-1.2-4.5z" />
    </svg>
  );
}
