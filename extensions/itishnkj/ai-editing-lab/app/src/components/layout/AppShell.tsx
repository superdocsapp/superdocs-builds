import { useMemo, useState, type ReactNode } from 'react';
import { Link, useLocation } from 'wouter';
import { useClerk, useUser } from '@clerk/react';
import {
  Activity,
  BarChart3,
  ChevronsUpDown,
  FileText,
  GitCompare,
  History,
  LineChart,
  LogIn,
  LogOut,
  MessageSquareText,
  PenLine,
  Settings,
  Upload,
  UserRound,
} from 'lucide-react';
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuBadge,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarTrigger,
} from '@/components/ui/sidebar';
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  Avatar,
  AvatarFallback,
  AvatarImage,
} from '@/components/ui/avatar';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  EngineStatusList,
  SystemStatusPopover,
} from '@/components/layout/SystemStatusPopover';
import { basePath } from '@/lib/clerk';
import { requestEditorIntent } from '@/lib/editor-intents';
import { formatRelativeTime } from '@/lib/history';
import { usePreferences } from '@/lib/preferences';
import { documentSessionTitle, useLabStore } from '@/lib/store';

function AppMark() {
  return (
    <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-primary text-primary-foreground">
      <PenLine className="h-4 w-4" />
    </span>
  );
}

const ACCOUNT_TRIGGER_CLASSES =
  'flex w-full items-center gap-2 rounded-md p-2 text-left transition-colors hover:bg-sidebar-accent group-data-[collapsible=icon]:justify-center group-data-[collapsible=icon]:p-1.5';

function SystemStatusDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { preferences } = usePreferences();
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>System status</DialogTitle>
          <DialogDescription>
            The editing engines available to this lab and whether they are
            ready to use.
          </DialogDescription>
        </DialogHeader>
        <EngineStatusList showModels={preferences.developerMode} />
      </DialogContent>
    </Dialog>
  );
}

function GuestMenu() {
  const [, navigate] = useLocation();
  const { preferences, setPreference } = usePreferences();
  const [statusOpen, setStatusOpen] = useState(false);
  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button
            type="button"
            className={ACCOUNT_TRIGGER_CLASSES}
            data-testid="button-account-menu"
          >
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-muted text-muted-foreground">
              <UserRound className="h-4 w-4" />
            </span>
            <span className="min-w-0 flex-1 group-data-[collapsible=icon]:hidden">
              <span className="block truncate text-sm font-medium">Guest session</span>
              <span className="block truncate text-xs text-muted-foreground">
                Working locally
              </span>
            </span>
            <ChevronsUpDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground group-data-[collapsible=icon]:hidden" />
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent side="top" align="start" className="w-64">
          <DropdownMenuLabel>
            <p className="text-sm font-medium">Guest session</p>
            <p className="text-xs font-normal text-muted-foreground">
              Your work is saved in this browser.
            </p>
          </DropdownMenuLabel>
          <DropdownMenuSeparator />
          <DropdownMenuItem
            onSelect={() => navigate('/sign-in')}
            data-testid="menu-item-sign-in"
          >
            <LogIn className="mr-2 h-4 w-4" />
            Sign in to save your work
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuCheckboxItem
            checked={preferences.developerMode}
            onCheckedChange={(checked) =>
              setPreference('developerMode', checked === true)
            }
            data-testid="menu-item-developer-mode"
          >
            Developer Mode
          </DropdownMenuCheckboxItem>
          <DropdownMenuItem
            onSelect={() => setStatusOpen(true)}
            data-testid="menu-item-system-status"
          >
            <Activity className="mr-2 h-4 w-4" />
            System Status
          </DropdownMenuItem>
          <DropdownMenuItem
            onSelect={() => navigate('/settings')}
            data-testid="menu-item-settings"
          >
            <Settings className="mr-2 h-4 w-4" />
            Settings
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      <SystemStatusDialog open={statusOpen} onOpenChange={setStatusOpen} />
    </>
  );
}

