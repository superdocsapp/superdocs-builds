import { useMemo, useState } from 'react';
import { Download, FileJson, Search } from 'lucide-react';
import { format } from 'date-fns';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { csvCell, downloadText } from '@/lib/experiment';
import { usePreferences } from '@/lib/preferences';
import { useLabStore } from '@/lib/store';

const FILTERS = [
  'All',
  'DIY',
  'SuperDocs',
  'Success',
  'Errors',
  'Accepted',
  'Rejected',
] as const;

export function ActivityTab() {
  const { activity } = useLabStore();
  const { preferences } = usePreferences();
  const [search, setSearch] = useState('');
  const [filter, setFilter] =
    useState<(typeof FILTERS)[number]>('All');

  const filtered = useMemo(
    () =>
      activity.filter((entry) => {
        const query = search.toLowerCase();
        const matchesSearch =
          entry.action.toLowerCase().includes(query) ||
          entry.details.toLowerCase().includes(query) ||
          entry.requestId?.toLowerCase().includes(query);
        const matchesFilter =
          filter === 'All' ||
          (filter === 'DIY' && entry.engine === 'diy') ||
          (filter === 'SuperDocs' && entry.engine === 'superdocs') ||
          (filter === 'Success' && entry.status === 'success') ||
          (filter === 'Errors' && entry.status === 'error') ||
          (filter === 'Accepted' && entry.status === 'accepted') ||
          (filter === 'Rejected' && entry.status === 'rejected');
        return Boolean(matchesSearch && matchesFilter);
      }),
    [activity, filter, search],
  );

  const exportCsv = () => {
    const headers = [
      'timestamp',
      'action',
      'engine',
      'status',
      'scope',
      'request_id',
      'latency_ms',
      'retry_count',
      'total_tokens',
      'details',
    ];
    const rows = filtered.map((entry) =>
      [
        entry.timestamp,
        entry.action,
        entry.engine ?? '',
        entry.status ?? '',
        entry.scope ?? '',
        entry.requestId ?? '',
        entry.latencyMs ?? '',
        entry.retryCount ?? '',
        entry.totalTokens ?? '',
        entry.details,
      ]
        .map(csvCell)
        .join(','),
    );
    downloadText(
      `activity-${format(new Date(), 'yyyy-MM-dd-HH-mm')}.csv`,
      [headers.join(','), ...rows].join('\n'),
      'text/csv',
    );
  };

  const exportJson = () =>
    downloadText(
      `activity-${format(new Date(), 'yyyy-MM-dd-HH-mm')}.json`,
      JSON.stringify(filtered, null, 2),
      'application/json',
    );

  return (
    <div className="space-y-4 pb-8">
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <p className="max-w-xl text-sm text-muted-foreground">
          A complete log of everything that happened — edit requests, review
          decisions, imports, and benchmark runs.
        </p>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={exportCsv} data-testid="button-export-activity-csv">
            <Download className="mr-2 h-4 w-4" />
            CSV
          </Button>
          <Button variant="outline" size="sm" onClick={exportJson} data-testid="button-export-activity-json">
            <FileJson className="mr-2 h-4 w-4" />
            JSON
          </Button>
        </div>
      </div>

      <div className="flex flex-wrap gap-3">
        <div className="relative w-full sm:w-72">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search actions and details…"
            className="bg-background pl-9"
            data-testid="input-search-activity"
          />
        </div>
        <div className="flex flex-wrap rounded-md border bg-background p-1">
          {FILTERS.map((item) => (
            <button
              key={item}
              type="button"
              onClick={() => setFilter(item)}
              className={`rounded px-3 py-1.5 text-xs font-medium transition ${
                filter === item
                  ? 'bg-primary text-primary-foreground'
                  : 'text-muted-foreground hover:text-foreground'
              }`}
              data-testid={`filter-activity-${item.toLowerCase()}`}
            >
              {item}
            </button>
          ))}
        </div>
      </div>

      <div className="overflow-hidden rounded-md border shadow-sm">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[980px] text-left text-xs">
            <thead className="border-b bg-muted/50 text-muted-foreground">
              <tr>
                <th className="px-3 py-2.5 font-medium">Timestamp</th>
                <th className="px-3 py-2.5 font-medium">Action</th>
                <th className="px-3 py-2.5 font-medium">Engine</th>
                <th className="px-3 py-2.5 font-medium">Status</th>
                <th className="px-3 py-2.5 font-medium">Latency</th>
                <th className="px-3 py-2.5 font-medium">Retries</th>
                <th className="px-3 py-2.5 font-medium">Tokens</th>
                <th className="px-3 py-2.5 font-medium">Details</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {filtered.map((entry) => (
                <tr key={entry.id} className="align-top hover:bg-muted/20">
                  <td className="whitespace-nowrap px-3 py-3 font-mono text-[10px] text-muted-foreground">
                    {format(
                      new Date(entry.timestamp),
                      'MMM dd, yyyy HH:mm:ss',
                    )}
                  </td>
                  <td className="px-3 py-3 font-medium">{entry.action}</td>
                  <td className="px-3 py-3 uppercase">
                    {entry.engine ?? '—'}
                  </td>
                  <td className="px-3 py-3">
                    <span
                      className={`rounded-full px-2 py-0.5 ${
                        entry.status === 'error'
                          ? 'bg-destructive/10 text-destructive'
                          : entry.status === 'success' ||
                              entry.status === 'accepted'
                            ? 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-400'
                            : 'bg-muted text-muted-foreground'
                      }`}
                    >
                      {entry.status ?? 'recorded'}
                    </span>
                  </td>
                  <td className="px-3 py-3 font-mono">
                    {entry.latencyMs != null
                      ? `${entry.latencyMs} ms`
                      : 'N/A'}
                  </td>
                  <td className="px-3 py-3 font-mono">
                    {entry.retryCount ?? 'N/A'}
                  </td>
                  <td className="px-3 py-3 font-mono">
                    {entry.totalTokens ?? 'Not exposed'}
                  </td>
                  <td className="max-w-md px-3 py-3 text-muted-foreground">
                    <details>
                      <summary className="line-clamp-2 cursor-pointer">
                        {entry.details}
                      </summary>
                      <dl className="mt-2 grid grid-cols-[90px_1fr] gap-1 rounded border bg-muted/20 p-2 font-mono text-[10px]">
                        {preferences.developerMode && (
                          <>
                            <dt>request</dt>
                            <dd>{entry.requestId ?? 'N/A'}</dd>
                          </>
                        )}
                        <dt>scope</dt>
                        <dd>{entry.scope ?? 'N/A'}</dd>
                      </dl>
                    </details>
                  </td>
                </tr>
              ))}
              {!filtered.length && (
                <tr>
                  <td
                    colSpan={8}
                    className="px-4 py-12 text-center text-muted-foreground"
                  >
                    No matching activity yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
