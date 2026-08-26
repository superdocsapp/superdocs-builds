import { useMemo, useState } from 'react';
import type { EditInputScope, EditResult } from '@workspace/api-client-react';
import { Check, ChevronDown, RefreshCcw, X } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible';
import { diffWords, type DiffSegment } from '@/lib/history';
import { stripHtml } from '@/lib/telemetry';

const MAX_INLINE_DIFF_CHARS = 1600;

const OPERATION_LABELS: Record<string, string> = {
  edit: 'Changed',
  create: 'Added',
  delete: 'Removed',
};

function InlineDiff({ segments }: { segments: DiffSegment[] }) {
  return (
    <p className="text-sm leading-relaxed" data-testid="text-inline-diff">
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

function BeforeAfter({
  beforeHtml,
  afterHtml,
  afterLabel,
}: {
  beforeHtml: string | null | undefined;
  afterHtml: string | null | undefined;
  afterLabel: string;
}) {
  return (
    <div className="grid min-w-0 max-w-full gap-2 text-xs">
      <div className="min-w-0 max-w-full rounded-md border bg-muted/30 p-2.5">
        <p className="mb-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
          Before
        </p>
        <div
          className="prose-sm max-h-32 max-w-full overflow-hidden break-words text-muted-foreground [&_*]:max-w-full [&_*]:break-words [&_a]:underline [&_table]:table-fixed [&_table]:w-full"
          dangerouslySetInnerHTML={{
            __html: beforeHtml || '<em>No existing content</em>',
          }}
        />
      </div>
      <div className="min-w-0 max-w-full rounded-md border border-emerald-500/30 bg-emerald-500/5 p-2.5">
        <p className="mb-1 text-[11px] font-medium uppercase tracking-wide text-emerald-700 dark:text-emerald-400">
          {afterLabel}
        </p>
        <div
          className="prose-sm max-h-36 max-w-full overflow-hidden break-words [&_*]:max-w-full [&_*]:break-words [&_a]:underline [&_table]:table-fixed [&_table]:w-full"
          dangerouslySetInnerHTML={{
            __html: afterHtml || '<em>This content is removed</em>',
          }}
        />
      </div>
    </div>
  );
}

function ChangeBlock({
  change,
  assistantMessage,
  developerMode,
}: {
  change: EditResult['proposedChanges'][number];
  assistantMessage: string | null | undefined;
  developerMode: boolean;
}) {
  const [showFormatted, setShowFormatted] = useState(false);
  const beforeText = useMemo(
    () => stripHtml(change.oldHtml ?? '').trim(),
    [change.oldHtml],
  );
  const afterText = useMemo(
    () => stripHtml(change.newHtml ?? '').trim(),
    [change.newHtml],
  );
  const canInlineDiff =
    change.operation === 'edit' &&
    beforeText.length > 0 &&
    afterText.length > 0 &&
    beforeText.length <= MAX_INLINE_DIFF_CHARS &&
    afterText.length <= MAX_INLINE_DIFF_CHARS;
  const segments = useMemo(
    () => (canInlineDiff ? diffWords(beforeText, afterText) : []),
    [afterText, beforeText, canInlineDiff],
  );
  const explanation = change.explanation ?? assistantMessage;

  return (
    <div className="space-y-2 rounded-md border bg-background p-3">
      <div className="flex items-center justify-between gap-2">
        <Badge variant="secondary" className="text-[10px]">
          {OPERATION_LABELS[change.operation] ?? change.operation}
        </Badge>
        {developerMode && change.chunkId && (
          <span className="font-mono text-[10px] text-muted-foreground">
            {change.chunkId}
          </span>
        )}
      </div>
      {explanation && (
        <p className="text-xs text-muted-foreground">{explanation}</p>
      )}
      {canInlineDiff ? (
        <>
          <InlineDiff segments={segments} />
          <button
            type="button"
            className="text-[11px] text-muted-foreground underline-offset-2 hover:underline"
            onClick={() => setShowFormatted((value) => !value)}
            data-testid="button-toggle-formatted-view"
          >
            {showFormatted ? 'Hide formatted view' : 'Show formatted view'}
          </button>
          {showFormatted && (
            <BeforeAfter
              beforeHtml={change.oldHtml}
              afterHtml={change.newHtml}
              afterLabel="After"
            />
          )}
        </>
      ) : (
        <BeforeAfter
          beforeHtml={change.oldHtml}
          afterHtml={change.newHtml}
          afterLabel={
            change.operation === 'create'
              ? 'New content'
              : change.operation === 'delete'
                ? 'Proposed removal'
                : 'After'
          }
        />
      )}
    </div>
  );
}

export type ReviewCardProps = {
  result: EditResult;
  scope: EditInputScope;
  busy: boolean;
  developerMode: boolean;
  onAccept: (result: EditResult) => void;
  onReject: (result: EditResult) => void;
  onAskAgain: (result: EditResult) => void;
  onCancelHosted: (result: EditResult) => void;
};

export function ReviewCard({
  result,
  scope,
  busy,
  developerMode,
  onAccept,
  onReject,
  onAskAgain,
  onCancelHosted,
}: ReviewCardProps) {
  const isWholeDocument = scope === 'document';

  return (
    <article
      className="min-w-0 max-w-full overflow-hidden rounded-lg border border-primary/25 bg-card p-3 shadow-sm"
      data-testid={`card-review-${result.engine}`}
    >
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <p className="text-sm font-semibold">Suggested edit</p>
        <Badge variant="outline" className="text-[10px]">
          {result.engineLabel}
        </Badge>
        {isWholeDocument && (
          <Badge variant="secondary" className="text-[10px]">
            Whole document
          </Badge>
        )}
        {developerMode && (
          <span className="ml-auto font-mono text-[10px] text-muted-foreground">
            {result.latencyMs}ms · {result.retryCount} retries
          </span>
        )}
      </div>

      {result.review && (
        <p className="mb-2 rounded-md border border-primary/20 bg-primary/5 p-2 text-[11px] text-muted-foreground">
          SuperDocs reviews changes in steps — this is step{' '}
          {result.review.batchNumber} with {result.proposedChanges.length}{' '}
          {result.proposedChanges.length === 1 ? 'change' : 'changes'}. Your
          decision is sent back to the service.
          {developerMode && result.reviewWaitMs && result.reviewWaitMs > 0
            ? ` Reviewer wait: ${result.reviewWaitMs}ms.`
            : ''}
        </p>
      )}

      <div className="space-y-2">
        {result.proposedChanges.map((change) => (
          <ChangeBlock
            key={change.id}
            change={change}
            assistantMessage={result.assistantMessage}
            developerMode={developerMode}
          />
        ))}
        {result.proposedChanges.length === 0 && result.candidateDocumentHtml && (
          <Collapsible>
            <p className="text-xs text-muted-foreground">
              {result.assistantMessage ??
                'The assistant rewrote the document based on your instruction.'}
            </p>
            <CollapsibleTrigger asChild>
              <button
                type="button"
                className="mt-1 flex items-center gap-1 text-[11px] text-muted-foreground underline-offset-2 hover:underline"
                data-testid="button-view-full-document-result"
              >
                View updated document
                <ChevronDown className="h-3 w-3" />
              </button>
            </CollapsibleTrigger>
            <CollapsibleContent>
              <div
                className="prose-sm mt-2 max-h-60 overflow-y-auto rounded-md border bg-background p-3"
                dangerouslySetInnerHTML={{ __html: result.candidateDocumentHtml }}
              />
            </CollapsibleContent>
          </Collapsible>
        )}
      </div>

      {developerMode && (
        <p className="mt-2 break-all font-mono text-[10px] text-muted-foreground">
          request {result.requestId}
        </p>
      )}

      <div className="sticky bottom-0 z-10 -mx-3 mt-3 border-t border-primary/15 bg-card/95 px-3 pb-1 pt-3 backdrop-blur supports-[backdrop-filter]:bg-card/85">
        <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
          Review actions
        </p>
        <div className="grid grid-cols-2 gap-2">
        <Button
          size="sm"
          className="col-span-2 h-10 w-full text-sm font-semibold"
          onClick={() => onAccept(result)}
          disabled={busy}
          data-testid={`button-accept-${result.engine}`}
        >
          <Check className="mr-1.5 h-4 w-4" />
          {result.review ? 'Accept these changes' : 'Accept'}
        </Button>
        <Button
          variant="outline"
          size="sm"
          className="h-10 min-w-0 whitespace-normal"
          onClick={() => onReject(result)}
          disabled={busy}
          data-testid={`button-reject-${result.engine}`}
        >
          <X className="mr-1.5 h-4 w-4" />
          Reject
        </Button>
        <Button
          variant="ghost"
          size="sm"
          className="h-10 min-w-0 whitespace-normal px-2 text-xs"
          onClick={() => onAskAgain(result)}
          disabled={busy}
          data-testid={`button-ask-again-${result.engine}`}
        >
          <RefreshCcw className="mr-1.5 h-4 w-4 shrink-0" />
          Try another approach
        </Button>
        </div>
        {result.review && (
          <Button
            variant="outline"
            size="sm"
            className="mt-2 h-9 w-full whitespace-normal text-muted-foreground"
            onClick={() => onCancelHosted(result)}
            disabled={busy}
            data-testid={`button-cancel-hosted-${result.engine}`}
          >
            Stop this review — keep my document as is
          </Button>
        )}
      </div>
    </article>
  );
}
