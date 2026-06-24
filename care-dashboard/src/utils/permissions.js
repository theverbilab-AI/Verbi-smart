/** Permission keys — must match care-backend/permissions.py */

export const PERMISSIONS = [
  { key: "dashboard_view", label: "View Dashboard" },
  { key: "upload_calls", label: "Upload Calls" },
  { key: "view_reports", label: "View Reports" },
  { key: "export_reports", label: "Export Reports" },
  { key: "manage_users", label: "Manage Users" },
  { key: "manage_settings", label: "Manage Settings" },
  { key: "view_call_details", label: "View Call Details" },
  { key: "delete_calls", label: "Delete Calls" },
  { key: "compliance_flags", label: "Compliance Flags" },
  { key: "agent_performance", label: "Agent Performance" },
  { key: "crm_usage", label: "CRM Usage" },
];

const ADMIN_ROLES = new Set(["super_admin", "admin"]);

export function resolvePermissions(user) {
  if (!user) return new Set();
  if (ADMIN_ROLES.has(user.role)) {
    return new Set(PERMISSIONS.map((p) => p.key));
  }
  const custom = Array.isArray(user.permissions) ? user.permissions : [];
  if (custom.length) return new Set(custom);
  const defaults = {
    qa_manager: [
      "dashboard_view", "upload_calls", "view_reports", "export_reports",
      "view_call_details", "compliance_flags", "agent_performance",
    ],
    team_leader: [
      "dashboard_view", "view_reports", "view_call_details",
      "compliance_flags", "agent_performance",
    ],
    read_only: ["dashboard_view", "view_reports", "view_call_details"],
    user: ["dashboard_view", "view_call_details"],
  };
  return new Set(defaults[user.role] || defaults.user);
}

export function hasPermission(user, perm) {
  return resolvePermissions(user).has(perm);
}

export function getStoredUser() {
  try {
    return JSON.parse(localStorage.getItem("care_user") || "null");
  } catch {
    return null;
  }
}
