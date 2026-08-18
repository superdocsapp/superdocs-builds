import * as React from "react";

import { cn } from "@/lib/utils";

function Input({ className, ...props }: React.ComponentProps<"input">) {
  return (
    <input
      data-slot="input"
      className={cn(
        "h-9 w-full rounded-[var(--radius-control)] border border-line-strong bg-surface px-3 text-sm text-ink transition-colors duration-150",
        "placeholder:text-faint",
        "hover:border-faint focus:border-accent focus:outline-none focus:ring-[3px] focus:ring-accent/15",
        "disabled:cursor-not-allowed disabled:bg-canvas disabled:text-muted",
        className,
      )}
      {...props}
    />
  );
}

export { Input };
