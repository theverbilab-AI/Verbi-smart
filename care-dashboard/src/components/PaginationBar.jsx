export default function PaginationBar({ page, pages, total, pageSize, onPageChange }) {
  if (!total || pages <= 1) return null;

  const start = (page - 1) * pageSize + 1;
  const end = Math.min(page * pageSize, total);

  const windowStart = Math.max(1, page - 3);
  const windowEnd = Math.min(pages, windowStart + 6);
  const nums = [];
  for (let n = windowStart; n <= windowEnd; n += 1) nums.push(n);

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 pt-3 border-t border-slate-700/60">
      <p className="text-xs text-slate-500">
        Showing {start}–{end} of {total}
      </p>
      <div className="flex flex-wrap items-center gap-1">
        <button
          type="button"
          disabled={page <= 1}
          onClick={() => onPageChange(page - 1)}
          className="px-3 py-1 text-sm rounded-md border border-slate-600 text-slate-300 hover:bg-slate-800 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          Previous
        </button>
        {windowStart > 1 && (
          <>
            <button type="button" onClick={() => onPageChange(1)} className="min-w-[2rem] px-2 py-1 text-sm rounded-md border border-slate-600 text-slate-300 hover:bg-slate-800">1</button>
            {windowStart > 2 && <span className="text-slate-500 px-1">…</span>}
          </>
        )}
        {nums.map((n) => (
          <button
            key={n}
            type="button"
            onClick={() => onPageChange(n)}
            className={`min-w-[2rem] px-2 py-1 text-sm rounded-md border transition-colors ${
              n === page
                ? "bg-cyan-600 border-cyan-500 text-white"
                : "bg-slate-800 border-slate-600 text-slate-300 hover:bg-slate-700"
            }`}
          >
            {n}
          </button>
        ))}
        {windowEnd < pages && (
          <>
            {windowEnd < pages - 1 && <span className="text-slate-500 px-1">…</span>}
            <button type="button" onClick={() => onPageChange(pages)} className="min-w-[2rem] px-2 py-1 text-sm rounded-md border border-slate-600 text-slate-300 hover:bg-slate-800">{pages}</button>
          </>
        )}
        <button
          type="button"
          disabled={page >= pages}
          onClick={() => onPageChange(page + 1)}
          className="px-3 py-1 text-sm rounded-md border border-slate-600 text-slate-300 hover:bg-slate-800 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          Next
        </button>
      </div>
    </div>
  );
}
