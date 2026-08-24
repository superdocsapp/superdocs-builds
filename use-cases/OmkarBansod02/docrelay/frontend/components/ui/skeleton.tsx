import { cn } from "@/lib/utils"

function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="skeleton"
      // A slow light sweep, not a blink: a surface being prepared reads as
      // calm rather than as something flickering on the page.
      className={cn("sheen rounded-md", className)}
      {...props}
    />
  )
}

export { Skeleton }