function AccountMenu() {
  const [, navigate] = useLocation();
  const { user } = useUser();
  const { signOut } = useClerk();
  const { flushPersistence } = useLabStore();
  const { preferences, setPreference } = usePreferences();
  const [statusOpen, setStatusOpen] = useState(false);

  if (!user) return null;

  const displayName =
    user.fullName?.trim() ||
    user.username ||
    user.primaryEmailAddress?.emailAddress ||
    'Your account';
  const email = user.primaryEmailAddress?.emailAddress ?? '';
  const initials =
    `${user.firstName?.[0] ?? ''}${user.lastName?.[0] ?? ''}`.toUpperCase() ||
    displayName.slice(0, 1).toUpperCase();

  const handleSignOut = async () => {
    try {
      // Push any queued workspace changes before the session ends.
      await flushPersistence();
    } catch {
      // Sign-out proceeds even if the final save could not complete.
    }
    await signOut({ redirectUrl: basePath || '/' });
  };

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button
            type="button"
            className={ACCOUNT_TRIGGER_CLASSES}
            data-testid="button-account-menu"
          >
            <Avatar className="h-8 w-8 shrink-0">
              <AvatarImage src={user.imageUrl} alt={displayName} />
              <AvatarFallback className="bg-primary/10 text-xs font-medium text-primary">
                {initials}
              </AvatarFallback>
            </Avatar>
            <span className="min-w-0 flex-1 group-data-[collapsible=icon]:hidden">
              <span
                className="block truncate text-sm font-medium"
                data-testid="text-account-name"
              >
                {displayName}
              </span>
              <span className="block truncate text-xs text-muted-foreground">
                Saved to your account
              </span>
            </span>
            <ChevronsUpDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground group-data-[collapsible=icon]:hidden" />
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent side="top" align="start" className="w-64">
          <DropdownMenuLabel>
            <p className="truncate text-sm font-medium">{displayName}</p>
            {email ? (
              <p className="truncate text-xs font-normal text-muted-foreground">
                {email}
              </p>
            ) : null}
          </DropdownMenuLabel>
          <DropdownMenuSeparator />
          <DropdownMenuItem
            onSelect={() => navigate('/settings')}
            data-testid="menu-item-profile"
          >
            <UserRound className="mr-2 h-4 w-4" />
            Profile
          </DropdownMenuItem>
          <DropdownMenuCheckboxItem
            checked={preferences.developerMode}
            onCheckedChange={(checked) =>
              setPreference('developerMode', checked === true)
            }
            data-testid="menu-item-developer-mode"
          >
            Developer Mode
          </DropdownMenuCheckboxItem>
          <DropdownMenuItem
            onSelect={() => setStatusOpen(true)}
            data-testid="menu-item-system-status"
          >
            <Activity className="mr-2 h-4 w-4" />
            System Status
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem
            onSelect={() => void handleSignOut()}
            data-testid="menu-item-sign-out"
          >
            <LogOut className="mr-2 h-4 w-4" />
            Sign out
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      <SystemStatusDialog open={statusOpen} onOpenChange={setStatusOpen} />
    </>
  );
}

function AccountArea() {
  const { user } = useUser();
  return user ? <AccountMenu /> : <GuestMenu />;
}

