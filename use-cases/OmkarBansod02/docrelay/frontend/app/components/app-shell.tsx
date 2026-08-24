"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useMemo, useState, useSyncExternalStore, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Sheet,
  SheetContent,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

import {
  getAuthorizeUrl,
  getConnections,
  listRuns,
  listSources,
  type GoogleConnection,
  type RegisteredSource,
  type RunSummary,
} from "../lib/api";
import {
  ACTIVE_DOCUMENT_EVENT,
  NEW_DOCUMENT_EVENT,
  requestOpenRecentDocument,
  type ActiveDocumentDetail,
} from "../lib/conversation";
import {
  formatRelativeTime,
  recentDocuments,
  type ActiveDocument,
  type RecentDocument,
} from "../lib/import-state";
import {
  hideRecentDocument,
  readHiddenRecents,
  restoreRecentDocument,
  subscribeToHiddenRecents,
} from "../lib/recent-preferences";
import {
  sidebarServerSnapshot,
  sidebarSnapshot,
  subscribeToSidebar,
  toggleSidebarCollapsed,
} from "../lib/ui-preferences";
import { ICON_STROKE, icons } from "@/lib/icons";
import { DocRelayAvatar, GoogleDocsMark } from "./brand";

const navigation = [
  { href: "/", label: "Workspace", icon: icons.workspace },
  { href: "/watch", label: "Watch", icon: icons.watch },
  { href: "/runs", label: "Activity", icon: icons.activity },
] as const;

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [connection, setConnection] = useState<GoogleConnection | null>(null);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [sources, setSources] = useState<RegisteredSource[]>([]);
  const [active, setActive] = useState<ActiveDocument | null>(null);
  const [hidden, setHidden] = useState<ReadonlySet<string>>(() => new Set<string>());
  const activeFileId = active?.providerFileId ?? null;
  // Presentation of the rail is driven by the `data-sidebar` attribute the
  // head script already applied before first paint, so this value only informs
  // behaviour (tooltips, aria) and never causes a hydration mismatch.
  const collapsed = useSyncExternalStore(
    subscribeToSidebar,
    sidebarSnapshot,
    sidebarServerSnapshot,
  );

  useEffect(() => {
    const sync = () => setHidden(readHiddenRecents());
    sync();
    return subscribeToHiddenRecents(sync);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void getConnections(controller.signal)
      .then((response) => {
        setConnection(response.connections.find((item) => item.status === "CONNECTED") ?? null);
      })
      .catch(() => setConnection(null));
    return () => controller.abort();
  }, []);

  // Recent is derived from authoritative backend state only: the registered
  // source documents and the runs performed on them. Re-running whenever the
  // open document changes is the invalidation step — registering a source is
  // exactly what makes it appear in `listSources`, so no reload is needed.
  const connectionId = connection?.connection_id ?? null;
  useEffect(() => {
    // Without a connection there is nothing authoritative to read; the list is
    // already gated on `connection` below, so no state has to be cleared here.
    if (!connectionId) return;

    const controller = new AbortController();
    const aborted = (reason: unknown) => (
      controller.signal.aborted
      || (reason instanceof Error && reason.name === "AbortError")
    );

    void listRuns(controller.signal)
      .then((response) => {
        if (controller.signal.aborted) return;
        setRuns(response.runs);
      })
      .catch((reason) => {
        if (!aborted(reason)) setRuns([]);
      });

    void listSources(connectionId, controller.signal)
      .then((response) => {
        if (controller.signal.aborted) return;
        setSources(response.sources);
      })
      .catch((reason) => {
        if (!aborted(reason)) setSources([]);
      });

    return () => controller.abort();
  }, [connectionId, pathname, activeFileId]);

  useEffect(() => {
    const onActive = (event: Event) => {
      const detail = (event as CustomEvent<ActiveDocumentDetail>).detail;
      const providerFileId = detail?.providerFileId ?? null;
      setActive(providerFileId
        ? { providerFileId, name: detail?.name?.trim() || "Google document" }
        : null);
    };
    window.addEventListener(ACTIVE_DOCUMENT_EVENT, onActive);
    return () => window.removeEventListener(ACTIVE_DOCUMENT_EVENT, onActive);
  }, []);

  // Working on a document again makes it eligible for Recent, even if it was
  // previously removed from the list.
  useEffect(() => {
    if (activeFileId) restoreRecentDocument(activeFileId);
  }, [activeFileId]);

  const recent = useMemo(
    () => recentDocuments({ runs, sources, active }),
    [active, runs, sources],
  );
  const visibleRecent = connection ? recent.filter((item) => !hidden.has(item.providerFileId)) : [];

  const openRecent = (document: RecentDocument) => {
    if (!connection) return;
    if (activeFileId === document.providerFileId && pathname === "/") {
      setMobileOpen(false);
      return;
    }
    requestOpenRecentDocument({
      fileId: document.providerFileId,
      name: document.name,
      mimeType: "application/vnd.google-apps.document",
    });
    setMobileOpen(false);
    if (pathname !== "/") router.push("/");
  };

  return (
    <div className="flex h-dvh overflow-hidden bg-background">
      {/* One authoritative width, one boundary, overflow hidden: no sidebar
          content can ever reach across into the workbench. */}
      <aside
        data-nav="rail"
        className="nav-rail hidden h-dvh min-h-0 shrink-0 flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground lg:flex"
      >
        <SidebarChrome
          pathname={pathname}
          connection={connection}
          recent={visibleRecent}
          activeFileId={activeFileId}
          collapsed={collapsed}
          onToggleCollapsed={toggleSidebarCollapsed}
          onNewDocument={() => router.push("/")}
          onOpenRecent={openRecent}
          onRemoveRecent={hideRecentDocument}
        />
      </aside>

      <div className="flex h-full min-h-0 min-w-0 flex-1 flex-col bg-background">
        <header className="flex h-14 shrink-0 items-center gap-2.5 border-b border-border bg-sidebar px-3 lg:hidden">
          <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
            <SheetTrigger asChild>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label="Open navigation"
                className="text-foreground"
              >
                <icons.menu strokeWidth={ICON_STROKE} />
              </Button>
            </SheetTrigger>
            <SheetContent
              side="left"
              showCloseButton={false}
              data-nav="sheet"
              className="w-[268px] gap-0 border-sidebar-border bg-sidebar p-0 text-sidebar-foreground sm:max-w-[268px]"
            >
              <SheetTitle className="sr-only">Navigation</SheetTitle>
              <SidebarChrome
                pathname={pathname}
                connection={connection}
                recent={visibleRecent}
                activeFileId={activeFileId}
                collapsed={false}
                onNavigate={() => setMobileOpen(false)}
                onOpenRecent={openRecent}
                onRemoveRecent={hideRecentDocument}
                onNewDocument={() => {
                  setMobileOpen(false);
                  router.push("/");
                }}
              />
            </SheetContent>
          </Sheet>
          <Brand compact />
        </header>

        <main className="min-h-0 min-w-0 flex-1 overflow-y-auto">{children}</main>
      </div>
    </div>
  );
}

