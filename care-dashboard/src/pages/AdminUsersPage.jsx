import { useEffect, useState, useCallback } from "react";
import {
  getUsers,
  createUser,
  updateUser,
  updateUserPermissions,
  updateUserStatus,
  deleteUser,
} from "../services/api";
import { PERMISSIONS, getStoredUser } from "../utils/permissions";

const ROLES = ["super_admin", "admin", "qa_manager", "team_leader", "read_only"];

function formatRole(role) {
  return (role || "user").replace(/_/g, " ");
}

function ConfirmModal({ open, title, message, confirmLabel, danger, loading, onConfirm, onCancel }) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60">
      <div className="bg-slate-900 border border-slate-700 rounded-xl p-6 max-w-md w-full shadow-xl">
        <h3 className="text-lg font-semibold text-white">{title}</h3>
        <p className="text-sm text-slate-400 mt-2">{message}</p>
        <div className="flex gap-3 mt-6 justify-end">
          <button type="button" onClick={onCancel} disabled={loading}
            className="px-4 py-2 text-sm text-slate-300 hover:text-white">
            Cancel
          </button>
          <button type="button" onClick={onConfirm} disabled={loading}
            className={`px-4 py-2 text-sm font-semibold rounded-lg ${
              danger ? "bg-red-600 hover:bg-red-500 text-white" : "bg-cyan-600 hover:bg-cyan-500 text-black"
            }`}>
            {loading ? "Please wait…" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

function EditUserModal({ user, open, saving, onClose, onSave }) {
  const [form, setForm] = useState({ name: "", role: "qa_manager", is_active: true, permissions: [] });

  useEffect(() => {
    if (user && open) {
      setForm({
        name: user.name || "",
        role: user.role || "qa_manager",
        is_active: Boolean(user.is_active),
        permissions: Array.isArray(user.permissions) ? [...user.permissions] : [],
      });
    }
  }, [user, open]);

  if (!open || !user) return null;

  const togglePerm = (key) => {
    setForm((f) => ({
      ...f,
      permissions: f.permissions.includes(key)
        ? f.permissions.filter((p) => p !== key)
        : [...f.permissions, key],
    }));
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    onSave(user.id, form);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 overflow-y-auto">
      <div className="bg-slate-900 border border-slate-700 rounded-xl p-6 max-w-lg w-full shadow-xl my-8">
        <h3 className="text-lg font-semibold text-white">Edit user</h3>
        <p className="text-xs text-slate-500 mt-1 font-mono">{user.email}</p>
        <form onSubmit={handleSubmit} className="mt-4 space-y-4">
          <div>
            <label className="text-xs text-slate-400">Full name</label>
            <input required value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              className="w-full mt-1 bg-slate-800 rounded-lg px-3 py-2 text-sm border border-slate-600" />
          </div>
          <div>
            <label className="text-xs text-slate-400">Role</label>
            <select value={form.role} onChange={(e) => setForm((f) => ({ ...f, role: e.target.value }))}
              className="w-full mt-1 bg-slate-800 rounded-lg px-3 py-2 text-sm border border-slate-600">
              {ROLES.map((r) => <option key={r} value={r}>{formatRole(r)}</option>)}
            </select>
          </div>
          <label className="flex items-center gap-2 text-sm text-slate-300 cursor-pointer">
            <input type="checkbox" checked={form.is_active}
              onChange={(e) => setForm((f) => ({ ...f, is_active: e.target.checked }))} />
            Account active
          </label>
          <div>
            <p className="text-xs text-slate-400 mb-2">Permissions</p>
            <div className="flex flex-wrap gap-2 max-h-40 overflow-y-auto">
              {PERMISSIONS.map((p) => (
                <label key={p.key} className="flex items-center gap-1.5 text-xs bg-slate-800/80 px-2 py-1 rounded border border-slate-700 cursor-pointer">
                  <input type="checkbox" checked={form.permissions.includes(p.key)} onChange={() => togglePerm(p.key)} />
                  {p.label}
                </label>
              ))}
            </div>
          </div>
          <div className="flex gap-3 justify-end pt-2">
            <button type="button" onClick={onClose} disabled={saving} className="text-sm text-slate-400 hover:text-white">Cancel</button>
            <button type="submit" disabled={saving}
              className="bg-cyan-600 hover:bg-cyan-500 disabled:opacity-50 text-black font-semibold px-4 py-2 rounded-lg text-sm">
              {saving ? "Saving…" : "Save changes"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export default function AdminUsersPage({ onSessionExpired }) {
  const self = getStoredUser();
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [creating, setCreating] = useState(false);
  const [editUser, setEditUser] = useState(null);
  const [editSaving, setEditSaving] = useState(false);
  const [confirm, setConfirm] = useState(null);
  const [confirmLoading, setConfirmLoading] = useState(false);
  const [form, setForm] = useState({
    email: "", name: "", role: "qa_manager", password: "",
    permissions: PERMISSIONS.map((p) => p.key),
  });

  const flash = (msg) => {
    setSuccess(msg);
    setTimeout(() => setSuccess(""), 4000);
  };

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await getUsers();
      setUsers(data.users ?? []);
    } catch (e) {
      if (e.status === 401) {
        setError(e.message);
        onSessionExpired?.();
        return;
      }
      setError(e.message || "Could not load users");
    } finally {
      setLoading(false);
    }
  }, [onSessionExpired]);

  useEffect(() => { load(); }, [load]);

  const togglePerm = (key) => {
    setForm((f) => ({
      ...f,
      permissions: f.permissions.includes(key)
        ? f.permissions.filter((p) => p !== key)
        : [...f.permissions, key],
    }));
  };

  const handleCreate = async (e) => {
    e.preventDefault();
    setCreating(true);
    setError("");
    try {
      await createUser({
        email: form.email.trim().toLowerCase(),
        name: form.name.trim(),
        role: form.role,
        password: form.password || undefined,
        permissions: form.permissions,
      });
      setForm({ email: "", name: "", role: "qa_manager", password: "", permissions: PERMISSIONS.map((p) => p.key) });
      flash("User created successfully");
      await load();
    } catch (err) {
      if (err.status === 401) {
        setError(err.message);
        onSessionExpired?.();
        return;
      }
      setError(err.message || "Create failed");
    } finally {
      setCreating(false);
    }
  };

  const handleEditSave = async (userId, data) => {
    setEditSaving(true);
    setError("");
    try {
      await updateUser(userId, {
        name: data.name,
        role: data.role,
        is_active: data.is_active,
      });
      await updateUserPermissions(userId, data.permissions);
      setEditUser(null);
      flash("User updated");
      await load();
    } catch (err) {
      setError(err.message || "Update failed");
    } finally {
      setEditSaving(false);
    }
  };

  const runConfirm = async () => {
    if (!confirm) return;
    setConfirmLoading(true);
    setError("");
    try {
      if (confirm.type === "delete") {
        await deleteUser(confirm.user.id);
        flash("User deleted");
      } else if (confirm.type === "toggle") {
        await updateUserStatus(confirm.user.id, !confirm.user.is_active);
        flash(confirm.user.is_active ? "User disabled" : "User enabled");
      }
      setConfirm(null);
      await load();
    } catch (err) {
      setError(err.message || "Action failed");
    } finally {
      setConfirmLoading(false);
    }
  };

  const isSelf = (u) => u.id === self?.id;

  return (
    <div className="p-4 md:p-6 text-white space-y-6 max-w-6xl mx-auto">
      <div>
        <h1 className="text-2xl font-bold">User Management</h1>
        <p className="text-sm text-slate-400 mt-1">Create employee accounts and assign permissions.</p>
      </div>

      {error && (
        <div className="bg-red-900/40 border border-red-700 text-red-300 rounded-lg px-4 py-3 text-sm">{error}</div>
      )}
      {success && (
        <div className="bg-emerald-900/40 border border-emerald-700 text-emerald-300 rounded-lg px-4 py-3 text-sm">{success}</div>
      )}

      <form onSubmit={handleCreate} className="glass-card rounded-xl p-5 space-y-4">
        <h2 className="font-semibold text-cyan-300">Create User</h2>
        <div className="grid md:grid-cols-2 gap-3">
          <input required type="email" placeholder="Email *" value={form.email}
            onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))}
            className="bg-slate-800 rounded-lg px-3 py-2 text-sm border border-slate-600" />
          <input required type="text" placeholder="Full name *" value={form.name}
            onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
            className="bg-slate-800 rounded-lg px-3 py-2 text-sm border border-slate-600" />
          <select required value={form.role} onChange={(e) => setForm((f) => ({ ...f, role: e.target.value }))}
            className="bg-slate-800 rounded-lg px-3 py-2 text-sm border border-slate-600">
            {ROLES.map((r) => <option key={r} value={r}>{formatRole(r)}</option>)}
          </select>
          <input type="text" placeholder="Temp password (optional — OTP login)" value={form.password}
            onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))}
            className="bg-slate-800 rounded-lg px-3 py-2 text-sm border border-slate-600" />
        </div>
        <div className="flex flex-wrap gap-2">
          {PERMISSIONS.map((p) => (
            <label key={p.key} className="flex items-center gap-1.5 text-xs bg-slate-800/80 px-2 py-1 rounded border border-slate-700 cursor-pointer">
              <input type="checkbox" checked={form.permissions.includes(p.key)} onChange={() => togglePerm(p.key)} />
              {p.label}
            </label>
          ))}
        </div>
        <button type="submit" disabled={creating}
          className="bg-cyan-600 hover:bg-cyan-500 disabled:opacity-50 text-black font-semibold px-4 py-2 rounded-lg text-sm">
          {creating ? "Creating…" : "Create User"}
        </button>
      </form>

      <div className="glass-card rounded-xl overflow-hidden">
        <h2 className="font-semibold px-5 py-3 border-b border-slate-700">Existing Users</h2>
        {loading ? (
          <p className="p-5 text-slate-400 animate-pulse">Loading…</p>
        ) : users.length === 0 ? (
          <p className="p-5 text-slate-500 text-sm">No users yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm min-w-[640px]">
              <thead>
                <tr className="text-slate-500 text-xs uppercase border-b border-slate-700">
                  <th className="text-left p-3">Name</th>
                  <th className="text-left p-3">Email</th>
                  <th className="text-left p-3">Role</th>
                  <th className="text-left p-3">Status</th>
                  <th className="text-right p-3">Actions</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.id} className="border-b border-slate-800/60 hover:bg-slate-800/30">
                    <td className="p-3">{u.name || "—"}</td>
                    <td className="p-3 font-mono text-xs">{u.email}</td>
                    <td className="p-3">{formatRole(u.role)}</td>
                    <td className="p-3">
                      <span className={u.is_active ? "text-emerald-400" : "text-slate-500"}>
                        {u.is_active ? "Active" : "Disabled"}
                      </span>
                    </td>
                    <td className="p-3 text-right space-x-2 whitespace-nowrap">
                      <button type="button" onClick={() => setEditUser(u)}
                        className="text-xs text-cyan-400 hover:text-cyan-300">Edit</button>
                      {!isSelf(u) && (
                        <>
                          <button type="button"
                            onClick={() => setConfirm({
                              type: "toggle",
                              user: u,
                              title: u.is_active ? "Disable user?" : "Enable user?",
                              message: `${u.is_active ? "Disable" : "Enable"} ${u.email}?`,
                              confirmLabel: u.is_active ? "Disable" : "Enable",
                              danger: u.is_active,
                            })}
                            className="text-xs text-amber-400 hover:text-amber-300">
                            {u.is_active ? "Disable" : "Enable"}
                          </button>
                          <button type="button"
                            onClick={() => setConfirm({
                              type: "delete",
                              user: u,
                              title: "Delete user?",
                              message: `Permanently delete ${u.email}? This cannot be undone.`,
                              confirmLabel: "Delete",
                              danger: true,
                            })}
                            className="text-xs text-red-400 hover:text-red-300">Delete</button>
                        </>
                      )}
                      {isSelf(u) && <span className="text-xs text-slate-600">(you)</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <EditUserModal
        user={editUser}
        open={Boolean(editUser)}
        saving={editSaving}
        onClose={() => setEditUser(null)}
        onSave={handleEditSave}
      />

      <ConfirmModal
        open={Boolean(confirm)}
        title={confirm?.title}
        message={confirm?.message}
        confirmLabel={confirm?.confirmLabel || "Confirm"}
        danger={confirm?.danger}
        loading={confirmLoading}
        onConfirm={runConfirm}
        onCancel={() => setConfirm(null)}
      />
    </div>
  );
}
