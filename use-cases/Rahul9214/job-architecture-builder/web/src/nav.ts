export const PRIMARY_LINKS = [
  { to: "/", label: "Overview", icon: "overview" },
  { to: "/sources", label: "Sources", icon: "sources" },
  { to: "/architecture", label: "Architecture", icon: "architecture" },
  { to: "/exceptions", label: "Exceptions", icon: "exceptions" },
  { to: "/framework", label: "Framework", icon: "framework" },
  { to: "/profiles", label: "Profiles", icon: "profiles" },
  { to: "/impact", label: "Change Impact", icon: "impact" },
  { to: "/review", label: "Review", icon: "review" },
  { to: "/export", label: "Export", icon: "export" },
] as const;

export type NavIconName = (typeof PRIMARY_LINKS)[number]["icon"];

export const SIDEBAR_STORAGE_KEY = "job-arch-sidebar-collapsed";

export function currentNavLabel(pathname: string): string {
  const match = PRIMARY_LINKS.find((item) =>
    item.to === "/" ? pathname === "/" : pathname === item.to || pathname.startsWith(`${item.to}/`),
  );
  return match?.label ?? "Job architecture";
}