function SidebarChrome({
  pathname,
  connection,
  recent,
  activeFileId,
  collapsed,
  onToggleCollapsed,
  onNavigate,
  onOpenRecent,
  onNewDocument,
  onRemoveRecent,
}: {
  pathname: string;
  connection: GoogleConnection | null;
  recent: RecentDocument[];
  activeFileId: string | null;
  collapsed: boolean;
  onToggleCollapsed?: () => void;
  onNavigate?: () => void;
  onOpenRecent: (document: RecentDocument) => void;
  onNewDocument?: () => void;
  onRemoveRecent: (providerFileId: string) => void;
}) {
  return (
    <div className="flex h-full min-h-0 min-w-0 flex-col">
      <div className="nav-inset relative flex h-[68px] shrink-0 items-center justify-between gap-1">
        <Brand />
        {onToggleCollapsed ? (
          <>
            {/* Collapsed, the mark is the rail's header and hands over to the
                expand control only while the rail is hovered or focused. */}
            <div className="rail-brand nav-collapsed-only mx-auto w-fit">
              <DocRelayAvatar className="size-[30px]" />
            </div>
            <RailToggle collapsed={collapsed} onToggle={onToggleCollapsed} />
          </>
        ) : null}
      </div>

      <div className="nav-inset pb-1">
        <NewDocumentButton
          pathname={pathname}
          collapsed={collapsed}
          onNavigate={onNavigate}
          onNewDocument={onNewDocument}
        />
      </div>

      <ScrollArea className="scrollbar-inset min-h-0 min-w-0 flex-1">
        <div className="flex min-w-0 flex-col pt-4 pb-4">
          <div className="nav-inset min-w-0">
            <PrimaryNavigation pathname={pathname} collapsed={collapsed} onNavigate={onNavigate} />
          </div>
          {/* A hairline is enough to separate navigation from documents; the
              rail never nests a card inside itself. */}
          <div className="nav-expanded-only mx-4 mt-5 h-px shrink-0 bg-sidebar-border" aria-hidden="true" />
          <div className="nav-expanded-only nav-inset mt-4 min-w-0">
            <RecentDocuments
              documents={recent}
              activeFileId={activeFileId}
              connected={Boolean(connection)}
              onOpen={onOpenRecent}
              onNavigate={onNavigate}
              onRemove={onRemoveRecent}
            />
          </div>
        </div>
      </ScrollArea>

      <AccountArea connection={connection} collapsed={collapsed} />
    </div>
  );
}

