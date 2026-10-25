interface ReviewProgressProps {
  reviewed: number;
  total: number;
}

export function ReviewProgress({ reviewed, total }: ReviewProgressProps) {
  const pct = total === 0 ? 0 : Math.round((reviewed / total) * 100);
  const complete = reviewed === total && total > 0;

  return (
    <div
      className="rounded-lg border border-slate-200 bg-white px-5 py-4"
      aria-label={`Review progress: ${reviewed} of ${total} findings reviewed`}
    >
      <div className="mb-2 flex items-center justify-between">
        <p className="text-sm font-semibold text-slate-700">Review Progress</p>
        <p className="text-sm text-slate-500">
          {total === 0
            ? "No findings"
            : complete
            ? "Review complete"
            : reviewed === 0
            ? "Awaiting review"
            : `${reviewed} of ${total} reviewed`}
        </p>
      </div>
      {total > 0 && (
        <>
          <div
            role="progressbar"
            aria-valuenow={pct}
            aria-valuemin={0}
            aria-valuemax={100}
            className="h-2 w-full overflow-hidden rounded-full bg-slate-100"
          >
            <div
              className={`h-full rounded-full transition-all duration-500 ${
                complete ? "bg-green-500" : "bg-blue-500"
              }`}
              style={{ width: `${pct}%` }}
            />
          </div>
          <p className="mt-1.5 text-xs text-slate-400">{pct}% complete</p>
        </>
      )}
    </div>
  );
}
