import { useState, useEffect, useCallback } from 'react'
import { PRODUCT_NAME } from '../config/branding.js'
import { PARAMS, formatKpiScore } from '../utils/kpiMetrics'
import { maskSalesKpiLabel } from '../config/qaDisplay'
import { useNavigate, useSearchParams } from 'react-router-dom'
import {
  Search, Download, Eye, RotateCcw,
  ChevronLeft, ChevronRight,
  Phone, Calendar, User, AlertTriangle,
  CheckCircle2, XCircle, Clock, RefreshCw
} from 'lucide-react'
import { getCalls, callsFromResponse, downloadCSVExport, downloadAuditComparisonCSV } from '../services/api'
import { formatAgentDisplayName } from '../utils/kpiMetrics'
import { useAuditMode, filterCallsByMode } from '../utils/useAuditMode'

// ── Score badge ───────────────────────────────────────────────────────────────
function ScoreBadge({ score, pct, isSales }) {
  if (score == null) return <span className="text-slate-600 text-xs">—</span>
  const p = pct ?? Math.round((score / (isSales ? 100 : 20)) * 100)
  const cls =
    p >= 75 ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30' :
    p >= 50 ? 'bg-amber-500/20  text-amber-400  border-amber-500/30' :
              'bg-rose-500/20   text-rose-400   border-rose-500/30'
  return (
    <span className={`inline-flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-full border ${cls}`}>
      {score}/{isSales ? 100 : 20}
      {!isSales && <span className="opacity-70">· {p}%</span>}
    </span>
  )
}