function RailToggle({ collapsed, onToggle }: { collapsed: boolean; onToggle: () => void }) {
  const label = collapsed ? "Expand sidebar" : "Collapse sidebar";
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          onClick={onToggle}
          aria-label={label}
          aria-expanded={!collapsed}
          className={cn(
            "rail-toggle grid size-8 shrink-0 place-items-center rounded-[8px] text-sidebar-muted",
            "hover:bg-sidebar-accent hover:text-sidebar-foreground",
          )}
        >
          <icons.collapseRail
            className="nav-expanded-only size-4"
            strokeWidth={ICON_STROKE}
            aria-hidden="true"
          />
          <icons.expandRail
            className="nav-collapsed-only size-4"
            strokeWidth={ICON_STROKE}
            aria-hidden="true"
          />
        </button>
      </TooltipTrigger>
      <TooltipContent side="right">{label}</TooltipContent>
    </Tooltip>
  );
}

function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <div className={cn("flex min-w-0 items-center gap-2.5", compact ? "" : "nav-expanded-only")}>
      <DocRelayAvatar className="size-[30px]" />
      <span className="min-w-0">
        <span className="block truncate text-[15.5px] leading-[1.15] font-semibold tracking-[-0.03em] text-sidebar-foreground">
          DocRelay
        </span>
        {compact ? null : (
          <span className="mt-[3px] block truncate text-[11.75px] leading-none font-medium tracking-[-0.004em] text-sidebar-muted">
            AI-safe Google Docs editing
          </span>
        )}
      </span>
    </div>
  );
}

function NewDocumentButton({
  pathname,
  collapsed,
  onNavigate,
  onNewDocument,
}: {
  pathname: string;
  collapsed: boolean;
  onNavigate?: () => void;
  onNewDocument?: () => void;
}) {
  const start = () => {
    onNavigate?.();
    if (pathname === "/") {
      window.dispatchEvent(new Event(NEW_DOCUMENT_EVENT));
      return;
    }
    onNewDocument?.();
  };

  // The one filled control in the rail. Everything else is quiet, so the
  // product's starting action is unmistakable at a glance.
  const button = (
    <button
      type="button"
      onClick={start}
      aria-label="New document"
      className={cn(
        "nav-item group/new flex h-[38px] w-full items-center justify-center rounded-[10px]",
        "bg-primary text-[13.5px] leading-none font-medium tracking-[-0.012em] text-primary-foreground",
        "shadow-[var(--shadow-raised)]",
        "transition-[background-color,box-shadow,translate] duration-[var(--motion-duration)] ease-[var(--motion-ease)]",
        "hover:bg-primary-hover hover:shadow-[var(--shadow-raised)] active:translate-y-px",
      )}
    >
      <icons.plus className="size-4 shrink-0" strokeWidth={2.25} aria-hidden="true" />
      <span className="nav-label truncate">New document</span>
    </button>
  );

  if (!collapsed) return button;
  return (
    <Tooltip>
      <TooltipTrigger asChild>{button}</TooltipTrigger>
      <TooltipContent side="right">New document</TooltipContent>
    </Tooltip>
  );
}

function PrimaryNavigation({
  pathname,
  collapsed,
  onNavigate,
}: {
  pathname: string;
  collapsed: boolean;
  onNavigate?: () => void;
}) {
  return (
    <nav aria-label="Primary" className="flex min-w-0 flex-col gap-1">
      {navigation.map((item) => {
        const active = isActive(pathname, item.href);
        const Icon = item.icon;
        const link = (
          <Link
            href={item.href}
            onClick={onNavigate}
            aria-label={item.label}
            aria-current={active ? "page" : undefined}
            className={cn(
              "nav-item type-nav relative flex h-9 min-w-0 items-center rounded-[9px]",
              "transition-[background-color,color] duration-[var(--motion-duration)] ease-[var(--motion-ease)]",
              active
                ? "bg-accent-soft font-medium text-primary"
                : "text-sidebar-muted hover:bg-sidebar-accent hover:text-sidebar-foreground",
            )}
          >
            <Icon
              className={cn("size-[17px] shrink-0", active ? "text-primary" : "text-muted-soft")}
              strokeWidth={ICON_STROKE}
            />
            <span className="nav-label truncate">{item.label}</span>
          </Link>
        );

        if (!collapsed) return <div key={item.href} className="min-w-0">{link}</div>;
        return (
          <Tooltip key={item.href}>
            <TooltipTrigger asChild>{link}</TooltipTrigger>
            <TooltipContent side="right">{item.label}</TooltipContent>
          </Tooltip>
        );
      })}
    </nav>
  );
}

