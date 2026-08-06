import { Link, NavLink } from "react-router-dom";
import { Moon, Sun } from "lucide-react";
import type { PropsWithChildren } from "react";

import { Button } from "@/components/ui/button";
import { useTheme } from "@/hooks/useTheme";
import { cn } from "@/lib/utils";

const nav = [
  { to: "/", label: "Home" },
  { to: "/upload", label: "Create Brief" },
  { to: "/history", label: "History" },
];

export function AppShell({ children }: PropsWithChildren) {
  const { isDark, toggle } = useTheme();

  return (
    <div className="mx-auto flex min-h-screen max-w-6xl flex-col px-4 py-6 sm:px-6">
      <header className="mb-8 flex flex-wrap items-center justify-between gap-4 border-b border-border pb-4">
        <div className="space-y-1">
          <Link to="/" className="font-display text-2xl font-bold tracking-tight">
            Interview Preparation Brief
          </Link>
          <p className="text-sm text-muted-foreground">Evidence-grounded interview prep</p>
        </div>

        <div className="flex items-center gap-2">
          <nav className="flex flex-wrap items-center gap-1">
            {nav.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === "/"}
                className={({ isActive }) =>
                  cn(
                    "rounded-md px-3 py-2 text-sm font-semibold transition",
                    isActive
                      ? "bg-primary/10 text-primary"
                      : "text-muted-foreground hover:bg-muted hover:text-foreground",
                  )
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
          <Button
            type="button"
            variant="outline"
            size="icon"
            onClick={toggle}
            aria-label="Toggle dark mode"
          >
            {isDark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </Button>
        </div>
      </header>

      <main className="flex-1 animate-fade-in">{children}</main>

      <footer className="mt-12 border-t border-border pt-4 text-xs text-muted-foreground">
        Never fabricates resume evidence · Missing evidence returns “No evidence found.”
      </footer>
    </div>
  );
}
