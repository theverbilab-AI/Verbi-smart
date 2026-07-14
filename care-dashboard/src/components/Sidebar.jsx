import { useEffect, useState } from 'react'
import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard, Upload, FileBarChart2, Settings,
  Phone, Shield, Users, TrendingUp, X, Link2
} from 'lucide-react'
import { getDashboard } from '../services/api'
import BrandLogo from './BrandLogo'
import { PRODUCT_NAME, PRODUCT_VERSION } from '../config/branding.js'
import { hasPermission } from '../utils/permissions'

const mainNav = [
  { to: '/dashboard', icon: LayoutDashboard, label: 'Dashboard', perm: 'dashboard_view' },
  { to: '/kpis', icon: TrendingUp, label: 'KPI Tracker', perm: 'agent_performance' },
  { to: '/upload', icon: Upload, label: 'Upload Document', perm: 'upload_calls' },
  { to: '/reports', icon: FileBarChart2, label: 'Reports', perm: 'view_reports' },
  { to: '/settings', icon: Settings, label: 'Settings', perm: 'dashboard_view' },
  { to: '/admin/crm-usage', icon: Link2, label: 'CRM Usage', perm: 'crm_usage' },
  { to: '/admin/users', icon: Users, label: 'Users', perm: 'manage_users' },
]

export default function Sidebar({ user, open, onClose }) {
  const [stats, setStats] = useState({
    live_calls: 0,
    compliance_flags: 0,
    calls_today: 0,
    processed: 0,
    processing_pct: 0,
  })

  useEffect(() => {
    let mounted = true
    let timer

    const load = async () => {
      try {
        const data = await getDashboard()
        if (!mounted) return
        setStats({
          live_calls: Number(data.live_calls || 0),
          compliance_flags: Number(data.compliance_flags || 0),
          calls_today: Number(data.calls_today || 0),
          processed: Number(data.processed || data.processed_calls || 0),
          processing_pct: Number(data.processing_pct || data.processed_pct || 0),
        })
      } catch (_e) {
        // silent — sidebar should never block UI on API errors
      }
    }

    load()
    timer = setInterval(load, 30_000)
    return () => {
      mounted = false
      clearInterval(timer)
    }
  }, [])

  const queueActive = stats.live_calls > 0 || stats.processing_pct < 100
  const fmtBadge = (n) => (n > 99 ? '99+' : String(n))

  const quickLinks = [
    {
      to: '/dashboard?filter=live',
      icon: Phone,
      label: 'Live Calls',
      badge: stats.live_calls > 0 ? fmtBadge(stats.live_calls) : null,
    },
    {
      to: '/dashboard?filter=flags',
      icon: Shield,
      label: 'Compliance Flags',
      badge: stats.compliance_flags > 0 ? fmtBadge(stats.compliance_flags) : null,
      badgeColor: 'rose',
    },
    { to: '/kpis', icon: Users, label: 'Agent Performance' },
    { to: '/kpis', icon: TrendingUp, label: 'KPI Tracker' },
  ]

  return (
    <>
      {/* Overlay for mobile */}
      {open && (
        <div
          className="fixed inset-0 z-40 bg-slate-950/80 backdrop-blur-sm lg:hidden"
          onClick={onClose}
        />
      )}

      {/* Sidebar */}
      <aside
        className={`
          care-sidebar
          fixed lg:sticky top-0 left-0 z-50 lg:z-auto
          h-screen w-64 flex-shrink-0
          flex flex-col
          backdrop-blur-xl border-r
          transition-transform duration-300 ease-in-out
          ${open ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'}
        `}
      >
        {/* Brand header */}
        <div className="flex items-center justify-between p-4 border-b" style={{ borderColor: "var(--care-border)" }}>
          <BrandLogo size="sidebar" showTagline={false} />
          <button
            onClick={onClose}
            className="lg:hidden p-1.5 rounded-lg text-slate-400 hover:text-slate-100 hover:bg-slate-800"
            aria-label="Close sidebar"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Scroll area */}
        <div className="flex-1 overflow-y-auto py-4 px-3 flex flex-col gap-6">

          {/* Main Navigation */}
          <div>
            <p className="care-sidebar-label">Navigation</p>
            <nav className="flex flex-col gap-1">
              {mainNav.filter((item) => !item.perm || hasPermission(user, item.perm)).map(({ to, icon: Icon, label }) => (
                <NavLink
                  key={to}
                  to={to}
                  onClick={onClose}
                  className={({ isActive }) =>
                    `nav-item ${isActive ? 'active' : ''}`
                  }
                >
                  <Icon className="w-4 h-4 flex-shrink-0" />
                  <span>{label}</span>
                </NavLink>
              ))}
            </nav>
          </div>

          {/* Quick Links */}
          <div>
            <p className="care-sidebar-label">Quick Access</p>
            <nav className="flex flex-col gap-1">
              {quickLinks.map(({ to, icon: Icon, label, badge, badgeColor }) => (
                <NavLink
                  key={label}
                  to={to}
                  onClick={onClose}
                  className={({ isActive }) =>
                    `nav-item w-full text-left justify-between group ${isActive ? 'active' : ''}`
                  }
                >
                  <div className="flex items-center gap-3">
                    <Icon className="w-4 h-4 flex-shrink-0" />
                    <span>{label}</span>
                  </div>
                  {badge && (
                    <span className={`badge ${
                      badgeColor === 'rose'
                        ? 'bg-rose-500/15 text-rose-400'
                        : 'bg-cyan-500/15 text-cyan-400'
                    }`}>
                      {badge}
                    </span>
                  )}
                </NavLink>
              ))}
            </nav>
          </div>

          {/* Processing status card — live */}
          <div className="glass-card rounded-xl p-4 mx-0">
            <div className="flex items-center justify-between mb-3">
              <p className="text-xs font-semibold care-text-secondary">Processing Queue</p>
              <span className={`badge ${queueActive ? 'bg-amber-500/15 text-amber-400' : 'bg-emerald-500/15 text-emerald-400'}`}>
                {queueActive ? 'Active' : 'Idle'}
              </span>
            </div>
            <div className="space-y-2">
              <div className="flex justify-between text-xs">
                <span className="care-muted">Calls today</span>
                <span className="font-mono font-medium" style={{ color: "var(--care-text-primary)" }}>{stats.calls_today}</span>
              </div>
              <div className="w-full rounded-full h-1.5" style={{ background: "var(--care-progress-track)" }}>
                <div
                  className="bg-gradient-to-r from-cyan-500 to-emerald-500 h-1.5 rounded-full transition-all duration-500"
                  style={{ width: `${Math.min(100, stats.processing_pct)}%` }}
                />
              </div>
              <div className="flex justify-between text-xs">
                <span className="care-muted">Processed: {stats.processed}</span>
                <span style={{ color: "var(--care-accent-strong)" }}>{stats.processing_pct}%</span>
              </div>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="p-3 border-t care-sidebar-footer" style={{ borderColor: "var(--care-border)" }}>
          <div className="flex items-center gap-2.5 px-3 py-2">
            <div className="w-2 h-2 bg-emerald-500 rounded-full animate-pulse" />
            <span className="text-xs">All systems operational</span>
          </div>
          <p className="text-xs px-3 care-muted">{PRODUCT_NAME} {PRODUCT_VERSION}</p>
        </div>
      </aside>
    </>
  )
}