function RecentDocuments({
  documents,
  activeFileId,
  connected,
  onOpen,
  onNavigate,
  onRemove,
}: {
  documents: RecentDocument[];
  activeFileId: string | null;
  connected: boolean;
  onOpen: (document: RecentDocument) => void;
  onNavigate?: () => void;
  onRemove: (providerFileId: string) => void;
}) {
  return (
    <section aria-label="Recent documents" className="flex min-w-0 flex-col gap-2">
      <h2 className="type-section-heading px-[11px]">Recent</h2>
      {documents.length > 0 ? (
        <ul className="flex min-w-0 flex-col gap-0.5">
          {documents.map((document) => (
            <RecentDocumentRow
              key={document.providerFileId}
              document={document}
              active={activeFileId === document.providerFileId}
              connected={connected}
              onOpen={onOpen}
              onNavigate={onNavigate}
              onRemove={onRemove}
            />
          ))}
        </ul>
      ) : (
        <p className="px-[11px] py-1 text-[12.75px] leading-[1.5] text-muted-soft">
          {connected ? "No documents yet." : "Connect Drive to see documents."}
        </p>
      )}
      <Link
        href="/runs"
        onClick={onNavigate}
        aria-label="View all documents in Activity"
        className="type-caption mt-1 inline-flex w-fit items-center gap-0.5 rounded-[7px] px-[11px] py-1 text-sidebar-muted transition-colors duration-[var(--motion-duration)] hover:text-sidebar-foreground"
      >
        View all documents
        <icons.chevronRight className="size-3.5" strokeWidth={ICON_STROKE} aria-hidden="true" />
      </Link>
    </section>
  );
}

