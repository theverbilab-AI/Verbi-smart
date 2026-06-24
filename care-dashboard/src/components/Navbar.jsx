import { useState, useEffect, useRef, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { Bell, Search, ChevronDown, Phone, User, FileText } from 'lucide-react'
import { NAVBAR_TITLE } from '../config/branding.js'
import { getCalls, callsFromResponse } from '../services/api'
import { formatAgentDisplayName } from '../utils/kpiMetrics'
import ThemeToggle from './ThemeToggle'

function callSearchText(call) {
  return [
    call.id,
    call.filename,
    call.agent_id,
    call.agent_name,
    call.loan_id,
    call.customer_id,
    formatAgentDisplayName(call),
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase()
}

function filterCalls(calls, query) {
  const q = query.trim().toLowerCase()
  if (!q || q.length < 2) return []
  return calls.filter((c) => callSearchText(c).includes(q)).slice(0, 8)
}

function userInitials(user) {
  const name = (user?.name || user?.email || '?').trim()
  const parts = name.split(/\s+/).filter(Boolean)
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase()
  return name.slice(0, 2).toUpperCase()
}

function formatRoleLabel(role) {
  return (role || 'user').replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

export default function Navbar({ user, onLogout, sidebarOpen, setSidebarOpen }) {
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)
  const [profileOpen, setProfileOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [results, setResults] = useState([])
  const wrapRef = useRef(null)
  const profileRef = useRef(null)
  const inputRef = useRef(null)
  const callsCacheRef = useRef(null)

  const displayName = user?.name || user?.email || 'User'
  const displayEmail = user?.email || ''
  const displayRole = formatRoleLabel(user?.role)

  const loadCalls = useCallback(async () => {
    if (callsCacheRef.current) return callsCacheRef.current
    setLoading(true)
    try {
      const data = await getCalls({ limit: 500 })
      const list = callsFromResponse(data)
      callsCacheRef.current = list
      return list
    } catch {
      return []
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    const q = query.trim()
    if (q.length < 2) {
      setResults([])
      return undefined
    }

    const timer = setTimeout(async () => {
      const list = callsCacheRef.current || await loadCalls()
      setResults(filterCalls(list, q))
      setOpen(true)
    }, 250)

    return () => clearTimeout(timer)
  }, [query, loadCalls])

  useEffect(() => {
    const onDocClick = (e) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) {
        setOpen(false)
      }
      if (profileRef.current && !profileRef.current.contains(e.target)) {
        setProfileOpen(false)
      }
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [])

  const goToCall = (callId) => {
    setOpen(false)
    setQuery('')
    navigate(`/calls/${callId}`)
  }

  const goToReports = (q) => {
    setOpen(false)
    setQuery('')
    navigate(`/reports?q=${encodeURIComponent(q.trim())}`)
  }

  const onSubmit = (e) => {
    e.preventDefault()
    const q = query.trim()
    if (!q) return
    if (results.length === 1) {
      goToCall(results[0].id)
      return
    }
    if (results.length > 0) {
      goToCall(results[0].id)
      return
    }
    goToReports(q)
  }

  const onFocus = () => {
    if (query.trim().length >= 2) setOpen(true)
    if (!callsCacheRef.current) loadCalls()
  }

  const handleLogout = () => {
    setProfileOpen(false)
    onLogout?.()
  }

  return (
    <header className="sticky top-0 z-30 h-16 care-navbar glass-card border-b flex items-center justify-between px-4 lg:px-6">
      <div className="flex items-center gap-4">
        <button
          className="lg:hidden p-2 rounded-lg text-slate-400 hover:text-slate-100 hover:bg-slate-800 transition-colors"
          onClick={() => setSidebarOpen?.(!sidebarOpen)}
          aria-label="Toggle sidebar"
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
          </svg>
        </button>

        <div className="min-w-0">
          <p className="text-sm font-semibold tracking-wide truncate" style={{ color: "var(--care-text-primary)" }}>{NAVBAR_TITLE}</p>
          <p className="text-[10px] hidden sm:block care-muted">Company Finance · QA</p>
        </div>
      </div>

      <div className="hidden md:flex flex-1 max-w-md mx-6" ref={wrapRef}>
        <form onSubmit={onSubmit} className="relative w-full">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500 pointer-events-none" />
          <input
            ref={inputRef}
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onFocus={onFocus}
            placeholder="Search calls, agents, customers..."
            autoComplete="off"
            aria-label="Search calls, agents, customers"
            className="care-search-input"
          />

          {open && query.trim().length >= 2 && (
            <div className="absolute top-full left-0 right-0 mt-1 care-search-dropdown rounded-xl shadow-xl overflow-hidden z-50">
              {loading && results.length === 0 ? (
                <p className="px-4 py-3 text-sm care-muted">Searching…</p>
              ) : results.length === 0 ? (
                <div className="px-4 py-3">
                  <p className="text-sm text-slate-400">No matches found.</p>
                  <button
                    type="button"
                    onClick={() => goToReports(query)}
                    className="mt-1 text-xs text-cyan-400 hover:text-cyan-300"
                  >
                    Search all in Reports →
                  </button>
                </div>
              ) : (
                <>
                  <ul className="max-h-72 overflow-y-auto">
                    {results.map((call) => (
                      <li key={call.id}>
                        <button
                          type="button"
                          onClick={() => goToCall(call.id)}
                          className="w-full text-left px-4 py-2.5 hover:bg-slate-800/80 transition-colors border-b border-slate-800/60 last:border-0"
                        >
                          <div className="flex items-start gap-2">
                            <Phone className="w-4 h-4 text-cyan-500 mt-0.5 shrink-0" />
                            <div className="min-w-0 flex-1">
                              <p className="text-sm text-slate-200 truncate font-mono">{call.id}</p>
                              <p className="text-xs text-slate-500 truncate">{call.filename || '—'}</p>
                              <div className="flex flex-wrap gap-x-3 gap-y-0.5 mt-0.5 text-xs text-slate-400">
                                <span className="inline-flex items-center gap-1">
                                  <User className="w-3 h-3" />
                                  {formatAgentDisplayName(call)}
                                </span>
                                {call.loan_id && (
                                  <span className="inline-flex items-center gap-1">
                                    <FileText className="w-3 h-3" />
                                    {call.loan_id}
                                  </span>
                                )}
                              </div>
                            </div>
                            {call.score_pct != null && (
                              <span className="text-xs font-semibold text-cyan-400 shrink-0">{call.score_pct}%</span>
                            )}
                          </div>
                        </button>
                      </li>
                    ))}
                  </ul>
                  <button
                    type="button"
                    onClick={() => goToReports(query)}
                    className="w-full px-4 py-2 text-xs text-cyan-400 hover:bg-slate-800/50 border-t border-slate-700/60"
                  >
                    View all results in Reports →
                  </button>
                </>
              )}
            </div>
          )}
        </form>
      </div>

      <div className="flex items-center gap-2">
        <div className="hidden sm:flex items-center gap-2 px-3 py-1.5 bg-emerald-500/10 border border-emerald-500/20 rounded-full">
          <div className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
          <span className="text-xs text-emerald-400 font-medium font-mono">LIVE</span>
        </div>

        <button type="button" className="relative p-2.5 rounded-lg text-slate-400 hover:text-slate-100 hover:bg-slate-800 transition-colors">
          <Bell className="w-5 h-5" />
          <span className="absolute top-1.5 right-1.5 w-2 h-2 bg-rose-500 rounded-full" />
        </button>

        <ThemeToggle />

        <div className="relative" ref={profileRef}>
          <button
            type="button"
            onClick={() => setProfileOpen((v) => !v)}
            className="flex items-center gap-2 ml-1 pl-3 border-l hover:opacity-90"
            style={{ borderColor: "var(--care-border)" }}
            aria-expanded={profileOpen}
            aria-haspopup="true"
          >
            <div className="w-8 h-8 rounded-full bg-gradient-to-br from-cyan-500 to-blue-600 flex items-center justify-center text-xs font-bold text-white">
              {userInitials(user)}
            </div>
            <div className="hidden md:block text-left max-w-[180px]">
              <p className="text-sm font-medium leading-none truncate" style={{ color: "var(--care-text-primary)" }}>{displayName}</p>
              <p className="text-xs care-muted mt-0.5 truncate">{displayRole}</p>
            </div>
            <ChevronDown className={`w-4 h-4 text-slate-500 hidden md:block shrink-0 transition-transform ${profileOpen ? 'rotate-180' : ''}`} />
          </button>

          {profileOpen && (
            <div className="absolute right-0 top-full mt-2 w-64 care-search-dropdown rounded-xl shadow-xl z-50 overflow-hidden">
              <div className="px-4 py-3 border-b" style={{ borderColor: "var(--care-border)" }}>
                <p className="text-sm font-medium truncate" style={{ color: "var(--care-text-primary)" }}>{displayName}</p>
                <p className="text-xs care-muted truncate mt-0.5">{displayEmail}</p>
                <p className="text-xs mt-1 capitalize" style={{ color: "var(--care-accent-strong)" }}>{displayRole}</p>
              </div>
              <button
                type="button"
                onClick={() => { setProfileOpen(false); navigate('/settings') }}
                className="w-full text-left px-4 py-2.5 text-sm care-text-secondary hover:opacity-80"
                style={{ background: "var(--care-table-row-hover)" }}
              >
                Profile & Settings
              </button>
              <button
                type="button"
                onClick={handleLogout}
                className="w-full text-left px-4 py-2.5 text-sm text-red-500 hover:opacity-80 border-t"
                style={{ borderColor: "var(--care-border)" }}
              >
                Log out
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  )
}
