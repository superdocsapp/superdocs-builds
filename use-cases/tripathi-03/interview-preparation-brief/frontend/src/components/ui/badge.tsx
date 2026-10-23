import { HTMLAttributes } from "react";

import { cn } from "@/lib/utils";

export function Badge({
  className,
  variant = "default",
  ...props
}: HTMLAttributes<HTMLSpanElement> & {
  variant?: "default" | "success" | "warning" | "destructive" | "outline";
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md px-2 py-0.5 text-xs font-semibold",
        variant === "default" && "bg-primary/15 text-primary",
        variant === "success" && "bg-success/15 text-success",
        variant === "warning" && "bg-warning/15 text-warning",
        variant === "destructive" && "bg-destructive/15 text-destructive",
        variant === "outline" && "border border-border text-muted-foreground",
        className,
      )}
      {...props}
    />
  );
}