function RecentDocumentRow({
  document,
  active,
  connected,
  onOpen,
  onNavigate,
  onRemove,
}: {
  document: RecentDocument;
  active: boolean;
  connected: boolean;
  onOpen: (document: RecentDocument) => void;
  onNavigate?: () => void;
  onRemove: (providerFileId: string) => void;
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const timestamp = formatRelativeTime(document.updatedAt);

  return (
    <li
      className={cn(
        "group/recent relative min-w-0 rounded-[9px] transition-colors duration-[var(--motion-duration)] ease-[var(--motion-ease)]",
        "motion-safe:animate-in motion-safe:fade-in motion-safe:duration-[var(--motion-duration)]",
        active ? "bg-accent-soft" : "hover:bg-sidebar-accent",
        menuOpen && !active ? "bg-sidebar-accent" : "",
      )}
    >
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            onClick={() => onOpen(document)}
            disabled={!connected}
            aria-current={active ? "true" : undefined}
            aria-label={timestamp ? `${document.name}, ${timestamp}` : document.name}
            className="flex w-full min-w-0 items-start gap-2.5 rounded-[9px] py-2 pr-[34px] pl-[11px] text-left outline-none disabled:pointer-events-none disabled:opacity-50"
          >
            <GoogleDocsMark className="mt-[1px] size-[15px]" />
            <span className="block min-w-0 flex-1">
              {/* Two lines, then an ellipsis: a long agreement title stays
                  readable instead of collapsing to a few words. */}
              <span className="line-clamp-2 text-[13.5px] leading-[1.38] font-medium tracking-[-0.014em] text-sidebar-foreground">
                {document.name}
              </span>
              <span className="mt-[3px] block truncate text-[11.75px] leading-[1.4] text-muted-soft">
                {active ? (timestamp ? `Open · ${timestamp}` : "Open") : timestamp}
              </span>
            </span>
          </button>
        </TooltipTrigger>
        <TooltipContent side="right" className="max-w-[16rem]">
          {document.name}
        </TooltipContent>
      </Tooltip>

      {/* Contained inside the row's reserved right inset, so it can never sit
          on top of the title or push the row wider. */}
      <div className="pointer-events-none absolute top-2 right-1.5 grid size-6 place-items-center">
        {active && !menuOpen ? (
          <span
            className="col-start-1 row-start-1 size-1.5 rounded-full bg-primary transition-opacity duration-[var(--motion-duration)] group-hover/recent:opacity-0"
            aria-hidden="true"
          />
        ) : null}
        <DropdownMenu open={menuOpen} onOpenChange={setMenuOpen}>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              aria-label={`Actions for ${document.name}`}
              className={cn(
                "pointer-events-auto col-start-1 row-start-1 grid size-6 place-items-center rounded-[6px] text-sidebar-muted",
                "transition-[opacity,background-color,color] duration-[var(--motion-duration)] ease-[var(--motion-ease)]",
                "hover:bg-sidebar-accent hover:text-sidebar-foreground focus-visible:opacity-100",
                menuOpen
                  ? "opacity-100"
                  : "opacity-0 group-hover/recent:opacity-100 group-focus-within/recent:opacity-100",
              )}
            >
              <icons.more className="size-4" strokeWidth={ICON_STROKE} aria-hidden="true" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" side="right" className="w-48">
            <DropdownMenuItem asChild>
              <Link href="/runs" onClick={onNavigate}>
                <icons.activity strokeWidth={ICON_STROKE} aria-hidden="true" />
                View activity
              </Link>
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              variant="destructive"
              onSelect={() => onRemove(document.providerFileId)}
            >
              <icons.hide strokeWidth={ICON_STROKE} aria-hidden="true" />
              Remove from Recents
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </li>
  );
}

function AccountArea({
  connection,
  collapsed,
}: {
  connection: GoogleConnection | null;
  collapsed: boolean;
}) {
  const connected = connection?.status === "CONNECTED";

  const trigger = (
    <button
      type="button"
      aria-label={`Account · Google Drive ${connected ? "connected" : "not connected"}`}
      className={cn(
        "nav-item flex w-full min-w-0 items-center rounded-[10px] py-2 text-left",
        "transition-colors duration-[var(--motion-duration)] hover:bg-sidebar-accent aria-expanded:bg-sidebar-accent",
      )}
    >
      <span className="relative grid shrink-0 place-items-center">
        <span
          className="grid size-[30px] place-items-center rounded-full border border-sidebar-border bg-surface text-muted"
          aria-hidden="true"
        >
          <icons.account className="size-4" strokeWidth={ICON_STROKE} />
        </span>
        <span
          className={cn(
            "absolute right-0 bottom-0 size-[9px] rounded-full ring-2 ring-sidebar",
            connected ? "bg-success" : "bg-sidebar-border",
          )}
          aria-hidden="true"
        />
      </span>
      <span className="nav-label min-w-0 flex-1">
        <span className="block truncate text-[13.25px] leading-[1.35] font-medium text-sidebar-foreground">
          Account
        </span>
        <span className="block truncate text-[11.75px] leading-[1.4] text-muted-soft">
          Drive · {connected ? "Connected" : "Not connected"}
        </span>
      </span>
      <icons.chevronDown
        className="nav-label size-3.5 shrink-0 text-sidebar-muted"
        strokeWidth={ICON_STROKE}
        aria-hidden="true"
      />
    </button>
  );

  return (
    <div className="nav-inset shrink-0 border-t border-sidebar-border py-2.5">
      <DropdownMenu>
        {collapsed ? (
          <Tooltip>
            <TooltipTrigger asChild>
              <DropdownMenuTrigger asChild>{trigger}</DropdownMenuTrigger>
            </TooltipTrigger>
            <TooltipContent side="right">
              Google Drive · {connected ? "Connected" : "Not connected"}
            </TooltipContent>
          </Tooltip>
        ) : (
          <DropdownMenuTrigger asChild>{trigger}</DropdownMenuTrigger>
        )}
        <DropdownMenuContent side="top" align="start" className="w-56">
          <DropdownMenuLabel>Google Drive</DropdownMenuLabel>
          <DropdownMenuSeparator />
          <DropdownMenuGroup>
            <DropdownMenuItem onClick={() => window.location.assign(getAuthorizeUrl())}>
              {connected ? "Reconnect Drive" : "Connect Google Drive"}
            </DropdownMenuItem>
            <DropdownMenuItem asChild>
              <Link href="/runs">Activity</Link>
            </DropdownMenuItem>
          </DropdownMenuGroup>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}

function isActive(pathname: string, href: string): boolean {
  return href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`);
}
