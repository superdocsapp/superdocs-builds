import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { Slot } from "radix-ui"

import { cn } from "@/lib/utils"

const buttonVariants = cva(
  "group/button type-button inline-flex shrink-0 items-center justify-center rounded-[9px] border border-transparent bg-clip-padding whitespace-nowrap transition-[background-color,color,box-shadow,border-color] duration-[var(--motion-duration)] ease-[var(--motion-ease)] outline-none select-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/40 disabled:pointer-events-none disabled:opacity-50 aria-invalid:border-destructive aria-invalid:ring-3 aria-invalid:ring-destructive/20 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        default:
          "bg-primary text-primary-foreground shadow-[var(--shadow-subtle)] hover:bg-primary-hover",
        outline:
          "border-border bg-surface text-foreground hover:border-border hover:bg-surface-sunken hover:text-foreground aria-expanded:bg-surface-muted",
        secondary:
          "border-border bg-surface text-foreground hover:bg-surface-sunken hover:text-foreground aria-expanded:bg-surface-muted",
        ghost:
          "bg-transparent hover:bg-surface-muted hover:text-foreground aria-expanded:bg-surface-muted",
        destructive:
          "border-destructive/30 bg-surface text-destructive hover:bg-error-soft focus-visible:border-destructive/40 focus-visible:ring-destructive/20",
        link: "text-primary underline-offset-4 hover:underline",
      },
      /* One control ladder — 26 / 30 / 34 / 38 — shared by every button,
         icon button and menu trigger in the product. */
      size: {
        default:
          "h-[34px] gap-1.5 px-3.5 has-data-[icon=inline-end]:pr-2.5 has-data-[icon=inline-start]:pl-2.5",
        xs: "h-[26px] gap-1 rounded-[7px] px-2 text-xs in-data-[slot=button-group]:rounded-lg has-data-[icon=inline-end]:pr-1.5 has-data-[icon=inline-start]:pl-1.5 [&_svg:not([class*='size-'])]:size-3",
        sm: "h-[30px] gap-1.5 rounded-[8px] px-2.5 text-[0.8125rem] in-data-[slot=button-group]:rounded-lg has-data-[icon=inline-end]:pr-1.5 has-data-[icon=inline-start]:pl-1.5 [&_svg:not([class*='size-'])]:size-3.5",
        lg: "h-[38px] gap-2 px-5 has-data-[icon=inline-end]:pr-3.5 has-data-[icon=inline-start]:pl-3.5",
        icon: "size-[34px] rounded-[9px]",
        "icon-xs":
          "size-[26px] rounded-[7px] in-data-[slot=button-group]:rounded-lg [&_svg:not([class*='size-'])]:size-3",
        "icon-sm":
          "size-[30px] rounded-[8px] in-data-[slot=button-group]:rounded-lg",
        "icon-lg": "size-[38px] rounded-[9px]",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

function Button({
  className,
  variant = "default",
  size = "default",
  asChild = false,
  ...props
}: React.ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean
  }) {
  const Comp = asChild ? Slot.Root : "button"

  return (
    <Comp
      data-slot="button"
      data-variant={variant}
      data-size={size}
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  )
}

export { Button, buttonVariants }
