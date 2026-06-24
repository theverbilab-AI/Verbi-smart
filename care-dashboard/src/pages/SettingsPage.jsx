import { useState } from 'react'
import { PRODUCT_NAME } from '../config/branding.js'
import { hasPermission } from '../utils/permissions'
import {
  User, Bell, Shield, Link2, Database, Palette,
  Save, ChevronRight, Lock, Globe, Sliders, Mail,
  Building2, Key, Eye, EyeOff, CheckCircle2, AlertCircle
} from 'lucide-react'
import Card from '../components/Card'
import ProfileSettings from '../components/ProfileSettings'
import { applyTheme, getTheme } from '../utils/theme'

const sections = [
  { id: 'profile', label: 'Profile & Organisation', icon: User },
  { id: 'notifications', label: 'Notifications & Alerts', icon: Bell },
  { id: 'scoring', label: 'Scoring & Thresholds', icon: Sliders },
  { id: 'integrations', label: 'Integrations', icon: Link2 },
  { id: 'security', label: 'Security & Access', icon: Shield },
  { id: 'data', label: 'Data & Retention', icon: Database },
  { id: 'appearance', label: 'Appearance', icon: Palette },
]

const integrations = [
  { name: 'Google Drive', desc: 'Sync audio from Drive folders', status: 'connected', icon: '🔵' },
  { name: 'Microsoft OneDrive', desc: 'Delta query sync via Graph API', status: 'connected', icon: '☁️' },
  { name: 'Amazon S3', desc: 'IAM role-based bucket access', status: 'disconnected', icon: '🪣' },
  { name: 'Exotel Dialer', desc: 'Real-time call webhook', status: 'connected', icon: '📞' },
  { name: 'Ozonetel', desc: 'CDR webhook integration', status: 'disconnected', icon: '🏢' },
  { name: 'LeadSquared CRM', desc: 'Sales audit sync + webhook (configure in .env)', status: 'disconnected', icon: '🔗' },
  { name: 'Salesforce CRM', desc: 'Customer master sync', status: 'disconnected', icon: '☁️' },
]