// ── Status badge ──────────────────────────────────────────────────────────────
function StatusBadge({ status }) {
  const map = {
    processed:   { cls: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/20', icon: <CheckCircle2 className="w-3 h-3" />, label: 'Processed' },
    scored:      { cls: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/20', icon: <CheckCircle2 className="w-3 h-3" />, label: 'Scored' },
    failed:      { cls: 'bg-rose-500/15    text-rose-400    border-rose-500/20',    icon: <XCircle       className="w-3 h-3" />, label: 'Failed' },
    transcribing:{ cls: 'bg-amber-500/15  text-amber-400   border-amber-500/20',   icon: <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse inline-block" />, label: 'Transcribing' },
    scoring:     { cls: 'bg-amber-500/15  text-amber-400   border-amber-500/20',   icon: <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse inline-block" />, label: 'Scoring' },
    queued:      { cls: 'bg-slate-700/50   text-slate-400   border-slate-600/30',   icon: <Clock         className="w-3 h-3" />, label: 'Queued' },
    fetching:    { cls: 'bg-amber-500/15  text-amber-400   border-amber-500/20',   icon: <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse inline-block" />, label: 'Fetching' },
  }
  const s = map[(status || '').toLowerCase()] || map.queued
  return (
    <span className={`inline-flex items-center gap-1.5 text-xs font-medium px-2 py-0.5 rounded-full border ${s.cls}`}>
      {s.icon} {s.label}
    </span>
  )
}

// ── Export single SALES call as CSV row ───────────────────────────────────────
function exportSingleSalesCall(call) {
  const a = call.analysis?.sales_kpi || {}
  const kpis = Array.isArray(a.kpis) ? a.kpis : []
  const headers = [
    'ID', 'Filename', 'Agent', 'Status', 'Score /100', 'Sales Probability', 'Customer Intent',
    'Review Required', 'Fatal Error',
    ...kpis.map((k, i) => `${maskSalesKpiLabel(i, k.name)} (score)`),
    'Executive Summary', 'Strengths', 'Missed Opportunities', 'Coaching', 'Uploaded At', 'Processed At',
  ]
  const s = a.summary || {}
  const row = [
    call.id, call.filename, call.agent_id || '', call.status,
    a.total_pct ?? call.score ?? '', a.sales_probability || '', a.customer_intent || '',
    a.review_required ? 'Yes' : 'No', a.critical_fail ? 'Yes' : 'No',
    ...kpis.map(k => `${k.score}/${k.max}`),
    (s.executive || '').replace(/,/g, ';'),
    (s.strengths || []).join('; '),
    (s.missed_opportunities || []).join('; '),
    (s.coaching || []).join('; '),
    call.uploaded_at || '', call.processed_at || '',
  ]
  const csv = [headers.join(','), row.map(v => `"${String(v ?? '').replace(/"/g, '""')}"`).join(',')].join('\n')
  const blob = new Blob([csv], { type: 'text/csv' })
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob)
  link.download = `${PRODUCT_NAME}_sales_${call.id}_${new Date().toISOString().slice(0, 10)}.csv`
  link.click()
}

// ── Export single call as CSV row ─────────────────────────────────────────────
function exportSingleCall(call) {
  if (String(call.analysis?.audit_mode || '').toLowerCase() === 'sales') {
    return exportSingleSalesCall(call)
  }
  const bd = call.scores_breakdown || {}
  const kpiCols = PARAMS.map((p) => {
    const raw = bd[p.key]
    if (raw == null || raw === '') return ''
    const { score, max } = formatKpiScore(raw, p.nativeMax ?? p.max)
    return KPI_MASK_CLIENT_NAMES ? `${score}/${max}` : raw
  })
  const kpiHeaders = PARAMS.map((p) => p.label)
  const headers = [
    'ID','Filename','Agent','Loan ID','Status','Score','Score %',
    'PTP Detected','PTP Amount','PTP Date','PTP Mode',
    'Compliance Flags','Sentiment',
    ...kpiHeaders,
    'Summary','Key Issues','Strengths','Coaching Tip',
    'Uploaded At','Processed At'
  ]
  const row = [
    call.id, call.filename, call.agent_id || '', call.loan_id || '',
    call.status, call.score ?? '', call.score_pct ?? '',
    call.ptp_detected ? 'Yes' : 'No',
    call.ptp_amount || '', call.ptp_date || '', call.ptp_mode || '',
    (call.compliance_flags || []).join('; '),
    call.agent_sentiment || '',
    ...kpiCols,
    (call.summary || '').replace(/,/g, ';'),
    (call.key_issues || []).join('; '),
    (call.strengths || []).join('; '),
    (call.coaching_tip || '').replace(/,/g, ';'),
    call.uploaded_at || '', call.processed_at || ''
  ]
  const csv = [headers.join(','), row.map(v => `"${String(v ?? '').replace(/"/g, '""')}"`).join(',')].join('\n')
  const blob = new Blob([csv], { type: 'text/csv' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `${PRODUCT_NAME}_${call.id}_${new Date().toISOString().slice(0,10)}.csv`
  a.click()
}

// ── Bulk export via backend endpoint ─────────────────────────────────────────
async function exportAuditCSV(setExporting, setError) {
  try {
    setExporting?.('audit');
    setError?.(null);
    await downloadAuditComparisonCSV();
  } catch (err) {
    const msg = err.message || 'Audit export failed';
    setError?.(msg);
    alert(msg);
  } finally {
    setExporting?.(false);
  }
}
async function exportAllCSV(setExporting, setError) {
  try {
    setExporting?.(true);
    setError?.(null);
    await downloadCSVExport();
  } catch (err) {
    const msg = err.message || 'Export failed — check backend connection';
    setError?.(msg);
    alert(msg);
  } finally {
    setExporting?.(false);
  }
}

const PER_PAGE = 10

export default function ReportsPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [mode] = useAuditMode()
  const isSales = mode === 'sales'
  const [calls, setCalls]           = useState([])
  const [loading, setLoading]       = useState(true)
  const [error, setError]           = useState(null)
  const [search, setSearch]         = useState(() => searchParams.get('q') || '')
  const [statusFilter, setStatusFilter] = useState('all')
  const [page, setPage]             = useState(1)
  const [lastRefresh, setLastRefresh] = useState(null)
  const [exporting, setExporting] = useState(false)

  // ── Fetch real calls ──────────────────────────────────────────────────────
  const fetchCalls = useCallback(async () => {
    try {
      setLoading(true)
      setError(null)
      const data = await getCalls({ limit: 500 })
      const list = callsFromResponse(data)
      setCalls(list)
      setLastRefresh(new Date())
    } catch (err) {
      setError('Could not load calls — is Flask running?')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchCalls() }, [fetchCalls])

  useEffect(() => {
    const q = searchParams.get('q')
    if (q != null) {
      setSearch(q)
      setPage(1)
    }
  }, [searchParams])

  // Auto-refresh every 15s if any call is still processing
  useEffect(() => {
    const active = calls.some(c => ['queued','transcribing','scoring','fetching'].includes(c.status))
    if (!active) return
    const t = setTimeout(fetchCalls, 15_000)
    return () => clearTimeout(t)
  }, [calls, fetchCalls])

  // ── Filter ────────────────────────────────────────────────────────────────
  const modeCalls = filterCallsByMode(calls, mode)
  const filtered = modeCalls.filter(c => {
    const q = search.toLowerCase()
    const matchSearch = !q || [
      c.id, c.filename, c.agent_id, c.agent_name, c.loan_id, c.customer_id,
      formatAgentDisplayName(c),
    ].filter(Boolean).some(v => String(v).toLowerCase().includes(q))
    const matchStatus = statusFilter === 'all' ||
      (statusFilter === 'processed' && c.status === 'processed') ||
      (statusFilter === 'failed'    && c.status === 'failed')    ||
      (statusFilter === 'pending'   && ['queued','transcribing','scoring','fetching'].includes(c.status))
    return matchSearch && matchStatus
  })

  const totalPages = Math.max(1, Math.ceil(filtered.length / PER_PAGE))
  const paginated  = filtered.slice((page - 1) * PER_PAGE, page * PER_PAGE)

  // Summary counts from real data (scoped to the active audit product)
  const counts = {
    total:     modeCalls.length,
    processed: modeCalls.filter(c => c.status === 'processed').length,
    failed:    modeCalls.filter(c => c.status === 'failed').length,
    pending:   modeCalls.filter(c => ['queued','transcribing','scoring','fetching'].includes(c.status)).length,
  }

  const fmtDate = ts => {
    if (!ts) return '—'
    try { return new Date(ts).toLocaleString() } catch { return ts }
  }

  return (
    <div className="p-6 space-y-5 text-white animate-fade-in">

      {/* ── Header ── */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">{isSales ? 'Sales Call Reports' : 'Collections Call Reports'}</h1>
          <p className="text-sm text-slate-400 mt-0.5">
            {isSales ? 'Sales QA · KPI score /100 · conversion & review' : 'Collections QA · AI scores · Compliance flags'}
            {lastRefresh && <span className="ml-2 text-slate-600">· Updated {lastRefresh.toLocaleTimeString()}</span>}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={fetchCalls}
            disabled={loading}
            className="flex items-center gap-2 bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-300 text-xs px-3 py-2 rounded-lg transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
          {!isSales && (
            <button
              onClick={() => exportAuditCSV(setExporting, setError)}
              disabled={!!exporting}
              className="flex items-center gap-2 bg-violet-600 hover:bg-violet-500 text-white font-semibold text-xs px-4 py-2 rounded-lg transition-colors disabled:opacity-50"
            >
              <Download className={`w-3.5 h-3.5 ${exporting === 'audit' ? 'animate-pulse' : ''}`} />
              {exporting === 'audit' ? 'Exporting…' : 'Audit Excel CSV'}
            </button>
          )}
          <button
            onClick={() => exportAllCSV(setExporting, setError)}
            disabled={!!exporting}
            className="flex items-center gap-2 bg-cyan-600 hover:bg-cyan-500 text-white font-semibold text-xs px-4 py-2 rounded-lg transition-colors disabled:opacity-50"
          >
            <Download className={`w-3.5 h-3.5 ${exporting === true ? 'animate-pulse' : ''}`} />
            {exporting === true ? 'Exporting…' : 'Export All CSV'}
          </button>
        </div>
      </div>

      {/* ── Error ── */}
      {error && (
        <div className="bg-red-900/30 border border-red-700 text-red-300 rounded-lg px-4 py-3 text-sm">
          ⚠ {error}
        </div>
      )}

      {/* ── Summary strip ── */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { label: 'Total Calls',  value: counts.total,     icon: Phone,         color: 'text-cyan-400'    },
          { label: 'Processed',    value: counts.processed,  icon: CheckCircle2,  color: 'text-emerald-400' },
          { label: 'Failed',       value: counts.failed,     icon: XCircle,       color: 'text-rose-400'    },
          { label: 'In Progress',  value: counts.pending,    icon: Clock,         color: 'text-amber-400'   },
        ].map(item => (
          <div key={item.label} className="bg-gray-800/60 border border-slate-700/50 rounded-xl p-4 flex items-center gap-3">
            <item.icon className={`w-5 h-5 ${item.color} flex-shrink-0`} />
            <div>
              <p className="text-xl font-bold text-slate-100">{item.value}</p>
              <p className="text-xs text-slate-400">{item.label}</p>
            </div>
          </div>
        ))}
      </div>

      {/* ── Filters ── */}
      <div className="bg-gray-800/60 border border-slate-700/50 rounded-xl p-4">
        <div className="flex flex-col sm:flex-row gap-3">
          {/* Search */}
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
            <input
              type="text"
              placeholder="Search by Call ID, filename, agent or loan ID..."
              value={search}
              onChange={e => { setSearch(e.target.value); setPage(1) }}
              className="w-full bg-slate-900/60 border border-slate-700/50 rounded-lg pl-9 pr-4 py-2.5 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-cyan-500/50 transition-all"
            />
          </div>
          {/* Status tabs */}
          <div className="flex items-center gap-1 bg-slate-900/60 border border-slate-700/50 rounded-lg p-1">
            {[
              { key: 'all',       label: `All (${counts.total})`           },
              { key: 'processed', label: `Processed (${counts.processed})` },
              { key: 'pending',   label: `Pending (${counts.pending})`     },
              { key: 'failed',    label: `Failed (${counts.failed})`       },
            ].map(s => (
              <button
                key={s.key}
                onClick={() => { setStatusFilter(s.key); setPage(1) }}
                className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all whitespace-nowrap ${
                  statusFilter === s.key ? 'bg-slate-700 text-slate-100' : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                {s.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* ── Table ── */}
      <div className="bg-gray-800/60 border border-slate-700/50 rounded-xl overflow-hidden">
        {loading && calls.length === 0 ? (
          <div className="text-center py-16 text-slate-500">
            <RefreshCw className="w-8 h-8 mx-auto mb-3 animate-spin opacity-40" />
            Loading calls…
          </div>
        ) : filtered.length === 0 ? (
          <div className="text-center py-16 text-slate-500">
            <Phone className="w-8 h-8 mx-auto mb-3 opacity-30" />
            {modeCalls.length === 0 ? `No ${isSales ? 'Sales' : 'Collections'} calls yet. Upload a call with Audit Type = ${isSales ? 'Sales' : 'Collections'}.` : 'No calls match your filters.'}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-800/60 bg-slate-800/30">
                  {(isSales
                    ? ['Call ID','File','Agent','Score','Status','Probability','Intent','Review','Uploaded','']
                    : ['Call ID','File','Agent','Score','Status','Flags','PTP','Uploaded','']
                  ).map((h, i) => (
                    <th key={`${h}-${i}`} className="text-left text-xs font-semibold text-slate-500 uppercase tracking-wider px-4 py-3 whitespace-nowrap first:pl-5 last:pr-5">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {paginated.map((call, i) => {
                  const flags = call.compliance_flags || []
                  const isPending = ['queued','transcribing','scoring','fetching'].includes(call.status)
                  return (
                    <tr
                      key={call.id}
                      className="border-b border-slate-800/40 hover:bg-slate-700/20 transition-colors cursor-pointer"
                      onClick={() => navigate(`/calls/${call.id}`)}
                    >
                      {/* Call ID */}
                      <td className="px-4 py-3 pl-5">
                        <span className="font-mono text-xs text-cyan-400">{call.id}</span>
                      </td>

                      {/* Filename */}
                      <td className="px-4 py-3 max-w-[160px]">
                        <p className="text-slate-200 text-xs truncate font-medium" title={call.filename}>
                          {call.filename || '—'}
                        </p>
                        {call.file_size && (
                          <p className="text-slate-500 text-xs">
                            {call.file_size >= 1024*1024
                              ? (call.file_size/1024/1024).toFixed(1) + ' MB'
                              : Math.round(call.file_size/1024) + ' KB'}
                          </p>
                        )}
                      </td>

                      {/* Agent */}
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2 text-slate-400 text-xs">
                          <User className="w-3.5 h-3.5 flex-shrink-0" />
                          {call.agent_id || <span className="text-slate-600">—</span>}
                        </div>
                      </td>

                      {/* Score */}
                      <td className="px-4 py-3">
                        <ScoreBadge score={call.score} pct={call.score_pct} isSales={isSales} />
                      </td>

                      {/* Status */}
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <StatusBadge status={call.status} />
                          {isPending && <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-ping inline-block" />}
                        </div>
                      </td>

                      {isSales ? (
                        <>
                          {/* Sales probability */}
                          <td className="px-4 py-3">
                            <span className="text-xs capitalize text-slate-300">{call.analysis?.sales_kpi?.sales_probability || '—'}</span>
                          </td>
                          {/* Customer intent */}
                          <td className="px-4 py-3">
                            <span className="text-xs capitalize text-slate-300">{call.analysis?.sales_kpi?.customer_intent || '—'}</span>
                          </td>
                          {/* Review required */}
                          <td className="px-4 py-3">
                            {call.analysis?.sales_kpi?.review_required
                              ? <span className="text-xs text-amber-400 font-semibold">Required</span>
                              : call.status === 'processed'
                                ? <span className="text-xs text-emerald-400">OK</span>
                                : <span className="text-slate-600 text-xs">—</span>}
                          </td>
                        </>
                      ) : (
                        <>
                          {/* Flags */}
                          <td className="px-4 py-3">
                            {flags.length > 0 ? (
                              <div className="flex flex-wrap gap-1">
                                {flags.slice(0, 2).map(flag => (
                                  <span key={flag} className="inline-flex items-center gap-1 text-xs px-1.5 py-0.5 rounded-full bg-rose-500/15 text-rose-400 border border-rose-500/20">
                                    <AlertTriangle className="w-2.5 h-2.5" />
                                    {flag.replace(/_/g, ' ')}
                                  </span>
                                ))}
                                {flags.length > 2 && (
                                  <span className="text-xs text-rose-400">+{flags.length - 2}</span>
                                )}
                              </div>
                            ) : (
                              <span className="text-slate-700 text-xs">—</span>
                            )}
                          </td>

                          {/* PTP */}
                          <td className="px-4 py-3">
                            {call.ptp_detected === true  && <span className="text-xs text-emerald-400 font-semibold">✓ {call.ptp_amount || 'Yes'}</span>}
                            {call.ptp_detected === false && call.status === 'processed' && <span className="text-xs text-rose-400">✗ None</span>}
                            {call.ptp_detected == null   && <span className="text-slate-600 text-xs">—</span>}
                          </td>
                        </>
                      )}

                      {/* Uploaded */}
                      <td className="px-4 py-3 text-slate-500 text-xs whitespace-nowrap">
                        {fmtDate(call.uploaded_at)}
                      </td>

                      {/* Actions */}
                      <td className="px-4 py-3 pr-5" onClick={e => e.stopPropagation()}>
                        <div className="flex items-center gap-1">
                          <button
                            onClick={() => navigate(`/calls/${call.id}`)}
                            className="p-1.5 rounded-lg text-slate-400 hover:text-cyan-400 hover:bg-cyan-400/10 transition-colors"
                            title="View detail"
                          >
                            <Eye className="w-3.5 h-3.5" />
                          </button>
                          {call.status === 'processed' && (
                            <button
                              onClick={() => exportSingleCall(call)}
                              className="p-1.5 rounded-lg text-slate-400 hover:text-emerald-400 hover:bg-emerald-400/10 transition-colors"
                              title="Download CSV"
                            >
                              <Download className="w-3.5 h-3.5" />
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}

        {/* Pagination */}
        {filtered.length > PER_PAGE && (
          <div className="flex items-center justify-between px-5 py-3 border-t border-slate-800/60 bg-slate-800/10">
            <p className="text-xs text-slate-500">
              {Math.min((page-1)*PER_PAGE+1, filtered.length)}–{Math.min(page*PER_PAGE, filtered.length)} of {filtered.length} calls
            </p>
            <div className="flex items-center gap-1">
              <button
                onClick={() => setPage(p => Math.max(1, p-1))}
                disabled={page === 1}
                className="p-1.5 rounded-lg text-slate-400 hover:text-slate-100 hover:bg-slate-800 disabled:opacity-30 disabled:cursor-not-allowed transition-all"
              >
                <ChevronLeft className="w-4 h-4" />
              </button>
              {Array.from({ length: Math.min(totalPages, 7) }, (_, i) => {
                const p = totalPages <= 7 ? i+1 : i + Math.max(1, page-3)
                if (p > totalPages) return null
                return (
                  <button
                    key={p}
                    onClick={() => setPage(p)}
                    className={`w-7 h-7 rounded-lg text-xs font-medium transition-all ${
                      p === page ? 'bg-cyan-500/20 text-cyan-400 border border-cyan-500/30' : 'text-slate-400 hover:text-slate-100 hover:bg-slate-800'
                    }`}
                  >
                    {p}
                  </button>
                )
              })}
              <button
                onClick={() => setPage(p => Math.min(totalPages, p+1))}
                disabled={page === totalPages}
                className="p-1.5 rounded-lg text-slate-400 hover:text-slate-100 hover:bg-slate-800 disabled:opacity-30 disabled:cursor-not-allowed transition-all"
              >
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}