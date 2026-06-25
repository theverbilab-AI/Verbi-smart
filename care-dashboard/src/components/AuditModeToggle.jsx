import { useAuditMode } from "../utils/useAuditMode";

/**
 * Global Collections / Sales switch. Controls which audit product the
 * Dashboard, KPI Tracker and Reports pages display. Persisted in localStorage.
 */
export default function AuditModeToggle() {
  const [mode, setMode] = useAuditMode();
  const opts = [
    { id: "collections", label: "Collections" },
    { id: "sales", label: "Sales" },
  ];
  return (
    <div
      className="flex items-center rounded-full p-0.5 border"
      style={{ borderColor: "var(--care-border)", background: "var(--care-table-row-hover)" }}
      title="Switch audit product"
    >
      {opts.map((o) => {
        const active = mode === o.id;
        return (
          <button
            key={o.id}
            type="button"
            onClick={() => setMode(o.id)}
            className={`px-3 py-1 text-xs font-semibold rounded-full transition-colors ${
              active ? "bg-cyan-600 text-white shadow" : "text-slate-400 hover:text-slate-200"
            }`}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
