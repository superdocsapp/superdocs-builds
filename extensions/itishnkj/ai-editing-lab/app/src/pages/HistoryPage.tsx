import { useEffect, useMemo, useState } from 'react';
import { Link, useLocation, useSearch } from 'wouter';
import { format, isToday, isYesterday } from 'date-fns';
import {
  ChevronDown,
  FileClock,
  GitCommit,
  MessageSquareText,
  RotateCcw,
  Sparkles,
  XCircle,
} from 'lucide-react';
import { toast } from 'sonner';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  diffWords,
  formatRelativeTime,
  type DiffSegment,
  type EditEvent,
  partitionEditEventsBySession,
} from '@/lib/history';
import { stripHtml } from '@/lib/telemetry';
import { useLabStore, type DocumentVersion } from '@/lib/store';

const MAX_DIALOG_DIFF_CHARS = 6000;

function DiffText({ segments }: { segments: DiffSegment[] }) {
  return (
    <p className="whitespace-pre-wrap text-sm leading-relaxed">
      {segments.map((segment, index) =>
        segment.type === 'same' ? (
          <span key={index}>{segment.text}</span>
        ) : segment.type === 'removed' ? (
          <del
            key={index}
            className="rounded-sm bg-destructive/10 px-0.5 text-destructive/90 decoration-destructive/60"
          >
            {segment.text}
          </del>
        ) : (
          <ins
            key={index}
            className="rounded-sm bg-emerald-500/15 px-0.5 text-emerald-800 no-underline dark:text-emerald-300"
          >
            {segment.text}
          </ins>
        ),
      )}
    </p>
  );
}

function dayLabel(iso: string): string {
  const date = new Date(iso);
  if (isToday(date)) return 'Today';
  if (isYesterday(date)) return 'Yesterday';
  return format(date, 'EEEE, MMM d');
}

type TimelineEntry =
  | {
      type: 'version';
      timestamp: string;
      version: DocumentVersion;
      number: number;
      isCurrent: boolean;
      acceptedEvent: EditEvent | null;
      previous: DocumentVersion | null;
    }
  | { type: 'rejected'; timestamp: string; event: EditEvent };