function Toggle({ enabled, onChange, label }) {
  return (
    <label className="flex items-center gap-3 cursor-pointer group">
      <div
        onClick={() => onChange(!enabled)}
        className={`relative w-10 h-6 rounded-full transition-colors duration-200 flex-shrink-0 ${enabled ? 'bg-cyan-500' : 'bg-slate-700'}`}
      >
        <span className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform duration-200 ${enabled ? 'translate-x-4' : 'translate-x-0'}`} />
      </div>
      {label && <span className="text-sm text-slate-300 group-hover:text-slate-100 transition-colors">{label}</span>}
    </label>
  )
}

function FieldRow({ label, hint, children }) {
  return (
    <div className="flex flex-col sm:flex-row sm:items-center gap-3 py-4 border-b border-slate-800/50 last:border-0">
      <div className="sm:w-56 flex-shrink-0">
        <p className="text-sm font-medium text-slate-200">{label}</p>
        {hint && <p className="text-xs text-slate-500 mt-0.5">{hint}</p>}
      </div>
      <div className="flex-1">{children}</div>
    </div>
  )
}

function TextInput({ value, placeholder, type = 'text' }) {
  const [val, setVal] = useState(value || '')
  return (
    <input
      type={type}
      value={val}
      onChange={e => setVal(e.target.value)}
      placeholder={placeholder}
      className="w-full bg-slate-800/60 border border-slate-700/50 rounded-lg px-3 py-2.5 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-cyan-500/50 focus:ring-1 focus:ring-cyan-500/20 transition-all"
    />
  )
}

export default function SettingsPage({ user, onUserUpdate }) {
  const visibleSections = sections.filter((s) =>
    s.id === 'profile' || hasPermission(user, 'manage_settings')
  )
  const [activeSection, setActiveSection] = useState('profile')
  const [notifs, setNotifs] = useState({
    complianceFlag: true, lowScore: true, ptpDetected: true,
    batchComplete: false, weeklyReport: true, systemAlerts: true,
  })
  const [showApiKey, setShowApiKey] = useState(false)
  const [scoreThreshold, setScoreThreshold] = useState(70)
  const [lowConfThreshold, setLowConfThreshold] = useState(70)
  const [theme, setTheme] = useState(() => getTheme())

  const setAppTheme = (next) => {
    const applied = applyTheme(next)
    setTheme(applied)
  }

  return (
    <div className="space-y-5 animate-fade-in">
      {/* Header */}
      <div>
        <h1 className="font-display font-bold text-2xl text-slate-100">Settings</h1>
        <p className="text-sm text-slate-400 mt-0.5">Configure {PRODUCT_NAME} for your organisation</p>
      </div>

      <div className="flex flex-col lg:flex-row gap-5">
        {/* Section nav */}
        <aside className="lg:w-56 flex-shrink-0">
          <Card className="p-2">
            <nav className="space-y-0.5">
              {visibleSections.map(({ id, label, icon: Icon }) => (
                <button
                  key={id}
                  onClick={() => setActiveSection(id)}
                  className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-all text-left ${
                    activeSection === id
                      ? 'bg-cyan-500/10 text-cyan-400 border border-cyan-500/20'
                      : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'
                  }`}
                >
                  <Icon className="w-4 h-4 flex-shrink-0" />
                  <span className="flex-1">{label}</span>
                  {activeSection === id && <ChevronRight className="w-3.5 h-3.5" />}
                </button>
              ))}
            </nav>
          </Card>
        </aside>

        {/* Content */}
        <div className="flex-1 min-w-0 space-y-4">

          {/* Profile */}
          {activeSection === 'profile' && (
            <ProfileSettings user={user} onUserUpdate={onUserUpdate} />
          )}

          {/* Notifications */}
          {activeSection === 'notifications' && (
            <Card className="p-6 animate-fade-in">
              <div className="flex items-center gap-3 mb-6">
                <Bell className="w-5 h-5 text-cyan-400" />
                <h2 className="font-display font-semibold text-slate-100 text-lg">Notifications & Alerts</h2>
              </div>

              <div className="space-y-0">
                {[
                  { key: 'complianceFlag', label: 'Compliance Flag Raised', hint: 'Instant alert when threat/abuse is detected', severity: 'critical' },
                  { key: 'lowScore', label: 'Low Quality Score Alert', hint: 'Score below threshold triggers notification', severity: 'warning' },
                  { key: 'ptpDetected', label: 'PTP Commitment Detected', hint: 'Promise-to-pay detected in call transcript' },
                  { key: 'batchComplete', label: 'Batch Processing Complete', hint: 'Notify when a batch upload finishes scoring' },
                  { key: 'weeklyReport', label: 'Weekly Summary Report', hint: 'Emailed every Monday at 9 AM IST' },
                  { key: 'systemAlerts', label: 'System Health Alerts', hint: 'Downtime or API failure notifications' },
                ].map(({ key, label, hint, severity }) => (
                  <FieldRow key={key} label={label} hint={hint}>
                    <div className="flex items-center gap-3">
                      <Toggle
                        enabled={notifs[key]}
                        onChange={v => setNotifs(n => ({ ...n, [key]: v }))}
                      />
                      {severity === 'critical' && (
                        <span className="badge bg-rose-500/15 text-rose-400 border border-rose-500/20">Critical</span>
                      )}
                      {severity === 'warning' && (
                        <span className="badge bg-amber-500/15 text-amber-400 border border-amber-500/20">Warning</span>
                      )}
                    </div>
                  </FieldRow>
                ))}
              </div>

              <div className="mt-4 p-4 bg-slate-800/40 rounded-xl flex items-center gap-3">
                <Mail className="w-4 h-4 text-slate-400 flex-shrink-0" />
                <div className="flex-1">
                  <p className="text-sm text-slate-300">Alert delivery: <span className="text-cyan-400">qam@companyfinance.in</span></p>
                  <p className="text-xs text-slate-500 mt-0.5">Also delivered via web push and in-app notification centre</p>
                </div>
                <button className="btn-secondary text-xs px-3 py-1.5">Edit</button>
              </div>

              <div className="mt-4 flex justify-end">
                <button className="btn-primary">
                  <Save className="w-4 h-4" />
                  Save Preferences
                </button>
              </div>
            </Card>
          )}

          {/* Scoring & Thresholds */}
          {activeSection === 'scoring' && (
            <Card className="p-6 animate-fade-in">
              <div className="flex items-center gap-3 mb-6">
                <Sliders className="w-5 h-5 text-cyan-400" />
                <h2 className="font-display font-semibold text-slate-100 text-lg">Scoring & Thresholds</h2>
              </div>

              <FieldRow label="Quality Alert Threshold" hint="Calls below this score trigger a low-quality alert">
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-slate-500">Score: <span className="text-cyan-400 font-mono">{scoreThreshold}%</span></span>
                    <span className="text-xs text-slate-500">of max 20 pts</span>
                  </div>
                  <input
                    type="range" min="0" max="100" value={scoreThreshold}
                    onChange={e => setScoreThreshold(+e.target.value)}
                    className="w-full accent-cyan-500"
                  />
                  <div className="flex justify-between text-xs text-slate-600">
                    <span>0%</span><span>50%</span><span>100%</span>
                  </div>
                </div>
              </FieldRow>

              <FieldRow label="Low Confidence Threshold" hint="Below this AI confidence % → auto-flag for human review">
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-slate-500">Confidence: <span className="text-amber-400 font-mono">{lowConfThreshold}%</span></span>
                  </div>
                  <input
                    type="range" min="0" max="100" value={lowConfThreshold}
                    onChange={e => setLowConfThreshold(+e.target.value)}
                    className="w-full accent-amber-500"
                  />
                </div>
              </FieldRow>

              <FieldRow label="Re-audit on Critical Fail" hint="Mandatory re-audit when any critical parameter scores 0">
                <Toggle enabled={true} onChange={() => {}} label="Always enabled (compliance requirement)" />
              </FieldRow>

              <FieldRow label="Active Learning" hint="Feed human overrides back into AI model quarterly">
                <Toggle enabled={true} onChange={() => {}} label="Enabled" />
              </FieldRow>

              {/* Score grades */}
              <div className="mt-4 p-4 bg-slate-800/30 rounded-xl">
                <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">Score Grade Bands</p>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                  {[
                    { label: 'Excellent', range: '18–20', color: 'emerald' },
                    { label: 'Good', range: '14–17', color: 'cyan' },
                    { label: 'Needs Work', range: '8–13', color: 'amber' },
                    { label: 'Poor', range: '0–7', color: 'rose' },
                  ].map(g => (
                    <div key={g.label} className={`p-2.5 rounded-lg border text-center ${
                      g.color === 'emerald' ? 'bg-emerald-500/10 border-emerald-500/20' :
                      g.color === 'cyan' ? 'bg-cyan-500/10 border-cyan-500/20' :
                      g.color === 'amber' ? 'bg-amber-500/10 border-amber-500/20' :
                      'bg-rose-500/10 border-rose-500/20'
                    }`}>
                      <p className={`text-xs font-semibold ${
                        g.color === 'emerald' ? 'text-emerald-400' :
                        g.color === 'cyan' ? 'text-cyan-400' :
                        g.color === 'amber' ? 'text-amber-400' : 'text-rose-400'
                      }`}>{g.label}</p>
                      <p className="text-xs text-slate-400 font-mono mt-0.5">{g.range} pts</p>
                    </div>
                  ))}
                </div>
              </div>

              <div className="mt-4 flex justify-end">
                <button className="btn-primary"><Save className="w-4 h-4" />Save Thresholds</button>
              </div>
            </Card>
          )}

          {/* Integrations */}
          {activeSection === 'integrations' && (
            <Card className="p-6 animate-fade-in">
              <div className="flex items-center gap-3 mb-6">
                <Link2 className="w-5 h-5 text-cyan-400" />
                <h2 className="font-display font-semibold text-slate-100 text-lg">Integrations</h2>
              </div>
              <div className="space-y-3">
                {integrations.map(int => (
                  <div key={int.name} className="flex items-center gap-4 p-4 bg-slate-800/30 rounded-xl border border-slate-700/30 hover:border-slate-600/50 transition-colors">
                    <span className="text-2xl flex-shrink-0">{int.icon}</span>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-slate-200">{int.name}</p>
                      <p className="text-xs text-slate-500 mt-0.5">{int.desc}</p>
                    </div>
                    <span className={`badge border flex-shrink-0 ${
                      int.status === 'connected'
                        ? 'bg-emerald-500/15 text-emerald-400 border-emerald-500/20'
                        : 'bg-slate-700/50 text-slate-400 border-slate-600/30'
                    }`}>
                      {int.status === 'connected' ? <CheckCircle2 className="w-3 h-3" /> : <AlertCircle className="w-3 h-3" />}
                      {int.status}
                    </span>
                    <button className={int.status === 'connected' ? 'btn-secondary text-xs px-3 py-1.5' : 'btn-primary text-xs px-3 py-1.5'}>
                      {int.status === 'connected' ? 'Configure' : 'Connect'}
                    </button>
                  </div>
                ))}
              </div>
            </Card>
          )}

          {/* Security */}
          {activeSection === 'security' && (
            <Card className="p-6 animate-fade-in">
              <div className="flex items-center gap-3 mb-6">
                <Shield className="w-5 h-5 text-cyan-400" />
                <h2 className="font-display font-semibold text-slate-100 text-lg">Security & Access</h2>
              </div>

              <FieldRow label="Change Password">
                <button className="btn-secondary text-xs px-3 py-2"><Lock className="w-3.5 h-3.5" />Update Password</button>
              </FieldRow>
              <FieldRow label="Two-Factor Authentication" hint="Adds extra security to your account">
                <Toggle enabled={true} onChange={() => {}} label="Enabled via Authenticator App" />
              </FieldRow>
              <FieldRow label="API Key" hint="Use this to authenticate REST API calls">
                <div className="flex items-center gap-2">
                  <div className="flex-1 bg-slate-800/60 border border-slate-700/50 rounded-lg px-3 py-2.5 font-mono text-xs text-slate-400">
                    {showApiKey ? 'sk-care-aBcDeFgH1234567890XYZ' : '••••••••••••••••••••••••••••'}
                  </div>
                  <button
                    onClick={() => setShowApiKey(!showApiKey)}
                    className="p-2.5 rounded-lg bg-slate-800 border border-slate-700/50 text-slate-400 hover:text-slate-200 transition-colors"
                  >
                    {showApiKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                  <button className="btn-secondary text-xs px-3 py-2"><Key className="w-3.5 h-3.5" />Regenerate</button>
                </div>
              </FieldRow>
              <FieldRow label="Session Timeout" hint="Auto-logout after inactivity">
                <select className="bg-slate-800/60 border border-slate-700/50 rounded-lg px-3 py-2.5 text-sm text-slate-200 focus:outline-none focus:border-cyan-500/50 transition-all">
                  <option>30 minutes</option>
                  <option>1 hour</option>
                  <option>4 hours</option>
                  <option>8 hours</option>
                </select>
              </FieldRow>
              <FieldRow label="Allowed IP Ranges" hint="Restrict access by IP (comma-separated CIDR)">
                <TextInput placeholder="e.g. 10.0.0.0/24, 192.168.1.0/24" />
              </FieldRow>

              <div className="mt-4 flex justify-end">
                <button className="btn-primary"><Save className="w-4 h-4" />Save Security Settings</button>
              </div>
            </Card>
          )}

          {/* Data & Retention */}
          {activeSection === 'data' && (
            <Card className="p-6 animate-fade-in">
              <div className="flex items-center gap-3 mb-6">
                <Database className="w-5 h-5 text-cyan-400" />
                <h2 className="font-display font-semibold text-slate-100 text-lg">Data & Retention</h2>
              </div>
              <FieldRow label="Audio Retention Period" hint="How long raw audio files are stored">
                <select className="bg-slate-800/60 border border-slate-700/50 rounded-lg px-3 py-2.5 text-sm text-slate-200 focus:outline-none focus:border-cyan-500/50 transition-all">
                  <option>90 days</option>
                  <option>180 days</option>
                  <option>1 year</option>
                  <option>3 years</option>
                </select>
              </FieldRow>
              <FieldRow label="Transcript Retention" hint="Transcript and scoring data retention">
                <select className="bg-slate-800/60 border border-slate-700/50 rounded-lg px-3 py-2.5 text-sm text-slate-200 focus:outline-none focus:border-cyan-500/50 transition-all">
                  <option>1 year</option>
                  <option>3 years</option>
                  <option>5 years</option>
                  <option>Indefinite</option>
                </select>
              </FieldRow>
              <FieldRow label="Auto-delete flagged data" hint="Auto-purge compliance-flagged PII after retention period">
                <Toggle enabled={true} onChange={() => {}} label="Enabled" />
              </FieldRow>
              <FieldRow label="Export All Data">
                <button className="btn-secondary text-xs px-3 py-2"><Globe className="w-3.5 h-3.5" />Request Data Export</button>
              </FieldRow>
              <div className="mt-4 flex justify-end">
                <button className="btn-primary"><Save className="w-4 h-4" />Save Preferences</button>
              </div>
            </Card>
          )}

          {/* Appearance */}
          {activeSection === 'appearance' && (
            <Card className="p-6 animate-fade-in">
              <div className="flex items-center gap-3 mb-6">
                <Palette className="w-5 h-5 text-cyan-400" />
                <h2 className="font-display font-semibold text-slate-100 text-lg">Appearance</h2>
              </div>
              <FieldRow label="Theme" hint="Light or dark dashboard appearance">
                <div className="flex gap-2">
                  {[
                    { id: 'dark', label: 'Dark' },
                    { id: 'light', label: 'Light' },
                  ].map((t) => (
                    <button
                      key={t.id}
                      type="button"
                      onClick={() => setAppTheme(t.id)}
                      className={`px-4 py-2 rounded-lg border text-xs font-medium transition-all ${
                        theme === t.id
                          ? 'border-cyan-500 text-cyan-400 bg-cyan-500/10'
                          : 'border-slate-700 text-slate-400 hover:border-slate-600'
                      }`}
                    >
                      {t.label}
                    </button>
                  ))}
                </div>
              </FieldRow>
              <FieldRow label="Accent Colour" hint="Primary highlight colour across the UI (coming soon)">
                <div className="flex gap-2">
                  {['bg-cyan-500', 'bg-emerald-500', 'bg-blue-500', 'bg-violet-500', 'bg-amber-500'].map(c => (
                    <button key={c} className={`w-7 h-7 rounded-full ${c} ${c === 'bg-cyan-500' ? 'ring-2 ring-white ring-offset-2 ring-offset-slate-900' : ''} transition-all hover:scale-110`} />
                  ))}
                </div>
              </FieldRow>
              <FieldRow label="Table Density">
                <div className="flex gap-1 bg-slate-800/60 border border-slate-700/50 rounded-lg p-1">
                  {['Compact', 'Default', 'Comfortable'].map((d, i) => (
                    <button key={d} className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all ${i === 1 ? 'bg-slate-700 text-slate-100' : 'text-slate-400 hover:text-slate-200'}`}>{d}</button>
                  ))}
                </div>
              </FieldRow>
              <FieldRow label="Organisation Logo" hint="Shown on PDF audit reports">
                <button className="btn-secondary text-xs px-3 py-2">Upload Logo</button>
              </FieldRow>
              <div className="mt-4 flex justify-end">
                <button className="btn-primary"><Save className="w-4 h-4" />Apply Changes</button>
              </div>
            </Card>
          )}
        </div>
      </div>
    </div>
  )
}