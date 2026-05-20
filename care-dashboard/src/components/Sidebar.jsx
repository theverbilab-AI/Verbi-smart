import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard, Upload, FileBarChart2, Settings,
  Phone, Shield, Users, TrendingUp, X, Zap
} from 'lucide-react'

const mainNav = [
  { to: '/dashboard', icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/kpis', icon: TrendingUp, label: 'KPI Tracker' },
  { to: '/upload', icon: Upload, label: 'Upload Document' },
  { to: '/reports', icon: FileBarChart2, label: 'Reports' },
  { to: '/settings', icon: Settings, label: 'Settings' },
]

const quickLinks = [
  { icon: Phone, label: 'Live Calls', badge: '12' },
  { icon: Shield, label: 'Compliance Flags', badge: '3', badgeColor: 'rose' },
  { icon: Users, label: 'Agent Performance' },
  { icon: TrendingUp, label: 'KPI Tracker' },
]

export default function Sidebar({ open, onClose }) {
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
          fixed lg:sticky top-0 left-0 z-50 lg:z-auto
          h-screen w-64 flex-shrink-0
          flex flex-col
          bg-slate-900/95 backdrop-blur-xl border-r border-slate-800/50
          transition-transform duration-300 ease-in-out
          ${open ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'}
        `}
      >
        {/* Mobile close button */}
        <div className="flex lg:hidden items-center justify-between p-4 border-b border-slate-800/50">
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-cyan-400 to-emerald-500 flex items-center justify-center">
              <Zap className="w-3.5 h-3.5 text-slate-950" strokeWidth={2.5} />
            </div>
            <span className="font-display font-bold text-slate-100">CARE</span>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg text-slate-400 hover:text-slate-100 hover:bg-slate-800">
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Scroll area */}
        <div className="flex-1 overflow-y-auto py-4 px-3 flex flex-col gap-6">

          {/* Main Navigation */}
          <div>
            <p className="text-xs font-semibold text-slate-500 uppercase tracking-widest px-3 mb-2">Navigation</p>
            <nav className="flex flex-col gap-1">
              {mainNav.map(({ to, icon: Icon, label }) => (
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
            <p className="text-xs font-semibold text-slate-500 uppercase tracking-widest px-3 mb-2">Quick Access</p>
            <nav className="flex flex-col gap-1">
              {quickLinks.map(({ icon: Icon, label, badge, badgeColor }) => (
                <button key={label} className="nav-item w-full text-left justify-between group">
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
                </button>
              ))}
            </nav>
          </div>

          {/* Processing status card */}
          <div className="glass-card rounded-xl p-4 mx-0">
            <div className="flex items-center justify-between mb-3">
              <p className="text-xs font-semibold text-slate-300">Processing Queue</p>
              <span className="badge bg-amber-500/15 text-amber-400">Active</span>
            </div>
            <div className="space-y-2">
              <div className="flex justify-between text-xs">
                <span className="text-slate-400">Calls today</span>
                <span className="text-slate-200 font-mono font-medium">847</span>
              </div>
              <div className="w-full bg-slate-800 rounded-full h-1.5">
                <div className="bg-gradient-to-r from-cyan-500 to-emerald-500 h-1.5 rounded-full" style={{ width: '78%' }} />
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-slate-500">Processed: 660</span>
                <span className="text-cyan-400">78%</span>
              </div>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="p-3 border-t border-slate-800/50">
          <div className="flex items-center gap-2.5 px-3 py-2">
            <div className="w-2 h-2 bg-emerald-400 rounded-full animate-pulse" />
            <span className="text-xs text-slate-400">All systems operational</span>
          </div>
          <p className="text-xs text-slate-600 px-3">CARE v1.0 · Company Finance 2025</p>
        </div>
      </aside>
    </>
  )
}
