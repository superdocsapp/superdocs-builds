import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Trash2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { clearHistory, loadHistory, removeHistoryItem } from "@/lib/history";
import { formatDate } from "@/lib/utils";
import type { HistoryItem } from "@/types/brief";

export function HistoryPage() {
  const [items, setItems] = useState<HistoryItem[]>([]);

  useEffect(() => {
    setItems(loadHistory());
  }, []);

  const sorted = useMemo(
    () => [...items].sort((a, b) => +new Date(b.created_at) - +new Date(a.created_at)),
    [items],
  );

  function refresh() {
    setItems(loadHistory());
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="font-display text-3xl font-bold">History</h1>
          <p className="mt-1 text-muted-foreground">Previously generated interview briefs on this device.</p>
        </div>
        {sorted.length > 0 && (
          <Button
            variant="outline"
            onClick={() => {
              clearHistory();
              refresh();
            }}
          >
            Clear all
          </Button>
        )}
      </div>

      {sorted.length === 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>No briefs yet</CardTitle>
            <CardDescription>Generate your first interview preparation brief to see it here.</CardDescription>
          </CardHeader>
          <CardContent>
            <Link to="/upload">
              <Button>Create brief</Button>
            </Link>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-3">
          {sorted.map((item) => (
            <Card key={item.brief_id}>
              <CardContent className="flex flex-col gap-3 p-5 sm:flex-row sm:items-center sm:justify-between">
                <div className="min-w-0 space-y-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <h2 className="truncate font-semibold">{item.company_name}</h2>
                    <Badge
                      variant={
                        item.status === "completed"
                          ? "success"
                          : item.status === "failed"
                            ? "destructive"
                            : "warning"
                      }
                    >
                      {item.status}
                    </Badge>
                  </div>
                  <p className="text-xs text-muted-foreground">{formatDate(item.created_at)}</p>
                  {item.role_summary && (
                    <p className="line-clamp-2 text-sm text-muted-foreground">{item.role_summary}</p>
                  )}
                </div>
                <div className="flex gap-2">
                  <Link to={`/reports/${item.brief_id}`}>
                    <Button variant="secondary">Open</Button>
                  </Link>
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label="Delete"
                    onClick={() => {
                      removeHistoryItem(item.brief_id);
                      refresh();
                    }}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
