import { API_ROOT } from "../config.js";
import { PRODUCT_NAME } from "../config/branding.js";

const BASE = `${API_ROOT}/api/v1`;
const AUTH = `${API_ROOT}/api/auth`;
const ADMIN = `${API_ROOT}/api/admin`;
function getToken() {
  return localStorage.getItem("care_token") || "";
}

function authHeaders() {
  return {
    "Authorization": `Bearer ${getToken()}`,
    "Content-Type": "application/json",
  };
}

async function parseJsonResponse(res) {
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const msg = data.error || data.detail || `Request failed (${res.status})`;
    const err = new Error(msg);
    err.status = res.status;
    if (res.status === 401) {
      localStorage.removeItem("care_token");
      localStorage.removeItem("care_user");
      err.message = "Session expired — please sign in again.";
    }
    throw err;
  }
  return data;
}

async function apiFetch(url, options = {}) {
  try {
    const res = await fetch(url, options);
    return parseJsonResponse(res);
  } catch (e) {
    if (e.status === 401) throw e;
    if (e instanceof TypeError || e.message === "Failed to fetch") {
      throw new Error("Cannot reach backend. Start care-backend: python app.py (port 5000)");
    }
    throw e;
  }
}

// ── Auth ──────────────────────────────────────────────────────────────────────
export async function login(email, password) {
  const res = await fetch(`${AUTH}/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "Login failed");
  return data;
}

export async function getMe() {
  return apiFetch(`${AUTH}/me`, { headers: authHeaders() });
}

export async function updateProfile(payload) {
  return apiFetch(`${AUTH}/profile`, {
    method: "PATCH",
    headers: authHeaders(),
    body: JSON.stringify(payload),
  });
}

export async function getAuthConfig() {
  const res = await fetch(`${AUTH}/config`);
  if (!res.ok) throw new Error("Could not load auth config");
  return res.json();
}

export async function getUsers() {
  return apiFetch(`${ADMIN}/users`, { headers: authHeaders() });
}

/** @deprecated use getUsers */
export async function listUsers() {
  return getUsers();
}

export async function createUser(payload) {
  return apiFetch(`${ADMIN}/users`, {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify(payload),
  });
}

export async function updateUser(userId, payload) {
  return apiFetch(`${ADMIN}/users/${userId}`, {
    method: "PATCH",
    headers: authHeaders(),
    body: JSON.stringify(payload),
  });
}

export async function updateUserPermissions(userId, permissions) {
  return apiFetch(`${ADMIN}/users/${userId}/permissions`, {
    method: "PATCH",
    headers: authHeaders(),
    body: JSON.stringify({ permissions }),
  });
}

export async function updateUserStatus(userId, is_active) {
  return apiFetch(`${ADMIN}/users/${userId}/status`, {
    method: "PATCH",
    headers: authHeaders(),
    body: JSON.stringify({ is_active }),
  });
}

export async function deleteUser(userId) {
  return apiFetch(`${ADMIN}/users/${userId}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
}

export async function getCrmUsage(limit = 100) {
  return apiFetch(`${BASE}/admin/crm-usage?limit=${limit}`, { headers: authHeaders() });
}

export function logout() {
  localStorage.removeItem("care_token");
  localStorage.removeItem("care_user");
}

// ── Calls ─────────────────────────────────────────────────────────────────────
export async function uploadCall(file, metadata = {}, onProgress) {
  return new Promise((resolve, reject) => {
    const formData = new FormData();
    formData.append("file", file);
    Object.entries(metadata).forEach(([k, v]) => { if (v) formData.append(k, v); });

    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${BASE}/calls/ingest`);
    xhr.setRequestHeader("Authorization", `Bearer ${getToken()}`);

    if (onProgress) {
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100));
      };
    }
    xhr.onload = () => {
      if (xhr.status === 200 || xhr.status === 201) {
        resolve(JSON.parse(xhr.responseText));
        return;
      }
      let msg = `Upload failed (${xhr.status})`;
      try {
        const body = JSON.parse(xhr.responseText);
        if (body.error) msg = body.error;
        else if (body.detail) msg = `${body.error || msg}: ${body.detail}`;
      } catch (_e) { /* ignore */ }
      reject(new Error(msg));
    };
    xhr.onerror = () => reject(new Error("Cannot reach backend. Is Flask running?"));
    xhr.send(formData);
  });
}

export async function getCalls(params = {}) {
  const qs = new URLSearchParams({ limit: 50, ...params }).toString();
  return apiFetch(`${BASE}/calls?${qs}`, { headers: authHeaders() });
}

/** Normalise list-calls payload to an array. */
export function callsFromResponse(data) {
  if (Array.isArray(data)) return data;
  return data?.calls ?? [];
}

/** Fetch audio with auth headers — returns blob URL for <audio src>. */
export async function fetchCallAudioBlob(callId) {
  const token = getToken();
  const res = await fetch(getCallAudioUrl(callId), {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    credentials: "include",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    const msg = [err.error, err.hint].filter(Boolean).join(" — ");
    throw new Error(msg || `Audio failed (${res.status})`);
  }
  const blob = await res.blob();
  if (!blob.size) throw new Error("Audio file is empty on server");
  if (blob.type && !blob.type.startsWith("audio/") && blob.type !== "application/octet-stream") {
    throw new Error("Server did not return audio — check S3 credentials and redeploy backend");
  }
  return URL.createObjectURL(blob);
}

/** Upload multiple files with limited concurrency (default 3). */
export async function uploadCallsBatch(files, metadata = {}, onFileProgress) {
  const queue = [...files];
  const results = [];
  const errors = [];
  const workers = 2;

  async function worker() {
    while (queue.length) {
      const file = queue.shift();
      if (!file) break;
      try {
        const res = await uploadCall(file, metadata, (pct) => onFileProgress?.(file.name, pct));
        results.push(res);
      } catch (err) {
        errors.push({ file: file.name, error: err.message });
      }
    }
  }

  await Promise.all(Array.from({ length: Math.min(workers, files.length) }, () => worker()));
  return { results, errors };
}

export async function getCall(callId) {
  const res = await fetch(`${BASE}/calls/${callId}`, { headers: authHeaders() });
  if (!res.ok) throw new Error(`getCall failed (${res.status})`);
  return res.json();
}

/** Full URL for HTML5 audio player (includes auth token for browser playback). */
export function getCallAudioUrl(callId) {
  const token = getToken();
  const qs = token ? `?token=${encodeURIComponent(token)}` : "";
  return `${API_ROOT}/api/v1/calls/${callId}/audio${qs}`;
}

export async function getDashboard(params = {}) {
  const qs = new URLSearchParams(params).toString();
  const res = await fetch(`${BASE}/reports/dashboard${qs ? "?" + qs : ""}`, { headers: authHeaders() });
  if (!res.ok) throw new Error(`getDashboard failed (${res.status})`);
  return res.json();
}

export async function getAgentKPIs() {
  const res = await fetch(`${BASE}/agents/kpis`, { headers: authHeaders() });
  if (!res.ok) throw new Error(`getAgentKPIs failed (${res.status})`);
  return res.json();
}

// ── Export CSV ────────────────────────────────────────────────────────────────
export async function downloadDispositionLoans(disposition, params = {}) {
  const qs = new URLSearchParams({ disposition, ...params }).toString();
  const res = await fetch(`${BASE}/reports/disposition-loans?${qs}`, {
    headers: { Authorization: `Bearer ${getToken()}` },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || `Download failed (${res.status})`);
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${PRODUCT_NAME}_${String(disposition).toLowerCase()}_loan_ids.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

export async function downloadAuditComparisonCSV(params = {}) {
  const qs = new URLSearchParams({ rescore: "1", ...params }).toString();
  const res = await fetch(`${BASE}/reports/audit-export?${qs}`, {
    headers: { Authorization: `Bearer ${getToken()}` },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || `Audit export failed (${res.status})`);
  }
  const blob = await res.blob();
  if (!blob.size) {
    throw new Error("Audit export is empty — no processed calls");
  }
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${PRODUCT_NAME}_Audit_Comparison_${new Date().toISOString().slice(0, 10)}.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export async function downloadCSVExport(params = {}) {
  const qs = new URLSearchParams(params).toString();
  const res = await fetch(`${BASE}/reports/export${qs ? `?${qs}` : ""}`, {
    headers: { Authorization: `Bearer ${getToken()}` },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || `Export failed (${res.status})`);
  }
  const blob = await res.blob();
  if (!blob.size) {
    throw new Error("Export is empty — no processed calls to download");
  }
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${PRODUCT_NAME}_Export_${new Date().toISOString().slice(0, 10)}.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

// ── Google Drive Sync ─────────────────────────────────────────────────────────
export async function syncGDrive(folderIdOrUrl = null) {
  const res = await fetch(`${BASE}/connectors/gdrive/sync`, {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify(folderIdOrUrl ? { folder_id: folderIdOrUrl } : {}),
  });
  if (!res.ok) throw new Error(`Drive sync failed (${res.status})`);
  return res.json();
}

export async function saveGDriveConfig(folderUrl, autoSync = false) {
  const res = await fetch(`${BASE}/connectors/gdrive/config`, {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify({ folder_url: folderUrl, auto_sync: autoSync }),
  });
  if (!res.ok) throw new Error("Failed to save Drive config");
  return res.json();
}

// ── S3 Ingest ─────────────────────────────────────────────────────────────────
async function parseApiError(res, fallback) {
  const body = await res.json().catch(() => ({}));
  const msg = body.error || body.message || fallback;
  const detail = body.detail || body.hint;
  return detail ? `${msg} — ${detail}` : msg;
}

export async function ingestFromS3(s3Uri, metadata = {}) {
  const res = await fetch(`${BASE}/calls/ingest-s3`, {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify({ s3_uri: s3Uri, ...metadata }),
  });
  if (!res.ok) throw new Error(await parseApiError(res, `S3 ingest failed (${res.status})`));
  return res.json();
}

export async function ingestFromUrl(url, metadata = {}) {
  const res = await fetch(`${BASE}/calls/ingest-url`, {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify({ url, ...metadata }),
  });
  if (!res.ok) throw new Error(await parseApiError(res, `URL ingest failed (${res.status})`));
  return res.json();
}