export default function HistoryPage() {
  const search = useSearch();
  const [, navigate] = useLocation();
  const {
    versions,
    saveVersion,
    documentSession,
    conversations,
    editEvents,
    setActiveConversation,
  } = useLabStore();
  const [tab, setTab] = useState<'edits' | 'chats'>(() =>
    new URLSearchParams(search).get('tab') === 'chats' ? 'chats' : 'edits',
  );
  const [viewChange, setViewChange] = useState<{
    version: DocumentVersion;
    number: number;
    previous: DocumentVersion;
  } | null>(null);

  useEffect(() => {
    if (new URLSearchParams(search).get('tab') === 'chats') setTab('chats');
  }, [search]);

  const { currentSessionEvents, earlierSessionEvents } = useMemo(() => {
    const partitioned = partitionEditEventsBySession(
      editEvents,
      documentSession.sessionKey,
    );
    return {
      currentSessionEvents: partitioned.currentSession,
      earlierSessionEvents: [...partitioned.earlierSessions].sort(
        (a, b) =>
          new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime(),
      ),
    };
  }, [documentSession.sessionKey, editEvents]);

  const entries = useMemo<TimelineEntry[]>(() => {
    const acceptedByVersion = new Map(
      editEvents
        .filter((event) => event.decision === 'accepted' && event.versionAfterId)
        .map((event) => [event.versionAfterId as string, event]),
    );
    const versionEntries: TimelineEntry[] = versions.map((version, index) => ({
      type: 'version',
      timestamp: version.timestamp,
      version,
      number: versions.length - index,
      isCurrent: index === 0,
      acceptedEvent: acceptedByVersion.get(version.id) ?? null,
      previous: versions[index + 1] ?? null,
    }));
    const rejectedEntries: TimelineEntry[] = currentSessionEvents
      .filter((event) => event.decision === 'rejected')
      .map((event) => ({
        type: 'rejected',
        timestamp: event.timestamp,
        event,
      }));
    return [...versionEntries, ...rejectedEntries].sort(
      (a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime(),
    );
  }, [currentSessionEvents, editEvents, versions]);

  const groupedByDay = useMemo(() => {
    const groups: Array<{ label: string; items: TimelineEntry[] }> = [];
    entries.forEach((entry) => {
      const label = dayLabel(entry.timestamp);
      const group = groups[groups.length - 1];
      if (group && group.label === label) group.items.push(entry);
      else groups.push({ label, items: [entry] });
    });
    return groups;
  }, [entries]);

  const sortedConversations = useMemo(
    () =>
      [...conversations].sort(
        (a, b) =>
          new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime(),
      ),
    [conversations],
  );

  const restoreVersion = (version: DocumentVersion, number: number) => {
    saveVersion(version.html, 'Evaluator', `Restored ${version.description}`);
    toast.success(
      `Version ${number} restored as the newest version — nothing was lost.`,
    );
  };

  const diffForDialog = useMemo(() => {
    if (!viewChange) return null;
    const before = stripHtml(viewChange.previous.html);
    const after = stripHtml(viewChange.version.html);
    if (
      before.length > MAX_DIALOG_DIFF_CHARS ||
      after.length > MAX_DIALOG_DIFF_CHARS
    ) {
      return null;
    }
    return diffWords(before, after);
  }, [viewChange]);

  return (
    <div className="mx-auto max-w-4xl space-y-6 p-4 md:p-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">History</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Every version of your document and every conversation with the
          assistant. Restoring never asks the AI anything — it simply brings a
          saved version back.
        </p>
      </header>

      <Tabs value={tab} onValueChange={(value) => setTab(value as 'edits' | 'chats')}>
        <TabsList>
          <TabsTrigger value="edits" data-testid="tab-edit-history">
            <FileClock className="mr-1.5 h-4 w-4" />
            Edit history
          </TabsTrigger>
          <TabsTrigger value="chats" data-testid="tab-chat-history">
            <MessageSquareText className="mr-1.5 h-4 w-4" />
            Chats
          </TabsTrigger>
        </TabsList>
      </Tabs>

      {tab === 'edits' ? (
        <section className="space-y-6" data-testid="section-edit-history">
          {groupedByDay.length === 0 ? (
            <div className="flex flex-col items-center rounded-lg border border-dashed py-14 text-center">
              <GitCommit className="h-8 w-8 text-muted-foreground" />
              <p className="mt-3 text-sm font-medium">No versions yet</p>
              <p className="mt-1 max-w-xs text-xs text-muted-foreground">
                Accept a suggested edit in the editor and each change will show
                up here as a version you can revisit or restore.
              </p>
              <Button className="mt-4" asChild>
                <Link href="/" data-testid="button-empty-go-editor">
                  <Sparkles className="mr-2 h-4 w-4" />
                  Open the editor
                </Link>
              </Button>
            </div>
          ) : (
            groupedByDay.map((group) => (
              <div key={group.label}>
                <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  {group.label}
                </p>
                <ol className="space-y-2 border-l pl-4">
                  {group.items.map((entry) =>
                    entry.type === 'version' ? (
                      <li
                        key={entry.version.id}
                        className="relative rounded-md border bg-card p-3"
                        data-testid={`row-version-${entry.number}`}
                      >
                        <span className="absolute -left-[21.5px] top-4 h-2.5 w-2.5 rounded-full border-2 border-background bg-primary" />
                        <div className="flex flex-wrap items-center gap-2">
                          <p className="text-sm font-medium">
                            Version {entry.number}
                          </p>
                          {entry.isCurrent && (
                            <Badge className="text-[10px]">Current</Badge>
                          )}
                          {entry.acceptedEvent && (
                            <Badge variant="outline" className="text-[10px]">
                              {entry.acceptedEvent.engineLabel}
                            </Badge>
                          )}
                          <span className="ml-auto text-[11px] text-muted-foreground">
                            {format(new Date(entry.timestamp), 'HH:mm')}
                          </span>
                        </div>
                        <p className="mt-1 text-xs text-muted-foreground">
                          {entry.version.author} · {entry.version.description}
                        </p>
                        {entry.acceptedEvent && (
                          <p className="mt-1 truncate text-xs text-muted-foreground">
                            “{entry.acceptedEvent.instruction}”
                          </p>
                        )}
                        <div className="mt-2 flex gap-2">
                          {entry.previous && (
                            <Button
                              variant="outline"
                              size="sm"
                              className="h-7 text-xs"
                              onClick={() =>
                                setViewChange({
                                  version: entry.version,
                                  number: entry.number,
                                  previous: entry.previous as DocumentVersion,
                                })
                              }
                              data-testid={`button-view-change-${entry.number}`}
                            >
                              View change
                            </Button>
                          )}
                          {!entry.isCurrent && (
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-7 text-xs"
                              onClick={() =>
                                restoreVersion(entry.version, entry.number)
                              }
                              data-testid={`button-restore-${entry.number}`}
                            >
                              <RotateCcw className="mr-1 h-3 w-3" />
                              Restore
                            </Button>
                          )}
                        </div>
                      </li>
                    ) : (
                      <li
                        key={entry.event.id}
                        className="relative rounded-md border border-dashed bg-muted/20 p-3"
                        data-testid={`row-rejected-${entry.event.id}`}
                      >
                        <span className="absolute -left-[21.5px] top-4 h-2.5 w-2.5 rounded-full border-2 border-background bg-muted-foreground/40" />
                        <div className="flex flex-wrap items-center gap-2">
                          <XCircle className="h-3.5 w-3.5 text-muted-foreground" />
                          <p className="text-sm text-muted-foreground">
                            Rejected suggestion
                          </p>
                          <Badge variant="outline" className="text-[10px]">
                            {entry.event.engineLabel}
                          </Badge>
                          <span className="ml-auto text-[11px] text-muted-foreground">
                            {format(new Date(entry.timestamp), 'HH:mm')}
                          </span>
                        </div>
                        <p className="mt-1 truncate text-xs text-muted-foreground">
                          “{entry.event.instruction}”
                        </p>
                      </li>
                    ),
                  )}
                </ol>
              </div>
            ))
          )}

          {earlierSessionEvents.length > 0 && (
            <Collapsible>
              <CollapsibleTrigger asChild>
                <button
                  type="button"
                  className="flex w-full items-center justify-between rounded-md border bg-muted/20 px-3 py-2 text-sm text-muted-foreground"
                  data-testid="button-earlier-sessions"
                >
                  Decisions from earlier sessions ({earlierSessionEvents.length})
                  <ChevronDown className="h-4 w-4" />
                </button>
              </CollapsibleTrigger>
              <CollapsibleContent>
                <ul className="mt-2 space-y-2">
                  {earlierSessionEvents.map((event) => (
                    <li
                      key={event.id}
                      className="rounded-md border bg-card p-3 text-xs"
                    >
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-medium">{event.documentTitle}</span>
                        <Badge variant="outline" className="text-[10px]">
                          {event.engineLabel}
                        </Badge>
                        <Badge
                          variant={event.decision === 'accepted' ? 'default' : 'secondary'}
                          className="text-[10px]"
                        >
                          {event.decision}
                        </Badge>
                        <span className="ml-auto text-muted-foreground">
                          {formatRelativeTime(event.timestamp)}
                        </span>
                      </div>
                      <p className="mt-1 truncate text-muted-foreground">
                        “{event.instruction}”
                      </p>
                      <p className="mt-1 text-muted-foreground">
                        These versions belong to an earlier document session, so
                        restore is unavailable.
                      </p>
                    </li>
                  ))}
                </ul>
              </CollapsibleContent>
            </Collapsible>
          )}
        </section>
      ) : (
        <section className="space-y-2" data-testid="section-chat-history">
          {sortedConversations.length === 0 ? (
            <div className="flex flex-col items-center rounded-lg border border-dashed py-14 text-center">
              <MessageSquareText className="h-8 w-8 text-muted-foreground" />
              <p className="mt-3 text-sm font-medium">No conversations yet</p>
              <p className="mt-1 max-w-xs text-xs text-muted-foreground">
                Ask the assistant for an edit and the whole exchange will be
                saved here so you can revisit it any time.
              </p>
              <Button className="mt-4" asChild>
                <Link href="/" data-testid="button-empty-go-assistant">
                  <Sparkles className="mr-2 h-4 w-4" />
                  Ask the assistant
                </Link>
              </Button>
            </div>
          ) : (
            sortedConversations.map((conversation) => (
              <button
                key={conversation.id}
                type="button"
                onClick={() => navigate(`/history/chats/${conversation.id}`)}
                className="flex w-full items-center gap-3 rounded-md border bg-card p-3 text-left transition hover:border-primary/40"
                data-testid={`row-conversation-${conversation.id}`}
              >
                <MessageSquareText className="h-4 w-4 shrink-0 text-muted-foreground" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium">
                    {conversation.title}
                  </span>
                  <span className="block truncate text-xs text-muted-foreground">
                    {conversation.documentTitle} · {conversation.messages.length}{' '}
                    messages
                  </span>
                </span>
                {conversation.sessionKey != null &&
                  conversation.sessionKey === documentSession.sessionKey && (
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-7 shrink-0 text-xs"
                    onClick={(event) => {
                      event.stopPropagation();
                      setActiveConversation(conversation.id);
                      navigate('/');
                    }}
                    data-testid={`button-continue-${conversation.id}`}
                  >
                    Continue
                  </Button>
                )}
                <span className="shrink-0 text-[11px] text-muted-foreground">
                  {formatRelativeTime(conversation.updatedAt)}
                </span>
              </button>
            ))
          )}
        </section>
      )}

      <Dialog
        open={viewChange != null}
        onOpenChange={(open) => {
          if (!open) setViewChange(null);
        }}
      >
        <DialogContent className="max-h-[85vh] max-w-2xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle>
              Version {viewChange?.number}: what changed
            </DialogTitle>
            <DialogDescription>
              Compared with the previous version. Removed text is struck
              through, added text is highlighted.
            </DialogDescription>
          </DialogHeader>
          {viewChange &&
            (diffForDialog ? (
              <div className="rounded-md border bg-muted/10 p-3">
                <DiffText segments={diffForDialog} />
              </div>
            ) : (
              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <p className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    Before
                  </p>
                  <div
                    className="prose-sm max-h-72 overflow-y-auto rounded-md border bg-muted/20 p-3 text-xs"
                    dangerouslySetInnerHTML={{ __html: viewChange.previous.html }}
                  />
                </div>
                <div>
                  <p className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    After
                  </p>
                  <div
                    className="prose-sm max-h-72 overflow-y-auto rounded-md border bg-muted/20 p-3 text-xs"
                    dangerouslySetInnerHTML={{ __html: viewChange.version.html }}
                  />
                </div>
              </div>
            ))}
        </DialogContent>
      </Dialog>
    </div>
  );
}
