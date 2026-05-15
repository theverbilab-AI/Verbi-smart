// Uses VITE_API_URL env var in production, falls back to localhost for dev
const API_ROOT = import.meta.env.VITE_API_URL || "http://localhost:5000";
const BASE = `${API_ROOT}/api/v1`;
const AUTH = `${API_ROOT}/api/auth`;
function getToken() {
  return localStorage.getItem("care_token") || "";
}

function authHeaders() {
  return {
    "Authorization": `Bearer ${getToken()}`,
    "Content-Type": "application/json",
  };
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
  const res = await fetch(`${AUTH}/me`, { headers: authHeaders() });
  if (!res.ok) throw new Error("Not authenticated");
  return res.json();
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
      if (xhr.status === 200 || xhr.status === 201) resolve(JSON.parse(xhr.responseText));
      else reject(new Error(`Upload failed (${xhr.status})`));
    };
    xhr.onerror = () => reject(new Error("Cannot reach backend. Is Flask running?"));
    xhr.send(formData);
  });
}

export async function getCalls(params = {}) {
  const qs = new URLSearchParams(params).toString();
  const res = await fetch(`${BASE}/calls${qs ? "?" + qs : ""}`, { headers: authHeaders() });
  if (!res.ok) throw new Error(`getCalls failed (${res.status})`);
  return res.json();
}

export async function getCall(callId) {
  const res = await fetch(`${BASE}/calls/${callId}`, { headers: authHeaders() });
  if (!res.ok) throw new Error(`getCall failed (${res.status})`);
  return res.json();
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
export function downloadCSVExport(params = {}) {
  const qs = new URLSearchParams(params).toString();
  const url = `${BASE}/reports/export${qs ? "?" + qs : ""}`;
  // Create a link with auth header workaround — open in new tab
  const a = document.createElement("a");
  a.href = url;
  a.download = `CARE_Export_${new Date().toISOString().slice(0,10)}.csv`;
  a.click();
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
export async function ingestFromS3(s3Uri, metadata = {}) {
  const res = await fetch(`${BASE}/calls/ingest-s3`, {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify({ s3_uri: s3Uri, ...metadata }),
  });
  if (!res.ok) throw new Error(`S3 ingest failed (${res.status})`);
  return res.json();
}

export async function ingestFromUrl(url, metadata = {}) {
  const res = await fetch(`${BASE}/calls/ingest-url`, {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify({ url, ...metadata }),
  });
  if (!res.ok) throw new Error(`URL ingest failed (${res.status})`);
  return res.json();
}
