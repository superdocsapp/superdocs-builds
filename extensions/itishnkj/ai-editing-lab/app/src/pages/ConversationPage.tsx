import { useMemo } from 'react';
import { Link, useLocation, useParams } from 'wouter';
import { format } from 'date-fns';
import { ArrowLeft, Info, MessageSquareText, Sparkles } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import type { ChatMessage } from '@/lib/history';
import { useLabStore } from '@/lib/store';
import { cn } from '@/lib/utils';

function ReadOnlyDecisionChip({ message }: { message: ChatMessage }) {
  if (message.kind !== 'proposal' || !message.decision) return null;
  if (message.decision === 'accepted') {
    return (
      <span className="rounded-full bg-emerald-500/15 px-2 py-0.5 text-[10px] font-medium text-emerald-700 dark:text-emerald-300">
        Accepted{message.versionAfterNumber ? ` · v${message.versionAfterNumber}` : ''}
      </span>
    );
  }
  const label =
    message.decision === 'rejected'
      ? 'Rejected'
      : message.decision === 'cancelled'
        ? 'Cancelled'
        : message.decision === 'error'
          ? 'Failed'
          : 'Not decided';
  return (
    <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
      {label}
    </span>
  );
}

export default function ConversationPage() {
  const params = useParams<{ conversationId: string }>();
  const [, navigate] = useLocation();
  const { conversations, documentSession, setActiveConversation } = useLabStore();

  const conversation = useMemo(
    () =>
      conversations.find((item) => item.id === params.conversationId) ?? null,
    [conversations, params.conversationId],
  );

  if (!conversation) {
    return (
      <div className="flex h-full items-center justify-center p-6">
        <div className="max-w-sm text-center">
          <MessageSquareText className="mx-auto h-10 w-10 text-muted-foreground" />
          <h1 className="mt-4 text-lg font-semibold">Conversation not found</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            This conversation may have been cleared, or the link is out of date.
          </p>
          <Button className="mt-4" asChild>
            <Link href="/history?tab=chats" data-testid="button-back-to-history">
              Back to history
            </Link>
          </Button>
        </div>
      </div>
    );
  }

  const belongsToCurrentDocument =
    conversation.sessionKey != null &&
    conversation.sessionKey === documentSession.sessionKey;

  return (
    <div className="mx-auto flex h-full max-w-3xl flex-col p-4 md:p-6">
      <header className="shrink-0">
        <Button
          variant="ghost"
          size="sm"
          className="-ml-2 text-muted-foreground"
          asChild
        >
          <Link href="/history?tab=chats" data-testid="link-back-history">
            <ArrowLeft className="mr-1.5 h-4 w-4" />
            All chats
          </Link>
        </Button>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <h1 className="text-xl font-semibold tracking-tight">
            {conversation.title}
          </h1>
          <Badge variant="outline" className="text-[10px]">
            {conversation.documentTitle}
          </Badge>
        </div>
        <p className="mt-1 text-xs text-muted-foreground">
          Started {format(new Date(conversation.createdAt), 'MMM d, yyyy HH:mm')} ·{' '}
          {conversation.messages.length} messages
        </p>

        {belongsToCurrentDocument ? (
          <Button
            className="mt-3"
            size="sm"
            onClick={() => {
              setActiveConversation(conversation.id);
              navigate('/');
            }}
            data-testid="button-continue-in-editor"
          >
            <Sparkles className="mr-2 h-4 w-4" />
            Continue in editor
          </Button>
        ) : (
          <p className="mt-3 flex items-start gap-2 rounded-md border bg-muted/20 p-2.5 text-xs text-muted-foreground">
            <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            This chat belongs to an earlier document session
            (“{conversation.documentTitle}”). You can read it here, but it can’t
            be continued because that document is no longer active.
          </p>
        )}
      </header>

      <div
        className="mt-4 min-h-0 flex-1 space-y-3 overflow-y-auto rounded-lg border bg-muted/10 p-4"
        data-testid="thread-conversation"
      >
        {conversation.messages.map((message) =>
          message.role === 'user' ? (
            <div key={message.id} className="flex justify-end">
              <div className="max-w-[85%]">
                <div className="rounded-2xl rounded-br-sm bg-primary px-3 py-2 text-sm text-primary-foreground">
                  {message.text}
                </div>
                <p className="mt-0.5 text-right text-[10px] text-muted-foreground">
                  {message.scope === 'selection' ? 'Selected text' : 'Whole document'}
                  {' · '}
                  {format(new Date(message.timestamp), 'HH:mm')}
                </p>
              </div>
            </div>
          ) : (
            <div key={message.id} className="flex justify-start">
              <div className="max-w-[90%]">
                <div
                  className={cn(
                    'rounded-2xl rounded-bl-sm px-3 py-2 text-sm',
                    message.kind === 'error'
                      ? 'border border-destructive/30 bg-destructive/5 text-destructive'
                      : 'bg-muted text-foreground',
                  )}
                >
                  {message.engineLabel && (
                    <p className="mb-0.5 text-[10px] font-medium text-muted-foreground">
                      {message.engineLabel}
                    </p>
                  )}
                  {message.text}
                </div>
                <p className="mt-0.5 flex items-center gap-1.5 text-[10px] text-muted-foreground">
                  <ReadOnlyDecisionChip message={message} />
                  {format(new Date(message.timestamp), 'HH:mm')}
                </p>
              </div>
            </div>
          ),
        )}
        {conversation.messages.length === 0 && (
          <p className="py-8 text-center text-sm text-muted-foreground">
            This conversation has no messages.
          </p>
        )}
      </div>
      <p className="mt-2 shrink-0 text-center text-[11px] text-muted-foreground">
        Reading history never re-runs AI requests.
      </p>
    </div>
  );
}