export function AppShell({ children }: { children: ReactNode }) {
  const [location, navigate] = useLocation();
  const { documentSession, versions, conversations, setActiveConversation } =
    useLabStore();
  const { preferences, setPreference } = usePreferences();

  const recentConversations = useMemo(
    () =>
      [...conversations]
        .sort(
          (a, b) =>
            new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime(),
        )
        .slice(0, 5),
    [conversations],
  );

  const editorActive = location === '/' || location.startsWith('/editor');
  const documentTitle = documentSessionTitle(documentSession);
  const sourceBadge =
    documentSession.sourceType === 'imported'
      ? documentSession.importedDocument?.format.toUpperCase() ?? 'FILE'
      : 'Demo';

  const openConversation = (conversation: {
    id: string;
    sessionKey?: string;
  }) => {
    if (
      conversation.sessionKey != null &&
      conversation.sessionKey === documentSession.sessionKey
    ) {
      setActiveConversation(conversation.id);
      navigate('/');
      return;
    }
    navigate(`/history/chats/${conversation.id}`);
  };

  return (
    <SidebarProvider
      open={!preferences.sidebarCollapsed}
      onOpenChange={(open) => setPreference('sidebarCollapsed', !open)}
    >
      <Sidebar collapsible="icon">
        <SidebarHeader>
          <div className="flex items-center gap-2 px-1 py-1 group-data-[collapsible=icon]:justify-center group-data-[collapsible=icon]:px-0">
            <AppMark />
            <span className="min-w-0 flex-1 group-data-[collapsible=icon]:hidden">
              <span className="block truncate text-sm font-semibold leading-tight">
                AI Editing Lab
              </span>
              <span className="block truncate text-[11px] text-muted-foreground">
                Your documents, edited with care
              </span>
            </span>
            <SidebarTrigger
              className="shrink-0 group-data-[collapsible=icon]:hidden"
              data-testid="button-sidebar-toggle"
            />
          </div>
          <div className="hidden justify-center pt-2 group-data-[collapsible=icon]:flex">
            <SidebarTrigger
              aria-label="Expand sidebar"
              title="Expand sidebar"
              data-testid="button-sidebar-expand"
            />
          </div>
          <SidebarMenu>
            <SidebarMenuItem>
              <SidebarMenuButton
                tooltip="Upload document"
                onClick={() => {
                  requestEditorIntent('upload-document');
                  navigate('/');
                }}
                data-testid="button-upload-document"
              >
                <Upload />
                <span>Upload document</span>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarHeader>

        <SidebarContent>
          <SidebarGroup>
            <SidebarGroupContent>
              <SidebarMenu>
                <SidebarMenuItem>
                  <SidebarMenuButton
                    asChild
                    isActive={editorActive}
                    tooltip="Editor"
                  >
                    <Link href="/" data-testid="link-nav-editor">
                      <FileText />
                      <span>Editor</span>
                    </Link>
                  </SidebarMenuButton>
                </SidebarMenuItem>
                <SidebarMenuItem>
                  <SidebarMenuButton
                    asChild
                    isActive={location.startsWith('/history')}
                    tooltip="History"
                  >
                    <Link href="/history" data-testid="link-nav-history">
                      <History />
                      <span>History</span>
                    </Link>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>

          <SidebarGroup>
            <SidebarGroupLabel>Documents</SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                <SidebarMenuItem>
                  <SidebarMenuButton
                    asChild
                    isActive={editorActive}
                    tooltip={documentTitle}
                    className="pr-12"
                  >
                    <Link href="/" data-testid="link-document-current">
                      <FileText />
                      <span className="min-w-0 flex-1 truncate">{documentTitle}</span>
                    </Link>
                  </SidebarMenuButton>
                  <SidebarMenuBadge className="group-data-[collapsible=icon]:hidden">
                    {sourceBadge}
                  </SidebarMenuBadge>
                </SidebarMenuItem>
              </SidebarMenu>
              <p className="px-2 pt-1 text-[11px] leading-snug text-muted-foreground group-data-[collapsible=icon]:hidden">
                v{versions.length} · one document per session
              </p>
            </SidebarGroupContent>
          </SidebarGroup>

          <SidebarGroup className="group-data-[collapsible=icon]:hidden">
            <SidebarGroupLabel>Recent</SidebarGroupLabel>
            <SidebarGroupContent>
              {recentConversations.length === 0 ? (
                <p className="px-2 py-1 text-xs leading-snug text-muted-foreground">
                  Conversations with the assistant will appear here.
                </p>
              ) : (
                <SidebarMenu>
                  {recentConversations.map((conversation) => (
                    <SidebarMenuItem key={conversation.id}>
                      <SidebarMenuButton
                        onClick={() =>
                          openConversation(conversation)
                        }
                        isActive={location === `/history/chats/${conversation.id}`}
                        className="h-auto py-1.5"
                        data-testid={`link-recent-conversation-${conversation.id}`}
                      >
                        <MessageSquareText className="shrink-0" />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-sm leading-tight">
                            {conversation.title}
                          </span>
                          <span className="block truncate text-[11px] text-muted-foreground">
                            {formatRelativeTime(conversation.updatedAt)}
                          </span>
                        </span>
                      </SidebarMenuButton>
                    </SidebarMenuItem>
                  ))}
                  <SidebarMenuItem>
                    <SidebarMenuButton asChild className="text-muted-foreground">
                      <Link
                        href="/history?tab=chats"
                        data-testid="link-view-all-conversations"
                      >
                        <span className="text-xs">View all conversations</span>
                      </Link>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                </SidebarMenu>
              )}
            </SidebarGroupContent>
          </SidebarGroup>

          <SidebarGroup>
            <SidebarGroupLabel>Lab</SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                <SidebarMenuItem>
                  <SidebarMenuButton
                    asChild
                    isActive={location === '/compare'}
                    tooltip="Compare"
                  >
                    <Link href="/compare" data-testid="link-nav-compare">
                      <GitCompare />
                      <span>Compare</span>
                    </Link>
                  </SidebarMenuButton>
                </SidebarMenuItem>
                <SidebarMenuItem>
                  <SidebarMenuButton
                    asChild
                    isActive={location === '/benchmark'}
                    tooltip="Benchmark"
                  >
                    <Link href="/benchmark" data-testid="link-nav-benchmark">
                      <BarChart3 />
                      <span>Benchmark</span>
                    </Link>
                  </SidebarMenuButton>
                </SidebarMenuItem>
                <SidebarMenuItem>
                  <SidebarMenuButton
                    asChild
                    isActive={location.startsWith('/insights')}
                    tooltip="Insights"
                  >
                    <Link href="/insights" data-testid="link-nav-insights">
                      <LineChart />
                      <span>Insights</span>
                    </Link>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        </SidebarContent>

        <SidebarFooter>
          <div className="group-data-[collapsible=icon]:hidden">
            <SystemStatusPopover />
          </div>
          <div className="hidden justify-center group-data-[collapsible=icon]:flex">
            <SystemStatusPopover compact />
          </div>
          <AccountArea />
        </SidebarFooter>
      </Sidebar>

      <SidebarInset className="h-svh min-w-0">
        <div className="flex h-full min-h-0 flex-col">
          <header className="flex h-14 shrink-0 items-center gap-2 border-b bg-background px-3 md:hidden">
            <SidebarTrigger data-testid="button-mobile-sidebar" />
            <AppMark />
            <span className="truncate text-sm font-semibold">AI Editing Lab</span>
            <div className="ml-auto">
              <SystemStatusPopover compact />
            </div>
          </header>
          <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
        </div>
      </SidebarInset>
    </SidebarProvider>
  );
}
