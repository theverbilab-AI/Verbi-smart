import { useState } from "react";
import { Building2, Save } from "lucide-react";
import Card from "../components/Card";
import { updateProfile } from "../services/api";

function FieldRow({ label, hint, children }) {
  return (
    <div className="flex flex-col sm:flex-row sm:items-center gap-3 py-4 border-b border-slate-800/50 last:border-0">
      <div className="sm:w-56 flex-shrink-0">
        <p className="text-sm font-medium text-slate-200">{label}</p>
        {hint && <p className="text-xs text-slate-500 mt-0.5">{hint}</p>}
      </div>
      <div className="flex-1">{children}</div>
    </div>
  );
}

function formatRole(role) {
  return (role || "user").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export default function ProfileSettings({ user, onUserUpdate }) {
  const [name, setName] = useState(user?.name || "");
  const [email, setEmail] = useState(user?.email || "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const validate = () => {
    if (!name.trim()) return "Name is required";
    if (!email.trim() || !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim())) {
      return "Valid email is required";
    }
    return "";
  };

  const handleSave = async (e) => {
    e.preventDefault();
    const msg = validate();
    if (msg) {
      setError(msg);
      return;
    }
    setSaving(true);
    setError("");
    setSuccess("");
    try {
      const updated = await updateProfile({
        name: name.trim(),
        email: email.trim().toLowerCase(),
      });
      localStorage.setItem("care_user", JSON.stringify({ ...user, ...updated }));
      onUserUpdate?.(updated);
      setSuccess("Profile updated");
    } catch (err) {
      setError(err.message || "Could not save profile");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card className="p-6 animate-fade-in">
      <div className="flex items-center gap-3 mb-6">
        <Building2 className="w-5 h-5 text-cyan-400" />
        <h2 className="font-display font-semibold text-slate-100 text-lg">Profile</h2>
      </div>

      {error && (
        <div className="mb-4 bg-red-900/40 border border-red-700 text-red-300 rounded-lg px-4 py-2 text-sm">{error}</div>
      )}
      {success && (
        <div className="mb-4 bg-emerald-900/40 border border-emerald-700 text-emerald-300 rounded-lg px-4 py-2 text-sm">{success}</div>
      )}

      <form onSubmit={handleSave}>
        <FieldRow label="Your Name" hint="Shown in header and reports">
          <input
            type="text"
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full bg-slate-800/60 border border-slate-700/50 rounded-lg px-3 py-2.5 text-sm text-slate-200 focus:outline-none focus:border-cyan-500/50"
          />
        </FieldRow>
        <FieldRow label="Email Address" hint="Used for OTP login">
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="w-full bg-slate-800/60 border border-slate-700/50 rounded-lg px-3 py-2.5 text-sm text-slate-200 focus:outline-none focus:border-cyan-500/50"
          />
        </FieldRow>
        <FieldRow label="Role" hint="Contact admin to change role">
          <p className="text-sm text-slate-300 capitalize">{formatRole(user?.role)}</p>
        </FieldRow>
        <FieldRow label="Organisation">
          <p className="text-sm text-slate-400">{user?.org_id || "org_default"}</p>
        </FieldRow>

        <div className="mt-6 flex justify-end">
          <button type="submit" disabled={saving} className="btn-primary disabled:opacity-50">
            <Save className="w-4 h-4" />
            {saving ? "Saving…" : "Save Changes"}
          </button>
        </div>
      </form>
    </Card>
  );
}
