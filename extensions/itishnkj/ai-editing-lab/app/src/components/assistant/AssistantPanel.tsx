import {
  useEffect,
  useMemo,
  useRef,
  type KeyboardEvent,
  type RefObject,
} from 'react';
import type {
  EditInputEngine,
  EditInputScope,
  EditResult,
} from '@workspace/api-client-react';
import {
  ArrowUp,
  ChevronDown,
  FileText,
  Loader2,
  MessageSquarePlus,
  MoreHorizontal,
  Sparkles,
  TextSelect,
  X,
} from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Textarea } from '@/components/ui/textarea';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { ReviewCard } from '@/components/assistant/ReviewCard';
import { PROMPT_PRESETS } from '@/lib/constants';
import type { ChatMessage } from '@/lib/history';
import { formatUsd, type estimateRequestContext } from '@/lib/telemetry';
import { cn } from '@/lib/utils';

type Preflight = ReturnType<typeof estimateRequestContext>;

export type EngineStatusInfo = {
  id: string;
  label: string;
  configured: boolean;
  modelLabel?: string | null;
};

export type AssistantDevMetrics = {
  diyModelLabel: string;
  superdocsModelLabel: string;
  promptVersion: string;
  chunkSummary: string;
  latestLatencyMs: number | null;
  latestTokens: number | string | null;
  latestRetries: number | null;
};

const ENGINE_OPTIONS: Array<{
  id: EditInputEngine | 'both';
  label: string;
  hint: string;
}> = [
  { id: 'diy', label: 'DIY', hint: 'Uses your configured AI model' },
  { id: 'superdocs', label: 'SuperDocs', hint: 'Hosted editing service with staged review' },
  { id: 'both', label: 'Compare', hint: 'Asks both engines so you can pick the better edit' },
];

const SELECTION_PRESETS = ['Make concise', 'Fix grammar', 'Improve clarity'];
const DOCUMENT_PRESETS = ['Improve clarity', 'Professional tone', 'Simplify language'];

function DecisionChip({
  message,
  reviewStillOpen,
}: {
  message: ChatMessage;
  reviewStillOpen: boolean;
}) {
  if (message.kind !== 'proposal' || !message.decision) return null;
  if (message.decision === 'accepted') {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/15 px-2 py-0.5 text-[10px] font-medium text-emerald-700 dark:text-emerald-300">
        Accepted{message.versionAfterNumber ? ` · v${message.versionAfterNumber}` : ''}
      </span>
    );
  }
  if (message.decision === 'rejected') {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
        Rejected
      </span>
    );
  }
  if (message.decision === 'cancelled') {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
        Cancelled
      </span>
    );
  }
  if (message.decision === 'error') {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-destructive/10 px-2 py-0.5 text-[10px] font-medium text-destructive">
        Failed
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-amber-500/15 px-2 py-0.5 text-[10px] font-medium text-amber-700 dark:text-amber-300">
      {reviewStillOpen ? 'Awaiting your review' : 'Review closed'}
    </span>
  );
}

export type AssistantPanelProps = {
  engineMode: EditInputEngine | 'both';
  onEngineModeChange: (mode: EditInputEngine | 'both') => void;
  statuses: Map<string, EngineStatusInfo>;
  selectedConfigured: boolean;
  messages: ChatMessage[];
  onNewChat: () => void;
  isRunning: boolean;
  elapsedMs: number;
  pendingResults: EditResult[];
  reviewScope: EditInputScope | null;
  scope: EditInputScope;
  selectionText: string;
  onUseWholeDocument: () => void;
  instruction: string;
  onInstructionChange: (value: string) => void;
  onSubmit: () => void;
  canSubmit: boolean;
  preflight: Preflight;
  diyCostUsd: number | null;
  hardBudgetChars: number;
  developerMode: boolean;
  busyReview: boolean;
  onAccept: (result: EditResult) => void;
  onReject: (result: EditResult) => void;
  onRejectAll: () => void;
  onAskAgain: (result: EditResult) => void;
  onCancelHosted: (result: EditResult) => void;
  composerRef: RefObject<HTMLTextAreaElement | null>;
  devMetrics: AssistantDevMetrics;
  className?: string;
};

