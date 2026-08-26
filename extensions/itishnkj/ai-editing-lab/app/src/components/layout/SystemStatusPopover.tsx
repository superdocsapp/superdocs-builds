import { useGetLabConfig, useHealthCheck } from '@workspace/api-client-react';
import { Activity } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import { cn } from '@/lib/utils';

const ENGINE_DESCRIPTIONS: Record<string, string> = {
  diy: 'Editing engine built in this app',
  superdocs: 'Hosted editing service',
};

const ENGINE_SETUP_HINTS: Record<string, string> = {
  diy: 'Add OPENAI_API_KEY and OPENAI_MODEL to enable it.',
  superdocs: 'Add SUPERDOCS_API_KEY to enable it.',
};

export function useSystemStatus() {
  const { data: health, isLoading } = useHealthCheck();
  const { data: config } = useGetLabConfig();
  const engines = config?.engines ?? [];
  const serverOk = health?.status === 'ok';
  const allReady =
    serverOk && engines.length > 0 && engines.every((engine) => engine.configured);
  return { engines, serverOk, allReady, isLoading };
}

export function StatusDot({
  ready,
  className,
}: {
  ready: boolean;
  className?: string;
}) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        'inline-block h-2 w-2 shrink-0 rounded-full',
        ready ? 'bg-emerald-500' : 'bg-amber-500',
        className,
      )}
    />
  );
}

/** Plain-language status list, shared by the popover and the Settings page. */
export function EngineStatusList({ showModels }: { showModels?: boolean }) {
  const { engines, serverOk, isLoading } = useSystemStatus();
  return (
    <ul className="space-y-3" data-testid="list-engine-status">
      <li className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm font-medium">App server</p>
          <p className="text-xs text-muted-foreground">
            Handles editing requests from this browser
          </p>
        </div>
        <span
          className={cn(
            'mt-0.5 flex items-center gap-1.5 text-xs font-medium',
            serverOk ? 'text-emerald-600 dark:text-emerald-400' : 'text-amber-600 dark:text-amber-400',
          )}
          data-testid="status-server"
        >
          <StatusDot ready={serverOk} />
          {isLoading ? 'Checking…' : serverOk ? 'Ready' : 'Unreachable'}
        </span>
      </li>
      {engines.map((engine) => (
        <li key={engine.id} className="flex items-start justify-between gap-3">
          <div>
            <p className="text-sm font-medium">{engine.label}</p>
            <p className="text-xs text-muted-foreground">
              {ENGINE_DESCRIPTIONS[engine.id] ?? 'Editing engine'}
              {showModels && engine.configured && engine.modelLabel
                ? ` · ${engine.modelLabel}`
                : ''}
            </p>
            {!engine.configured && (
              <p className="mt-0.5 text-xs text-amber-700 dark:text-amber-300">
                {ENGINE_SETUP_HINTS[engine.id] ?? 'Needs setup.'}
              </p>
            )}
          </div>
          <span
            className={cn(
              'mt-0.5 flex items-center gap-1.5 text-xs font-medium',
              engine.configured
                ? 'text-emerald-600 dark:text-emerald-400'
                : 'text-amber-600 dark:text-amber-400',
            )}
            data-testid={`status-engine-${engine.id}`}
          >
            <StatusDot ready={engine.configured} />
            {engine.configured ? 'Ready' : 'Needs setup'}
          </span>
        </li>
      ))}
      {engines.length === 0 && !isLoading && (
        <li className="text-xs text-muted-foreground">
          Engine status is unavailable right now.
        </li>
      )}
    </ul>
  );
}

export function SystemStatusPopover({
  compact,
  showModels,
}: {
  compact?: boolean;
  showModels?: boolean;
}) {
  const { allReady, isLoading } = useSystemStatus();
  return (
    <Popover>
      <PopoverTrigger asChild>
        {compact ? (
          <Button
            variant="ghost"
            size="icon"
            aria-label="System status"
            data-testid="button-system-status"
          >
            <StatusDot ready={allReady} className="h-2.5 w-2.5" />
          </Button>
        ) : (
          <Button
            variant="ghost"
            size="sm"
            className="w-full justify-start gap-2 px-2 text-xs text-muted-foreground"
            data-testid="button-system-status"
          >
            <StatusDot ready={allReady} />
            <span className="truncate">
              {isLoading
                ? 'Checking status…'
                : allReady
                  ? 'All systems ready'
                  : 'Some setup needed'}
            </span>
            <Activity className="ml-auto h-3.5 w-3.5 opacity-60" />
          </Button>
        )}
      </PopoverTrigger>
      <PopoverContent
        align={compact ? 'end' : 'start'}
        className="w-80"
        data-testid="popover-system-status"
      >
        <p className="mb-3 text-sm font-semibold">System status</p>
        <EngineStatusList showModels={showModels} />
        <p className="mt-3 border-t pt-2 text-[11px] text-muted-foreground">
          Your documents and history stay in this browser.
        </p>
      </PopoverContent>
    </Popover>
  );
}
