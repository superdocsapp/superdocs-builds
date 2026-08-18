import * as React from "react";

import { cn } from "@/lib/utils";

function Textarea({ className, ...props }: React.ComponentProps<"textarea">) {
  return (
    <textarea
      data-slot="textarea"
      className={cn(
        "w-full rounded-[var(--radius-control)] border border-line-strong bg-surface px-3 py-2 text-sm leading-relaxed text-ink transition-colors duration-150",
        "placeholder:text-faint",
        "hover:border-faint focus:border-accent focus:outline-none focus:ring-[3px] focus:ring-accent/15",
        "disabled:cursor-not-allowed disabled:bg-canvas disabled:text-muted",
        className,
      )}
      {...props}
    />
  );
}

export { Textarea };