export function AssistantPanel({
  engineMode,
  onEngineModeChange,
  statuses,
  selectedConfigured,
  messages,
  onNewChat,
  isRunning,
  elapsedMs,
  pendingResults,
  reviewScope,
  scope,
  selectionText,
  onUseWholeDocument,
  instruction,
  onInstructionChange,
  onSubmit,
  canSubmit,
  preflight,
  diyCostUsd,
  hardBudgetChars,
  developerMode,
  busyReview,
  onAccept,
  onReject,
  onRejectAll,
  onAskAgain,
  onCancelHosted,
  composerRef,
  devMetrics,
  className,
}: AssistantPanelProps) {
  const threadEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    threadEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages.length, pendingResults.length, isRunning]);

  const pendingKeys = useMemo(
    () =>
      new Set(pendingResults.map((result) => `${result.requestId}:${result.engine}`)),
    [pendingResults],
  );

  const contextualPresets =
    scope === 'selection' ? SELECTION_PRESETS : DOCUMENT_PRESETS;
  const morePresets = PROMPT_PRESETS.filter(
    (preset) => !contextualPresets.includes(preset),
  );

  const isEmpty = messages.length === 0 && pendingResults.length === 0 && !isRunning;
  const currentEngineHint =
    ENGINE_OPTIONS.find((option) => option.id === engineMode)?.hint ?? '';

  const handleComposerKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      if (canSubmit) onSubmit();
    }
  };

  return (
    <div className={cn('flex h-full min-h-0 flex-col bg-card', className)}>
      <header className="flex h-12 shrink-0 items-center gap-2 border-b px-3">
        <Sparkles className="h-4 w-4 text-primary" />
        <h2 className="text-sm font-semibold">AI Assistant</h2>
        <div className="ml-auto">
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                aria-label="Start a new chat"
                onClick={onNewChat}
                disabled={isRunning || pendingResults.length > 0 || messages.length === 0}
                data-testid="button-new-chat"
              >
                <MessageSquarePlus className="h-4 w-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Start a new chat</TooltipContent>
          </Tooltip>
        </div>
      </header>

      <div className="shrink-0 border-b px-3 py-2">
        <div
          className="grid grid-cols-3 rounded-md border bg-muted/40 p-1"
          role="group"
          aria-label="Editing engine"
        >
          {ENGINE_OPTIONS.map((option) => {
            const disabled =
              option.id === 'both'
                ? !statuses.get('diy')?.configured ||
                  !statuses.get('superdocs')?.configured
                : !statuses.get(option.id)?.configured;
            return (
              <button
                key={option.id}
                type="button"
                disabled={disabled}
                onClick={() => onEngineModeChange(option.id)}
                aria-pressed={engineMode === option.id}
                title={option.hint}
                className={cn(
                  'rounded px-2 py-1.5 text-xs font-medium transition',
                  engineMode === option.id
                    ? 'bg-background text-foreground shadow-sm'
                    : 'text-muted-foreground hover:text-foreground',
                  'disabled:cursor-not-allowed disabled:opacity-40',
                )}
                data-testid={`button-engine-${option.id}`}
              >
                {option.label}
              </button>
            );
          })}
        </div>
        <p className="mt-1.5 text-[11px] text-muted-foreground">{currentEngineHint}</p>
        {!selectedConfigured && (
          <p className="mt-1.5 rounded-md border border-amber-500/30 bg-amber-500/5 p-2 text-[11px] text-muted-foreground">
            {engineMode === 'superdocs'
              ? 'SuperDocs needs setup — add SUPERDOCS_API_KEY through Replit Secrets.'
              : engineMode === 'both'
                ? 'Comparing needs both engines to be ready.'
                : 'DIY needs setup — add OPENAI_API_KEY and OPENAI_MODEL.'}
          </p>
        )}
      </div>

      <ScrollArea className="min-h-0 flex-1 overflow-x-hidden">
        <div className="min-w-0 space-y-3 overflow-x-hidden p-3" data-testid="thread-assistant">
          {isEmpty ? (
            <div className="flex flex-col items-center px-4 py-10 text-center">
              <span className="flex h-12 w-12 items-center justify-center rounded-full bg-accent">
                <Sparkles className="h-5 w-5 text-primary" />
              </span>
              <p className="mt-3 text-sm font-medium">Ask for any edit</p>
              <p className="mt-1 max-w-[240px] text-xs text-muted-foreground">
                Describe a change in your own words, or start with one of these:
              </p>
              <div className="mt-3 flex w-full max-w-[240px] flex-col gap-1.5">
                {contextualPresets.map((preset) => (
                  <button
                    key={preset}
                    type="button"
                    onClick={() => onInstructionChange(preset)}
                    className="rounded-md border bg-background px-3 py-2 text-xs text-muted-foreground transition hover:border-primary/40 hover:text-foreground"
                    data-testid={`button-empty-preset-${preset.toLowerCase().replace(/\s+/g, '-')}`}
                  >
                    {preset}
                  </button>
                ))}
              </div>
              <p className="mt-4 text-[11px] text-muted-foreground">
                Nothing changes until you approve it.
              </p>
            </div>
          ) : (
            messages.map((message) => {
              if (message.role === 'user') {
                return (
                  <div key={message.id} className="flex justify-end">
                    <div className="max-w-[85%]">
                      <div className="rounded-2xl rounded-br-sm bg-primary px-3 py-2 text-sm text-primary-foreground">
                        {message.text}
                      </div>
                      <p className="mt-0.5 text-right text-[10px] text-muted-foreground">
                        {message.scope === 'selection' ? 'Selected text' : 'Whole document'}
                        {' · '}
                        {new Date(message.timestamp).toLocaleTimeString([], {
                          hour: '2-digit',
                          minute: '2-digit',
                        })}
                      </p>
                    </div>
                  </div>
                );
              }
              const reviewStillOpen =
                message.requestId != null &&
                message.engine != null &&
                message.engine !== 'both' &&
                pendingKeys.has(`${message.requestId}:${message.engine}`);
              return (
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
                      <DecisionChip message={message} reviewStillOpen={reviewStillOpen} />
                      {new Date(message.timestamp).toLocaleTimeString([], {
                        hour: '2-digit',
                        minute: '2-digit',
                      })}
                    </p>
                  </div>
                </div>
              );
            })
          )}

          {isRunning && (
            <div className="flex justify-start">
              <div className="flex items-center gap-2 rounded-2xl rounded-bl-sm bg-muted px-3 py-2 text-sm text-muted-foreground">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                Working on your edit… {(elapsedMs / 1000).toFixed(1)}s
              </div>
            </div>
          )}

          {pendingResults.length > 0 && reviewScope && (
            <section
              className="min-w-0 space-y-2 pt-1"
              aria-label="Suggested edits awaiting review"
            >
              <div className="flex items-center justify-between">
                <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                  For your review
                </p>
                {pendingResults.length > 1 && (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-6 px-2 text-[11px] text-muted-foreground"
                    onClick={onRejectAll}
                    disabled={busyReview}
                    data-testid="button-reject-all"
                  >
                    <X className="mr-1 h-3 w-3" />
                    Reject all
                  </Button>
                )}
              </div>
              {pendingResults.map((result) => (
                <ReviewCard
                  key={`${result.requestId}:${result.engine}`}
                  result={result}
                  scope={reviewScope}
                  busy={busyReview}
                  developerMode={developerMode}
                  onAccept={onAccept}
                  onReject={onReject}
                  onAskAgain={onAskAgain}
                  onCancelHosted={onCancelHosted}
                />
              ))}
            </section>
          )}

          {developerMode && (
            <Collapsible>
              <CollapsibleTrigger asChild>
                <button
                  type="button"
                  className="flex w-full items-center justify-between rounded-md border bg-muted/20 px-3 py-2 text-xs font-medium text-muted-foreground"
                  data-testid="button-dev-metrics"
                >
                  Developer metrics
                  <ChevronDown className="h-3.5 w-3.5" />
                </button>
              </CollapsibleTrigger>
              <CollapsibleContent>
                <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1.5 rounded-md border bg-muted/10 p-3 text-[11px] text-muted-foreground">
                  <dt>DIY model</dt>
                  <dd className="text-right font-mono">{devMetrics.diyModelLabel}</dd>
                  <dt>SuperDocs model</dt>
                  <dd className="text-right font-mono">{devMetrics.superdocsModelLabel}</dd>
                  <dt>Prompt version</dt>
                  <dd className="text-right font-mono">{devMetrics.promptVersion}</dd>
                  <dt>Structured output</dt>
                  <dd className="text-right">Enabled</dd>
                  <dt>Max repair retries</dt>
                  <dd className="text-right font-mono">1</dd>
                  <dt>Chunk IDs</dt>
                  <dd className="text-right font-mono">{devMetrics.chunkSummary}</dd>
                  <dt>Latest latency</dt>
                  <dd className="text-right font-mono">
                    {devMetrics.latestLatencyMs != null
                      ? `${devMetrics.latestLatencyMs} ms`
                      : 'N/A'}
                  </dd>
                  <dt>Latest tokens</dt>
                  <dd className="text-right font-mono">
                    {devMetrics.latestTokens ?? 'Not exposed'}
                  </dd>
                  <dt>Latest retries</dt>
                  <dd className="text-right font-mono">
                    {devMetrics.latestRetries ?? 'N/A'}
                  </dd>
                </dl>
              </CollapsibleContent>
            </Collapsible>
          )}

          <div ref={threadEndRef} />
        </div>
      </ScrollArea>

      <div className="min-w-0 shrink-0 space-y-2 border-t bg-card p-3">
        <div className="flex items-center gap-1.5">
          {scope === 'selection' ? (
            <span
              className="flex min-w-0 items-center gap-1.5 rounded-full border border-primary/30 bg-accent px-2.5 py-1 text-[11px] text-accent-foreground"
              data-testid="chip-scope-selection"
            >
              <TextSelect className="h-3 w-3 shrink-0" />
              <span className="shrink-0 font-medium">Editing selected text</span>
              <span className="truncate text-muted-foreground">“{selectionText}”</span>
              <button
                type="button"
                onClick={onUseWholeDocument}
                aria-label="Switch to editing the whole document"
                className="ml-0.5 shrink-0 rounded-full p-0.5 hover:bg-primary/10"
                data-testid="button-clear-selection-scope"
              >
                <X className="h-3 w-3" />
              </button>
            </span>
          ) : (
            <span
              className="flex items-center gap-1.5 rounded-full border bg-muted/40 px-2.5 py-1 text-[11px] text-muted-foreground"
              data-testid="chip-scope-document"
            >
              <FileText className="h-3 w-3" />
              Editing whole document — select text to narrow it
            </span>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-1.5">
          {contextualPresets.map((preset) => (
            <button
              key={preset}
              type="button"
              onClick={() => onInstructionChange(preset)}
              className="rounded-full border bg-background px-2.5 py-1 text-[11px] text-muted-foreground transition hover:border-primary/40 hover:text-foreground"
              data-testid={`button-preset-${preset.toLowerCase().replace(/\s+/g, '-')}`}
            >
              {preset}
            </button>
          ))}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                aria-label="More presets"
                className="rounded-full border bg-background p-1.5 text-muted-foreground transition hover:border-primary/40 hover:text-foreground"
                data-testid="button-more-presets"
              >
                <MoreHorizontal className="h-3.5 w-3.5" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
              {morePresets.map((preset) => (
                <DropdownMenuItem
                  key={preset}
                  onSelect={() => onInstructionChange(preset)}
                  data-testid={`menu-preset-${preset.toLowerCase().replace(/\s+/g, '-')}`}
                >
                  {preset}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>

        <div className="relative">
          <Textarea
            ref={composerRef}
            value={instruction}
            onChange={(event) => onInstructionChange(event.target.value)}
            onKeyDown={handleComposerKeyDown}
            placeholder="Describe the edit you want…"
            aria-label="Editing instruction"
            className="max-h-40 min-h-[64px] resize-none pr-12"
            data-testid="input-instruction"
          />
          <Button
            size="icon"
            className="absolute bottom-2 right-2 h-8 w-8 rounded-full"
            onClick={onSubmit}
            disabled={!canSubmit}
            aria-label={
              engineMode === 'both' ? 'Ask both engines' : 'Send instruction'
            }
            data-testid="button-send-instruction"
          >
            {isRunning ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <ArrowUp className="h-4 w-4" />
            )}
          </Button>
        </div>

        <Collapsible>
          <div className="flex items-center justify-between gap-2 text-[11px] text-muted-foreground">
            <p data-testid="text-cost-line">
              Sends ~{preflight.contextChars.toLocaleString()} characters
              {diyCostUsd != null ? ` · est. ${formatUsd(diyCostUsd)}` : ''}
            </p>
            <CollapsibleTrigger asChild>
              <button
                type="button"
                className="flex shrink-0 items-center gap-0.5 underline-offset-2 hover:underline"
                data-testid="button-cost-details"
              >
                Details
                <ChevronDown className="h-3 w-3" />
              </button>
            </CollapsibleTrigger>
          </div>
          <CollapsibleContent>
            <div className="mt-2 rounded-md border bg-muted/20 p-2.5 text-[11px]">
              <p className="text-muted-foreground">{preflight.note}</p>
              <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 font-mono">
                <dt className="text-muted-foreground">Context sent</dt>
                <dd className="text-right">
                  {preflight.contextChars.toLocaleString()} chars
                </dd>
                <dt className="text-muted-foreground">Prompt estimate</dt>
                <dd className="text-right">
                  {preflight.estimatedPromptChars.toLocaleString()} chars
                </dd>
                <dt className="text-muted-foreground">DIY cost estimate</dt>
                <dd className="text-right">
                  {diyCostUsd == null ? 'Pricing not configured' : formatUsd(diyCostUsd)}
                </dd>
              </dl>
              <p className="mt-2 text-muted-foreground">
                Planning estimate based on characters. Recorded DIY spend uses actual
                provider tokens after completion.
              </p>
            </div>
          </CollapsibleContent>
        </Collapsible>

        {preflight.softExceeded && !preflight.hardExceeded && (
          <p className="rounded-md border border-amber-500/30 bg-amber-500/5 p-2 text-[11px] text-amber-700 dark:text-amber-300">
            This is a large request — you will be asked to confirm before it is sent.
          </p>
        )}
        {preflight.hardExceeded && (
          <p className="rounded-md border border-destructive/30 bg-destructive/5 p-2 text-[11px] text-destructive">
            Over the context limit of {hardBudgetChars.toLocaleString()} characters.
            Shorten the request or raise the limit in Insights → Cost & Context.
          </p>
        )}
      </div>
    </div>
  );
}
